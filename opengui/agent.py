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
import json
import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from opengui.action import Action, ActionError, describe_action, parse_action
from opengui.interfaces import (
    DeviceBackend,
    InterventionHandler,
    InterventionRequest,
    LLMProvider,
    LLMResponse,
    ProgressCallback,
)
from opengui.skills.shortcut_router import (
    ApplicabilityDecision,
    ShortcutApplicabilityRouter,
    filter_candidates_by_context,
)
from opengui.skills.normalization import normalize_app_identifier
from opengui.observation import Observation
from opengui.prompts.system import build_system_prompt
from opengui.trajectory.recorder import ExecutionPhase, TrajectoryRecorder

logger = logging.getLogger(__name__)


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
    next_observation: Observation | None = None
    action_debug: dict[str, Any] | None = None
    prompt_snapshot: dict[str, Any] | None = None
    model_snapshot: dict[str, Any] | None = None
    execution_snapshot: dict[str, Any] | None = None
    intervention_requested: bool = False
    done: bool = False


@dataclass(frozen=True)
class HistoryTurn:
    """One completed step kept in the prompt history window."""

    step_index: int
    observation: Observation
    assistant_message: dict[str, Any]
    tool_result_message: dict[str, Any]
    action_summary: str


@dataclass(frozen=True)
class AgentResult:
    """Final result of a complete GUI task run (possibly with retries)."""

    success: bool
    summary: str
    model_summary: str | None = None
    trace_path: str | None = None
    steps_taken: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

_COMPUTER_USE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "computer_use",
        "description": "Perform a GUI action on the device screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": [
                        "tap", "double_tap", "long_press", "swipe", "drag",
                        "input_text", "hotkey", "scroll",
                        "wait", "open_app", "close_app",
                        "back", "home", "done", "request_intervention",
                    ],
                },
                "x": {"type": "number", "description": "Primary X coordinate."},
                "y": {"type": "number", "description": "Primary Y coordinate."},
                "x2": {"type": "number", "description": "End X for swipe/drag."},
                "y2": {"type": "number", "description": "End Y for swipe/drag."},
                "text": {
                    "type": "string",
                    "description": (
                        "Text for input_text, direction for scroll, or app identifier "
                        "for open_app/close_app. Use a short reason for "
                        "request_intervention. On Android, use package names."
                    ),
                },
                "key": {"type": "array", "items": {"type": "string"}, "description": "Keys for hotkey."},
                "pixels": {"type": "integer", "description": "Scroll distance."},
                "duration_ms": {"type": "integer", "description": "Duration in ms."},
                "relative": {"type": "boolean", "description": "True if [0,999] relative coords."},
                "status": {"type": "string", "enum": ["success", "failure"], "description": "For done action."},
            },
            "required": ["action_type"],
        },
    },
}


def _summarize_shortcut_success(result: Any) -> str:
    """Build a concise shortcut execution summary for subsequent agent steps."""
    lines = [f"Shortcut '{result.skill_id}' executed {len(result.step_results)} step(s):"]
    for step_result in result.step_results:
        action_desc = getattr(step_result.action, "action_type", "unknown")
        lines.append(
            f"Step {step_result.step_index}: {action_desc} -> {step_result.backend_result}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent-side protocol implementations for SkillExecutor
# ---------------------------------------------------------------------------

class _AgentActionGrounder:
    """Ground a non-fixed SkillStep into a concrete Action via vision LLM.

    Sends the current screenshot and step description to the LLM with the
    ``computer_use`` tool and parses the returned tool call into an Action.
    """

    _MAX_RETRIES = 2

    def __init__(self, llm: LLMProvider, model: str) -> None:
        self._llm = llm
        self._model = model

    async def ground(
        self,
        step: Any,  # SkillStep — avoid circular import
        screenshot: "Path | bytes",
        params: dict[str, str],
    ) -> "Action":
        from opengui.action import parse_action
        from opengui.skills.executor import _ground_text

        target = _ground_text(step.target, params)
        extra_ctx = ""
        if step.parameters:
            extra_ctx = f"\nContext: {step.parameters}"

        prompt = (
            f"Look at the screenshot carefully. Perform the following action:\n"
            f"  action_type: {step.action_type}\n"
            f"  target: {target}{extra_ctx}\n\n"
            f"Respond with ONLY a computer_use tool call. "
            f"You MUST use action_type='{step.action_type}'."
        )
        import base64
        if isinstance(screenshot, Path):
            image_data = base64.b64encode(screenshot.read_bytes()).decode()
        else:
            image_data = base64.b64encode(screenshot).decode()

        messages: list[dict[str, Any]] = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
            ],
        }]

        for attempt in range(self._MAX_RETRIES + 1):
            try:
                response = await self._llm.chat(
                    messages=messages,
                    tools=[_COMPUTER_USE_TOOL],
                    tool_choice="required",
                )
            except Exception as exc:
                raise RuntimeError(f"ActionGrounder LLM call failed: {exc}") from exc

            if response.tool_calls:
                tc = response.tool_calls[0]
                if tc.name == "computer_use":
                    try:
                        return parse_action(tc.arguments)
                    except Exception as exc:
                        if attempt < self._MAX_RETRIES:
                            messages.append({"role": "assistant", "content": response.content or ""})
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": f"Error parsing action: {exc}. Please fix.",
                            })
                            continue
                        raise RuntimeError(f"ActionGrounder parse failed: {exc}") from exc

            if attempt < self._MAX_RETRIES:
                messages.append({"role": "assistant", "content": response.content or ""})
                messages.append({
                    "role": "tool",
                    "tool_call_id": "error",
                    "content": "Error: no computer_use tool call. You must use it.",
                })
            else:
                raise RuntimeError("ActionGrounder: LLM did not return a computer_use call after retries.")

        raise RuntimeError("ActionGrounder: unexpected exit from retry loop.")


class _AgentSubgoalRunner:
    """Mini vision-action loop to recover to a desired screen state.

    Maintains an isolated history (not shared with the main agent loop) and
    runs up to ``max_steps`` observe → LLM → execute → validate cycles.
    """

    def __init__(
        self,
        llm: LLMProvider,
        backend: "DeviceBackend",
        state_validator: Any,
        model: str,
        artifacts_root: "Path",
    ) -> None:
        self._llm = llm
        self._backend = backend
        self._state_validator = state_validator
        self._model = model
        self._artifacts_root = Path(artifacts_root)
        self._step_counter = 0

    async def run_subgoal(
        self,
        goal: str,
        screenshot: "Path | bytes",
        *,
        max_steps: int = 3,
    ) -> "Any":  # SubgoalResult
        from opengui.action import parse_action, ActionError
        from opengui.skills.executor import SubgoalResult, _should_skip_validation

        summaries: list[str] = []
        current_screenshot: Path | bytes = screenshot

        for i in range(max_steps):
            # Build a minimal prompt for the subgoal
            history_text = (
                "\n".join(f"  Sub-step {j+1}: {s}" for j, s in enumerate(summaries))
                if summaries else "  None"
            )
            prompt = (
                f"Your current sub-goal is: {goal}\n\n"
                f"Previous sub-steps:\n{history_text}\n\n"
                f"Look at the screenshot and choose ONE action that moves you "
                f"closer to the sub-goal. Respond with ONLY a computer_use tool call."
            )

            import base64
            if isinstance(current_screenshot, Path):
                img_bytes = current_screenshot.read_bytes()
            else:
                img_bytes = current_screenshot
            image_data = base64.b64encode(img_bytes).decode()

            messages: list[dict[str, Any]] = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
                ],
            }]

            try:
                response = await self._llm.chat(
                    messages=messages,
                    tools=[_COMPUTER_USE_TOOL],
                    tool_choice="required",
                )
            except Exception as exc:
                logger.error("Subgoal LLM call failed at sub-step %d: %s", i, exc)
                return SubgoalResult(success=False, steps_taken=i, action_summaries=summaries, error=str(exc))

            if not response.tool_calls or response.tool_calls[0].name != "computer_use":
                logger.warning("Subgoal LLM returned no valid tool call at sub-step %d", i)
                summaries.append(f"Sub-step {i+1}: no valid action returned")
                continue

            tc = response.tool_calls[0]
            try:
                action = parse_action(tc.arguments)
            except ActionError as exc:
                logger.warning("Subgoal action parse failed at sub-step %d: %s", i, exc)
                summaries.append(f"Sub-step {i+1}: action parse error — {exc}")
                continue

            # Skip terminal actions inside a subgoal
            if action.action_type in ("done", "request_intervention"):
                summaries.append(f"Sub-step {i+1}: terminal action skipped in subgoal")
                continue

            try:
                await self._backend.execute(action)
            except Exception as exc:
                logger.warning("Subgoal execution failed at sub-step %d: %s", i, exc)
                summaries.append(f"Sub-step {i+1}: {action.action_type} — execution error: {exc}")
                continue

            # Observe new screen
            self._step_counter += 1
            subgoal_dir = self._artifacts_root / "subgoal_screenshots"
            subgoal_dir.mkdir(parents=True, exist_ok=True)
            next_path = subgoal_dir / f"subgoal_{int(time.time() * 1000)}_{self._step_counter}.png"
            try:
                obs = await self._backend.observe(next_path)
                current_screenshot = Path(obs.screenshot_path) if obs.screenshot_path else current_screenshot
            except Exception as exc:
                logger.warning("Subgoal observe failed at sub-step %d: %s", i, exc)

            action_desc = f"{action.action_type}"
            if hasattr(action, "x") and action.x is not None:
                action_desc += f" at ({action.x}, {action.y})"
            elif hasattr(action, "text") and action.text:
                action_desc += f" '{action.text}'"
            summaries.append(f"Sub-step {i+1}: {action_desc}")

            # Check if the goal state has been reached
            if not _should_skip_validation(goal) and self._state_validator is not None:
                try:
                    reached = await self._state_validator.validate(goal, screenshot=current_screenshot)
                except Exception:
                    reached = False
                if reached:
                    logger.info("Subgoal reached after %d sub-steps", i + 1)
                    return SubgoalResult(
                        success=True,
                        steps_taken=i + 1,
                        action_summaries=summaries,
                        final_screenshot=current_screenshot,
                    )

        return SubgoalResult(
            success=False,
            steps_taken=max_steps,
            action_summaries=summaries,
            error=f"Subgoal not reached after {max_steps} sub-steps",
        )


class _AgentScreenshotProvider:
    """Provide the current screenshot via ``DeviceBackend.observe()``."""

    def __init__(self, backend: "DeviceBackend", artifacts_root: "Path") -> None:
        self._backend = backend
        self._artifacts_root = Path(artifacts_root)
        self._counter = 0

    async def get_screenshot(self) -> Path | None:
        self._counter += 1
        skill_dir = self._artifacts_root / "skill_screenshots"
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_dir / f"skill_{int(time.time() * 1000)}_{self._counter}.png"
        try:
            obs = await self._backend.observe(path)
            if obs.screenshot_path:
                return Path(obs.screenshot_path)
        except Exception as exc:
            logger.warning("ScreenshotProvider observe failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# GuiAgent
# ---------------------------------------------------------------------------

class GuiAgent:
    """Standalone GUI automation agent with vision-action loop.

    Args:
        llm: LLM provider conforming to :class:`~opengui.interfaces.LLMProvider`.
        backend: Device backend conforming to :class:`~opengui.interfaces.DeviceBackend`.
        model: Model name string (used for prompt customisation).
        artifacts_root: Root directory for run artifacts (traces, screenshots).
        max_steps: Maximum steps per single attempt.
        step_timeout: Timeout in seconds for each step (LLM + execute + observe).
        history_image_window: Number of recent screenshot turns kept as full image context.
        include_date_context: Whether to include today's date in the task framing text.
        progress_callback: Optional async callback for progress reporting.
    """

    _MAX_TOOL_RETRIES = 2
    _MODEL_RELATIVE_GRID_HINTS = ("qwen", "gemini")
    _COORDINATE_ACTIONS = frozenset({"tap", "double_tap", "long_press", "swipe", "drag", "scroll"})
    _POST_ACTION_SETTLE_SECONDS = 0.50
    _NO_SETTLE_ACTIONS = frozenset({"wait", "done", "request_intervention"})

    def __init__(
        self,
        llm: LLMProvider,
        backend: DeviceBackend,
        trajectory_recorder: TrajectoryRecorder,
        model: str = "",
        artifacts_root: Path | str = ".opengui/runs",
        max_steps: int = 15,
        step_timeout: float = 30.0,
        history_image_window: int = 4,
        include_date_context: bool = True,
        progress_callback: ProgressCallback | None = None,
        memory_retriever: Any = None,
        skill_library: Any = None,
        skill_executor: Any = None,
        shortcut_executor: Any = None,
        memory_top_k: int = 5,
        skill_threshold: float = 0.6,
        installed_apps: list[str] | None = None,
        intervention_handler: InterventionHandler | None = None,
        policy_context: str | None = None,
        unified_skill_search: Any = None,
        memory_store: Any = None,
        shortcut_applicability_router: ShortcutApplicabilityRouter | None = None,
    ) -> None:
        self.llm = llm
        self.backend = backend
        self.model = model
        self.artifacts_root = Path(artifacts_root)
        self.max_steps = max_steps
        self.step_timeout = step_timeout
        self.history_image_window = max(1, history_image_window)
        self.include_date_context = include_date_context
        self.progress_callback = progress_callback
        self._trajectory_recorder = trajectory_recorder
        self._memory_retriever = memory_retriever
        self._policy_context = policy_context
        self._skill_library = skill_library
        self._skill_executor = skill_executor
        self._shortcut_executor = shortcut_executor
        self._memory_top_k = memory_top_k
        self._skill_threshold = skill_threshold
        self._installed_apps = installed_apps
        self._intervention_handler = intervention_handler
        self._unified_skill_search = unified_skill_search
        self._memory_store = memory_store
        self._shortcut_applicability_router = shortcut_applicability_router

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

        # 3. Search skill library (once)
        skill_match = await self._search_skill(task)

        matched_skill: Any | None = None
        final_score: float | None = None
        if skill_match is not None:
            if hasattr(skill_match, "layer"):
                matched_skill = skill_match.skill
                final_score = skill_match.score
            else:
                matched_skill, final_score = skill_match
            memory_context = await self._inject_skill_memory_context(matched_skill, memory_context)

        # 3b. Retrieve shortcut candidates (multi-candidate, filtered by platform + app)
        shortcut_candidates = await self._retrieve_shortcut_candidates(
            task, platform=self.backend.platform, app_hint=app_hint,
        )

        # 4. If skill matched (legacy path), attempt skill execution first.
        # Shortcut candidates from step 3b are evaluated inside the retry loop
        # at attempt 0 using a live screenshot so applicability is screen-aware.
        skill_context: str | None = None
        if matched_skill is not None and self._skill_executor is not None and final_score is not None:
            self._trajectory_recorder.set_phase(
                ExecutionPhase.SKILL,
                reason=f"Matched skill: {matched_skill.name} (score={final_score:.2f})",
            )
            try:
                skill_result = await self._skill_executor.execute(matched_skill)
                execution_summary = getattr(skill_result, "execution_summary", None)
                skill_context = execution_summary if isinstance(execution_summary, str) else None
                if skill_result.state.value == "succeeded":
                    # Skill succeeded — fall through to agent for confirmation
                    self._trajectory_recorder.set_phase(
                        ExecutionPhase.AGENT, reason="Skill complete, agent confirms"
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

        # Tracks whether the first attempt used a shortcut so retries can clear
        # matched_skill and skill_context to avoid stale shortcut context.
        _shortcut_attempted: bool = False

        for attempt in range(max_retries):
            run_dir = self._make_run_dir(task, attempt)
            last_trace_path = str(run_dir)

            # Attempt 0: evaluate shortcut applicability using a live screenshot.
            # When applicability returns "run", the selected shortcut takes priority
            # over any legacy _search_skill match and its execution result supplies
            # skill_context for this attempt.
            if attempt == 0 and shortcut_candidates:
                pre_obs = await self.backend.observe(
                    run_dir / "screenshots" / "pre_shortcut_check.png",
                    timeout=self.step_timeout,
                )
                pre_screenshot = (
                    Path(pre_obs.screenshot_path) if pre_obs.screenshot_path else None
                )
                applicability_decision = await self._evaluate_shortcut_applicability(
                    shortcut_candidates,
                    screenshot_path=pre_screenshot,
                    task=task,
                )
                if applicability_decision.outcome == "run":
                    # Find the candidate matching the approved shortcut_id
                    approved = next(
                        (
                            r for r in shortcut_candidates
                            if r.skill.skill_id == applicability_decision.shortcut_id
                        ),
                        None,
                    )
                    if approved is not None:
                        matched_skill = approved.skill
                        final_score = applicability_decision.score
                        memory_context = await self._inject_skill_memory_context(
                            matched_skill, memory_context
                        )
                        if self._shortcut_executor is not None:
                            score_text = f"{final_score:.2f}" if final_score is not None else "n/a"
                            self._trajectory_recorder.set_phase(
                                ExecutionPhase.SKILL,
                                reason=(
                                    f"Executing approved shortcut '{matched_skill.name}' "
                                    f"via ShortcutExecutor (score={score_text})"
                                ),
                            )
                            try:
                                shortcut_result = await self._shortcut_executor.execute(matched_skill)
                                if shortcut_result.is_violation:
                                    self._trajectory_recorder.record_event(
                                        "shortcut_execution", outcome="violation",
                                        skill_id=shortcut_result.skill_id,
                                        step_index=shortcut_result.step_index,
                                        boundary=shortcut_result.boundary,
                                        failed_condition=shortcut_result.failed_condition.value,
                                    )
                                    matched_skill = None
                                    skill_context = None
                                    self._trajectory_recorder.set_phase(
                                        ExecutionPhase.AGENT,
                                        reason=(
                                            "Shortcut contract violation, falling back "
                                            "to free exploration"
                                        ),
                                    )
                                else:
                                    skill_context = _summarize_shortcut_success(shortcut_result)
                                    self._trajectory_recorder.record_event(
                                        "shortcut_execution", outcome="success",
                                        skill_id=shortcut_result.skill_id,
                                        steps_taken=len(shortcut_result.step_results),
                                    )
                                    self._trajectory_recorder.set_phase(
                                        ExecutionPhase.AGENT,
                                        reason="Shortcut complete, agent confirms",
                                    )
                            except Exception as exc:
                                self._trajectory_recorder.record_event(
                                    "shortcut_execution", outcome="exception",
                                    error_type=type(exc).__name__,
                                    error_message=str(exc),
                                )
                                matched_skill = None
                                skill_context = None
                                self._trajectory_recorder.set_phase(
                                    ExecutionPhase.AGENT,
                                    reason="Shortcut execution raised exception, falling back",
                                )
                        _shortcut_attempted = True

            # On retries after a failed shortcut attempt, clear shortcut context so
            # subsequent retries use free exploration instead of a stale shortcut.
            if attempt > 0 and _shortcut_attempted:
                matched_skill = None
                skill_context = None

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
                if result.error and result.error.startswith("intervention_cancelled"):
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
                await self._log_attempt_event(
                    run_dir,
                    "attempt_exception",
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                if attempt < max_retries - 1:
                    await self._log_attempt_event(
                        run_dir,
                        "retry",
                        attempt=attempt,
                        next_attempt=attempt + 1,
                        reason=last_error,
                    )

        if result is None or not result.success:
            result = AgentResult(
                success=False,
                summary=f"Failed after {max_retries} attempt(s).",
                model_summary=last_model_summary,
                trace_path=last_trace_path,
                steps_taken=last_steps_taken,
                error=last_error,
            )

        # 6. Finish trajectory
        self._trajectory_recorder.finish(success=result.success, error=result.error)

        # 7. Post-run skill maintenance
        await self._skill_maintenance(skill_match, result.success)

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
                summary=f"Preflight failed: {exc}",
                trace_path=str(run_dir),
                error=str(exc),
            )

        # 2. Initial observation
        obs = await self.backend.observe(
            run_dir / "screenshots" / "step_000.png",
            timeout=self.step_timeout,
        )

        history: list[HistoryTurn] = []

        # 4. Step loop
        steps_taken = 0
        for step in range(self.max_steps):
            step_index = step + 1
            messages = self._build_messages(
                task=task,
                current_observation=obs,
                history=history,
                app_hint=app_hint,
                memory_context=memory_context,
                skill_context=skill_context,
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
                    summary=f"Step {step_index} timed out.",
                    model_summary=None,
                    trace_path=str(run_dir),
                    steps_taken=step_index,
                    error="step_timeout",
                )

            steps_taken = step_index

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

            # Write trace entry
            await self._write_trace(run_dir / "trace.jsonl", self._scrub_for_log({
                "event": "step",
                "step_index": step_index,
                "action": self._serialize_action(result.action),
                "action_debug": result.action_debug,
                "prompt": result.prompt_snapshot,
                "model_output": result.model_snapshot,
                "execution": result.execution_snapshot,
                "tool_result": self._scrub_text_for_action(result.tool_result, result.action),
                "screenshot_path": (
                    result.next_observation.screenshot_path
                    if result.next_observation else None
                ),
                "done": result.done,
                "timestamp": time.time(),
            }))

            # Record trajectory step
            self._trajectory_recorder.record_step(
                action=self._scrub_for_log(self._serialize_action(result.action)),
                model_output=self._scrub_text_for_action(result.action_summary, result.action) or "",
                screenshot_path=(
                    str(result.next_observation.screenshot_path)
                    if result.next_observation and result.next_observation.screenshot_path
                    else None
                ),
                prompt=result.prompt_snapshot,
                model_response=result.model_snapshot,
                execution=result.execution_snapshot,
            )

            if intervention_cancelled:
                return AgentResult(
                    success=False,
                    summary=f"Task cancelled during intervention after {steps_taken} step(s).",
                    model_summary=result.action_summary,
                    trace_path=str(run_dir),
                    steps_taken=steps_taken,
                    error=f"intervention_cancelled: {cancellation_note}",
                )

            if result.done:
                success = result.action.status == "success"
                return AgentResult(
                    success=success,
                    summary=f"Task {'completed' if success else 'failed'} "
                            f"after {steps_taken} step(s).",
                    model_summary=result.action_summary,
                    trace_path=str(run_dir),
                    steps_taken=steps_taken,
                    error=None if success else result.tool_result,
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
                )
            )

            if result.next_observation is not None:
                obs = result.next_observation

        return AgentResult(
            success=False,
            summary=f"Reached max steps ({self.max_steps}) without completion.",
            model_summary=None,
            trace_path=str(run_dir),
            steps_taken=steps_taken,
            error="max_steps_exceeded",
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
        retries_left = self._MAX_TOOL_RETRIES + 1

        while retries_left > 0:
            retries_left -= 1

            # Call LLM
            response: LLMResponse = await self.llm.chat(
                messages=messages,
                tools=[_COMPUTER_USE_TOOL],
                tool_choice="required",
            )

            # Append assistant message
            assistant_msg = self._build_assistant_message(response)
            messages.append(assistant_msg)

            # Validate tool call
            if not response.tool_calls or len(response.tool_calls) == 0:
                if retries_left > 0:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": "error",
                        "content": "Error: no tool call found. You must use the computer_use tool.",
                    })
                    continue
                raise RuntimeError("LLM did not return a computer_use tool call after retries.")

            tool_call = response.tool_calls[0]
            if tool_call.name != "computer_use":
                if retries_left > 0:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error: expected 'computer_use' tool, got '{tool_call.name}'.",
                    })
                    continue
                raise RuntimeError(f"LLM called unexpected tool '{tool_call.name}'.")

            # Parse action
            try:
                action = parse_action(tool_call.arguments)
                action = self._normalize_relative_coordinates(action)
            except ActionError as exc:
                if retries_left > 0:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error parsing action: {exc}. Please fix and retry.",
                    })
                    continue
                raise RuntimeError(f"Failed to parse action after retries: {exc}") from exc

            # Report progress
            if self.progress_callback is not None:
                await self.progress_callback(
                    f"GUI step {step_index}/{total_steps}: {describe_action(action)}"
                )

            action_text = self._normalize_action_text(response.content, action)
            assistant_message = self._build_assistant_message(
                response,
                content_override=action_text,
            )
            model_snapshot = self._snapshot_model_response(
                response=response,
                action=action,
                assistant_message=assistant_message,
                action_text=action_text,
            )

            # Handle terminal action (done)
            if action.action_type == "done":
                tool_result = f"Task terminated with status: {action.status or 'unknown'}"
                return StepResult(
                    action=action,
                    tool_call_id=tool_call.id,
                    tool_result=tool_result,
                    assistant_message=assistant_message,
                    action_summary=self._action_summary(action_text),
                    prompt_snapshot=prompt_snapshot,
                    model_snapshot=model_snapshot,
                    execution_snapshot={
                        "tool_result": tool_result,
                        "next_observation": None,
                        "done": True,
                    },
                    done=True,
                )

            if action.action_type == "request_intervention":
                return StepResult(
                    action=action,
                    tool_call_id=tool_call.id,
                    tool_result="intervention_requested",
                    assistant_message=assistant_message,
                    action_summary=self._action_summary(action_text),
                    prompt_snapshot=prompt_snapshot,
                    model_snapshot=model_snapshot,
                    execution_snapshot={
                        "tool_result": "intervention_requested",
                        "next_observation": None,
                        "done": False,
                    },
                    intervention_requested=True,
                )

            # Normalize app name to package name for Android open/close
            if (
                action.action_type in ("open_app", "close_app")
                and action.text
                and self.backend.platform == "android"
            ):
                from opengui.skills.normalization import resolve_android_package

                resolved = resolve_android_package(action.text)
                if resolved != action.text:
                    logger.debug("Resolved app name %r -> %r", action.text, resolved)
                    action = replace(action, text=resolved)

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
            try:
                next_observation = await self.backend.observe(
                    next_screenshot, timeout=self.step_timeout,
                )
            except Exception as exc:
                next_observation = None
                result_text += f" (observation failed: {exc})"

            return StepResult(
                action=action,
                tool_call_id=tool_call.id,
                tool_result=result_text,
                assistant_message=assistant_message,
                action_summary=self._action_summary(action_text),
                next_observation=next_observation,
                prompt_snapshot=prompt_snapshot,
                model_snapshot=model_snapshot,
                execution_snapshot={
                    "tool_result": self._scrub_text_for_action(result_text, action),
                    "next_observation": self._serialize_observation(next_observation),
                    "done": False,
                },
            )

        raise RuntimeError("GUI model did not return a valid computer_use call after retries.")

    def _coordinate_mode(self) -> str:
        return "relative_999" if self._model_uses_relative_grid() else "absolute"

    def _model_uses_relative_grid(self) -> bool:
        model = self.model.lower()
        return any(hint in model for hint in self._MODEL_RELATIVE_GRID_HINTS)

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
        return self._POST_ACTION_SETTLE_SECONDS

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        *,
        task: str,
        current_observation: Observation,
        history: list[HistoryTurn],
        app_hint: str | None,
        memory_context: str | None = None,
        skill_context: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build a Mobile-Agent-style prompt window with summaries and recent screenshots."""
        messages: list[dict[str, Any]] = [{
            "role": "system",
            "content": build_system_prompt(
                platform=self.backend.platform,
                coordinate_mode=self._coordinate_mode(),
                tool_definition=_COMPUTER_USE_TOOL,
                memory_context=memory_context,
                installed_apps=self._installed_apps,
            ),
        }]

        prompt_text = self._build_instruction_prompt(
            task=task,
            current_observation=current_observation,
            history=history,
            app_hint=app_hint,
            skill_context=skill_context,
        )
        recent_history = history[-self.history_image_window:]

        if recent_history:
            for idx, turn in enumerate(recent_history):
                messages.append(
                    self._history_user_message(
                        turn.observation,
                        prompt_text if idx == 0 else None,
                    )
                )
                messages.append(turn.assistant_message)
                messages.append(turn.tool_result_message)
            messages.append(
                self._current_user_message(
                    current_observation,
                    task=task,
                    step_index=len(history),
                    app_hint=app_hint,
                )
            )
        else:
            messages.append(
                self._current_user_message(
                    current_observation,
                    task=task,
                    step_index=0,
                    app_hint=app_hint,
                    prompt_text=prompt_text,
                )
            )

        return messages

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
        summarized_history = history[: -self.history_image_window] if len(history) > self.history_image_window else []
        previous_actions = self._format_previous_actions(summarized_history)
        lines = [
            "Please generate the next move according to the UI screenshot, instruction and previous actions.",
            "",
        ]

        if self.include_date_context:
            lines.append(f"Today's date is: {datetime.now().strftime('%Y-%m-%d %A')}.")

        lines.append(f"Instruction: {task}")
        lines.append(f"Platform: {self.backend.platform}")

        app_name = app_hint or current_observation.foreground_app
        if app_name:
            lines.append(f"Foreground app hint: {app_name}")

        lines.extend([
            "",
            "Previous actions:",
            previous_actions,
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
    def _format_previous_actions(history: list[HistoryTurn]) -> str:
        if not history:
            return "None"
        return "\n".join(
            f"Step {turn.step_index}: {turn.action_summary}"
            for turn in history
        )

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
    ) -> dict[str, Any]:
        """Build an assistant message dict from an LLM response."""
        msg: dict[str, Any] = {"role": "assistant"}

        content = content_override if content_override is not None else response.content
        if content:
            msg["content"] = content

        if response.tool_calls:
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
            "messages": self._scrub_for_log(messages),
            "history": [
                {
                    "step_index": turn.step_index,
                    "action_summary": turn.action_summary,
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
    ) -> dict[str, Any]:
        return {
            "raw_content": self._scrub_text_for_action(response.content, action),
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": self._scrub_for_log(tool_call.arguments),
                }
                for tool_call in (response.tool_calls or [])
            ],
            "assistant_message": self._scrub_assistant_message_for_log(assistant_message, action),
            "parsed_action": self._scrub_for_log(self._serialize_action(action)),
            "action_text": self._scrub_text_for_action(action_text, action),
            "action_summary": self._scrub_text_for_action(self._action_summary(action_text), action),
        }

    @staticmethod
    def _normalize_action_text(content: str, action: Action) -> str:
        text = content.strip() if content else ""
        if text:
            first_line = text.splitlines()[0].strip()
            if first_line.lower().startswith("action:"):
                return first_line
            return f"Action: {first_line}"
        return f"Action: {describe_action(action)}"

    @staticmethod
    def _action_summary(action_text: str) -> str:
        if action_text.lower().startswith("action:"):
            return action_text.split(":", 1)[1].strip()
        return action_text.strip()

    @staticmethod
    def _image_block(path: Path) -> dict[str, Any]:
        """Create a base64 image content block for an LLM message."""
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode()
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
        if isinstance(value, dict):
            scrubbed: dict[str, Any] = {}
            action_type = value.get("action_type") if isinstance(value.get("action_type"), str) else None
            for key, item in value.items():
                if key == "url" and isinstance(item, str) and item.startswith("data:image/"):
                    scrubbed[key] = "<omitted:image-data-url>"
                elif action_type == "input_text" and key == "text":
                    scrubbed[key] = "<redacted:input_text>"
                elif (action_type == "request_intervention" and key == "text") or key == "reason":
                    scrubbed[key] = "<redacted:intervention_reason>"
                elif any(token in key.lower() for token in ("password", "secret", "token", "otp", "credential")):
                    scrubbed[key] = "<redacted:sensitive_field>"
                else:
                    scrubbed[key] = GuiAgent._scrub_for_log(item)
            return scrubbed
        if isinstance(value, list):
            return [GuiAgent._scrub_for_log(item) for item in value]
        if isinstance(value, str):
            return GuiAgent._scrub_sensitive_text(value)
        return value

    @staticmethod
    def _scrub_text_for_action(text: str | None, action: Action) -> str | None:
        if text is None:
            return None
        scrubbed = GuiAgent._scrub_sensitive_text(text)
        if action.action_type == "input_text" and action.text:
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
        """Search skill libraries and return the top match when above threshold."""
        if self._unified_skill_search is not None:
            search_results = await self._unified_skill_search.search(task, top_k=1)
            if not search_results:
                return None
            result = search_results[0]
            if result.score >= self._skill_threshold:
                logger.info(
                    "Skill match: %s (layer=%s, score=%.2f)",
                    result.skill.name,
                    result.layer,
                    result.score,
                )
                return result
            return None

        if self._skill_library is None:
            return None
        from opengui.skills.data import compute_confidence

        search_results = await self._skill_library.search(task, top_k=1)
        if not search_results:
            return None
        skill, relevance = search_results[0]
        confidence = compute_confidence(skill)
        final_score = relevance * confidence
        if final_score >= self._skill_threshold:
            return (skill, final_score)
        return None

    async def _retrieve_shortcut_candidates(
        self,
        task: str,
        *,
        platform: str,
        app_hint: str | None = None,
    ) -> list:
        """Retrieve shortcut candidates filtered by platform and optional app context.

        Calls ``UnifiedSkillSearch.search(task, top_k=5)``, keeps only results
        at or above ``skill_threshold``, then applies platform + app filtering via
        ``filter_candidates_by_context``.  Emits a ``shortcut_retrieval`` trajectory
        event regardless of whether any candidates are found.

        Returns an empty list when ``unified_skill_search`` is not configured.
        The returned list is stored in ``run()`` for use by Plan 02's applicability
        gate; the existing score-only ``_search_skill`` path is left unchanged.
        """
        if self._unified_skill_search is None:
            return []

        search_results = await self._unified_skill_search.search(task, top_k=5)
        candidates = [r for r in search_results if r.score >= self._skill_threshold]
        filtered = filter_candidates_by_context(
            candidates, platform=platform, app_hint=app_hint,
        )

        self._trajectory_recorder.record_event(
            "shortcut_retrieval",
            task=task,
            platform=platform,
            app_hint=app_hint,
            candidate_count=len(filtered),
            candidates=[
                {
                    "skill_id": r.skill.skill_id,
                    "name": r.skill.name,
                    "score": round(r.score, 4),
                }
                for r in filtered
            ],
        )

        if filtered:
            logger.info(
                "Shortcut retrieval: %d candidate(s) for task=%r platform=%s",
                len(filtered),
                task,
                platform,
            )

        return filtered

    async def _evaluate_shortcut_applicability(
        self,
        candidates: list,
        *,
        screenshot_path: Path | None,
        task: str,
    ) -> ApplicabilityDecision:
        """Evaluate shortcut candidates against the live screen and return a decision.

        Iterates candidates in score order and returns the first one whose
        preconditions are satisfied.  When the candidate list is empty, or when
        no router / screenshot is available, returns a structured decision with
        a descriptive ``reason`` and emits a ``shortcut_applicability`` trajectory
        event on every code path for full traceability.

        Parameters
        ----------
        candidates:
            Ordered list of :class:`~opengui.skills.shortcut_store.SkillSearchResult`
            instances (highest-score first).
        screenshot_path:
            Path to the most recent screenshot for condition evaluation.
        task:
            The active task string, included in log output.
        """
        if not candidates:
            decision = ApplicabilityDecision(outcome="fallback", reason="no_candidates")
            self._trajectory_recorder.record_event(
                "shortcut_applicability",
                outcome=decision.outcome,
                shortcut_id=None,
                reason=decision.reason,
            )
            return decision

        if self._shortcut_applicability_router is None or screenshot_path is None:
            # No router or no screenshot — select first candidate by score as best-effort
            best = candidates[0]
            decision = ApplicabilityDecision(
                outcome="run",
                shortcut_id=best.skill.skill_id,
                reason="no_applicability_router",
                score=best.score,
            )
            self._trajectory_recorder.record_event(
                "shortcut_applicability",
                outcome=decision.outcome,
                shortcut_id=decision.shortcut_id,
                reason=decision.reason,
                score=decision.score,
            )
            logger.info(
                "Shortcut applicability (no router): selecting %r for task=%r",
                decision.shortcut_id,
                task,
            )
            return decision

        # Evaluate candidates in score order; return first that passes all preconditions
        last_decision: ApplicabilityDecision | None = None
        for result in candidates:
            candidate_decision = await self._shortcut_applicability_router.evaluate(
                result.skill, Path(screenshot_path),
            )
            if candidate_decision.outcome == "run":
                decision = ApplicabilityDecision(
                    outcome="run",
                    shortcut_id=result.skill.skill_id,
                    reason=candidate_decision.reason,
                    score=result.score,
                )
                self._trajectory_recorder.record_event(
                    "shortcut_applicability",
                    outcome=decision.outcome,
                    shortcut_id=decision.shortcut_id,
                    reason=decision.reason,
                    score=decision.score,
                )
                logger.info(
                    "Shortcut applicability: approved %r (score=%.2f) for task=%r",
                    decision.shortcut_id,
                    decision.score or 0.0,
                    task,
                )
                return decision
            last_decision = candidate_decision

        # All candidates failed applicability — emit a single fallback event
        assert last_decision is not None  # candidates was non-empty
        fallback = ApplicabilityDecision(
            outcome="fallback",
            shortcut_id=None,
            reason=f"all_candidates_failed:{last_decision.reason}",
            failed_condition=last_decision.failed_condition,
        )
        self._trajectory_recorder.record_event(
            "shortcut_applicability",
            outcome=fallback.outcome,
            shortcut_id=None,
            reason=fallback.reason,
            failed_condition=(
                {
                    "kind": fallback.failed_condition.kind,
                    "value": fallback.failed_condition.value,
                }
                if fallback.failed_condition else None
            ),
        )
        logger.info(
            "Shortcut applicability: all %d candidate(s) failed for task=%r",
            len(candidates),
            task,
        )
        return fallback

    async def _inject_skill_memory_context(
        self,
        skill: Any,
        existing_context: str | None,
    ) -> str | None:
        """Inject app memory context referenced by a TaskSkill.memory_context_id."""
        from opengui.skills.task_skill import TaskSkill as _TaskSkill

        if not isinstance(skill, _TaskSkill) or skill.memory_context_id is None:
            return existing_context
        if self._memory_store is None:
            return existing_context

        entry = self._memory_store.get(skill.memory_context_id)
        if entry is None:
            logger.warning(
                "Skill %s references missing memory context %s",
                skill.skill_id,
                skill.memory_context_id,
            )
            return existing_context

        injected = f"[Skill memory context]\n{entry.content}"
        return f"{injected}\n\n{existing_context}" if existing_context else injected

    async def _skill_maintenance(
        self, skill_match: Any | None, success: bool
    ) -> None:
        """Post-run: update confidence, discard low-confidence, check merge."""
        if skill_match is None or self._skill_library is None:
            return
        if hasattr(skill_match, "layer"):
            return
        from dataclasses import replace
        from opengui.skills.data import compute_confidence

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

        new_conf = compute_confidence(updated)
        total_attempts = updated.success_count + updated.failure_count
        if total_attempts >= 5 and new_conf < 0.3:
            self._skill_library.remove(skill.skill_id)
        else:
            self._skill_library.update(skill.skill_id, updated)
            await self._skill_library.add_or_merge(updated)
