"""
opengui.agent
=============
Core GUI automation agent with a vision-action loop.

``GuiAgent`` orchestrates a multi-step loop: observe the screen, call an LLM
with the screenshot, parse the tool-call response into an ``Action``, execute
it on the backend, and repeat until the task is done or max steps is reached.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from opengui.action import Action, ActionError, describe_action, parse_action
from opengui.agent_profiles import (
    build_mobileworld_messages,
    canonicalize_agent_profile,
    coordinate_mode_for_profile,
    normalize_profile_response_for_observation,
    normalize_profile_response_for_screen,
    profile_uses_native_tools,
    prompt_contract_for_profile,
)
from opengui.interfaces import (
    DeviceBackend,
    InterventionHandler,
    InterventionRequest,
    LLMProvider,
    LLMResponse,
    ProgressCallback,
    ToolCall,
)
from opengui.observation import Observation
from opengui.skills.deeplink import AppShortcutProfile
from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.state_contract import evaluate_state_contract, infer_interaction_target
from opengui.tool_schemas import (
    COMPUTER_USE_TOOL,
    build_shortcut_tool_defs,
    image_dimensions,
    minimal_tool_schema,
)
from opengui.trajectory.recorder import ExecutionPhase, TrajectoryRecorder
from opengui.trajectory.summarizer import build_state_note, is_state_note

logger = logging.getLogger(__name__)
_DONE_FAILURE_HINTS: tuple[str, ...] = (
    "fail",
    "failed",
    "failure",
    "unable",
    "cannot",
    "can't",
    "error",
    "not completed",
    "incomplete",
    "失败",
    "无法",
    "不能",
    "错误",
    "未完成",
)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepResult:
    """Result of a single vision-action step."""

    action: Action
    tool_call_id: str
    tool_result: str
    assistant_message: dict[str, Any]
    action_summary: str
    action_intent: str | None = None
    state_summary: str | None = None
    next_observation: Observation | None = None
    interaction_target: dict[str, Any] | None = None
    action_debug: dict[str, Any] | None = None
    prompt_snapshot: dict[str, Any] | None = None
    model_snapshot: dict[str, Any] | None = None
    execution_snapshot: dict[str, Any] | None = None
    intervention_requested: bool = False
    done: bool = False
    step_usage: dict[str, int] = dataclasses.field(default_factory=dict)
    duration_s: float = 0.0
    chat_latency_s: float | None = None
    ttft_s: float | None = None


@dataclass(frozen=True)
class HistoryTurn:
    """One completed step kept in the prompt history window."""

    step_index: int
    observation: Observation
    assistant_message: dict[str, Any]
    tool_result_message: dict[str, Any]
    action_summary: str
    action_intent: str | None = None
    state_summary: str | None = None
    raw_response_content: str | None = None


@dataclass(frozen=True)
class AgentResult:
    """Final result of a complete GUI task run (possibly with retries)."""

    success: bool
    summary: str
    model_summary: str | None = None
    trace_path: str | None = None
    steps_taken: int = 0
    error: str | None = None
    attempt_summary: str | None = None
    token_usage: dict[str, int] = dataclasses.field(default_factory=dict)


@dataclass(frozen=True)
class _ScreenFingerprint:
    """Compact screen signature for loop-stagnation detection."""

    app: str | None
    method: str
    digest: str


class _StepExecutionError(RuntimeError):
    """Runtime error raised from _run_step with optional model snapshot context."""

    def __init__(
        self,
        message: str,
        *,
        model_snapshot: dict[str, Any] | None = None,
        attempt_summary: str | None = None,
    ) -> None:
        super().__init__(message)
        self.model_snapshot = model_snapshot
        self.attempt_summary = attempt_summary


# ---------------------------------------------------------------------------
# Agent-side protocol implementations for SkillExecutor
# ---------------------------------------------------------------------------

from opengui.skills.action_grounder import ActionGrounder as _AgentActionGrounder  # noqa: E402
from opengui.skills.subgoal_runner import SubgoalRunner as _AgentSubgoalRunner  # noqa: E402
from opengui.skills.observation_provider import AgentScreenshotProvider as _AgentScreenshotProvider  # noqa: E402


# ---------------------------------------------------------------------------
# GuiAgent
# ---------------------------------------------------------------------------


def _clean_inferred_param(value: str) -> str:
    return value.strip().strip('`"\'“”‘’').strip()


def _looks_like_date_param(value: str) -> bool:
    return bool(re.search(r"\d+\s*(?:月|号|日|/|-)", value))


_SKILL_PARAM_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_ANDROID_LAUNCHER_PACKAGES = frozenset({
    "com.android.launcher",
    "com.android.launcher3",
    "com.google.android.apps.nexuslauncher",
    "com.miui.home",
})


def _skill_param_names(skill: Any) -> list[str]:
    return [
        str(name).strip()
        for name in (getattr(skill, "parameters", None) or ())
        if str(name).strip()
    ]


def _skill_required_param_names(skill: Any) -> list[str]:
    names = _skill_param_names(skill)
    if not names:
        return []
    placeholders: set[str] = set()
    for step in tuple(getattr(skill, "steps", ()) or ()):
        placeholders.update(_extract_template_placeholders(getattr(step, "target", None)))
        placeholders.update(_extract_template_placeholders(getattr(step, "valid_state", None)))
        placeholders.update(_extract_template_placeholders(getattr(step, "parameters", None)))
        placeholders.update(_extract_template_placeholders(getattr(step, "fixed_values", None)))
        placeholders.update(_extract_template_placeholders(getattr(step, "state_contract", None)))
    required = [name for name in names if name in placeholders]
    return required or names


def _missing_skill_params(skill: Any, params: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for name in _skill_required_param_names(skill):
        value = params.get(name)
        if value is None or not str(value).strip():
            missing.append(name)
    return missing


def _extract_template_placeholders(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {match.group(1) for match in _SKILL_PARAM_PLACEHOLDER_RE.finditer(value)}
    if isinstance(value, dict):
        found: set[str] = set()
        for key, item in value.items():
            found.update(_extract_template_placeholders(key))
            found.update(_extract_template_placeholders(item))
        return found
    if isinstance(value, (list, tuple, set)):
        found: set[str] = set()
        for item in value:
            found.update(_extract_template_placeholders(item))
        return found
    return set()


def _skill_entry_targets_android_launcher(skill: Any, first_step: Any) -> bool:
    platform = str(getattr(skill, "platform", "") or "").strip().lower()
    if platform != "android":
        return False
    candidates: list[str] = [
        str(getattr(skill, "app", "") or ""),
        str(getattr(first_step, "target", "") or ""),
    ]
    fixed_values = getattr(first_step, "fixed_values", None)
    if isinstance(fixed_values, dict):
        for key in ("text", "package", "app", "target"):
            value = fixed_values.get(key)
            if value:
                candidates.append(str(value))
    for candidate in candidates:
        normalized = normalize_app_identifier("android", candidate)
        if normalized in _ANDROID_LAUNCHER_PACKAGES:
            return True
    return False


class GuiAgent:
    """Standalone GUI automation agent with vision-action loop.

    Args:
        llm: LLM provider conforming to :class:`~opengui.interfaces.LLMProvider`.
        backend: Device backend conforming to :class:`~opengui.interfaces.DeviceBackend`.
        model: Model name string (used for prompt customisation).
        artifacts_root: Root directory for run artifacts (traces, screenshots).
        max_steps: Maximum steps per single attempt.
        step_timeout: Timeout in seconds for each step (LLM + execute + observe).
        history_image_window: Number of recent screenshot turns kept as full
            image context, including the current screen.
        include_date_context: Whether to include today's date in the task framing text.
        progress_callback: Optional async callback for progress reporting.
        stagnation_limit: Consecutive unchanged-screen transitions before abort.
    """

    _MAX_TOOL_RETRIES = 2
    _COORDINATE_ACTIONS = frozenset({"tap", "double_tap", "long_press", "swipe", "drag", "scroll"})
    _POST_ACTION_SETTLE_SECONDS = 0.50
    _OPEN_APP_SETTLE_SECONDS = 5.00
    _POST_ACTION_STABILITY_WINDOW_SECONDS = 2.0
    _POST_ACTION_STABILITY_POLL_SECONDS = 0.15
    _POST_ACTION_STABILITY_MAX_ATTEMPTS = 4
    _POST_ACTION_STABILITY_FRAMES_REQUIRED = 2
    _POST_ACTION_OBSERVE_TIMEOUT_SECONDS = 8.0
    _NO_SETTLE_ACTIONS = frozenset({"wait", "done", "request_intervention"})
    _STAGNATION_SSIM_SIZE = 64
    _STAGNATION_SSIM_THRESHOLD = 0.985

    def __init__(
        self,
        llm: LLMProvider,
        backend: DeviceBackend,
        trajectory_recorder: TrajectoryRecorder,
        model: str = "",
        artifacts_root: Path | str = ".opengui/runs",
        max_steps: int = 15,
        step_timeout: float = 30.0,
        history_image_window: int = 3,
        include_date_context: bool = True,
        history_text_window: int = 8,
        progress_callback: ProgressCallback | None = None,
        memory_retriever: Any = None,
        skill_library: Any = None,
        skill_executor: Any = None,
        skill_reuser: Any = None,
        memory_top_k: int = 5,
        skill_threshold: float = 0.35,
        installed_apps: list[str] | None = None,
        shortcut_backend: DeviceBackend | None = None,
        shortcut_cache_dir: Path | str | None = None,
        intervention_handler: InterventionHandler | None = None,
        policy_context: str | None = None,
        memory_store: Any = None,
        agent_profile: str | None = None,
        image_scale_ratio: float = 0.5,
        stagnation_limit: int = 0,
    ) -> None:
        self.llm = llm
        self.backend = backend
        self.model = model
        self.agent_profile = canonicalize_agent_profile(agent_profile)
        self.artifacts_root = Path(artifacts_root)
        self.max_steps = max_steps
        self.step_timeout = step_timeout
        self.history_image_window = max(1, history_image_window)
        self.history_text_window = max(1, history_text_window)
        self.include_date_context = include_date_context
        self.progress_callback = progress_callback
        self._trajectory_recorder = trajectory_recorder
        self._memory_retriever = memory_retriever
        self._policy_context = policy_context
        self._skill_library = skill_library
        self._skill_executor = skill_executor
        self._memory_top_k = memory_top_k
        if skill_reuser is None and skill_library is not None:
            from opengui.skills.reuser import SkillReuser
            skill_reuser = SkillReuser(llm, threshold=skill_threshold)
        self._skill_reuser = skill_reuser
        self._skill_threshold = skill_threshold
        self._installed_apps = installed_apps
        self._shortcuts: dict[str, AppShortcutProfile] = {}
        self._shortcut_backend = shortcut_backend
        self._shortcut_cache_dir = Path(shortcut_cache_dir) if shortcut_cache_dir else None
        self._shortcut_tools: list[dict[str, Any]] = []
        self._shortcut_action_map: dict[str, tuple[str, str, str, str | None]] = {}
        self._intervention_handler = intervention_handler
        self._memory_store = memory_store
        self._active_retry_summaries: tuple[str, ...] = ()
        self._image_scale_ratio = image_scale_ratio
        try:
            parsed_stagnation_limit = int(stagnation_limit)
        except (TypeError, ValueError):
            parsed_stagnation_limit = 0
        self.stagnation_limit = max(0, parsed_stagnation_limit)

    def _build_tools_list(self) -> list[dict[str, Any]]:
        tools = [COMPUTER_USE_TOOL]
        tools.extend(self._shortcut_tools)
        return tools

    async def _ensure_shortcuts_for_app(self, foreground_app: str) -> None:
        """Lazy-load shortcuts when a new foreground app is detected."""
        app = str(foreground_app or "").strip()
        if not app or not self._shortcut_cache_dir or not self._shortcut_backend:
            return
        if str(getattr(self._shortcut_backend, "platform", self.backend.platform)).lower() != "android":
            return
        app = normalize_app_identifier("android", app)
        if not app or app == "unknown":
            return
        if app in self._shortcuts:
            return

        cache_file = self._shortcut_cache_dir / f"{app}.json"
        if cache_file.exists():
            profile = AppShortcutProfile.from_dict(json.loads(cache_file.read_text(encoding="utf-8")))
        else:
            from opengui.skills.deeplink import extract_app_shortcuts

            profile = await extract_app_shortcuts(self._shortcut_backend, app)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        self._shortcuts[app] = profile
        if profile.deep_links or profile.deep_intents:
            self._shortcut_tools, self._shortcut_action_map = build_shortcut_tool_defs(self._shortcuts)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        *,
        max_retries: int = 3,
        app_hint: str | None = None,
    ) -> AgentResult:
        """Run the task with retry logic.

        Returns an :class:`AgentResult` summarising the outcome. On failure
        after all retries, ``success`` is ``False`` and ``error`` contains the
        last error message.
        """
        # 1. Start trajectory recording
        self._trajectory_recorder.start(phase=ExecutionPhase.AGENT)

        # 2. Retrieve memory context (once)
        memory_context = await self._retrieve_memory(task)

        skill_context: str | None = None

        # 3. Search the flat skill library once; LLM-gated when SkillReuser is available.
        reuser_usage: dict[str, int] = {}
        if self._skill_reuser is not None and self._skill_library is not None:
            skill_match = await self._skill_reuser.find(
                task,
                self._skill_library,
                self.backend.platform,
                trajectory_recorder=self._trajectory_recorder,
            )
            reuser_usage = self._skill_reuser.drain_usage()
        else:
            skill_match = await self._search_skill(task)

        matched_skill: Any | None = None
        final_score: float | None = None
        skill_match_for_maintenance: Any | None = skill_match
        if skill_match is not None:
            if hasattr(skill_match, "layer"):
                matched_skill = skill_match.skill
                final_score = skill_match.score
            else:
                matched_skill, final_score = skill_match

        # 4. If skill matched, attempt skill execution first.
        skill_result: Any | None = None
        if matched_skill is not None and self._skill_executor is not None and final_score is not None:
            entry_allowed = await self._skill_entry_allows_current_state(matched_skill)
            if not entry_allowed:
                skill_match_for_maintenance = None
                matched_skill = None
            else:
                memory_context = await self._inject_skill_memory_context(matched_skill, memory_context)
        elif matched_skill is not None:
            memory_context = await self._inject_skill_memory_context(matched_skill, memory_context)

        if matched_skill is not None and self._skill_executor is not None and final_score is not None:
            self._trajectory_recorder.set_phase(
                ExecutionPhase.SKILL,
                reason=f"Matched skill: {matched_skill.name} (score={final_score:.2f})",
            )
            try:
                skill_result = await self._execute_skill_with_params(task, matched_skill)
                execution_summary = getattr(skill_result, "execution_summary", None)
                skill_context = execution_summary if isinstance(execution_summary, str) else None
                if skill_result.state.value == "succeeded":
                    # Skill succeeded — fall through to agent for confirmation
                    self._trajectory_recorder.set_phase(
                        ExecutionPhase.AGENT,
                        reason="Skill complete, agent confirms",
                    )
                else:
                    # Skill partially succeeded — agent completes the rest
                    self._trajectory_recorder.set_phase(
                        ExecutionPhase.AGENT, reason="Skill partially succeeded, agent completes"
                    )
            except Exception:
                # Skill failed — fall back to free exploration
                self._trajectory_recorder.set_phase(
                    ExecutionPhase.AGENT, reason="Skill execution failed, falling back"
                )

        # 5. Retry loop with free exploration
        last_error: str | None = None
        last_model_summary: str | None = None
        last_trace_path: str | None = None
        last_steps_taken = 0
        result: AgentResult | None = None
        retry_summaries: list[str] = []
        # Seed total_usage with tokens consumed during skill retrieval + execution (if any)
        skill_token_usage: dict[str, int] = {}
        if skill_result is not None:
            raw_skill_token_usage = getattr(skill_result, "token_usage", None)
            if isinstance(raw_skill_token_usage, dict):
                skill_token_usage = dict(raw_skill_token_usage)
        total_usage: dict[str, int] = dict(skill_token_usage)
        for k, v in reuser_usage.items():
            total_usage[k] = total_usage.get(k, 0) + v

        try:
            for attempt in range(max_retries):
                self._active_retry_summaries = tuple(retry_summaries)
                run_dir = self._make_run_dir(task, attempt)
                last_trace_path = str(run_dir)

                await self._log_attempt_event(
                    run_dir,
                    "attempt_start",
                    attempt=attempt,
                    max_retries=max_retries,
                    task=task,
                )
                try:
                    result = await self._run_once(
                        task, app_hint=app_hint, run_dir=run_dir,
                        memory_context=memory_context,
                        skill_context=skill_context,
                    )
                    for k, v in result.token_usage.items():
                        total_usage[k] = total_usage.get(k, 0) + v
                    await self._log_attempt_event(
                        run_dir,
                        "attempt_result",
                        attempt=attempt,
                        success=result.success,
                        summary=result.summary,
                        model_summary=result.model_summary,
                        error=result.error,
                        steps_taken=result.steps_taken,
                        trace_path=result.trace_path,
                    )
                    if result.success:
                        break
                    last_error = result.error
                    last_model_summary = result.model_summary
                    last_trace_path = result.trace_path or last_trace_path
                    last_steps_taken = result.steps_taken
                    attempt_summary = result.attempt_summary or self._build_attempt_summary(
                        failure_reason=result.error or result.summary,
                        result_summary=result.summary,
                        model_summary=result.model_summary,
                        action_summaries=(),
                    )
                    retry_summaries.append(attempt_summary)
                    if result.error and (
                        result.error.startswith("intervention_cancelled")
                        or result.error == "stagnation_detected"
                    ):
                        break
                    if attempt < max_retries - 1:
                        await self._log_attempt_event(
                            run_dir,
                            "retry",
                            attempt=attempt,
                            next_attempt=attempt + 1,
                            reason=result.error or result.summary,
                        )
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    model_snapshot = getattr(exc, "model_snapshot", None)
                    attempt_summary = getattr(exc, "attempt_summary", None) or self._build_attempt_summary(
                        failure_reason=last_error,
                        result_summary="Attempt ended with an exception before completion.",
                        action_summaries=(),
                    )
                    retry_summaries.append(attempt_summary)
                    await self._log_attempt_event(
                        run_dir,
                        "attempt_exception",
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        model_response=model_snapshot,
                    )
                    if attempt < max_retries - 1:
                        await self._log_attempt_event(
                            run_dir,
                            "retry",
                            attempt=attempt,
                            next_attempt=attempt + 1,
                            reason=last_error,
                        )
        finally:
            self._active_retry_summaries = ()

        if result is None:
            status = "blocked" if last_error and any(
                keyword in last_error.lower()
                for keyword in ("stagnation", "intervention", "preflight")
            ) else "partial"
            result = AgentResult(
                success=False,
                summary=self._build_state_note(
                    status=status,
                    history=[],
                    current_observation=None,
                    error=last_error or f"Failed after {max_retries} attempt(s).",
                ),
                model_summary=last_model_summary,
                trace_path=last_trace_path,
                steps_taken=last_steps_taken,
                error=last_error,
                token_usage=total_usage,
            )
        else:
            result = dataclasses.replace(
                result,
                token_usage=total_usage,
                trace_path=last_trace_path or result.trace_path,
                error=last_error or result.error,
            )

        # 6. Finish trajectory
        self._trajectory_recorder.finish(
            success=result.success,
            error=result.error,
            token_usage=result.token_usage or None,
        )

        # 7. Post-run skill maintenance — use skill execution outcome,
        #    not overall task result, so prefix skills aren't penalised
        #    for agent failures after their steps complete.
        skill_exec_success = (
            skill_result is not None and skill_result.state.value == "succeeded"
        ) if skill_result is not None else result.success

        # 7b. Agent compensation detection — if the skill "succeeded" but the
        #     agent needed significantly more steps than the skill itself had,
        #     the skill didn't actually advance the task.  Demote to failure.
        if skill_exec_success and skill_result is not None and result is not None:
            skill_step_count = len(getattr(skill_result, "step_results", ()) or ())
            agent_steps = getattr(result, "steps_taken", 0)
            if agent_steps > skill_step_count + 1:
                skill_exec_success = False

        await self._skill_maintenance(skill_match_for_maintenance, skill_exec_success)

        return result

    # ------------------------------------------------------------------
    # Single attempt
    # ------------------------------------------------------------------

    async def _run_once(
        self,
        task: str,
        *,
        app_hint: str | None,
        run_dir: Path,
        memory_context: str | None = None,
        skill_context: str | None = None,
    ) -> AgentResult:
        """Execute one full attempt of the task."""
        # 1. Preflight
        try:
            await self.backend.preflight()
        except Exception as exc:
            return AgentResult(
                success=False,
                summary=self._build_state_note(
                    status="blocked",
                    history=[],
                    current_observation=None,
                    error=f"Preflight failed: {exc}",
                ),
                trace_path=str(run_dir),
                error=str(exc),
            )

        # 2. Initial observation
        obs = await self.backend.observe(
            run_dir / "screenshots" / "step_000.png",
            timeout=self.step_timeout,
        )

        history: list[HistoryTurn] = []
        previous_fingerprint: _ScreenFingerprint | None = None
        previous_action_type: str | None = None
        stagnation_streak = 0
        if self.stagnation_limit > 0:
            previous_fingerprint = self._build_screen_fingerprint(obs)

        # 4. Step loop
        steps_taken = 0
        total_usage: dict[str, int] = {}
        for step in range(self.max_steps):
            step_index = step + 1
            messages = self._build_messages(
                task=task,
                current_observation=obs,
                history=history,
            )
            prompt_snapshot = self._snapshot_step_prompt(
                task=task,
                step_index=step_index,
                messages=messages,
                current_observation=obs,
                history=history,
            )

            try:
                result = await asyncio.wait_for(
                    self._run_step(
                        messages=messages,
                        prompt_snapshot=prompt_snapshot,
                        step_index=step_index,
                        total_steps=self.max_steps,
                        current_observation=obs,
                    ),
                    timeout=self.step_timeout * 3,
                )
            except asyncio.TimeoutError:
                await self._write_trace(run_dir / "trace.jsonl", {
                    "event": "timeout", "step_index": step_index,
                    "timestamp": time.time(),
                })
                return AgentResult(
                    success=False,
                    summary=self._build_state_note(
                        status="partial",
                        history=history,
                        current_observation=obs,
                        error="step_timeout",
                    ),
                    model_summary=None,
                    trace_path=str(run_dir),
                    steps_taken=step_index,
                    error="step_timeout",
                    attempt_summary=self._build_attempt_summary(
                        failure_reason="step_timeout",
                        result_summary=self._build_state_note(
                            status="partial",
                            history=history,
                            current_observation=obs,
                            error="step_timeout",
                        ),
                        action_summaries=tuple(turn.action_summary for turn in history),
                    ),
                    token_usage=total_usage,
                )
            except _StepExecutionError as exc:
                raise _StepExecutionError(
                    str(exc),
                    model_snapshot=exc.model_snapshot,
                    attempt_summary=self._build_attempt_summary(
                        failure_reason=f"{type(exc).__name__}: {exc}",
                        result_summary="Attempt ended with an exception before completion.",
                        action_summaries=tuple(turn.action_summary for turn in history),
                    ),
                ) from exc

            steps_taken = step_index
            for k, v in result.step_usage.items():
                total_usage[k] = total_usage.get(k, 0) + v

            intervention_cancelled = False
            if result.intervention_requested:
                request = InterventionRequest(
                    task=task,
                    reason=result.action.text or "",
                    step_index=step_index,
                    platform=self.backend.platform,
                    foreground_app=obs.foreground_app,
                    target=dict(obs.extra),
                )
                await self._log_attempt_event(
                    run_dir,
                    "intervention_requested",
                    step_index=step_index,
                    platform=request.platform,
                    foreground_app=request.foreground_app,
                    reason=request.reason,
                    target=request.target,
                )
                if self._intervention_handler is None:
                    intervention_cancelled = True
                    cancellation_note = "missing_intervention_handler"
                else:
                    resolution = await self._intervention_handler.request_intervention(request)
                    if resolution.resume_confirmed:
                        await self._log_attempt_event(
                            run_dir,
                            "intervention_resumed",
                            step_index=step_index,
                            note=resolution.note,
                        )
                        next_screenshot = run_dir / "screenshots" / f"step_{step_index:03d}.png"
                        next_observation = await self.backend.observe(
                            next_screenshot,
                            timeout=self.step_timeout,
                        )
                        result = replace(
                            result,
                            tool_result="intervention_resumed",
                            next_observation=next_observation,
                            execution_snapshot={
                                "tool_result": "intervention_resumed",
                                "intervention": {
                                    "requested": True,
                                    "note": resolution.note,
                                },
                                "next_observation": self._serialize_observation(next_observation),
                                "done": False,
                            },
                        )
                    else:
                        intervention_cancelled = True
                        cancellation_note = resolution.note or "resume_not_confirmed"

                if intervention_cancelled:
                    await self._log_attempt_event(
                        run_dir,
                        "intervention_cancelled",
                        step_index=step_index,
                        note=cancellation_note,
                    )
                    result = replace(
                        result,
                        tool_result="intervention_cancelled",
                        execution_snapshot={
                            "tool_result": "intervention_cancelled",
                            "intervention": {
                                "requested": True,
                                "note": cancellation_note,
                            },
                            "next_observation": None,
                            "done": False,
                        },
                    )
                    summary_history = history + [
                        HistoryTurn(
                            step_index=step_index,
                            observation=obs,
                            assistant_message=self._scrub_assistant_message_for_log(
                                result.assistant_message,
                                result.action,
                            ),
                            tool_result_message={
                                "role": "tool",
                                "tool_call_id": result.tool_call_id,
                                "content": self._scrub_text_for_action(
                                    result.tool_result,
                                    result.action,
                                ),
                            },
                            action_summary=(
                                self._scrub_text_for_action(
                                    result.action_summary,
                                    result.action,
                                )
                                or result.action_summary
                            ),
                            action_intent=(
                                self._scrub_text_for_action(
                                    result.action_intent,
                                    result.action,
                                )
                                or result.action_intent
                            ),
                            state_summary=(
                                self._scrub_text_for_action(
                                    result.state_summary,
                                    result.action,
                                )
                                or result.state_summary
                            ),
                            raw_response_content=(
                                result.model_snapshot.get("raw_content")
                                if isinstance(result.model_snapshot, dict)
                                else None
                            ),
                        )
                    ]
                    summary_observation = result.next_observation or obs

            # Write trace entry
            await self._write_trace(
                run_dir / "trace.jsonl",
                self._scrub_for_artifact({
                    "event": "step",
                    "step_index": step_index,
                    "prompt": result.prompt_snapshot,
                    "model_output": result.model_snapshot,
                    "execution": result.execution_snapshot,
                    "action": self._serialize_action(result.action),
                    "action_summary": self._scrub_text_for_artifact_action(result.action_summary, result.action),
                    "action_intent": self._scrub_text_for_artifact_action(result.action_intent, result.action),
                    "state_summary": self._scrub_text_for_artifact_action(result.state_summary, result.action),
                    "screenshot_path": (
                        result.next_observation.screenshot_path
                        if result.next_observation else None
                    ),
                    "done": result.done,
                    "timestamp": time.time(),
                }),
            )
            self._write_mobileworld_traj(
                run_dir=run_dir,
                task=task,
                step_index=step_index,
                result=result,
                current_observation=obs,
                total_usage=total_usage,
            )

            # Record trajectory step
            self._trajectory_recorder.record_step(
                action=self._scrub_for_artifact(self._serialize_action(result.action)),
                model_output=self._scrub_text_for_artifact_action(result.action_summary, result.action) or "",
                screenshot_path=(
                    str(result.next_observation.screenshot_path)
                    if result.next_observation and result.next_observation.screenshot_path
                    else None
                ),
                foreground_app=(
                    result.next_observation.foreground_app
                    if result.next_observation else None
                ),
                screen_width=(
                    result.next_observation.screen_width
                    if result.next_observation else None
                ),
                screen_height=(
                    result.next_observation.screen_height
                    if result.next_observation else None
                ),
                platform=(
                    result.next_observation.platform
                    if result.next_observation else None
                ),
                observation_extra=(
                    self._scrub_for_artifact(result.next_observation.extra)
                    if result.next_observation else None
                ),
                interaction_target=self._scrub_for_artifact(result.interaction_target),
                token_usage=result.step_usage or None,
                duration_s=result.duration_s or None,
                chat_latency_s=result.chat_latency_s,
                ttft_s=result.ttft_s,
            )

            if intervention_cancelled:
                termination_summary = await self._generate_termination_summary(
                    task=task,
                    termination_reason=f"Task was interrupted by policy: {cancellation_note}",
                    history=summary_history,
                    run_dir=run_dir,
                )
                return AgentResult(
                    success=False,
                    summary=termination_summary or self._build_state_note(
                        status="blocked",
                        history=summary_history,
                        current_observation=summary_observation,
                        error="intervention_cancelled",
                    ),
                    model_summary=result.state_summary or result.action_summary,
                    trace_path=str(run_dir),
                    steps_taken=steps_taken,
                    error=f"intervention_cancelled: {cancellation_note}",
                    attempt_summary=self._build_attempt_summary(
                        failure_reason=f"intervention_cancelled: {cancellation_note}",
                        result_summary=self._build_state_note(
                            status="blocked",
                            history=summary_history,
                            current_observation=summary_observation,
                            error="intervention_cancelled",
                        ),
                        model_summary=result.state_summary or result.action_summary,
                        action_summaries=tuple(
                            list(turn.action_summary for turn in history) + [result.action_summary]
                        ),
                    ),
                    token_usage=total_usage,
                )

            if result.done:
                success = self._resolve_done_status(result.action) == "success"
                return AgentResult(
                    success=success,
                    summary=self._build_state_note(
                        status="completed" if success else "blocked",
                        history=history,
                        current_observation=obs,
                        current_action_summary=result.state_summary or result.action_summary,
                        error=None if success else result.tool_result,
                    ),
                    model_summary=result.state_summary or result.action_summary,
                    trace_path=str(run_dir),
                    steps_taken=steps_taken,
                    error=None if success else result.tool_result,
                    attempt_summary=None if success else self._build_attempt_summary(
                        failure_reason=result.tool_result,
                        result_summary=self._build_state_note(
                            status="blocked",
                            history=history,
                            current_observation=obs,
                            current_action_summary=result.state_summary or result.action_summary,
                            error=result.tool_result,
                        ),
                        model_summary=result.state_summary or result.action_summary,
                        action_summaries=tuple(
                            list(turn.action_summary for turn in history) + [result.action_summary]
                        ),
                    ),
                    token_usage=total_usage,
                )

            if self.stagnation_limit > 0 and result.next_observation is not None:
                current_fingerprint = self._build_screen_fingerprint(result.next_observation)
                if (
                    previous_fingerprint is not None
                    and current_fingerprint is not None
                    and (previous_action_type is None or previous_action_type == result.action.action_type)
                    and self._is_same_screen(previous_fingerprint, current_fingerprint)
                ):
                    stagnation_streak += 1
                else:
                    stagnation_streak = 0
                previous_fingerprint = current_fingerprint
                previous_action_type = result.action.action_type

                if stagnation_streak >= self.stagnation_limit:
                    app_label = (
                        result.next_observation.foreground_app
                        or obs.foreground_app
                        or "unknown"
                    )
                    history_with_current_step = history + [
                        HistoryTurn(
                            step_index=step_index,
                            observation=obs,
                            assistant_message=self._scrub_assistant_message_for_log(
                                result.assistant_message,
                                result.action,
                            ),
                            tool_result_message={
                                "role": "tool",
                                "tool_call_id": result.tool_call_id,
                                "content": self._scrub_text_for_action(
                                    result.tool_result,
                                    result.action,
                                ),
                            },
                            action_summary=(
                                self._scrub_text_for_action(
                                    result.action_summary,
                                    result.action,
                                )
                                or result.action_summary
                            ),
                            action_intent=(
                                self._scrub_text_for_action(
                                    result.action_intent,
                                    result.action,
                                )
                                or result.action_intent
                            ),
                            state_summary=(
                                self._scrub_text_for_action(
                                    result.state_summary,
                                    result.action,
                                )
                                or result.state_summary
                            ),
                            raw_response_content=(
                                result.model_snapshot.get("raw_content")
                                if isinstance(result.model_snapshot, dict)
                                else None
                            ),
                        )
                    ]
                    termination_summary = await self._generate_termination_summary(
                        task=task,
                        termination_reason=(
                            "Detected unchanged screen state for "
                            f"{stagnation_streak} consecutive step(s) in app {app_label}; "
                            "task stopped to avoid repeating the same action loop."
                        ),
                        history=history_with_current_step,
                        run_dir=run_dir,
                    )
                    await self._log_attempt_event(
                        run_dir,
                        "stagnation_detected",
                        step_index=step_index,
                        stagnation_streak=stagnation_streak,
                        stagnation_limit=self.stagnation_limit,
                        foreground_app=app_label,
                    )
                    return AgentResult(
                        success=False,
                        summary=termination_summary or self._build_state_note(
                            status="blocked",
                            history=history_with_current_step,
                            current_observation=result.next_observation or obs,
                            error="stagnation_detected",
                        ),
                        model_summary=result.state_summary or result.action_summary,
                        trace_path=str(run_dir),
                        steps_taken=steps_taken,
                        error="stagnation_detected",
                        attempt_summary=self._build_attempt_summary(
                            failure_reason="stagnation_detected",
                            result_summary=self._build_state_note(
                                status="blocked",
                                history=history_with_current_step,
                                current_observation=result.next_observation or obs,
                                error="stagnation_detected",
                            ),
                            model_summary=result.state_summary or result.action_summary,
                            action_summaries=tuple(
                                list(turn.action_summary for turn in history) + [result.action_summary]
                            ),
                        ),
                        token_usage=total_usage,
                    )

            history.append(
                HistoryTurn(
                    step_index=step_index,
                    observation=obs,
                    assistant_message=self._scrub_assistant_message_for_log(
                        result.assistant_message,
                        result.action,
                    ),
                    tool_result_message={
                        "role": "tool",
                        "tool_call_id": result.tool_call_id,
                        "content": self._scrub_text_for_action(result.tool_result, result.action),
                    },
                    action_summary=(
                        self._scrub_text_for_action(result.action_summary, result.action)
                        or result.action_summary
                    ),
                    action_intent=(
                        self._scrub_text_for_action(result.action_intent, result.action)
                        or result.action_intent
                    ),
                    state_summary=(
                        self._scrub_text_for_action(result.state_summary, result.action)
                        or result.state_summary
                    ),
                    raw_response_content=(
                        result.model_snapshot.get("raw_content")
                        if isinstance(result.model_snapshot, dict)
                        else None
                    ),
                )
            )

            if result.next_observation is not None:
                obs = result.next_observation

        termination_summary = await self._generate_termination_summary(
            task=task,
            termination_reason=f"Reached maximum step limit ({self.max_steps})",
            history=history,
            run_dir=run_dir,
        )
        return AgentResult(
            success=False,
            summary=termination_summary or self._build_state_note(
                status="partial",
                history=history,
                current_observation=obs,
                error="max_steps_exceeded",
            ),
            model_summary=None,
            trace_path=str(run_dir),
            steps_taken=steps_taken,
            error="max_steps_exceeded",
            attempt_summary=self._build_attempt_summary(
                failure_reason="max_steps_exceeded",
                result_summary=self._build_state_note(
                    status="partial",
                    history=history,
                    current_observation=obs,
                    error="max_steps_exceeded",
                ),
                action_summaries=tuple(turn.action_summary for turn in history),
            ),
            token_usage=total_usage,
        )

    # ------------------------------------------------------------------
    # Single step
    # ------------------------------------------------------------------

    async def _run_step(
        self,
        messages: list[dict[str, Any]],
        prompt_snapshot: dict[str, Any] | None,
        step_index: int,
        total_steps: int,
        current_observation: Observation,
    ) -> StepResult:
        """Execute a single vision-action step with retries on malformed calls."""
        _step_start = time.monotonic()
        fg = str(current_observation.foreground_app or "").strip() if current_observation else ""
        await self._ensure_shortcuts_for_app(fg)
        retries_left = self._MAX_TOOL_RETRIES + 1
        step_usage: dict[str, int] = {}
        step_chat_latency_s: float = 0.0
        step_ttft_s: float | None = None

        while retries_left > 0:
            retries_left -= 1

            # Call LLM
            native_tools_enabled = profile_uses_native_tools(self.agent_profile)
            response: LLMResponse = await self.llm.chat(
                messages=messages,
                tools=self._build_tools_list() if native_tools_enabled else None,
                tool_choice="required" if native_tools_enabled else None,
            )
            for k, v in (response.usage or {}).items():
                step_usage[k] = step_usage.get(k, 0) + v
            if response.latency_s is not None:
                step_chat_latency_s += response.latency_s
            if step_ttft_s is None and response.ttft_s is not None:
                step_ttft_s = response.ttft_s
            raw_response_snapshot = self._snapshot_failed_model_response(response)

            try:
                response = normalize_profile_response_for_observation(
                    self.agent_profile,
                    response,
                    current_observation,
                    model_name=self.model,
                )
            except ValueError as exc:
                detail = f"{exc}. Follow the required response format exactly."
                feedback = self._build_tool_format_error(
                    native_tools=native_tools_enabled,
                    detail=detail,
                )
                if retries_left > 0:
                    messages.append({
                        "role": "user",
                        "content": feedback,
                    })
                    continue
                raise _StepExecutionError(
                    f"Failed to parse profile response after retries: {exc}",
                    model_snapshot=raw_response_snapshot,
                ) from exc

            # Append assistant message
            assistant_msg = self._build_assistant_message(
                response,
                include_tool_calls=native_tools_enabled,
            )
            messages.append(assistant_msg)
            assistant_snapshot = self._snapshot_failed_model_response(
                response,
                assistant_message=assistant_msg,
            )

            # Validate tool call
            if not response.tool_calls or len(response.tool_calls) == 0:
                if retries_left > 0:
                    feedback = self._build_tool_format_error(
                        native_tools=native_tools_enabled,
                        detail=(
                            "No action payload found. "
                            "Return one `Thought:` + `Action:` response "
                            "in the configured profile format."
                        ),
                    )
                    messages.append({
                        "role": "user",
                        "content": feedback,
                    })
                    continue
                raise _StepExecutionError(
                    "LLM did not return a computer_use tool call after retries.",
                    model_snapshot=assistant_snapshot,
                )

            tool_call = response.tool_calls[0]
            if native_tools_enabled and tool_call.name != "computer_use" and tool_call.name not in self._shortcut_action_map:
                if retries_left > 0:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error: unexpected tool '{tool_call.name}'.",
                    })
                    continue
                raise _StepExecutionError(
                    f"LLM called unexpected tool '{tool_call.name}'.",
                    model_snapshot=assistant_snapshot,
                )
            if tool_call.name in self._shortcut_action_map:
                action_type, text, component, mime_type = self._shortcut_action_map[tool_call.name]
                arguments = {
                    "action_type": action_type,
                    "text": text,
                    "component": component,
                    "intent": f"Shortcut: {tool_call.name}",
                    "summary": f"Executing shortcut {tool_call.name}",
                }
                if action_type == "open_intent":
                    arguments["intent_action"] = text
                    if mime_type:
                        arguments["mime_type"] = mime_type
                tool_call = replace(tool_call, arguments=arguments)
            action_intent, state_summary = self._tool_call_semantics(tool_call)

            # Parse action
            try:
                action = parse_action(tool_call.arguments)
                action = self._normalize_relative_coordinates(action)
            except ActionError as exc:
                if retries_left > 0:
                    if native_tools_enabled:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"Error parsing action: {exc}. Please fix and retry.",
                        })
                    else:
                        messages.append({
                            "role": "user",
                            "content": f"Format error: {exc}. Please return {tool_call.name} output in the configured profile format.",
                        })
                    continue
                raise _StepExecutionError(
                    f"Failed to parse action after retries: {exc}",
                    model_snapshot=assistant_snapshot,
                ) from exc

            # Report progress
            if self.progress_callback is not None:
                await self.progress_callback(
                    f"GUI step {step_index}/{total_steps}: {describe_action(action)}"
                )

            action_text = self._normalize_action_text(
                response.content,
                action,
                tool_summary=action_intent or state_summary,
            )
            action_summary = action_intent or self._action_summary(action_text)
            assistant_message = self._build_assistant_message(
                response,
                content_override=action_text,
                include_tool_calls=native_tools_enabled,
            )
            model_snapshot = self._snapshot_model_response(
                response=response,
                action=action,
                assistant_message=assistant_message,
                action_text=action_text,
                action_intent=action_summary,
                state_summary=state_summary,
            )

            # Handle terminal action (done)
            if action.action_type == "done":
                done_status = self._resolve_done_status(action)
                if action.status != done_status:
                    action = replace(action, status=done_status)
                tool_result = f"Task terminated with status: {done_status}"
                return StepResult(
                    action=action,
                    tool_call_id=tool_call.id,
                    tool_result=tool_result,
                    assistant_message=assistant_message,
                    action_summary=action_summary,
                    action_intent=action_summary,
                    state_summary=state_summary,
                    prompt_snapshot=prompt_snapshot,
                    model_snapshot=model_snapshot,
                    execution_snapshot={
                        "tool_result": tool_result,
                        "next_observation": None,
                        "done": True,
                    },
                    done=True,
                    step_usage=step_usage,
                    duration_s=time.monotonic() - _step_start,
                    chat_latency_s=step_chat_latency_s or None,
                    ttft_s=step_ttft_s,
                )

            if action.action_type == "request_intervention":
                return StepResult(
                    action=action,
                    tool_call_id=tool_call.id,
                    tool_result="intervention_requested",
                    assistant_message=assistant_message,
                    action_summary=action_summary,
                    action_intent=action_summary,
                    state_summary=state_summary,
                    prompt_snapshot=prompt_snapshot,
                    model_snapshot=model_snapshot,
                    execution_snapshot={
                        "tool_result": "intervention_requested",
                        "next_observation": None,
                        "done": False,
                    },
                    intervention_requested=True,
                    step_usage=step_usage,
                    duration_s=time.monotonic() - _step_start,
                    chat_latency_s=step_chat_latency_s or None,
                    ttft_s=step_ttft_s,
                )

            # Normalize app identifiers for mobile open/close actions.
            if (
                action.action_type in ("open_app", "close_app")
                and action.text
                and self.backend.platform in ("android", "ios")
            ):
                resolved = normalize_app_identifier(self.backend.platform, action.text)
                if resolved != action.text:
                    logger.debug(
                        "Resolved %s app name %r -> %r",
                        self.backend.platform,
                        action.text,
                        resolved,
                    )
                    action = replace(action, text=resolved)

            interaction_target = infer_interaction_target(action, current_observation)

            # Execute action on backend
            try:
                result_text = await self.backend.execute(action, timeout=self.step_timeout)
            except Exception as exc:
                result_text = f"Action failed: {exc}"

            settle_seconds = self._post_action_settle_seconds(action)
            if settle_seconds > 0:
                await asyncio.sleep(settle_seconds)

            # Observe next state
            run_dir = Path(current_observation.screenshot_path or ".").parent.parent
            next_screenshot = run_dir / "screenshots" / f"step_{step_index:03d}.png"
            next_observation, observe_error = await self._observe_after_action(
                next_screenshot,
                previous_observation=current_observation,
                action=action,
                timeout=self.step_timeout,
            )
            if observe_error:
                result_text += f" (observation failed: {observe_error})"

            return StepResult(
                action=action,
                tool_call_id=tool_call.id,
                tool_result=result_text,
                assistant_message=assistant_message,
                action_summary=action_summary,
                action_intent=action_summary,
                state_summary=state_summary,
                next_observation=next_observation,
                interaction_target=interaction_target,
                prompt_snapshot=prompt_snapshot,
                model_snapshot=model_snapshot,
                execution_snapshot={
                    "tool_result": self._scrub_text_for_action(result_text, action),
                    "next_observation": self._serialize_observation(next_observation),
                    "done": False,
                },
                step_usage=step_usage,
                duration_s=time.monotonic() - _step_start,
                chat_latency_s=step_chat_latency_s or None,
                ttft_s=step_ttft_s,
            )

        raise RuntimeError("GUI model did not return a valid computer_use call after retries.")

    def _coordinate_mode(self) -> str:
        return coordinate_mode_for_profile(self.agent_profile, self.model)

    def _model_uses_relative_grid(self) -> bool:
        return self._coordinate_mode() == "relative_999"

    def _normalize_relative_coordinates(self, action: Action) -> Action:
        if action.relative or action.action_type not in self._COORDINATE_ACTIONS:
            return action
        if not self._model_uses_relative_grid():
            return action
        coords = [value for value in (action.x, action.y, action.x2, action.y2) if value is not None]
        if coords and all(0 <= value <= 999 for value in coords):
            return replace(action, relative=True)
        return action

    def _post_action_settle_seconds(self, action: Action) -> float:
        if action.action_type in self._NO_SETTLE_ACTIONS:
            return 0.0
        if action.action_type == "open_app":
            return self._OPEN_APP_SETTLE_SECONDS
        return self._POST_ACTION_SETTLE_SECONDS

    async def _observe_after_action(
        self,
        screenshot_path: Path,
        *,
        previous_observation: Observation | None = None,
        action: Action | None = None,
        timeout: float,
    ) -> tuple[Observation | None, str | None]:
        # Wait for the UI to reach a short stable state before returning the
        # observation used by the next planner turn.
        max_attempts = self._POST_ACTION_STABILITY_MAX_ATTEMPTS
        if action is not None and action.action_type in self._NO_SETTLE_ACTIONS:
            max_attempts = 1
        if action is None or self._post_action_settle_seconds(action) <= 0:
            max_attempts = min(max_attempts, 1)

        window_seconds = min(timeout, self._POST_ACTION_STABILITY_WINDOW_SECONDS)
        poll_interval = self._POST_ACTION_STABILITY_POLL_SECONDS
        observe_timeout = min(timeout, self._POST_ACTION_OBSERVE_TIMEOUT_SECONDS)
        attempts_within_window = max(
            1,
            int(window_seconds / max(poll_interval, 1e-6)),
        )
        max_attempts = max(1, min(max_attempts, attempts_within_window))

        previous_fingerprint = (
            self._build_screen_fingerprint(previous_observation)
            if previous_observation is not None
            else None
        )
        stable_count = 0
        stable_required = self._POST_ACTION_STABILITY_FRAMES_REQUIRED
        last_error: str | None = None
        last_observation: Observation | None = None
        deadline = time.monotonic() + window_seconds

        for attempt in range(max_attempts):
            try:
                observation = await self.backend.observe(
                    screenshot_path,
                    timeout=observe_timeout,
                )
                last_observation = observation
                current_fingerprint = self._build_screen_fingerprint(observation)

                if previous_fingerprint is not None and current_fingerprint is not None:
                    if self._is_same_screen(previous_fingerprint, current_fingerprint):
                        stable_count += 1
                    else:
                        stable_count = 1
                        previous_fingerprint = current_fingerprint
                else:
                    # Fingerprints are best-effort. If unavailable, just use the
                    # latest sampled observation as the fallback signal.
                    stable_count = min(stable_count + 1, stable_required)

                if stable_count >= stable_required:
                    return observation, None
            except Exception as exc:
                last_error = str(exc)

            if max_attempts > 1 and time.monotonic() < deadline:
                await asyncio.sleep(poll_interval)

        if last_observation is not None:
            return last_observation, last_error
        return None, last_error

    def _build_screen_fingerprint(self, observation: Observation) -> _ScreenFingerprint | None:
        screenshot = observation.screenshot_path
        if not screenshot:
            return None
        screenshot_path = Path(screenshot)
        if not screenshot_path.exists():
            return None

        app_name = self._normalize_stagnation_app(observation.foreground_app)
        try:
            data = screenshot_path.read_bytes()
        except OSError:
            return None

        try:
            from PIL import Image

            with Image.open(screenshot_path) as img:
                resampling = getattr(Image, "Resampling", Image)
                ssim_size = self._STAGNATION_SSIM_SIZE
                grayscale = img.convert("L").resize(
                    (ssim_size, ssim_size),
                    resampling.BILINEAR,
                )
                pixels = list(grayscale.tobytes())
                if pixels:
                    return _ScreenFingerprint(
                        app=app_name,
                        method="ssim",
                        digest=base64.b64encode(bytes(pixels)).decode("ascii"),
                    )
        except Exception:
            pass

        return _ScreenFingerprint(
            app=app_name,
            method="sha256",
            digest=hashlib.sha256(data).hexdigest(),
        )

    @classmethod
    def _is_same_screen(
        cls,
        previous: _ScreenFingerprint,
        current: _ScreenFingerprint,
    ) -> bool:
        if previous.app and current.app and previous.app != current.app:
            return False

        if previous.method == "ssim" and current.method == "ssim":
            try:
                return cls._ssim_is_similar(previous.digest, current.digest)
            except Exception:
                return previous.digest == current.digest

        if previous.method != current.method:
            return False
        return previous.digest == current.digest

    @classmethod
    def _ssim_is_similar(cls, previous_digest: str, current_digest: str) -> bool:
        previous_pixels = base64.b64decode(previous_digest)
        current_pixels = base64.b64decode(current_digest)
        if len(previous_pixels) != len(current_pixels) or len(previous_pixels) == 0:
            return False
        return cls._ssim_score(previous_pixels, current_pixels) >= cls._STAGNATION_SSIM_THRESHOLD

    @classmethod
    def _ssim_score(cls, previous_pixels: bytes, current_pixels: bytes) -> float:
        del cls

        if len(previous_pixels) != len(current_pixels) or len(previous_pixels) == 0:
            return 0.0

        n = len(previous_pixels)
        previous_values = [value for value in previous_pixels]
        current_values = [value for value in current_pixels]

        previous_mean = sum(previous_values) / n
        current_mean = sum(current_values) / n

        previous_variance = sum((value - previous_mean) ** 2 for value in previous_values) / n
        current_variance = sum((value - current_mean) ** 2 for value in current_values) / n
        covariance = sum(
            (previous_value - previous_mean) * (current_value - current_mean)
            for previous_value, current_value in zip(previous_values, current_values)
        ) / n

        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2
        denominator = (previous_mean * previous_mean + current_mean * current_mean + c1) * (
            previous_variance + current_variance + c2
        )

        if denominator == 0:
            return 1.0 if previous_mean == current_mean else 0.0

        numerator = (2 * previous_mean * current_mean + c1) * (2 * covariance + c2)
        return numerator / denominator

    def _normalize_stagnation_app(self, app: str | None) -> str | None:
        if not app:
            return None
        normalized = normalize_app_identifier(self.backend.platform, app)
        return None if normalized == "unknown" else normalized

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        *,
        task: str,
        current_observation: Observation,
        history: list[HistoryTurn],
    ) -> list[dict[str, Any]]:
        return build_mobileworld_messages(
            self.agent_profile,
            task=task,
            current_observation=current_observation,
            history=history,
            model_name=self.model,
            history_image_window=self.history_image_window,
        )

    def _build_instruction_prompt(
        self,
        *,
        task: str,
        current_observation: Observation,
        history: list[HistoryTurn],
        app_hint: str | None,
        skill_context: str | None = None,
    ) -> str:
        """Build the text prompt that frames the current step."""
        recent_intents = self._format_recent_intents(
            history,
            window=self.history_text_window,
        )
        latest_summary = self._latest_state_summary(history)
        lines = [
            "Please generate the next move according to the UI screenshot, instruction and recent progress context.",
            "",
        ]

        if self.include_date_context:
            lines.append(f"Today's date is: {datetime.now().strftime('%Y-%m-%d %A')}.")

        lines.append(f"Instruction: {task}")
        lines.append(f"Platform: {self.backend.platform}")

        app_name = app_hint or current_observation.foreground_app
        if app_name:
            lines.append(f"Foreground app hint: {app_name}")

        retry_summaries = self._format_retry_attempt_summaries(self._active_retry_summaries)
        if retry_summaries:
            lines.extend([
                "",
                "Previous attempt summaries:",
                retry_summaries,
                "",
                "Continue from the current screen state. Reuse the progress above and avoid blindly repeating the same failed action sequence.",
            ])

        lines.extend([
            "",
            "Recent intents:",
            recent_intents,
        ])
        if latest_summary:
            lines.extend([
                "",
                f"Latest state summary: {latest_summary}",
            ])

        if skill_context:
            lines.extend([
                "",
                "Previous skill execution (already completed):",
                skill_context,
                "",
                "Check the current screen. If the task is now complete, call "
                "done(status=\"success\"). Otherwise, continue with any remaining steps.",
            ])
        return "\n".join(lines)

    @staticmethod
    def _format_recent_intents(history: list[HistoryTurn], *, window: int = 8) -> str:
        if not history:
            return "None"
        recent_history = history[-max(1, window):]
        return "\n".join(
            f"Step {turn.step_index}: {turn.action_intent or turn.action_summary}"
            for turn in recent_history
        )

    @staticmethod
    def _latest_state_summary(history: list[HistoryTurn]) -> str | None:
        for turn in reversed(history):
            if turn.state_summary and turn.state_summary.strip():
                return turn.state_summary.strip()
        return None

    @staticmethod
    def _format_retry_attempt_summaries(attempt_summaries: tuple[str, ...]) -> str:
        if not attempt_summaries:
            return ""
        return "\n\n".join(
            f"Attempt {index}:\n{summary}"
            for index, summary in enumerate(attempt_summaries, start=1)
        )

    @staticmethod
    def _build_state_note(
        *,
        status: str,
        history: list[HistoryTurn],
        current_observation: Observation | None,
        current_action_summary: str | None = None,
        error: str | None = None,
    ) -> str:
        return build_state_note(
            status=status,
            done=GuiAgent._summarize_progress(history, current_action_summary),
            remaining=GuiAgent._remaining_hint(status=status, error=error),
            current=GuiAgent._describe_observation_state(current_observation),
            resume=GuiAgent._resume_hint(status=status, error=error),
        )

    @staticmethod
    def _summarize_progress(history: list[HistoryTurn], current_action_summary: str | None = None) -> str:
        summaries = [
            (turn.state_summary or turn.action_summary).strip()
            for turn in history
            if (turn.state_summary or turn.action_summary).strip()
        ]
        if current_action_summary and current_action_summary.strip():
            summaries.append(current_action_summary.strip())
        if not summaries:
            return "No GUI actions were completed."
        return "; ".join(summary.rstrip(".") for summary in summaries[-3:])

    @staticmethod
    def _describe_observation_state(observation: Observation | None) -> str:
        if observation is None:
            return "Current screen state unavailable."
        parts: list[str] = []
        if observation.foreground_app and observation.foreground_app.strip():
            parts.append(observation.foreground_app.strip())
        if isinstance(observation.screen_width, int) and isinstance(observation.screen_height, int):
            parts.append(f"{observation.screen_width}x{observation.screen_height}")
        if parts:
            return " ".join(parts)
        if observation.platform:
            return observation.platform
        return "Current screen state unavailable."

    @staticmethod
    def _remaining_hint(*, status: str, error: str | None) -> str:
        error_text = (error or "").lower()
        if status == "completed":
            return "none"
        if "stagnation_detected" in error_text:
            return "Change the action sequence from the current screen."
        if "intervention_cancelled" in error_text or "interruption" in error_text:
            return "Wait for the intervention blocker to be resolved."
        if "step_timeout" in error_text:
            return "Retry the timed-out step from the current screen."
        if "max_steps_exceeded" in error_text:
            return "Continue the remaining task from the current screen."
        if status == "blocked":
            return "Resolve the blocker before retrying."
        return "Continue from the current screen."

    @staticmethod
    def _resume_hint(*, status: str, error: str | None) -> str:
        error_text = (error or "").lower()
        if status == "completed":
            return "No further action needed."
        if "stagnation_detected" in error_text:
            return "Resume by trying a different action on the same screen."
        if "intervention_cancelled" in error_text or "interruption" in error_text:
            return "Resolve the intervention blocker, then continue from the current screen."
        if "step_timeout" in error_text:
            return "Resume from the current screen after the timeout clears."
        if "max_steps_exceeded" in error_text:
            return "Resume from the current screen and finish the remaining steps."
        if status == "blocked":
            return "Resolve the blocker, then continue from the current screen."
        return "Resume from the current screen."

    async def _generate_termination_summary(
        self,
        *,
        task: str,
        termination_reason: str,
        history: list[HistoryTurn],
        run_dir: Path,
    ) -> str | None:
        """Ask the LLM for a brief state note when the task terminates abnormally."""
        steps_text = "\n".join(
            f"  {i}. {turn.action_summary}" for i, turn in enumerate(history, 1)
        ) or "  (no steps completed)"
        fallback_status = "blocked" if any(
            keyword in termination_reason.lower()
            for keyword in ("interrupted", "cancel", "loop")
        ) else "partial"
        observation: Observation | None = None
        try:
            # Take a fresh screenshot for the summary
            screenshot_path = run_dir / "screenshots" / "termination_summary.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            observation = await self.backend.observe(
                screenshot_path, timeout=self.step_timeout,
            )
            prompt_text = (
                "Return a compact GUI state note for the terminated task.\n\n"
                f"Task: {task}\n"
                f"Termination reason: {termination_reason}\n"
                f"Steps executed:\n{steps_text}\n\n"
                "Use exactly these 5 labels and keep each value short:\n"
                "Status: completed|partial|blocked\n"
                "Done: ...\n"
                "Remaining: ...\n"
                "Current: ...\n"
                "Resume: ...\n\n"
                "Rules:\n"
                "- Do not add bullets, markdown, or extra lines.\n"
                "- Use a clear resume hint if continuation is still possible.\n"
                "- Use 'none' for Remaining when the task is completed."
            )
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
            if observation.screenshot_path and Path(observation.screenshot_path).exists():
                content.append(self._image_block(Path(observation.screenshot_path)))

            response = await self.llm.chat(
                messages=[{"role": "user", "content": content}],
                tools=None,
            )
            text = response.content.strip()
            if text and is_state_note(text):
                return text
        except Exception as exc:
            logger.warning("Failed to generate termination summary: %s", exc)

        return self._build_state_note(
            status=fallback_status,
            history=history,
            current_observation=observation,
            error=termination_reason,
        )

    @staticmethod
    def _build_attempt_summary(
        *,
        failure_reason: str,
        result_summary: str | None,
        action_summaries: tuple[str, ...],
        model_summary: str | None = None,
    ) -> str:
        lines = [f"Failure reason: {failure_reason}"]
        if result_summary and result_summary != failure_reason:
            lines.append(f"Attempt result: {result_summary}")
        if model_summary:
            lines.append(f"Latest model summary: {model_summary}")

        if action_summaries:
            lines.append("Completed GUI actions before the failure:")
            trimmed_actions = action_summaries[-6:]
            omitted_count = len(action_summaries) - len(trimmed_actions)
            if omitted_count > 0:
                lines.append(f"- ... {omitted_count} earlier step(s) omitted")
            start_index = len(action_summaries) - len(trimmed_actions) + 1
            for step_offset, action_summary in enumerate(trimmed_actions, start=start_index):
                lines.append(f"- Step {step_offset}: {action_summary}")
        else:
            lines.append("No completed GUI actions were recorded before the failure.")

        lines.append(
            "Retry guidance: Continue from the current screen state. Reuse the progress above and avoid blindly repeating the same failed action sequence."
        )
        return "\n".join(lines)

    def _history_user_message(
        self,
        observation: Observation,
        prompt_text: str | None = None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        if prompt_text:
            content.append({"type": "text", "text": prompt_text})
        if observation.screenshot_path and Path(observation.screenshot_path).exists():
            content.append(self._image_block(Path(observation.screenshot_path)))
        return {"role": "user", "content": content}

    @staticmethod
    def _history_image_prompt(turn: HistoryTurn) -> str:
        return (
            f"Historical screen before Step {turn.step_index}. "
            "The next assistant message summarizes the action taken from this screen."
        )

    @staticmethod
    def _history_assistant_message(turn: HistoryTurn) -> dict[str, Any]:
        lines = [f"Step {turn.step_index}: {turn.action_intent or turn.action_summary}"]
        if turn.state_summary and turn.state_summary.strip():
            lines.append(f"State summary: {turn.state_summary.strip()}")
        tool_result = turn.tool_result_message.get("content")
        if isinstance(tool_result, str) and tool_result.strip():
            lines.append(f"Tool result: {tool_result.strip()}")
        return {"role": "assistant", "content": "\n".join(lines)}

    def _current_user_message(
        self,
        observation: Observation,
        *,
        task: str,
        step_index: int,
        app_hint: str | None,
        prompt_text: str | None = None,
    ) -> dict[str, Any]:
        if self._coordinate_mode() == "relative_999":
            coord_inst = (
                "Use relative coordinates in [0, 999] for both x and y, "
                "and set relative=true."
            )
        else:
            coord_inst = "Prefer absolute pixel coordinates."

        content: list[dict[str, Any]] = []
        if prompt_text:
            content.append({"type": "text", "text": prompt_text})
        content.append({
            "type": "text",
            "text": observation.to_user_text(
                task,
                step_index=step_index,
                app_hint=app_hint,
                coordinate_instruction=coord_inst,
                include_extra=False,
            ),
        })
        if observation.screenshot_path and Path(observation.screenshot_path).exists():
            content.append(self._image_block(Path(observation.screenshot_path)))
        return {"role": "user", "content": content}

    @staticmethod
    def _build_assistant_message(
        response: LLMResponse,
        *,
        content_override: str | None = None,
        include_tool_calls: bool = True,
    ) -> dict[str, Any]:
        """Build an assistant message dict from an LLM response."""
        msg: dict[str, Any] = {"role": "assistant"}

        content = content_override if content_override is not None else response.content
        if content:
            msg["content"] = content

        if include_tool_calls and response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments)
                        if isinstance(tc.arguments, dict) else str(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]

        return msg

    @staticmethod
    def _extract_action_line_from_response(content: str) -> str | None:
        parts = content.split("Action:", 1)
        if len(parts) != 2:
            return None

        action_line = parts[1].strip().splitlines()
        if not action_line:
            return None

        first_line = action_line[0].strip()
        if not first_line:
            return None

        first_line = first_line.strip('"')
        return first_line.strip()

    @staticmethod
    def _build_tool_format_error(
        *,
        native_tools: bool,
        detail: str,
    ) -> str:
        if native_tools:
            return f"Error: {detail}"
        return "Format error: " + detail

    def _snapshot_step_prompt(
        self,
        *,
        task: str,
        step_index: int,
        messages: list[dict[str, Any]],
        current_observation: Observation,
        history: list[HistoryTurn],
    ) -> dict[str, Any]:
        return {
            "task": task,
            "step_index": step_index,
            "messages": self._scrub_for_artifact(messages),
            "history": [
                {
                    "step_index": turn.step_index,
                    "action_summary": turn.action_summary,
                    "action_intent": turn.action_intent,
                    "state_summary": turn.state_summary,
                    "raw_response_content": turn.raw_response_content,
                    "observation": self._serialize_observation(turn.observation),
                    "tool_result": turn.tool_result_message.get("content"),
                }
                for turn in history
            ],
            "current_observation": self._serialize_observation(current_observation),
        }

    def _snapshot_model_response(
        self,
        *,
        response: LLMResponse,
        action: Action,
        assistant_message: dict[str, Any],
        action_text: str,
        action_intent: str | None = None,
        state_summary: str | None = None,
    ) -> dict[str, Any]:
        return {
            "raw_content": self._scrub_text_for_artifact_action(response.content, action),
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": self._scrub_for_artifact(tool_call.arguments),
                }
                for tool_call in (response.tool_calls or [])
            ],
            "assistant_message": self._scrub_assistant_message_for_artifact(assistant_message, action),
            "parsed_action": self._scrub_for_artifact(self._serialize_action(action)),
            "action_text": self._scrub_text_for_artifact_action(action_text, action),
            "action_summary": self._scrub_text_for_artifact_action(self._action_summary(action_text), action),
            "action_intent": self._scrub_text_for_artifact_action(action_intent, action),
            "state_summary": self._scrub_text_for_artifact_action(state_summary, action),
        }

    def _snapshot_failed_model_response(
        self,
        response: LLMResponse,
        *,
        assistant_message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "raw_content": self._scrub_text_for_artifact_action(response.content, None),
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": self._scrub_for_artifact(tool_call.arguments),
                }
                for tool_call in (response.tool_calls or [])
            ],
        }
        if assistant_message is not None:
            snapshot["assistant_message"] = self._scrub_for_artifact(assistant_message)
        return snapshot

    @staticmethod
    def _normalize_action_text(
        content: str,
        action: Action,
        *,
        tool_summary: str | None = None,
    ) -> str:
        summary = GuiAgent._clean_action_summary(tool_summary)
        if summary:
            return f"Action: {summary}"
        text = content.strip() if content else ""
        action_line = GuiAgent._extract_action_line_from_response(text)
        if action_line:
            return f"Action: {action_line}"
        if text:
            first_line = text.splitlines()[0].strip()
            if first_line.lower().startswith("action:"):
                return first_line
            return f"Action: {first_line}"
        return f"Action: {describe_action(action)}"

    @staticmethod
    def _tool_call_summary(tool_call: ToolCall) -> str | None:
        intent, summary = GuiAgent._tool_call_semantics(tool_call)
        return intent or summary

    @staticmethod
    def _tool_call_semantics(tool_call: ToolCall) -> tuple[str | None, str | None]:
        arguments = tool_call.arguments or {}
        intent = GuiAgent._clean_action_summary(arguments.get("intent"))
        summary = GuiAgent._clean_action_summary(arguments.get("summary"))
        return intent, summary

    @staticmethod
    def _clean_action_summary(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split()).strip()
        if not text:
            return None
        lowered = text.casefold()
        if lowered.startswith("action:"):
            text = text.split(":", 1)[1].strip()
        text = text.strip("`\"'")
        return text or None

    @staticmethod
    def _action_summary(action_text: str) -> str:
        if action_text.lower().startswith("action:"):
            return action_text.split(":", 1)[1].strip()
        return action_text.strip()

    @staticmethod
    def _resolve_done_status(action: Action) -> str:
        """Resolve terminal status for done actions with safe fallback rules."""
        if action.status in {"success", "failure"}:
            return action.status
        text = (action.text or "").strip().lower()
        if any(hint in text for hint in _DONE_FAILURE_HINTS):
            return "failure"
        # Missing status is common for some providers; default to success so
        # we do not retry already-completed tasks.
        return "success"

    def _image_block(self, path: Path) -> dict[str, Any]:
        """Create a base64 image content block for an LLM message."""
        from opengui.skills.executor import _scale_image
        b64 = base64.b64encode(
            _scale_image(path.read_bytes(), scale_ratio=self._image_scale_ratio)
        ).decode()
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        }

    @staticmethod
    def _serialize_action(action: Action) -> dict[str, Any]:
        payload = dataclasses.asdict(action)
        return {
            key: value
            for key, value in payload.items()
            if value is not None and not (key == "relative" and value is False)
        }

    @staticmethod
    def _serialize_observation(observation: Observation | None) -> dict[str, Any] | None:
        if observation is None:
            return None
        return {
            "screenshot_path": observation.screenshot_path,
            "screen_width": observation.screen_width,
            "screen_height": observation.screen_height,
            "foreground_app": observation.foreground_app,
            "platform": observation.platform,
            "extra": GuiAgent._scrub_for_log(observation.extra),
        }

    @staticmethod
    def _scrub_for_log(value: Any) -> Any:
        return GuiAgent._scrub_value(value, redact_input_text=True)

    @staticmethod
    def _scrub_for_artifact(value: Any) -> Any:
        return GuiAgent._scrub_value(value, redact_input_text=False)

    @staticmethod
    def _scrub_value(value: Any, *, redact_input_text: bool) -> Any:
        if isinstance(value, dict):
            scrubbed: dict[str, Any] = {}
            action_type = value.get("action_type") if isinstance(value.get("action_type"), str) else None
            for key, item in value.items():
                if key == "url" and isinstance(item, str) and item.startswith("data:image/"):
                    scrubbed[key] = "<omitted:image-data-url>"
                elif redact_input_text and action_type == "input_text" and key == "text":
                    scrubbed[key] = "<redacted:input_text>"
                elif (action_type == "request_intervention" and key == "text") or key == "reason":
                    scrubbed[key] = "<redacted:intervention_reason>"
                elif any(token in key.lower() for token in ("password", "secret", "token", "otp", "credential")):
                    scrubbed[key] = "<redacted:sensitive_field>"
                else:
                    scrubbed[key] = GuiAgent._scrub_value(item, redact_input_text=redact_input_text)
            return scrubbed
        if isinstance(value, list):
            return [GuiAgent._scrub_value(item, redact_input_text=redact_input_text) for item in value]
        if isinstance(value, str):
            return GuiAgent._scrub_sensitive_text(value)
        return value

    @staticmethod
    def _scrub_text_for_action(text: str | None, action: Action | None) -> str | None:
        return GuiAgent._scrub_text(text, action, redact_input_text=True)

    @staticmethod
    def _scrub_text_for_artifact_action(text: str | None, action: Action | None) -> str | None:
        return GuiAgent._scrub_text(text, action, redact_input_text=False)

    @staticmethod
    def _scrub_text(text: str | None, action: Action | None, *, redact_input_text: bool) -> str | None:
        if text is None:
            return None
        scrubbed = GuiAgent._scrub_sensitive_text(text)
        if action is None:
            return scrubbed
        if redact_input_text and action.action_type == "input_text" and action.text:
            scrubbed = scrubbed.replace(action.text, "<redacted:input_text>")
        if action.action_type == "request_intervention" and action.text:
            scrubbed = scrubbed.replace(action.text, "<redacted:intervention_reason>")
        return scrubbed

    @staticmethod
    def _scrub_sensitive_text(text: str) -> str:
        return re.sub(
            r"(?i)(\b[\w-]*(?:password|secret|token|otp|credential)[\w-]*\b\s*[:=]\s*)([^\s,}\]]+)",
            r"\1<redacted:sensitive_field>",
            text,
        )

    @classmethod
    def _scrub_assistant_message_for_log(
        cls,
        assistant_message: dict[str, Any],
        action: Action,
    ) -> dict[str, Any]:
        scrubbed = cls._scrub_for_log(assistant_message)
        content = scrubbed.get("content")
        if isinstance(content, str):
            scrubbed["content"] = cls._scrub_text_for_action(content, action)
        for tool_call in scrubbed.get("tool_calls", []):
            if not isinstance(tool_call, dict):
                continue
            function_payload = tool_call.get("function")
            if not isinstance(function_payload, dict):
                continue
            arguments = function_payload.get("arguments")
            if not isinstance(arguments, str):
                continue
            try:
                function_payload["arguments"] = json.dumps(
                    cls._scrub_for_log(json.loads(arguments)),
                    ensure_ascii=False,
                )
            except json.JSONDecodeError:
                function_payload["arguments"] = cls._scrub_text_for_action(arguments, action)
        return scrubbed

    @classmethod
    def _scrub_assistant_message_for_artifact(
        cls,
        assistant_message: dict[str, Any],
        action: Action,
    ) -> dict[str, Any]:
        scrubbed = cls._scrub_for_artifact(assistant_message)
        content = scrubbed.get("content")
        if isinstance(content, str):
            scrubbed["content"] = cls._scrub_text_for_artifact_action(content, action)
        for tool_call in scrubbed.get("tool_calls", []):
            if not isinstance(tool_call, dict):
                continue
            function_payload = tool_call.get("function")
            if not isinstance(function_payload, dict):
                continue
            arguments = function_payload.get("arguments")
            if not isinstance(arguments, str):
                continue
            try:
                function_payload["arguments"] = json.dumps(
                    cls._scrub_for_artifact(json.loads(arguments)),
                    ensure_ascii=False,
                )
            except json.JSONDecodeError:
                function_payload["arguments"] = cls._scrub_text_for_artifact_action(arguments, action)
        return scrubbed

    # ------------------------------------------------------------------
    # Run directory and trace
    # ------------------------------------------------------------------

    def _make_run_dir(self, task: str, attempt: int) -> Path:
        """Create a unique run directory for this task attempt."""
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", task)[:48].strip("_") or "gui_task"
        name = f"{slug}_{int(time.time() * 1000)}_{attempt}"
        run_dir = self.artifacts_root / name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "screenshots").mkdir(exist_ok=True)
        return run_dir

    @staticmethod
    async def _write_trace(path: Path, payload: dict[str, Any]) -> None:
        """Append a JSON line to the trace file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    @classmethod
    def _write_mobileworld_traj(
        cls,
        *,
        run_dir: Path,
        task: str,
        step_index: int,
        result: StepResult,
        current_observation: Observation,
        total_usage: dict[str, int],
    ) -> None:
        """Write an inspectable MobileWorld-style trajectory snapshot."""
        traj_path = run_dir / "traj.json"
        task_id = "0"
        if traj_path.exists():
            try:
                log_data = json.loads(traj_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log_data = {}
        else:
            log_data = {}

        task_log = log_data.setdefault(task_id, {"tools": None, "traj": []})
        marked_screenshot = cls._write_marked_screenshot(
            run_dir=run_dir,
            step_index=step_index,
            action=result.action,
            screenshot_path=current_observation.screenshot_path,
        )
        step_payload = {
            "task_goal": task,
            "step": step_index,
            "prediction": result.model_snapshot.get("action_text") or result.action_summary,
            "action": cls._scrub_for_artifact(cls._serialize_action(result.action)),
            "intent": cls._scrub_text_for_artifact_action(result.action_intent, result.action),
            "summary": cls._scrub_text_for_artifact_action(result.state_summary, result.action),
            "action_summary": cls._scrub_text_for_artifact_action(result.action_summary, result.action),
            "tool_call": _first_tool_call(result.model_snapshot),
            "tool_result": cls._scrub_text_for_artifact_action(result.tool_result, result.action),
            "done": result.done,
            "screenshot": _relative_path(current_observation.screenshot_path, run_dir),
            "next_screenshot": _relative_path(
                result.next_observation.screenshot_path
                if result.next_observation else None,
                run_dir,
            ),
            "marked_screenshot": marked_screenshot,
            "observation": cls._serialize_observation(current_observation),
            "next_observation": (
                cls._serialize_observation(result.next_observation)
                if result.next_observation else None
            ),
            "duration_s": round(result.duration_s, 3),
            "token_usage": result.step_usage or None,
        }
        task_log["traj"].append(cls._scrub_for_artifact(step_payload))
        task_log["token_usage"] = dict(total_usage)

        traj_path.write_text(
            json.dumps(log_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _write_marked_screenshot(
        *,
        run_dir: Path,
        step_index: int,
        action: Action,
        screenshot_path: str | None,
    ) -> str | None:
        if action.action_type not in {"tap", "double_tap", "long_press", "drag", "swipe"}:
            return None
        if not screenshot_path or action.x is None or action.y is None:
            return None
        source = Path(screenshot_path)
        if not source.exists():
            return None
        marked_dir = run_dir / "marked_screenshots"
        marked_dir.mkdir(parents=True, exist_ok=True)
        target = marked_dir / f"marked-step_{step_index:03d}.png"
        try:
            from PIL import Image, ImageDraw

            with Image.open(source) as image:
                image = image.convert("RGB")
                width, height = image.size
                draw = ImageDraw.Draw(image)
                x1, y1 = _image_point(action.x, action.y, width, height, relative=action.relative)
                radius = max(4, min(width, height) // 50)
                if action.action_type in {"drag", "swipe"} and action.x2 is not None and action.y2 is not None:
                    x2, y2 = _image_point(action.x2, action.y2, width, height, relative=action.relative)
                    draw.line((x1, y1, x2, y2), fill="blue", width=max(2, radius // 2))
                    draw.ellipse((x1 - radius, y1 - radius, x1 + radius, y1 + radius), fill="green")
                    draw.ellipse((x2 - radius, y2 - radius, x2 + radius, y2 + radius), fill="red")
                else:
                    draw.ellipse((x1 - radius, y1 - radius, x1 + radius, y1 + radius), fill="red")
                image.save(target)
        except Exception as exc:
            logger.debug("Could not write marked screenshot %s: %s", target, exc)
            return None
        return target.relative_to(run_dir).as_posix()

    async def _log_attempt_event(
        self,
        run_dir: Path,
        event: str,
        **payload: Any,
    ) -> None:
        scrubbed_payload = self._scrub_for_log(payload)
        await self._write_trace(run_dir / "trace.jsonl", {
            "event": event,
            "timestamp": time.time(),
            **scrubbed_payload,
        })
        self._trajectory_recorder.record_event(event, **scrubbed_payload)

    # ------------------------------------------------------------------
    # Memory / skill / trajectory helpers
    # ------------------------------------------------------------------

    async def _retrieve_memory(self, task: str) -> str | None:
        """Return memory context for the current task.

        When ``_policy_context`` is set (nanobot path), policy entries are injected
        directly without embedding search — guaranteeing full policy coverage.  The
        legacy ``_memory_retriever`` path (opengui CLI) is preserved for backward
        compatibility when ``_policy_context`` is not provided.
        """
        if self._policy_context is not None:
            self._log_policy_injection(self._policy_context)
            return self._policy_context

        # Existing retriever-based path — used by the opengui CLI and any callers that
        # construct GuiAgent directly with a memory_retriever.
        if self._memory_retriever is None:
            return None
        from opengui.memory.types import MemoryType

        # Fetch relevant entries by query
        results = await self._memory_retriever.search(task, top_k=self._memory_top_k + 10)

        # Separate POLICY entries from search results
        policies = [(e, s) for e, s in results if e.memory_type == MemoryType.POLICY]
        others = [(e, s) for e, s in results if e.memory_type != MemoryType.POLICY][
            : self._memory_top_k
        ]

        # Also fetch all POLICY entries separately (they must always be included)
        policy_results = await self._memory_retriever.search(
            task, memory_type=MemoryType.POLICY, top_k=50,
        )
        # Merge: add any POLICY entries not already in the list
        seen_ids = {e.entry_id for e, _ in policies}
        for entry, score in policy_results:
            if entry.entry_id not in seen_ids:
                policies.append((entry, score))
                seen_ids.add(entry.entry_id)

        memory_entries = policies + others
        if not memory_entries:
            logger.info("Memory retrieval: no hits for task=%r", task)
            self._trajectory_recorder.record_event(
                "memory_retrieval",
                task=task,
                hit_count=0,
                hits=[],
                context="",
            )
            return None
        context = self._memory_retriever.format_context(memory_entries)
        self._log_memory_retrieval(task, memory_entries, context)
        return context

    def _log_policy_injection(self, context: str) -> None:
        """Record a trajectory event for direct policy context injection."""
        line_count = context.count("\n") + 1
        logger.info("Policy context injected directly: %d line(s)", line_count)
        self._trajectory_recorder.record_event(
            "memory_retrieval",
            task="(policy_direct_injection)",
            hit_count=line_count,
            hits=[],
            context=context[:200],
        )

    def _log_memory_retrieval(
        self,
        task: str,
        memory_entries: list[tuple[Any, float]],
        context: str,
    ) -> None:
        hits: list[dict[str, Any]] = []
        logger.info("Memory retrieval: %d hit(s) for task=%r", len(memory_entries), task)
        for entry, score in memory_entries:
            preview = re.sub(r"\s+", " ", entry.content).strip()[:160]
            hit = {
                "entry_id": entry.entry_id,
                "memory_type": entry.memory_type.value,
                "platform": entry.platform,
                "app": entry.app,
                "score": round(float(score), 4),
                "content_preview": preview,
            }
            hits.append(hit)
            logger.info(
                "Memory hit id=%s type=%s score=%.4f platform=%s app=%s content=%s",
                entry.entry_id,
                entry.memory_type.value,
                float(score),
                entry.platform,
                entry.app or "-",
                preview,
            )

        self._trajectory_recorder.record_event(
            "memory_retrieval",
            task=task,
            hit_count=len(hits),
            hits=hits,
            context=context,
        )

    async def _search_skill(self, task: str) -> Any | None:
        """Search the skill library and return the top match when above threshold."""
        if self._skill_library is None:
            self._trajectory_recorder.record_event(
                "skill_search",
                task=task,
                source="none",
                matched=False,
                reason="no_library",
                threshold=self._skill_threshold,
            )
            return None
        from opengui.skills.data import compute_confidence

        search_results = await self._skill_library.search(
            task, platform=self.backend.platform, top_k=1,
        )
        if not search_results:
            self._trajectory_recorder.record_event(
                "skill_search",
                task=task,
                source="legacy",
                matched=False,
                reason="no_results",
                threshold=self._skill_threshold,
            )
            return None
        skill, relevance = search_results[0]
        confidence = compute_confidence(skill)
        final_score = relevance
        if final_score >= self._skill_threshold:
            self._trajectory_recorder.record_event(
                "skill_search",
                task=task,
                source="legacy",
                matched=True,
                skill_id=skill.skill_id,
                skill_name=skill.name,
                score=round(final_score, 4),
                confidence=round(confidence, 4),
                relevance=round(relevance, 4),
                threshold=self._skill_threshold,
            )
            return (skill, final_score)
        self._trajectory_recorder.record_event(
            "skill_search",
            task=task,
            source="legacy",
            matched=False,
            reason="below_threshold",
            skill_name=skill.name,
            score=round(final_score, 4),
            confidence=round(confidence, 4),
            relevance=round(relevance, 4),
            threshold=self._skill_threshold,
        )
        return None

    async def _execute_skill_with_params(self, task: str, skill: Any) -> Any:
        """Execute a skill, extracting task parameters only when needed."""
        if self._skill_executor is None:
            raise RuntimeError("skill executor is not configured")
        skill_params: dict[str, str] = {}
        if getattr(skill, "parameters", None):
            skill_params = await self._extract_skill_params(task, skill)
            missing_params = _missing_skill_params(skill, skill_params)
            if missing_params:
                recorder = getattr(self, "_trajectory_recorder", None)
                if recorder is not None:
                    recorder.record_event(
                        "skill_param_extraction_failed",
                        skill_id=str(getattr(skill, "skill_id", "") or ""),
                        skill_name=str(getattr(skill, "name", "") or ""),
                        reason="missing_required_params",
                        missing_params=missing_params,
                        extracted_params=dict(skill_params),
                    )
                raise RuntimeError(
                    "missing required skill params: " + ", ".join(missing_params)
                )
        return await self._skill_executor.execute(skill, params=skill_params)

    async def _skill_entry_allows_current_state(self, skill: Any) -> bool:
        """Fail closed on mid-flow skills unless their first contract matches now."""
        steps = tuple(getattr(skill, "steps", ()) or ())
        skill_id = str(getattr(skill, "skill_id", "") or "")
        skill_name = str(getattr(skill, "name", "") or "")
        if not steps:
            self._trajectory_recorder.record_event(
                "skill_entry_rejected",
                skill_id=skill_id,
                skill_name=skill_name,
                reason="empty_skill",
            )
            return False

        first_step = steps[0]
        first_action = str(getattr(first_step, "action_type", "") or "")
        if first_action == "open_app" and _skill_entry_targets_android_launcher(skill, first_step):
            self._trajectory_recorder.record_event(
                "skill_entry_rejected",
                skill_id=skill_id,
                skill_name=skill_name,
                first_action=first_action,
                reason="launcher_entry_package",
                app=str(getattr(skill, "app", "") or "") or None,
                target=str(getattr(first_step, "target", "") or "") or None,
            )
            return False
        if first_action in {"open_app", "open_deeplink", "open_intent"}:
            self._trajectory_recorder.record_event(
                "skill_entry_accepted",
                skill_id=skill_id,
                skill_name=skill_name,
                first_action=first_action,
                reason="entry_action",
            )
            return True

        contract = getattr(first_step, "state_contract", None)
        if contract is None:
            self._trajectory_recorder.record_event(
                "skill_entry_rejected",
                skill_id=skill_id,
                skill_name=skill_name,
                first_action=first_action,
                reason="missing_first_step_state_contract",
            )
            return False

        screenshot_path = self.artifacts_root / "skill_entry_gate" / "current.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            observation = await self.backend.observe(
                screenshot_path,
                timeout=self.step_timeout,
            )
        except Exception as exc:
            logger.warning("Skill entry observation failed for %s: %s", skill_name, exc)
            self._trajectory_recorder.record_event(
                "skill_entry_rejected",
                skill_id=skill_id,
                skill_name=skill_name,
                first_action=first_action,
                reason="observe_failed",
                error=str(exc),
            )
            return False

        contract_result = evaluate_state_contract(contract, observation=observation)
        if contract_result is True:
            self._trajectory_recorder.record_event(
                "skill_entry_accepted",
                skill_id=skill_id,
                skill_name=skill_name,
                first_action=first_action,
                reason="state_contract_matched",
            )
            return True

        self._trajectory_recorder.record_event(
            "skill_entry_rejected",
            skill_id=skill_id,
            skill_name=skill_name,
            first_action=first_action,
            reason="state_contract_unevaluable" if contract_result is None else "state_contract_failed",
        )
        return False

    async def _inject_skill_memory_context(
        self,
        skill: Any,
        existing_context: str | None,
    ) -> str | None:
        """No-op: legacy Skill objects do not carry a memory_context_id."""
        return existing_context

    async def _extract_skill_params(
        self,
        task: str,
        skill: Any,
    ) -> dict[str, str]:
        """Extract runtime parameter values from the task description via LLM.

        Uses the skill's declared ``parameters`` list as a schema and asks the
        LLM to pull matching values from the task string.  Returns partial
        values when some parameters can be inferred deterministically.
        """
        param_names: list[str] = _skill_param_names(skill)
        if not param_names:
            return {}
        params = {
            name: value
            for name in param_names
            if (value := self._guess_skill_param(task, name)) is not None
        }
        if len(params) == len(param_names):
            return params
        json_template = "{" + ", ".join(f'"{p}": "value"' for p in param_names) + "}"
        prompt = (
            f"Task: {task}\n\n"
            f"Skill: {skill.name} — {skill.description}\n"
            f"Parameters to extract: {param_names}\n\n"
            f"Extract the value for each parameter from the task description.\n"
            f"Return JSON only, with exactly these keys: {json_template}"
        )
        try:
            response = await asyncio.wait_for(
                self.llm.chat([{"role": "user", "content": prompt}]),
                timeout=8.0,
            )
        except Exception as exc:
            logger.warning("Skill param extraction LLM call failed: %s", exc)
            recorder = getattr(self, "_trajectory_recorder", None)
            if recorder is not None:
                recorder.record_event(
                    "skill_param_extraction_failed",
                    skill_id=str(getattr(skill, "skill_id", "") or ""),
                    skill_name=str(getattr(skill, "name", "") or ""),
                    reason="llm_call_failed",
                    error=str(exc),
                    exception_type=type(exc).__name__,
                    missing_params=[name for name in param_names if name not in params],
                    extracted_params=dict(params),
                )
            return params
        text = (response.content or "").strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
                for key, value in obj.items():
                    if key in param_names and key not in params:
                        text_value = str(value).strip()
                        if text_value:
                            params[key] = text_value
                return params
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse skill param extraction response: %r", text[:120])
        recorder = getattr(self, "_trajectory_recorder", None)
        if recorder is not None:
            recorder.record_event(
                "skill_param_extraction_failed",
                skill_id=str(getattr(skill, "skill_id", "") or ""),
                skill_name=str(getattr(skill, "name", "") or ""),
                reason="parse_failed",
                response=text[:240],
                missing_params=[name for name in param_names if name not in params],
                extracted_params=dict(params),
            )
        return params

    @staticmethod
    def _guess_skill_param(task: str, param_name: str) -> str | None:
        name = param_name.strip().casefold()
        normalized = " ".join((task or "").split())
        if not normalized:
            return None
        quoted = re.search(r"[“\"']([^”\"']{1,80})[”\"']", normalized)
        text_like_names = {
            "search_query",
            "search_term",
            "query",
            "keyword",
            "title",
            "subject",
            "note",
            "memo",
            "message",
            "description",
            "text",
            "name",
            "contact_name",
            "person",
            "item",
        }
        if quoted is not None and name in text_like_names:
            return quoted.group(1).strip()
        if name in {"phone", "phone_number", "mobile", "mobile_phone", "tel", "telephone"}:
            for pattern in (
                r"(?:手机号|电话号码|联系电话|电话)\s*(?:是|为|:|：)?\s*([+()0-9][0-9()+\-\s]{5,24})",
                r"(?:phone|mobile|tel(?:ephone)?)\s*(?:number)?\s*(?:is|:)?\s*([+()0-9][0-9()+\-\s]{5,24})",
            ):
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if match is not None:
                    value = re.sub(r"\s+", "", match.group(1)).strip(".,;，。；")
                    if value:
                        return value
            return None
        if name in {"amount", "price", "cost", "total", "value", "money"}:
            for pattern in (
                r"(?:金额|价格|花费|费用|总额|支出)\s*(?:是|为|:|：)?\s*(?:¥|￥|\$)?\s*([0-9]+(?:\.[0-9]+)?)",
                r"(?:amount|price|cost|total|value)\s*(?:is|:)?\s*(?:\$)?\s*([0-9]+(?:\.[0-9]+)?)",
                r"(?:¥|￥|\$)\s*([0-9]+(?:\.[0-9]+)?)",
            ):
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if match is not None:
                    return match.group(1).strip()
            return None
        if name in {"date", "day"}:
            match = re.search(
                r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)?|\d{1,2}[-/]\d{1,2})",
                normalized,
            )
            return _clean_inferred_param(match.group(1)) if match else None
        if name in {"time", "clock_time"}:
            match = re.search(
                r"(\d{1,2}\s*[:：]\s*\d{2}(?:\s*(?:AM|PM|am|pm))?|\d{1,2}\s*(?:点|时)(?:\s*\d{1,2}\s*分?)?)",
                normalized,
            )
            return _clean_inferred_param(match.group(1)) if match else None
        if name in {"name", "contact_name", "person"}:
            for pattern in (
                r"(?:联系人|姓名|名字)\s*(?:是|为|叫|:|：)?\s*([^，,。.!?；;、]{1,40})",
                r"(?:named|called|name(?:d)?\s+is)\s+([^,.;]{1,60})",
            ):
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if match is not None:
                    value = _clean_inferred_param(match.group(1))
                    if value:
                        return value
            return None
        if name in {"city", "location", "destination", "place", "area"}:
            for pattern in (
                r"(?:搜索一下|搜一下|搜索|查找|找一下)\s*([^，,。.!?；;、]{2,30}?)(?:周边|附近|的酒店|酒店|民宿)",
                r"(?:去|到)\s*([^，,。.!?；;、]{2,16}?)(?:附近|周边|住|的|，|,|要)",
                r"住在\s*([^，,。.!?；;、]{2,16}?)(?:附近|周边|，|,|要)",
            ):
                for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
                    value = _clean_inferred_param(match.group(1))
                    if value and not _looks_like_date_param(value):
                        return value
            return None
        if name not in {"search_query", "search_term", "query", "keyword"}:
            return None
        account = re.search(r"(?:找一下|找|搜索|搜)\s*([^，,。.!?；;、]{1,30}?)(?:的账号|账号)", normalized)
        if account is not None:
            value = _clean_inferred_param(account.group(1))
            if value:
                return value
        for pattern in (
            r"(?:搜索一下|搜一下|搜索|查找)\s*([^\s，,。.!?；;、]+)",
            r"(?:search\s+for|search|find)\s*([^\s，,。.!?；;、]+)",
        ):
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match is None:
                continue
            value = _clean_inferred_param(match.group(1))
            if value:
                return value
        return None

    async def _skill_maintenance(
        self, skill_match: Any | None, success: bool
    ) -> None:
        """Post-run: update confidence while keeping failed skills evolvable."""
        if skill_match is None or self._skill_library is None:
            return
        if hasattr(skill_match, "layer"):
            return
        skill, _ = skill_match
        if success:
            updated = replace(
                skill,
                success_count=skill.success_count + 1,
                success_streak=skill.success_streak + 1,
                failure_streak=0,
            )
        else:
            updated = replace(
                skill,
                failure_count=skill.failure_count + 1,
                failure_streak=skill.failure_streak + 1,
                success_streak=0,
            )

        self._skill_library.update(skill.skill_id, updated)


def _first_tool_call(model_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    tool_calls = model_snapshot.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        first = tool_calls[0]
        if isinstance(first, dict):
            return first
    return None


def _relative_path(path: str | None, root: Path) -> str | None:
    if not path:
        return None
    target = Path(path)
    try:
        return target.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _image_point(
    x: float,
    y: float,
    width: int,
    height: int,
    *,
    relative: bool,
) -> tuple[int, int]:
    return (
        _image_coordinate(x, width, relative=relative),
        _image_coordinate(y, height, relative=relative),
    )


def _image_coordinate(value: float, extent: int, *, relative: bool) -> int:
    if extent <= 1:
        return 0
    if relative:
        pixel = round(float(value) / 999 * (extent - 1))
    else:
        pixel = round(float(value))
    return max(0, min(pixel, extent - 1))
