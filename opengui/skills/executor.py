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
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from opengui.action import Action, ActionError, parse_action
from opengui.interfaces import DeviceBackend
from opengui.observation import Observation
from opengui.skills.data import Skill, SkillStep
from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.state_contract import (
    evaluate_state_contract_detail,
    normalize_state_contract,
)

if typing.TYPE_CHECKING:
    from opengui.interfaces import LLMProvider
    from opengui.trajectory.recorder import TrajectoryRecorder

logger = logging.getLogger(__name__)

_POST_ACTION_SETTLE_SECONDS: float = 0.50
_OPEN_APP_SETTLE_SECONDS: float = 4.00
_OPEN_DEEPLINK_POST_VALIDATE_ATTEMPTS: int = 3
_OPEN_DEEPLINK_POST_VALIDATE_RETRY_SECONDS: float = 1.00
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
    observation: dict[str, Any] | None = None
    screenshot_path: str | None = None
    contract_eval_detail: dict[str, Any] | None = None


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


@typing.runtime_checkable
class ObservationProvider(ScreenshotProvider, typing.Protocol):
    """Provides a full observation with screenshot and structured metadata."""

    async def get_observation(self) -> Observation | None:
        """Capture and return the current observation."""
        ...


# ---------------------------------------------------------------------------
# LLM-based state validator
# ---------------------------------------------------------------------------

_VALIDATION_PROMPT = """\
Look at this screenshot and answer: does the current screen state match \
the following description?

Expected state: {valid_state}

Respond with ONLY a JSON object: {{"valid": true/false}}
"""


class LLMStateValidator:
    """Validate screen state using a vision LLM."""

    def __init__(self, llm: LLMProvider, image_scale_ratio: float = 0.5) -> None:
        self._llm = llm
        self._image_scale_ratio = _normalize_image_scale_ratio(image_scale_ratio)
        self._usage_accum: dict[str, int] = {}
        self._ttft_samples: list[float] = []
        self._latency_samples: list[float] = []

    def drain_usage(self) -> dict[str, int]:
        """Return accumulated token usage since last drain and reset the counter."""
        usage = dict(self._usage_accum)
        self._usage_accum.clear()
        return usage

    def drain_timings(self) -> dict[str, float]:
        """Return mean ttft_s / chat_latency_s across samples and reset."""
        out: dict[str, float] = {}
        if self._ttft_samples:
            out["ttft_s"] = sum(self._ttft_samples) / len(self._ttft_samples)
        if self._latency_samples:
            out["chat_latency_s"] = sum(self._latency_samples) / len(self._latency_samples)
        self._ttft_samples.clear()
        self._latency_samples.clear()
        return out

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
        if getattr(response, "ttft_s", None) is not None:
            self._ttft_samples.append(response.ttft_s)
        if getattr(response, "latency_s", None) is not None:
            self._latency_samples.append(response.latency_s)
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


_VOLATILE_CONTRACT_STATE_FLAGS: frozenset[str] = frozenset({"clickable", "enabled", "focused"})


def _can_relax_contract_failure(detail: Any) -> bool:
    """Allow relaxation only for selector state evidence, never identity anchors."""
    failed_required = list(getattr(detail, "failed_required", []) or [])
    unknown_required = list(getattr(detail, "unknown_required", []) or [])
    for item in failed_required + unknown_required:
        if isinstance(item, dict) and "anchor" in item:
            return False
    return bool(failed_required or unknown_required)


def _relax_state_contract_flags(contract: Any) -> dict[str, Any] | None:
    """Strip volatile UI state flags while preserving app and selector anchors."""
    normalized = normalize_state_contract(contract)
    if not normalized:
        return None

    signature = normalized.get("signature", {})
    required: list[dict[str, Any]] = []
    changed = False
    for element in signature.get("required", []) or []:
        selector = element.get("selector") if isinstance(element.get("selector"), dict) else {}
        states = [str(state) for state in (element.get("state") or []) if str(state)]
        if not selector:
            required.append(dict(element))
            continue
        relaxed_states = [
            state for state in states if state not in _VOLATILE_CONTRACT_STATE_FLAGS
        ]
        if "visible" not in relaxed_states:
            relaxed_states.append("visible")
        if relaxed_states != states:
            changed = True
        required.append({
            "selector": dict(selector),
            "state": relaxed_states,
        })

    if not changed:
        return None
    return normalize_state_contract({
        "anchor": dict(normalized.get("anchor", {})),
        "signature": {
            "required": required,
            "forbidden": list(signature.get("forbidden", []) or []),
        },
        "mask_rules": list(normalized.get("mask_rules", []) or []),
    })


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
    if "component" in values:
        kwargs["component"] = str(values["component"])
    if "package" in values:
        kwargs["package"] = str(values["package"])
    if "intent_action" in values:
        kwargs["intent_action"] = str(values["intent_action"])
    if "mime_type" in values:
        kwargs["mime_type"] = str(values["mime_type"])
    if "categories" in values:
        raw_categories = values["categories"]
        kwargs["categories"] = tuple(str(item) for item in raw_categories) if isinstance(raw_categories, (list, tuple)) else (str(raw_categories),)
    if "extras" in values:
        raw_extras = values["extras"]
        if isinstance(raw_extras, dict):
            kwargs["extras"] = tuple(raw_extras.items())
        elif isinstance(raw_extras, (list, tuple)):
            kwargs["extras"] = tuple(tuple(item) for item in raw_extras)
    if "relative" in values:
        kwargs["relative"] = bool(values["relative"])
    return Action(**kwargs)


def _build_template_action(step: SkillStep, params: dict[str, str]) -> Action:
    """Construct an Action via template substitution (legacy / fallback path).

    Used when no ``ActionGrounder`` is provided or when callers do not supply
    one. Mirrors the original ``_ground_step`` behaviour.
    """
    payload = _build_template_payload(step, params)
    return _lenient_action_from_payload(payload)


def _build_template_payload(step: SkillStep, params: dict[str, str]) -> dict[str, Any]:
    """Build a raw action payload from step templates and runtime parameters."""
    target = _ground_text(step.target, params)
    grounded: dict[str, Any] = {}
    for k, v in step.parameters.items():
        grounded[k] = _ground_text(str(v), params) if isinstance(v, str) else v

    payload: dict[str, Any] = {"action_type": step.action_type}
    for key in (
        "x",
        "y",
        "x2",
        "y2",
        "text",
        "key",
        "pixels",
        "duration_ms",
        "component",
        "package",
        "intent_action",
        "mime_type",
        "categories",
        "extras",
        "relative",
        "status",
        "auto_enter",
    ):
        if key in grounded:
            payload[key] = grounded[key]
    if "text" not in payload and step.action_type in {
        "input_text",
        "open_app",
        "open_deeplink",
        "close_app",
    }:
        payload["text"] = target
    return payload


def _lenient_action_from_payload(payload: dict[str, Any]) -> Action:
    """Create an Action while preserving legacy permissive template fallback."""
    kwargs: dict[str, Any] = {"action_type": str(payload.get("action_type") or "")}
    for key in ("x", "y", "x2", "y2"):
        if key in payload:
            kwargs[key] = float(payload[key])
    if "text" in payload:
        kwargs["text"] = str(payload["text"])
    if "key" in payload:
        raw_key = payload["key"]
        kwargs["key"] = [str(item) for item in raw_key] if isinstance(raw_key, list) else [str(raw_key)]
    if "pixels" in payload:
        kwargs["pixels"] = int(payload["pixels"])
    if "duration_ms" in payload:
        kwargs["duration_ms"] = int(payload["duration_ms"])
    if "component" in payload:
        kwargs["component"] = str(payload["component"])
    if "package" in payload:
        kwargs["package"] = str(payload["package"])
    if "intent_action" in payload:
        kwargs["intent_action"] = str(payload["intent_action"])
    if "mime_type" in payload:
        kwargs["mime_type"] = str(payload["mime_type"])
    if "categories" in payload:
        raw_categories = payload["categories"]
        kwargs["categories"] = tuple(str(item) for item in raw_categories) if isinstance(raw_categories, (list, tuple)) else (str(raw_categories),)
    if "extras" in payload:
        raw_extras = payload["extras"]
        if isinstance(raw_extras, dict):
            kwargs["extras"] = tuple(raw_extras.items())
        elif isinstance(raw_extras, (list, tuple)):
            kwargs["extras"] = tuple(tuple(item) for item in raw_extras)
    if "relative" in payload:
        kwargs["relative"] = bool(payload["relative"])
    if "status" in payload:
        kwargs["status"] = str(payload["status"])
    if "auto_enter" in payload:
        kwargs["auto_enter"] = bool(payload["auto_enter"])
    return Action(**kwargs)


def _try_build_complete_template_action(
    step: SkillStep,
    params: dict[str, str],
) -> Action | None:
    """Return a fully-resolved template action when no visual grounding is needed."""
    try:
        action = parse_action(_build_template_payload(step, params))
    except (ActionError, TypeError, ValueError):
        return None
    for value in (action.text, *(action.key or ())):
        if isinstance(value, str) and re.search(r"\{\{\w+\}\}", value):
            return None
    return action


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
    _last_contract_eval_detail: dict[str, Any] | None = dataclasses.field(
        default=None,
        init=False,
        repr=False,
    )

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
        visual_guarded_skill = "visual_guarded" in {
            str(tag) for tag in (getattr(skill, "tags", ()) or ())
        }

        if self.trajectory_recorder is not None:
            self.trajectory_recorder.record_event(
                "skill_execution_start",
                skill_id=skill.skill_id,
                skill_name=skill.name,
                step_count=len(skill.steps),
            )

        for i, step in enumerate(skill.steps):
            self._last_contract_eval_detail = None
            is_optional = bool(step.parameters.get("optional", False))
            post_action_contract = (
                step.action_type in {"open_deeplink", "open_intent"}
                and step.state_contract is not None
            )
            step_start = time.monotonic()
            validate_usage: dict[str, int] = {}
            grounding_usage: dict[str, int] = {}
            validate_dur = 0.0
            grounding_dur = 0.0
            visual_guard_block_reason: str | None = None

            # ------------------------------------------------------------------
            # 1. Capture current screenshot
            # ------------------------------------------------------------------
            observation, screenshot = await self._get_observation_and_screenshot()

            # ------------------------------------------------------------------
            # 2. Valid-state check
            #    Skip when the state was already confirmed via a done judgment
            #    in an earlier recovery within this execution.
            # ------------------------------------------------------------------
            visual_guarded_step = (
                visual_guarded_skill
                and not post_action_contract
                and step.action_type not in {"open_app", "open_deeplink", "open_intent", "wait", "done", "request_intervention"}
            )
            if visual_guarded_step and not step.valid_state:
                visual_guard_block_reason = "missing visual valid_state"
                valid, validate_usage, validate_dur = False, {}, None
            elif visual_guarded_step and self.state_validator is None:
                visual_guard_block_reason = "missing state validator"
                valid, validate_usage, validate_dur = False, {}, None
            elif visual_guarded_step and screenshot is None:
                visual_guard_block_reason = "missing screenshot"
                valid, validate_usage, validate_dur = False, {}, None
            elif post_action_contract:
                valid, validate_usage, validate_dur = True, {}, None
            elif step.valid_state and step.valid_state in confirmed_valid_states:
                logger.debug(
                    "Step %d: valid_state %r confirmed by prior done judgment, skipping check",
                    i, step.valid_state,
                )
                valid, validate_usage, validate_dur = True, {}, None
            else:
                valid, validate_usage, validate_dur = await self._validate_state(
                    step,
                    screenshot,
                    observation=observation,
                )
            _merge_usage(total_token_usage, validate_usage)

            # ------------------------------------------------------------------
            # 3. Recovery subgoal when valid_state fails
            # ------------------------------------------------------------------
            recovery_result: SubgoalResult | None = None
            should_enforce_state = (
                visual_guarded_step
                or not post_action_contract
                and (
                    step.state_contract is not None
                    or not _should_skip_validation(step.valid_state)
                )
            )
            if not valid and should_enforce_state and visual_guard_block_reason is None:
                can_recover_with_subgoal = (
                    not _should_skip_validation(step.valid_state)
                    and self.subgoal_runner is not None
                    and screenshot is not None
                )
                if can_recover_with_subgoal:
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
                            fresh_observation, fresh_screenshot = await self._get_observation_and_screenshot()
                            observation = fresh_observation or observation
                            screenshot = (
                                fresh_screenshot
                                or recovery_result.final_screenshot
                                or screenshot
                            )
                            revalidate_result, revalidate_usage, revalidate_dur = await self._validate_state(
                                step,
                                screenshot,
                                observation=observation,
                            )
                            valid = revalidate_result
                            _merge_usage(total_token_usage, revalidate_usage)
                            _merge_usage(validate_usage, revalidate_usage)
                            validate_dur = _merge_optional_duration(validate_dur, revalidate_dur)
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
            if not valid and should_enforce_state:
                step_dur = time.monotonic() - step_start
                state_description = step.valid_state or visual_guard_block_reason or "state_contract"
                step_result = StepResult(
                    step_index=i,
                    action=Action(action_type=step.action_type),
                    backend_result="",
                    state=ExecutionState.FAILED,
                    valid_state_check=False,
                    recovery_attempted=recovery_result is not None,
                    recovery_result=recovery_result,
                    error=f"valid_state not reached: {state_description}",
                    token_usage=dict(validate_usage),
                    duration_s=step_dur,
                    validate_duration_s=validate_dur,
                    observation=_serialize_observation(observation),
                    screenshot_path=_screenshot_path_string(screenshot),
                    contract_eval_detail=self._last_contract_eval_detail,
                )
                step_results.append(step_result)
                self._record_skill_step(skill, step, step_result)
                if is_optional:
                    logger.info("Optional step %d skipped (valid_state not reached)", i)
                    continue
                overall_state = ExecutionState.FAILED
                error_msg = f"Step {i} valid_state not reached: {state_description}"
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
                execution_error: Exception | None = None
                try:
                    result_text = await self.backend.execute(action, timeout=timeout)
                except Exception as exc:
                    if not post_action_contract:
                        raise
                    execution_error = exc
                    result_text = str(exc)
                    logger.warning(
                        "Step %d %s raised %s; validating post-state before failing",
                        i,
                        action.action_type,
                        type(exc).__name__,
                    )
                # Allow the UI to settle before the next step's
                # screenshot / validate / grounding cycle.
                if action.action_type in {"open_app", "open_deeplink", "open_intent"}:
                    await asyncio.sleep(_OPEN_APP_SETTLE_SECONDS)
                elif action.action_type not in _NO_SETTLE_ACTIONS:
                    await asyncio.sleep(_POST_ACTION_SETTLE_SECONDS)
                if post_action_contract:
                    post_valid = False
                    attempts = (
                        _OPEN_DEEPLINK_POST_VALIDATE_ATTEMPTS
                        if action.action_type in {"open_deeplink", "open_intent"}
                        else 1
                    )
                    for attempt_index in range(attempts):
                        post_observation, post_screenshot = await self._get_observation_and_screenshot()
                        post_valid, post_usage, post_dur = await self._validate_state(
                            step,
                            post_screenshot,
                            observation=post_observation,
                        )
                        _merge_usage(total_token_usage, post_usage)
                        _merge_usage(validate_usage, post_usage)
                        validate_dur = _merge_optional_duration(validate_dur, post_dur)
                        if post_valid:
                            break
                        if attempt_index < attempts - 1:
                            await asyncio.sleep(_OPEN_DEEPLINK_POST_VALIDATE_RETRY_SECONDS)
                    if post_valid and execution_error is not None and self.trajectory_recorder is not None:
                        self.trajectory_recorder.record_event(
                            "skill_action_error_post_state_ok",
                            skill_id=skill.skill_id,
                            skill_name=skill.name,
                            step_index=i,
                            action_type=action.action_type,
                            error=str(execution_error),
                            exception_type=type(execution_error).__name__,
                        )
                    if not post_valid:
                        step_dur = time.monotonic() - step_start
                        state_description = step.valid_state or "state_contract"
                        error_text = f"post-state not reached: {state_description}"
                        if execution_error is not None:
                            error_text = (
                                f"execution failed and post-state not reached: "
                                f"{state_description}: {execution_error}"
                            )
                        step_result = StepResult(
                            step_index=i,
                            action=action,
                            backend_result=result_text,
                            state=ExecutionState.FAILED,
                            valid_state_check=False,
                            grounding_mode=grounding_mode,
                            recovery_attempted=recovery_result is not None,
                            recovery_result=recovery_result,
                            action_summary=f"{action.action_type} on {step.target or 'target'}",
                            error=error_text,
                            token_usage=dict(validate_usage),
                            duration_s=step_dur,
                            validate_duration_s=validate_dur,
                            grounding_duration_s=grounding_dur,
                            observation=_serialize_observation(post_observation),
                            screenshot_path=_screenshot_path_string(post_screenshot),
                            contract_eval_detail=self._last_contract_eval_detail,
                        )
                        step_results.append(step_result)
                        self._record_skill_step(skill, step, step_result)
                        if is_optional:
                            logger.info("Optional deeplink step %d failed post-state validation", i)
                            continue
                        overall_state = ExecutionState.FAILED
                        error_msg = f"Step {i} post-state not reached: {state_description}"
                        if self.stop_on_failure:
                            break
                        continue
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
                    observation=_serialize_observation(observation),
                    screenshot_path=_screenshot_path_string(screenshot),
                    contract_eval_detail=self._last_contract_eval_detail,
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
            return self._normalize_app_action(_build_fixed_action(step, params)), "fixed", {}, 0.0

        template_action = _try_build_complete_template_action(step, params)
        if template_action is not None:
            return self._normalize_app_action(template_action), "template", {}, 0.0

        if self.action_grounder is not None and screenshot is not None:
            try:
                t0 = time.monotonic()
                action = await self.action_grounder.ground(step, screenshot, params)
                duration = time.monotonic() - t0
                usage: dict[str, int] = {}
                if hasattr(self.action_grounder, "drain_usage"):
                    usage = self.action_grounder.drain_usage()
                return self._normalize_app_action(action), "llm", usage, duration
            except Exception as exc:
                logger.warning(
                    "ActionGrounder failed for step %r, falling back to template: %s",
                    step.action_type, exc,
                )

        return self._normalize_app_action(_build_template_action(step, params)), "template", {}, 0.0

    def _normalize_app_action(self, action: Action) -> Action:
        """Resolve human/cross-platform app identifiers before backend execution."""
        if action.action_type not in ("open_app", "close_app") or not action.text:
            return action
        platform = getattr(self.backend, "platform", None)
        if platform not in ("android", "ios"):
            return action

        resolved = normalize_app_identifier(platform, action.text)
        if resolved == action.text:
            return action
        logger.debug(
            "Resolved %s app %r -> %r for skill execution",
            platform,
            action.text,
            resolved,
        )
        return dataclasses.replace(action, text=resolved)

    def _record_skill_step(self, skill: Skill, step: SkillStep, step_result: StepResult) -> None:
        if self.trajectory_recorder is None:
            return
        timings: dict[str, float] = {}
        for src in (self.action_grounder, self.state_validator):
            drain = getattr(src, "drain_timings", None)
            if callable(drain):
                for k, v in drain().items():
                    timings.setdefault(k, v)
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
            state_contract=step.state_contract,
            valid_state_check=step_result.valid_state_check,
            observation=step_result.observation,
            screenshot_path=step_result.screenshot_path,
            contract_eval_detail=step_result.contract_eval_detail,
            recovery_attempted=step_result.recovery_attempted,
            recovery_success=bool(step_result.recovery_result and step_result.recovery_result.success),
            error=step_result.error,
            token_usage=step_result.token_usage or None,
            duration_s=round(step_result.duration_s, 3) if step_result.duration_s else None,
            validate_duration_s=round(step_result.validate_duration_s, 3) if step_result.validate_duration_s is not None else None,
            grounding_duration_s=round(step_result.grounding_duration_s, 3) if step_result.grounding_duration_s is not None else None,
            chat_latency_s=round(timings["chat_latency_s"], 3) if "chat_latency_s" in timings else None,
            ttft_s=round(timings["ttft_s"], 3) if "ttft_s" in timings else None,
        )

    async def _validate_state(
        self,
        step: SkillStep,
        screenshot: Path | bytes | None,
        *,
        observation: Observation | None = None,
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
        contract_detail = evaluate_state_contract_detail(
            step.state_contract,
            observation=observation,
        )
        self._last_contract_eval_detail = _contract_eval_detail_to_dict(contract_detail)
        if contract_detail.passed is not None:
            if contract_detail.passed is False:
                relaxed_contract = _relax_state_contract_flags(step.state_contract)
                if relaxed_contract is not None and _can_relax_contract_failure(contract_detail):
                    relaxed_detail = evaluate_state_contract_detail(
                        relaxed_contract,
                        observation=observation,
                    )
                    if self._last_contract_eval_detail is not None:
                        self._last_contract_eval_detail["relaxed"] = (
                            _contract_eval_detail_to_dict(relaxed_detail)
                        )
                    if relaxed_detail.passed is True:
                        logger.debug(
                            "State contract relaxed volatile flags for step %s",
                            step.action_type,
                        )
                        if self.trajectory_recorder is not None:
                            self.trajectory_recorder.record_event(
                                "skill_state_contract_relaxed",
                                action_type=step.action_type,
                                original_reason=contract_detail.reason,
                                relaxed_score=round(relaxed_detail.score, 3),
                            )
                        return True, {}, None
            logger.debug(
                "State contract %s for step %s",
                "passed" if contract_detail.passed else "failed",
                step.action_type,
            )
            return bool(contract_detail.passed), {}, None
        if step.state_contract is not None:
            relaxed_contract = _relax_state_contract_flags(step.state_contract)
            if relaxed_contract is not None and _can_relax_contract_failure(contract_detail):
                relaxed_detail = evaluate_state_contract_detail(
                    relaxed_contract,
                    observation=observation,
                )
                if self._last_contract_eval_detail is not None:
                    self._last_contract_eval_detail["relaxed"] = (
                        _contract_eval_detail_to_dict(relaxed_detail)
                    )
                if relaxed_detail.passed is True:
                    logger.debug(
                        "State contract relaxed unevaluable volatile flags for step %s",
                        step.action_type,
                    )
                    if self.trajectory_recorder is not None:
                        self.trajectory_recorder.record_event(
                            "skill_state_contract_relaxed",
                            action_type=step.action_type,
                            original_reason=contract_detail.reason,
                            relaxed_score=round(relaxed_detail.score, 3),
                        )
                    return True, {}, None
            logger.debug(
                "State contract could not be evaluated for step %s; failing closed",
                step.action_type,
            )
            return False, {}, None

        if _should_skip_validation(step.valid_state):
            self._last_contract_eval_detail = None
            return True, {}, None

        if self.state_validator is None:
            logger.debug("No state validator; allowing step %s", step.action_type)
            self._last_contract_eval_detail = None
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

    async def _get_observation_and_screenshot(self) -> tuple[Observation | None, Path | bytes | None]:
        """Capture current observation when the provider supports it."""
        if self.screenshot_provider is not None:
            get_observation = getattr(self.screenshot_provider, "get_observation", None)
            if callable(get_observation):
                try:
                    observation = await get_observation()
                    if observation is not None and observation.screenshot_path:
                        return observation, Path(observation.screenshot_path)
                    return observation, None
                except Exception as exc:
                    logger.warning("ObservationProvider failed: %s", exc)
        return None, await self._get_screenshot()

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


def _serialize_observation(observation: Observation | None) -> dict[str, Any] | None:
    if observation is None:
        return None
    return {
        "screenshot_path": observation.screenshot_path,
        "screen_width": observation.screen_width,
        "screen_height": observation.screen_height,
        "foreground_app": observation.foreground_app,
        "platform": observation.platform,
        "extra": _scrub_trace_value(observation.extra),
    }


def _screenshot_path_string(screenshot: Path | bytes | None) -> str | None:
    return str(screenshot) if isinstance(screenshot, Path) else None


def _contract_eval_detail_to_dict(detail: Any) -> dict[str, Any]:
    return {
        "passed": getattr(detail, "passed", None),
        "score": round(float(getattr(detail, "score", 0.0) or 0.0), 3),
        "evidence_coverage": round(
            float(getattr(detail, "evidence_coverage", 0.0) or 0.0),
            3,
        ),
        "reason": getattr(detail, "reason", None),
        "matched_required": _scrub_trace_value(
            list(getattr(detail, "matched_required", []) or [])
        ),
        "failed_required": _scrub_trace_value(
            list(getattr(detail, "failed_required", []) or [])
        ),
        "unknown_required": _scrub_trace_value(
            list(getattr(detail, "unknown_required", []) or [])
        ),
        "failed_forbidden": _scrub_trace_value(
            list(getattr(detail, "failed_forbidden", []) or [])
        ),
        "unknown_forbidden": _scrub_trace_value(
            list(getattr(detail, "unknown_forbidden", []) or [])
        ),
    }


def _scrub_trace_value(value: Any) -> Any:
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        action_type = value.get("action_type") if isinstance(value.get("action_type"), str) else None
        for key, item in value.items():
            if key == "url" and isinstance(item, str) and item.startswith("data:image/"):
                scrubbed[key] = "<omitted:image-data-url>"
            elif action_type == "input_text" and key == "text":
                scrubbed[key] = "<redacted:input_text>"
            else:
                scrubbed[key] = _scrub_trace_value(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_trace_value(item) for item in value]
    if isinstance(value, tuple):
        return [_scrub_trace_value(item) for item in value]
    return value


def _merge_usage(target: dict[str, int], source: dict[str, int]) -> None:
    """Merge *source* token counts into *target* in-place, summing each key."""
    for k, v in source.items():
        target[k] = target.get(k, 0) + v


def _merge_optional_duration(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right
