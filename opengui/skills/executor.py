"""
opengui.skills.executor
~~~~~~~~~~~~~~~~~~~~~~
Step-by-step skill execution with agent-integrated parameter grounding,
valid-state verification, and subgoal recovery.

Execution pipeline per step:
1. Verify ``valid_state`` against current screenshot (LLM-based); skip if special.
2a. If valid_state passes and step is fixed → execute with ``fixed_values`` directly.
2b. If valid_state passes and step is not fixed → ground parameters via ``ActionGrounder``
    (vision-LLM call) or fall back to template substitution if no grounder is available.
3. If valid_state fails → run a mini recovery loop (``SubgoalRunner``) with valid_state
   as the goal; retry up to ``max_recovery_steps``; re-validate afterwards.
4. After all steps complete (or recovery exhausted), ``execution_summary`` carries a
   narrative for the outer agent loop to use as context when it takes over.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import io
import logging
import re
import time
import typing
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from opengui.action import Action
from opengui.interfaces import DeviceBackend
from opengui.skills.data import Skill, SkillStep

if typing.TYPE_CHECKING:
    from opengui.interfaces import LLMProvider
    from opengui.trajectory.recorder import TrajectoryRecorder

logger = logging.getLogger(__name__)

_POST_ACTION_SETTLE_SECONDS: float = 0.50
_NO_SETTLE_ACTIONS: frozenset[str] = frozenset({"wait", "done", "request_intervention"})


# ---------------------------------------------------------------------------
# Execution state
# ---------------------------------------------------------------------------

class ExecutionState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Subgoal result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubgoalResult:
    """Outcome of a mini recovery loop."""

    success: bool
    steps_taken: int
    action_summaries: list[str]
    final_screenshot: Path | bytes | None = None
    error: str | None = None
    token_usage: dict[str, int] = dataclasses.field(default_factory=dict)
    #: True when the subgoal succeeded because the model issued a ``done``
    #: action (highest-confidence self-declaration), not via LLM state validation.
    done_judgment: bool = False


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Outcome of a single skill step."""

    step_index: int
    action: Action
    backend_result: str
    state: ExecutionState
    valid_state_check: bool = True
    # "fixed" | "llm" | "template"
    grounding_mode: str = "template"
    recovery_attempted: bool = False
    recovery_result: SubgoalResult | None = None
    action_summary: str = ""
    error: str | None = None
    token_usage: dict[str, int] = dataclasses.field(default_factory=dict)
    duration_s: float = 0.0
    # None  → validation was intentionally skipped (no valid_state / no validator)
    # float → actual LLM validation call duration in seconds
    validate_duration_s: float | None = None
    grounding_duration_s: float | None = None


@dataclass
class SkillExecutionResult:
    """Outcome of a full skill execution."""

    skill: Skill
    step_results: list[StepResult]
    state: ExecutionState
    # Narrative summary of all steps; injected into the agent loop as context.
    execution_summary: str = ""
    error: str | None = None
    token_usage: dict[str, int] = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

@typing.runtime_checkable
class StateValidator(typing.Protocol):
    """Validates current screen state against a ``valid_state`` description."""

    async def validate(
        self,
        valid_state: str,
        screenshot: Path | bytes | None = None,
    ) -> bool:
        """Return True if the current screen matches *valid_state*."""
        ...


@typing.runtime_checkable
class ActionGrounder(typing.Protocol):
    """Grounds a non-fixed SkillStep into a concrete Action via vision LLM.

    Called when ``step.fixed`` is False. The implementation sends the current
    screenshot and step description to the LLM with the ``computer_use`` tool
    and parses the response into an Action.
    """

    async def ground(
        self,
        step: SkillStep,
        screenshot: Path | bytes,
        params: dict[str, str],
    ) -> Action:
        """Return a concrete Action for *step* given the current *screenshot*."""
        ...


@typing.runtime_checkable
class SubgoalRunner(typing.Protocol):
    """Runs a mini vision-action loop to recover to a desired screen state.

    Called when ``valid_state`` does not match. The implementation executes
    up to ``max_steps`` vision-action cycles, each time checking whether the
    goal state has been reached. The accumulated action summaries are returned
    so the caller can include them in the outer history.
    """

    async def run_subgoal(
        self,
        goal: str,
        screenshot: Path | bytes,
        *,
        max_steps: int = 3,
    ) -> SubgoalResult:
        """Navigate towards *goal* starting from *screenshot*."""
        ...


@typing.runtime_checkable
class ScreenshotProvider(typing.Protocol):
    """Provides the current screen screenshot as a Path or bytes object."""

    async def get_screenshot(self) -> Path | bytes | None:
        """Capture and return the current screenshot."""
        ...


# ---------------------------------------------------------------------------
# LLM-based state validator
# ---------------------------------------------------------------------------

_VALIDATION_PROMPT = """\
Look at this screenshot and answer: does the current screen state match \
the following description?

Expected state: {valid_state}

Respond with ONLY a JSON object: {{"valid": true/false, "reason": "one-line"}}
"""


class LLMStateValidator:
    """Validate screen state using a vision LLM."""

    def __init__(self, llm: LLMProvider, image_scale_ratio: float = 0.5) -> None:
        self._llm = llm
        self._image_scale_ratio = _normalize_image_scale_ratio(image_scale_ratio)
        self._usage_accum: dict[str, int] = {}

    def drain_usage(self) -> dict[str, int]:
        """Return accumulated token usage since last drain and reset the counter."""
        usage = dict(self._usage_accum)
        self._usage_accum.clear()
        return usage

    async def validate(
        self,
        valid_state: str,
        screenshot: Path | bytes | None = None,
    ) -> bool:
        if _should_skip_validation(valid_state):
            return True

        if screenshot is None:
            logger.warning("No screenshot for state validation; allowing execution")
            return True

        prompt = _VALIDATION_PROMPT.format(valid_state=valid_state)

        raw = screenshot.read_bytes() if isinstance(screenshot, Path) else screenshot
        image_data = base64.b64encode(
            _scale_image(raw, scale_ratio=self._image_scale_ratio)
        ).decode()
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
        ]

        messages = [{"role": "user", "content": content}]
        try:
            response = await self._llm.chat(messages)
        except Exception as exc:
            logger.error("State validation LLM call failed: %s", exc)
            return True  # Fail-open on LLM error

        for k, v in (response.usage or {}).items():
            self._usage_accum[k] = self._usage_accum.get(k, 0) + v
        return self._parse_response(response.content)

    @staticmethod
    def _parse_response(text: str) -> bool:
        import json as _json
        text = text.strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                obj = _json.loads(match.group(0))
                valid = obj.get("valid", obj.get("is_valid", obj.get("match")))
                if isinstance(valid, bool):
                    return valid
                if isinstance(valid, str):
                    return valid.strip().lower() in ("true", "yes", "matched")
            except _json.JSONDecodeError:
                pass
        lowered = text.lower()
        if "true" in lowered or "yes" in lowered or "match" in lowered:
            return True
        return False


def _should_skip_validation(valid_state: str | None) -> bool:
    """Return True when valid_state indicates no verification is needed."""
    if not valid_state:
        return True
    lowered = valid_state.strip().lower()
    skip_hints = ("no need to verify", "return true", "skip", "none", "n/a")
    return any(hint in lowered for hint in skip_hints)


def _normalize_image_scale_ratio(scale_ratio: float | None) -> float:
    """Normalize user-provided image scaling ratio to a safe range."""
    if scale_ratio is None:
        return 0.5
    try:
        value = float(scale_ratio)
    except (TypeError, ValueError):
        return 0.5
    if value <= 0:
        return 0.5
    return min(1.0, value)


def _scale_image(data: bytes, *, scale_ratio: float = 0.5) -> bytes:
    """Return *data* scaled by *scale_ratio* as PNG bytes.

    Falls back to the original bytes if PIL is unavailable or the image cannot
    be decoded (e.g. non-PNG/JPEG formats the LLM provider may still accept).
    """
    scale_ratio = _normalize_image_scale_ratio(scale_ratio)
    if scale_ratio >= 1.0:
        return data
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            scaled = img.resize(
                (max(1, int(w * scale_ratio)), max(1, int(h * scale_ratio))),
                Image.LANCZOS,
            )
            buf = io.BytesIO()
            scaled.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return data


def _scale_image_half(data: bytes) -> bytes:
    """Backward-compatible helper for existing call sites."""
    return _scale_image(data, scale_ratio=0.5)


# ---------------------------------------------------------------------------
# Parameter grounding helpers
# ---------------------------------------------------------------------------

def _ground_text(text: str, params: dict[str, str]) -> str:
    """Replace ``{{param}}`` placeholders with actual values."""
    for key, value in params.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    remaining = re.findall(r"\{\{(\w+)\}\}", text)
    if remaining:
        logger.warning("Unresolved placeholders: %s", remaining)
    return text


def _build_fixed_action(step: SkillStep, params: dict[str, str]) -> Action:
    """Construct an Action from ``step.fixed_values``.

    ``fixed_values`` holds concrete parameter values (coordinates, text, etc.)
    that bypass LLM grounding entirely. Template substitution is still applied
    to string values so that ``{{param}}`` placeholders in text fields resolve
    correctly.
    """
    values: dict[str, Any] = {}
    for k, v in step.fixed_values.items():
        values[k] = _ground_text(str(v), params) if isinstance(v, str) else v

    kwargs: dict[str, Any] = {"action_type": step.action_type}
    if "x" in values:
        kwargs["x"] = float(values["x"])
    if "y" in values:
        kwargs["y"] = float(values["y"])
    if "x2" in values:
        kwargs["x2"] = float(values["x2"])
    if "y2" in values:
        kwargs["y2"] = float(values["y2"])
    if "text" in values:
        kwargs["text"] = values["text"]
    if "key" in values:
        kwargs["key"] = values["key"]
    if "pixels" in values:
        kwargs["pixels"] = int(values["pixels"])
    if "duration_ms" in values:
        kwargs["duration_ms"] = int(values["duration_ms"])
    if "relative" in values:
        kwargs["relative"] = bool(values["relative"])
    return Action(**kwargs)


def _build_template_action(step: SkillStep, params: dict[str, str]) -> Action:
    """Construct an Action via template substitution (legacy / fallback path).

    Used when no ``ActionGrounder`` is provided or when callers do not supply
    one. Mirrors the original ``_ground_step`` behaviour.
    """
    target = _ground_text(step.target, params)
    grounded: dict[str, Any] = {}
    for k, v in step.parameters.items():
        grounded[k] = _ground_text(str(v), params) if isinstance(v, str) else v

    kwargs: dict[str, Any] = {"action_type": step.action_type}
    if "x" in grounded:
        kwargs["x"] = float(grounded["x"])
    if "y" in grounded:
        kwargs["y"] = float(grounded["y"])
    if "text" in grounded:
        kwargs["text"] = grounded["text"]
    elif step.action_type == "input_text":
        kwargs["text"] = target
    elif step.action_type == "open_app":
        kwargs["text"] = target
    return Action(**kwargs)


# ---------------------------------------------------------------------------
# Execution summary formatter
# ---------------------------------------------------------------------------

def _build_execution_summary(skill: Skill, step_results: list[StepResult]) -> str:
    """Build a human-readable narrative of the skill execution for the agent loop."""
    succeeded = sum(1 for r in step_results if r.state == ExecutionState.SUCCEEDED)
    total = len(skill.steps)

    lines = [f'Skill "{skill.name}" executed ({succeeded}/{total} steps succeeded):']
    for r in step_results:
        status_tag = "succeeded" if r.state == ExecutionState.SUCCEEDED else "failed"
        mode_tag = f"[{r.grounding_mode}]"
        recovery_tag = ""
        if r.recovery_attempted:
            if r.recovery_result and r.recovery_result.success:
                recovery_tag = f" [recovered in {r.recovery_result.steps_taken} sub-steps]"
            else:
                recovery_tag = " [recovery failed]"
        summary_text = f" — {r.action_summary}" if r.action_summary else ""
        lines.append(
            f"  Step {r.step_index + 1}: {r.action.action_type} {mode_tag}"
            f"{recovery_tag}{summary_text} — {status_tag}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SkillExecutor
# ---------------------------------------------------------------------------

@dataclass
class SkillExecutor:
    """Execute a :class:`Skill` step-by-step with agent-integrated validation.

    Parameters
    ----------
    backend:
        Device backend for action execution.
    state_validator:
        Optional LLM-based validator for per-step ``valid_state`` checks.
        Falls back to pass-through (allow) when ``None``.
    action_grounder:
        Optional vision-LLM grounder for non-fixed steps. When ``None``,
        falls back to template substitution (legacy behaviour).
    subgoal_runner:
        Optional mini agent-loop runner for recovering from a failed
        ``valid_state`` check. When ``None``, validation failures fail the
        step immediately (legacy behaviour).
    screenshot_provider:
        Optional async provider for the current screenshot. Falls back to
        ``None`` screenshots (validation is skipped) when not supplied.
    stop_on_failure:
        Whether to halt execution on the first non-optional step failure.
    max_recovery_steps:
        Maximum vision-action steps allowed inside a single recovery subgoal.
    """

    backend: DeviceBackend
    state_validator: StateValidator | None = None
    action_grounder: ActionGrounder | None = None
    subgoal_runner: SubgoalRunner | None = None
    screenshot_provider: ScreenshotProvider | None = None
    trajectory_recorder: TrajectoryRecorder | None = None
    stop_on_failure: bool = True
    max_recovery_steps: int = 3

    async def execute(
        self,
        skill: Skill,
        params: dict[str, str] | None = None,
        *,
        timeout: float = 5.0,
    ) -> SkillExecutionResult:
        """Run all steps of *skill* sequentially with state verification."""
        params = params or {}
        step_results: list[StepResult] = []
        overall_state = ExecutionState.RUNNING
        error_msg: str | None = None
        total_token_usage: dict[str, int] = {}
        # valid_state strings confirmed by a high-confidence done judgment;
        # subsequent steps sharing the same valid_state skip LLM re-validation.
        confirmed_valid_states: set[str] = set()

        if self.trajectory_recorder is not None:
            self.trajectory_recorder.record_event(
                "skill_execution_start",
                skill_id=skill.skill_id,
                skill_name=skill.name,
                step_count=len(skill.steps),
            )

        for i, step in enumerate(skill.steps):
            is_optional = bool(step.parameters.get("optional", False))
            step_start = time.monotonic()
            validate_usage: dict[str, int] = {}
            grounding_usage: dict[str, int] = {}
            validate_dur = 0.0
            grounding_dur = 0.0

            # ------------------------------------------------------------------
            # 1. Capture current screenshot
            # ------------------------------------------------------------------
            screenshot = await self._get_screenshot()

            # ------------------------------------------------------------------
            # 2. Valid-state check
            #    Skip when the state was already confirmed via a done judgment
            #    in an earlier recovery within this execution.
            # ------------------------------------------------------------------
            if step.valid_state and step.valid_state in confirmed_valid_states:
                logger.debug(
                    "Step %d: valid_state %r confirmed by prior done judgment, skipping check",
                    i, step.valid_state,
                )
                valid, validate_usage, validate_dur = True, {}, None
            else:
                valid, validate_usage, validate_dur = await self._validate_state(step, screenshot)
            _merge_usage(total_token_usage, validate_usage)

            # ------------------------------------------------------------------
            # 3. Recovery subgoal when valid_state fails
            # ------------------------------------------------------------------
            recovery_result: SubgoalResult | None = None
            if not valid and not _should_skip_validation(step.valid_state):
                if self.subgoal_runner is not None and screenshot is not None:
                    logger.info(
                        "Step %d: valid_state failed, attempting recovery for: %r",
                        i, step.valid_state,
                    )
                    recovery_result = await self.subgoal_runner.run_subgoal(
                        goal=step.valid_state or "",
                        screenshot=screenshot,
                        max_steps=self.max_recovery_steps,
                    )
                    _merge_usage(total_token_usage, recovery_result.token_usage)
                    if recovery_result.success:
                        if recovery_result.done_judgment:
                            # Model explicitly declared goal reached — treat as
                            # highest-confidence signal; skip re-validation and
                            # record this state as confirmed for future steps.
                            valid = True
                            logger.info(
                                "Step %d: recovery succeeded via done judgment, "
                                "skipping re-validation",
                                i,
                            )
                            if step.valid_state:
                                confirmed_valid_states.add(step.valid_state)
                                logger.debug(
                                    "Step %d: added %r to confirmed_valid_states",
                                    i, step.valid_state,
                                )
                        else:
                            # Standard recovery: refresh screenshot and re-validate.
                            screenshot = recovery_result.final_screenshot or screenshot
                            revalidate_result, revalidate_usage, revalidate_dur = await self._validate_state(step, screenshot)
                            valid = revalidate_result
                            _merge_usage(total_token_usage, revalidate_usage)
                            _merge_usage(validate_usage, revalidate_usage)
                            validate_dur += revalidate_dur
                            if not valid:
                                logger.warning(
                                    "Step %d: re-validation after recovery still failed", i
                                )
                    else:
                        logger.warning(
                            "Step %d: recovery exhausted (%d sub-steps), "
                            "valid_state still not reached",
                            i, recovery_result.steps_taken,
                        )
                else:
                    logger.info(
                        "Step %d: valid_state failed, no subgoal_runner available", i
                    )

            # ------------------------------------------------------------------
            # 4. If still invalid, record failure and decide whether to continue
            # ------------------------------------------------------------------
            if not valid and not _should_skip_validation(step.valid_state):
                step_dur = time.monotonic() - step_start
                step_result = StepResult(
                    step_index=i,
                    action=Action(action_type=step.action_type),
                    backend_result="",
                    state=ExecutionState.FAILED,
                    valid_state_check=False,
                    recovery_attempted=recovery_result is not None,
                    recovery_result=recovery_result,
                    error=f"valid_state not reached: {step.valid_state}",
                    token_usage=dict(validate_usage),
                    duration_s=step_dur,
                    validate_duration_s=validate_dur,
                )
                step_results.append(step_result)
                self._record_skill_step(skill, step, step_result)
                if is_optional:
                    logger.info("Optional step %d skipped (valid_state not reached)", i)
                    continue
                overall_state = ExecutionState.FAILED
                error_msg = f"Step {i} valid_state not reached: {step.valid_state}"
                if self.stop_on_failure:
                    break
                continue

            # ------------------------------------------------------------------
            # 5. Execute action
            # ------------------------------------------------------------------
            try:
                action, grounding_mode, grounding_usage, grounding_dur = await self._resolve_action(
                    step, screenshot, params
                )
                _merge_usage(total_token_usage, grounding_usage)
                result_text = await self.backend.execute(action, timeout=timeout)
                # Allow the UI to settle before the next step's
                # screenshot / validate / grounding cycle.
                if action.action_type == "open_app":
                    await asyncio.sleep(2.0)
                elif action.action_type not in _NO_SETTLE_ACTIONS:
                    await asyncio.sleep(_POST_ACTION_SETTLE_SECONDS)
                step_dur = time.monotonic() - step_start
                step_token_usage = dict(validate_usage)
                _merge_usage(step_token_usage, grounding_usage)
                step_result = StepResult(
                    step_index=i,
                    action=action,
                    backend_result=result_text,
                    state=ExecutionState.SUCCEEDED,
                    grounding_mode=grounding_mode,
                    recovery_attempted=recovery_result is not None,
                    recovery_result=recovery_result,
                    action_summary=f"{action.action_type} on {step.target or 'target'}",
                    token_usage=step_token_usage,
                    duration_s=step_dur,
                    validate_duration_s=validate_dur,
                    grounding_duration_s=grounding_dur,
                )
                step_results.append(step_result)
                self._record_skill_step(skill, step, step_result)
            except Exception as exc:
                logger.error("Step %d execution error: %s", i, exc)
                step_dur = time.monotonic() - step_start
                step_result = StepResult(
                    step_index=i,
                    action=Action(action_type=step.action_type),
                    backend_result=str(exc),
                    state=ExecutionState.FAILED,
                    recovery_attempted=recovery_result is not None,
                    recovery_result=recovery_result,
                    error=str(exc),
                    token_usage=dict(validate_usage),
                    duration_s=step_dur,
                    validate_duration_s=validate_dur,
                )
                step_results.append(step_result)
                self._record_skill_step(skill, step, step_result)
                if is_optional:
                    logger.info("Optional step %d failed with exception, continuing", i)
                    continue
                overall_state = ExecutionState.FAILED
                error_msg = f"Step {i} execution failed: {exc}"
                if self.stop_on_failure:
                    break
                continue

        if overall_state != ExecutionState.FAILED:
            overall_state = ExecutionState.SUCCEEDED

        result = SkillExecutionResult(
            skill=skill,
            step_results=step_results,
            state=overall_state,
            execution_summary=_build_execution_summary(skill, step_results),
            error=error_msg,
            token_usage=total_token_usage,
        )
        if self.trajectory_recorder is not None:
            self.trajectory_recorder.record_event(
                "skill_execution_result",
                skill_id=skill.skill_id,
                skill_name=skill.name,
                state=result.state.value,
                execution_summary=result.execution_summary,
                error=result.error,
            )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_action(
        self,
        step: SkillStep,
        screenshot: Path | bytes | None,
        params: dict[str, str],
    ) -> tuple[Action, str, dict[str, int], float]:
        """Return ``(action, grounding_mode, token_usage, duration_s)`` for the given step."""
        if step.fixed:
            return _build_fixed_action(step, params), "fixed", {}, 0.0

        if self.action_grounder is not None and screenshot is not None:
            try:
                t0 = time.monotonic()
                action = await self.action_grounder.ground(step, screenshot, params)
                duration = time.monotonic() - t0
                usage: dict[str, int] = {}
                if hasattr(self.action_grounder, "drain_usage"):
                    usage = self.action_grounder.drain_usage()
                return action, "llm", usage, duration
            except Exception as exc:
                logger.warning(
                    "ActionGrounder failed for step %r, falling back to template: %s",
                    step.action_type, exc,
                )

        return _build_template_action(step, params), "template", {}, 0.0

    def _record_skill_step(self, skill: Skill, step: SkillStep, step_result: StepResult) -> None:
        if self.trajectory_recorder is None:
            return
        self.trajectory_recorder.record_event(
            "skill_step",
            skill_id=skill.skill_id,
            skill_name=skill.name,
            step_index=step_result.step_index,
            target=step.target,
            action=_serialize_action(step_result.action),
            action_summary=step_result.action_summary,
            grounding_mode=step_result.grounding_mode,
            backend_result=step_result.backend_result,
            valid_state=step.valid_state,
            valid_state_check=step_result.valid_state_check,
            recovery_attempted=step_result.recovery_attempted,
            recovery_success=bool(step_result.recovery_result and step_result.recovery_result.success),
            error=step_result.error,
            token_usage=step_result.token_usage or None,
            duration_s=round(step_result.duration_s, 3) if step_result.duration_s else None,
            validate_duration_s=round(step_result.validate_duration_s, 3) if step_result.validate_duration_s is not None else None,
            grounding_duration_s=round(step_result.grounding_duration_s, 3) if step_result.grounding_duration_s is not None else None,
        )

    async def _validate_state(
        self,
        step: SkillStep,
        screenshot: Path | bytes | None,
    ) -> tuple[bool, dict[str, int], float | None]:
        """Validate per-step valid_state. Returns ``(valid, token_usage, duration_s)``.

        ``duration_s`` is ``None`` when validation is intentionally skipped
        (no ``valid_state`` description, no validator configured, or state
        confirmed by a prior done-judgment). A positive float indicates an
        actual LLM validation call was made.

        Note: ``step.fixed`` controls *action grounding* (use pre-recorded
        coordinates instead of LLM grounding), not state validation. A fixed
        step with a meaningful ``valid_state`` still requires verification.
        """
        if _should_skip_validation(step.valid_state):
            return True, {}, None
        if self.state_validator is None:
            logger.debug("No state validator; allowing step %s", step.action_type)
            return True, {}, None
        t0 = time.monotonic()
        try:
            result = await self.state_validator.validate(
                step.valid_state or "",
                screenshot=screenshot,
            )
        except Exception as exc:
            logger.error("State validator error: %s", exc)
            return True, {}, None  # Fail-open
        duration = time.monotonic() - t0
        usage: dict[str, int] = {}
        if hasattr(self.state_validator, "drain_usage"):
            usage = self.state_validator.drain_usage()
        return result, usage, duration

    async def _get_screenshot(self) -> Path | bytes | None:
        """Capture the current screenshot via the ScreenshotProvider."""
        if self.screenshot_provider is not None:
            try:
                return await self.screenshot_provider.get_screenshot()
            except Exception as exc:
                logger.warning("ScreenshotProvider failed: %s", exc)
        return None


def _serialize_action(action: Action) -> dict[str, Any]:
    payload = dataclasses.asdict(action)
    return {
        key: value
        for key, value in payload.items()
        if value is not None and not (key == "relative" and value is False)
    }


def _merge_usage(target: dict[str, int], source: dict[str, int]) -> None:
    """Merge *source* token counts into *target* in-place, summing each key."""
    for k, v in source.items():
        target[k] = target.get(k, 0) + v
