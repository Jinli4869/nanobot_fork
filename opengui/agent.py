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
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from opengui.action import Action, ActionError, describe_action, parse_action
from opengui.interfaces import DeviceBackend, LLMProvider, LLMResponse, ProgressCallback
from opengui.observation import Observation
from opengui.prompts.system import build_system_prompt
from opengui.trajectory.recorder import ExecutionPhase, TrajectoryRecorder


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
                        "back", "home", "done",
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
                        "for open_app/close_app. On Android, use package names."
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
        memory_top_k: int = 5,
        skill_threshold: float = 0.6,
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
        self._skill_library = skill_library
        self._skill_executor = skill_executor
        self._memory_top_k = memory_top_k
        self._skill_threshold = skill_threshold

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

        # 4. If skill matched, attempt skill execution first
        if skill_match is not None and self._skill_executor is not None:
            skill, final_score = skill_match
            self._trajectory_recorder.set_phase(
                ExecutionPhase.SKILL,
                reason=f"Matched skill: {skill.name} (score={final_score:.2f})",
            )
            try:
                skill_result = await self._skill_executor.execute(skill)
                if skill_result.state.value == "succeeded":
                    # Skill succeeded — fall through to agent for confirmation
                    self._trajectory_recorder.set_phase(
                        ExecutionPhase.AGENT, reason="Skill complete, agent confirms"
                    )
            except Exception:
                # Skill failed — fall back to free exploration
                self._trajectory_recorder.set_phase(
                    ExecutionPhase.AGENT, reason="Skill execution failed, falling back"
                )

        # 5. Retry loop with free exploration
        last_error: str | None = None
        last_trace_path: str | None = None
        last_steps_taken = 0
        result: AgentResult | None = None

        for attempt in range(max_retries):
            run_dir = self._make_run_dir(task, attempt)
            last_trace_path = str(run_dir)
            try:
                result = await self._run_once(
                    task, app_hint=app_hint, run_dir=run_dir,
                    memory_context=memory_context,
                )
                if result.success:
                    break
                last_error = result.error
                last_trace_path = result.trace_path or last_trace_path
                last_steps_taken = result.steps_taken
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

        if result is None or not result.success:
            result = AgentResult(
                success=False,
                summary=f"Failed after {max_retries} attempt(s).",
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
            )

            try:
                result = await asyncio.wait_for(
                    self._run_step(
                        messages=messages,
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
                    trace_path=str(run_dir),
                    steps_taken=step_index,
                    error="step_timeout",
                )

            steps_taken = step_index

            # Write trace entry
            await self._write_trace(run_dir / "trace.jsonl", {
                "event": "step",
                "step_index": step_index,
                "action": describe_action(result.action),
                "action_debug": result.action_debug,
                "tool_result": result.tool_result,
                "screenshot_path": (
                    result.next_observation.screenshot_path
                    if result.next_observation else None
                ),
                "done": result.done,
                "timestamp": time.time(),
            })

            # Record trajectory step
            self._trajectory_recorder.record_step(
                action=(
                    result.action.to_dict()
                    if hasattr(result.action, "to_dict")
                    else {"action_type": result.action.action_type}
                ),
                model_output=result.action_summary,
                screenshot_path=(
                    str(result.next_observation.screenshot_path)
                    if result.next_observation and result.next_observation.screenshot_path
                    else None
                ),
            )

            if result.done:
                success = result.action.status == "success"
                return AgentResult(
                    success=success,
                    summary=f"Task {'completed' if success else 'failed'} "
                            f"after {steps_taken} step(s).",
                    trace_path=str(run_dir),
                    steps_taken=steps_taken,
                    error=None if success else result.tool_result,
                )

            history.append(
                HistoryTurn(
                    step_index=step_index,
                    observation=obs,
                    assistant_message=result.assistant_message,
                    tool_result_message={
                        "role": "tool",
                        "tool_call_id": result.tool_call_id,
                        "content": result.tool_result,
                    },
                    action_summary=result.action_summary,
                )
            )

            if result.next_observation is not None:
                obs = result.next_observation

        return AgentResult(
            success=False,
            summary=f"Reached max steps ({self.max_steps}) without completion.",
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

            # Handle terminal action (done)
            if action.action_type == "done":
                return StepResult(
                    action=action,
                    tool_call_id=tool_call.id,
                    tool_result=f"Task terminated with status: {action.status or 'unknown'}",
                    assistant_message=assistant_message,
                    action_summary=self._action_summary(action_text),
                    done=True,
                )

            # Execute action on backend
            try:
                result_text = await self.backend.execute(action, timeout=self.step_timeout)
            except Exception as exc:
                result_text = f"Action failed: {exc}"

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
            )

        raise RuntimeError("GUI model did not return a valid computer_use call after retries.")

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
    ) -> list[dict[str, Any]]:
        """Build a Mobile-Agent-style prompt window with summaries and recent screenshots."""
        messages: list[dict[str, Any]] = [{
            "role": "system",
            "content": build_system_prompt(
                platform=self.backend.platform,
                tool_definition=_COMPUTER_USE_TOOL,
                memory_context=memory_context,
            ),
        }]

        prompt_text = self._build_instruction_prompt(
            task=task,
            current_observation=current_observation,
            history=history,
            app_hint=app_hint,
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
        content: list[dict[str, Any]] = []
        if prompt_text:
            content.append({"type": "text", "text": prompt_text})
        content.append({
            "type": "text",
            "text": observation.to_user_text(task, step_index=step_index, app_hint=app_hint),
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

    # ------------------------------------------------------------------
    # Memory / skill / trajectory helpers
    # ------------------------------------------------------------------

    async def _retrieve_memory(self, task: str) -> str | None:
        """Retrieve relevant memory entries for the task, always including POLICY entries."""
        if self._memory_retriever is None:
            return None
        from opengui.memory.types import MemoryType

        results = await self._memory_retriever.search(task, top_k=self._memory_top_k + 10)
        policies = [(e, s) for e, s in results if e.memory_type == MemoryType.POLICY]
        others = [(e, s) for e, s in results if e.memory_type != MemoryType.POLICY][
            : self._memory_top_k
        ]
        memory_entries = policies + others
        if not memory_entries:
            return None
        return self._memory_retriever.format_context(memory_entries)

    async def _search_skill(self, task: str) -> tuple[Any, float] | None:
        """Search skill library and return (skill, final_score) if above threshold."""
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

    async def _skill_maintenance(
        self, skill_match: tuple[Any, float] | None, success: bool
    ) -> None:
        """Post-run: update confidence, discard low-confidence, check merge."""
        if skill_match is None or self._skill_library is None:
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
