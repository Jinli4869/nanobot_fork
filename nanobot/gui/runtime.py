"""GUI runtime that drives a computer-use loop inside a nanobot tool."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from nanobot.providers.base import LLMProvider
from nanobot.utils.helpers import build_assistant_message, detect_image_mime, ensure_dir, safe_filename

from nanobot.gui.backend import (
    ComputerAction,
    DesktopObservation,
    DryRunDesktopBackend,
    GUIBackendError,
    LocalDesktopBackend,
    describe_action,
    parse_computer_action,
)

ProgressCallback = Callable[[str], Awaitable[None]]

_COMPUTER_USE_TOOL = {
    "type": "function",
    "function": {
        "name": "computer_use",
        "description": "Interact with a desktop GUI using structured desktop actions.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": [
                        "tap",
                        "move",
                        "right_click",
                        "middle_click",
                        "double_click",
                        "triple_click",
                        "swipe",
                        "scroll",
                        "hscroll",
                        "input_text",
                        "hotkey",
                        "wait",
                        "terminate",
                    ],
                },
                "x": {"type": "number"},
                "y": {"type": "number"},
                "x2": {"type": "number"},
                "y2": {"type": "number"},
                "relative": {"type": "boolean"},
                "text": {"type": "string"},
                "key": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "pixels": {"type": "number"},
                "duration_ms": {"type": "number"},
                "status": {
                    "type": "string",
                    "enum": ["success", "failure"],
                },
            },
            "required": ["action_type"],
        },
    },
}

_SYSTEM_PROMPT = """You are controlling a desktop GUI from screenshots only.

Rules:
- You must call exactly one computer_use tool on every step.
- Base decisions only on the latest screenshot and task text.
- Use `action_type` and the structured fields defined by the tool schema.
- Prefer absolute pixel coordinates matching the reported screen size and set `relative=false`.
- Prefer safe, reversible actions.
- Do NOT use destructive shortcuts (Cmd+Q, Cmd+W, Cmd+Delete, etc.) — they are blocked.
- If the UI needs time to update, use wait.
- Use terminate with status=success when the task is complete.
- Use terminate with status=failure if the task cannot be completed safely."""


@dataclass
class StepResult:
    """Outcome of a single GUI step."""

    action: ComputerAction
    tool_call_id: str
    tool_result: str
    next_observation: DesktopObservation | None = None
    done: bool = False


class GuiRuntime:
    """Run a lightweight desktop GUI task loop with function calling."""

    _MAX_TOOL_RETRIES = 2
    _MAX_IMAGE_MESSAGES = 3
    # The outer per-step timeout is set to this multiple of step_timeout_seconds.
    # One step includes an LLM call + action execution + observation capture,
    # so the outer guard must be generous enough to accommodate all three.
    _STEP_TIMEOUT_MULTIPLIER = 3

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        backend: LocalDesktopBackend | DryRunDesktopBackend,
        artifacts_root: Path,
        max_steps: int,
        step_timeout_seconds: int,
    ) -> None:
        self.provider = provider
        self.model = model
        self.backend = backend
        self.artifacts_root = artifacts_root
        self.max_steps = max_steps
        self.step_timeout_seconds = step_timeout_seconds

    async def run(
        self,
        *,
        task: str,
        max_steps: int | None = None,
        app_hint: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        """Run a GUI task to completion or failure."""
        total_steps = max(1, min(max_steps or self.max_steps, self.max_steps))
        run_dir = self._make_run_dir(task)
        screenshots_dir = ensure_dir(run_dir / "screenshots")
        trace_path = run_dir / "trace.jsonl"

        try:
            preflight_errors = await self._call_backend(
                self.backend.preflight,
                run_dir,
                self.step_timeout_seconds,
            )
            if preflight_errors:
                return self._format_failure(
                    "GUI preflight failed.",
                    run_dir=run_dir,
                    details=preflight_errors,
                )

            observation_counter = 0
            initial_observation = await self._observe(
                screenshots_dir=screenshots_dir,
                observation_counter=observation_counter,
            )
            observation_counter += 1
        except asyncio.TimeoutError:
            await self._write_trace(trace_path, {"event": "startup_timeout"})
            return self._format_failure(
                (
                    f"GUI initialization timed out after "
                    f"{self.step_timeout_seconds} seconds."
                ),
                run_dir=run_dir,
            )
        except GUIBackendError as exc:
            await self._write_trace(
                trace_path,
                {"event": "startup_backend_error", "error": str(exc)},
            )
            return self._format_failure(str(exc), run_dir=run_dir)

        messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        observation_indices: list[tuple[int, int]] = []
        self._append_observation_message(
            messages,
            observation=initial_observation,
            task=task,
            step_index=1,
            app_hint=app_hint,
            observation_indices=observation_indices,
        )
        await self._write_trace(
            trace_path,
            {
                "event": "initial_observation",
                "screenshot_path": initial_observation.screenshot_path,
                "foreground_app": initial_observation.foreground_app,
                "screen_width": initial_observation.screen_width,
                "screen_height": initial_observation.screen_height,
            },
        )

        current_observation = initial_observation
        final_action: ComputerAction | None = None
        failure_details: list[str] = []

        for step_index in range(1, total_steps + 1):
            try:
                result = await asyncio.wait_for(
                    self._run_step(
                        messages=messages,
                        current_observation=current_observation,
                        step_index=step_index,
                        total_steps=total_steps,
                        task=task,
                        app_hint=app_hint,
                        screenshots_dir=screenshots_dir,
                        observation_counter=observation_counter,
                        progress_callback=progress_callback,
                    ),
                    timeout=self.step_timeout_seconds * self._STEP_TIMEOUT_MULTIPLIER,
                )
            except asyncio.TimeoutError:
                await self._write_trace(
                    trace_path,
                    {
                        "event": "step_timeout",
                        "step_index": step_index,
                    },
                )
                return self._format_failure(
                    f"GUI step {step_index} timed out after {self.step_timeout_seconds} seconds.",
                    run_dir=run_dir,
                )
            except GUIBackendError as exc:
                await self._write_trace(
                    trace_path,
                    {
                        "event": "backend_error",
                        "step_index": step_index,
                        "error": str(exc),
                    },
                )
                return self._format_failure(str(exc), run_dir=run_dir)
            except RuntimeError as exc:
                await self._write_trace(
                    trace_path,
                    {
                        "event": "runtime_error",
                        "step_index": step_index,
                        "error": str(exc),
                    },
                )
                if self._looks_like_vision_error(str(exc)):
                    failure_details.append(
                        "The configured GUI model likely does not support image inputs. "
                        "Choose a vision-capable model for gui_run."
                    )
                return self._format_failure(str(exc), run_dir=run_dir, details=failure_details)

            final_action = result.action
            await self._write_trace(
                trace_path,
                {
                    "event": "step",
                    "step_index": step_index,
                    "action": describe_action(result.action),
                    "tool_result": result.tool_result,
                    "screenshot_path": (
                        result.next_observation.screenshot_path if result.next_observation else None
                    ),
                },
            )

            if result.done:
                status = result.action.status or "success"
                if progress_callback is not None:
                    await progress_callback(
                        "GUI task completed" if status == "success" else "GUI task failed"
                    )
                return self._format_success(
                    task=task,
                    run_dir=run_dir,
                    last_screenshot=current_observation.screenshot_path,
                    last_action=final_action,
                    step_count=step_index,
                    status=status,
                )

            if result.next_observation is None:
                return self._format_failure("GUI step completed without a follow-up observation.", run_dir=run_dir)

            observation_counter += 1
            current_observation = result.next_observation
            self._append_observation_message(
                messages,
                observation=current_observation,
                task=task,
                step_index=step_index + 1,
                app_hint=app_hint,
                observation_indices=observation_indices,
            )

        return self._format_failure(
            f"GUI task reached the step limit ({total_steps}) without terminating.",
            run_dir=run_dir,
            details=[f"Last action: {describe_action(final_action)}"] if final_action else None,
        )

    async def _run_step(
        self,
        *,
        messages: list[dict[str, Any]],
        current_observation: DesktopObservation,
        step_index: int,
        total_steps: int,
        task: str,
        app_hint: str | None,
        screenshots_dir: Path,
        observation_counter: int,
        progress_callback: ProgressCallback | None,
    ) -> StepResult:
        del current_observation, task, app_hint

        retries_left = self._MAX_TOOL_RETRIES + 1
        while retries_left > 0:
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=[_COMPUTER_USE_TOOL],
                model=self.model,
                tool_choice="required",
            )

            if response.finish_reason == "error":
                raise RuntimeError(response.content or "GUI model call failed.")

            tool_calls = list(response.tool_calls or [])
            assistant_message = build_assistant_message(
                response.content,
                tool_calls=[tc.to_openai_tool_call() for tc in tool_calls] if tool_calls else None,
                reasoning_content=response.reasoning_content,
                thinking_blocks=response.thinking_blocks,
            )
            messages.append(assistant_message)

            if len(tool_calls) != 1:
                retries_left -= 1
                if tool_calls:
                    for invalid_tool_call in tool_calls:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": invalid_tool_call.id,
                                "name": invalid_tool_call.name,
                                "content": (
                                    "Error: Call exactly one computer_use tool on this step."
                                ),
                            }
                        )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was invalid. "
                            "Call exactly one computer_use tool on this step."
                        ),
                    }
                )
                continue

            tool_call = tool_calls[0]
            if tool_call.name != "computer_use":
                retries_left -= 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": "Error: Call exactly one computer_use tool.",
                    }
                )
                continue

            try:
                action = parse_computer_action(tool_call.arguments)
            except GUIBackendError as exc:
                retries_left -= 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": f"Error: {exc}",
                    }
                )
                continue

            if progress_callback is not None:
                await progress_callback(
                    f"GUI step {step_index}/{total_steps}: {describe_action(action)}"
                )

            if action.action_type == "terminate":
                result_text = f"Terminate acknowledged with status={action.status}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result_text,
                    }
                )
                return StepResult(
                    action=action,
                    tool_call_id=tool_call.id,
                    tool_result=result_text,
                    done=True,
                )

            tool_result = await self._call_backend(
                self.backend.execute_action,
                action,
                self.step_timeout_seconds,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": tool_result,
                }
            )
            next_observation = await self._observe(
                screenshots_dir=screenshots_dir,
                observation_counter=observation_counter,
            )
            return StepResult(
                action=action,
                tool_call_id=tool_call.id,
                tool_result=tool_result,
                next_observation=next_observation,
            )

        raise RuntimeError("The GUI model did not return a valid computer_use call after retries.")

    async def _observe(
        self,
        *,
        screenshots_dir: Path,
        observation_counter: int,
    ) -> DesktopObservation:
        shot_path = screenshots_dir / f"obs_{observation_counter:03d}.png"
        return await self._call_backend(
            self.backend.observe,
            shot_path,
            self.step_timeout_seconds,
        )

    async def _call_backend(self, func: Callable[..., Any], *args: Any) -> Any:
        # Keep an asyncio-level timeout around the worker thread in addition to
        # backend subprocess timeouts. This remains a useful safety net if a
        # synchronous OS call stalls without raising its own TimeoutExpired.
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args),
            timeout=self.step_timeout_seconds,
        )

    def _append_observation_message(
        self,
        messages: list[dict[str, Any]],
        *,
        observation: DesktopObservation,
        task: str,
        step_index: int,
        app_hint: str | None,
        observation_indices: list[tuple[int, int]],
    ) -> None:
        content = [
            self._image_block(Path(observation.screenshot_path)),
            {
                "type": "text",
                "text": observation.to_user_text(task, step_index=step_index, app_hint=app_hint),
            },
        ]
        messages.append({"role": "user", "content": content})
        observation_indices.append((len(messages) - 1, step_index))
        self._degrade_old_observation_messages(messages, observation_indices)

    def _degrade_old_observation_messages(
        self,
        messages: list[dict[str, Any]],
        observation_indices: list[tuple[int, int]],
    ) -> None:
        while len(observation_indices) > self._MAX_IMAGE_MESSAGES:
            msg_index, step_number = observation_indices.pop(0)
            content = messages[msg_index].get("content")
            if not isinstance(content, list):
                continue
            degraded: list[dict[str, Any]] = []
            replaced = False
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "image_url"
                    and not replaced
                ):
                    degraded.append(
                        {
                            "type": "text",
                            "text": f"[screenshot degraded: step {step_number}]",
                        }
                    )
                    replaced = True
                else:
                    degraded.append(block)
            messages[msg_index]["content"] = degraded

    @staticmethod
    def _image_block(path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        mime = detect_image_mime(raw) or "image/png"
        encoded = base64.b64encode(raw).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        }

    def _make_run_dir(self, task: str) -> Path:
        slug = safe_filename(task)[:48] or "gui_task"
        return ensure_dir(self.artifacts_root / f"{slug}_{int(time.time() * 1000)}")

    @staticmethod
    async def _write_trace(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        await asyncio.to_thread(GuiRuntime._append_trace_line, path, line)

    @staticmethod
    def _append_trace_line(path: Path, line: str) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    @staticmethod
    def _looks_like_vision_error(message: str) -> bool:
        lower = message.lower()
        markers = ("vision", "multimodal", "image", "image_url", "input_image")
        unsupported = ("unsupported", "not support", "does not support", "only text")
        return any(marker in lower for marker in markers) and any(flag in lower for flag in unsupported)

    @staticmethod
    def _format_success(
        *,
        task: str,
        run_dir: Path,
        last_screenshot: str,
        last_action: ComputerAction | None,
        step_count: int,
        status: str,
    ) -> str:
        lines = [
            f"GUI task finished with status={status}.",
            f"Task: {task}",
            f"Steps: {step_count}",
            f"Artifacts: {run_dir}",
            f"Last screenshot: {last_screenshot}",
        ]
        if last_action is not None:
            lines.append(f"Last action: {describe_action(last_action)}")
        return "\n".join(lines)

    @staticmethod
    def _format_failure(
        message: str,
        *,
        run_dir: Path,
        details: list[str] | None = None,
    ) -> str:
        lines = [f"GUI task failed: {message}", f"Artifacts: {run_dir}"]
        if details:
            lines.extend(details)
        return "\n".join(lines)
