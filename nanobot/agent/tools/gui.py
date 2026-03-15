"""GUI tools for desktop observation and autonomous computer-use runs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool
from nanobot.gui.backend import (
    DesktopObservation,
    DryRunDesktopBackend,
    GUIBackendError,
    LocalDesktopBackend,
    describe_action,
    parse_computer_action,
)
from nanobot.gui.runtime import GuiRuntime
from nanobot.utils.helpers import ensure_dir

ProgressCallback = Callable[[str], Awaitable[None]]


class _BaseGuiTool(Tool):
    """Shared context and CLI-only guard for GUI tools."""

    def __init__(
        self,
        *,
        backend: LocalDesktopBackend | DryRunDesktopBackend,
        artifacts_root: Path,
        cli_only: bool,
        step_timeout_seconds: int,
    ) -> None:
        self.backend = backend
        self.artifacts_root = artifacts_root
        self.cli_only = cli_only
        self.step_timeout_seconds = step_timeout_seconds
        self._channel = "cli"
        self._chat_id = "direct"
        self._message_id: str | None = None

    def set_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
    ) -> None:
        self._channel = channel
        self._chat_id = chat_id
        self._message_id = message_id

    def _guard(self) -> str | None:
        if self.cli_only and self._channel != "cli":
            return "Error: GUI tools are only available in CLI sessions."
        return None

    async def _observe_once(self, prefix: str) -> DesktopObservation:
        artifacts = ensure_dir(self.artifacts_root / "manual")
        shot_path = artifacts / f"{prefix}.png"
        # This duplicates the backend's own subprocess timeout on purpose:
        # the outer asyncio timeout protects the event loop if a worker thread
        # gets stuck before the backend can raise a command-level timeout.
        return await asyncio.wait_for(
            asyncio.to_thread(self.backend.observe, shot_path, self.step_timeout_seconds),
            timeout=self.step_timeout_seconds,
        )


class GuiRunTool(_BaseGuiTool):
    """Autonomous desktop GUI task runner."""

    def __init__(
        self,
        *,
        runtime: GuiRuntime,
        backend: LocalDesktopBackend | DryRunDesktopBackend,
        artifacts_root: Path,
        cli_only: bool,
        step_timeout_seconds: int,
        gui_lock: asyncio.Lock,
    ) -> None:
        super().__init__(
            backend=backend,
            artifacts_root=artifacts_root,
            cli_only=cli_only,
            step_timeout_seconds=step_timeout_seconds,
        )
        self.runtime = runtime
        self.gui_lock = gui_lock
        self._progress_callback: ProgressCallback | None = None

    def set_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        super().set_context(channel, chat_id, message_id)
        self._progress_callback = progress_callback

    @property
    def name(self) -> str:
        return "gui_run"

    @property
    def description(self) -> str:
        return "Run a short autonomous desktop GUI task using screenshots and computer-use function calling."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The GUI task to complete."},
                "max_steps": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional step limit for this GUI run.",
                },
                "app_hint": {
                    "type": "string",
                    "description": "Optional target application hint for the GUI model.",
                },
            },
            "required": ["task"],
        }

    async def execute(
        self,
        task: str,
        max_steps: int | None = None,
        app_hint: str | None = None,
        **kwargs: Any,
    ) -> str:
        del kwargs
        if guard := self._guard():
            return guard
        if self.gui_lock.locked():
            return "Error: desktop busy"

        async with self.gui_lock:
            if self._progress_callback is not None:
                await self._progress_callback("Starting GUI task...")
            try:
                return await self.runtime.run(
                    task=task,
                    max_steps=max_steps,
                    app_hint=app_hint,
                    progress_callback=self._progress_callback,
                )
            except (GUIBackendError, asyncio.TimeoutError, RuntimeError) as exc:
                return "\n".join(["GUI task failed.", f"Error: {exc}"])


class DesktopObserveTool(_BaseGuiTool):
    """Capture the current desktop observation for debugging."""

    @property
    def name(self) -> str:
        return "desktop_observe"

    @property
    def description(self) -> str:
        return "Capture a screenshot and metadata from the current desktop."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        del kwargs
        if guard := self._guard():
            return guard
        try:
            observation = await self._observe_once("observe")
        except (GUIBackendError, asyncio.TimeoutError) as exc:
            return f"Error: {exc}"
        return "\n".join(
            [
                "Desktop observation captured.",
                f"Foreground app: {observation.foreground_app or 'Unknown'}",
                f"Screen size: {observation.screen_width}x{observation.screen_height}",
                f"Screenshot: {observation.screenshot_path}",
            ]
        )


class DesktopActTool(_BaseGuiTool):
    """Execute one desktop action and return a follow-up observation."""

    @property
    def name(self) -> str:
        return "desktop_act"

    @property
    def description(self) -> str:
        return "Execute one low-level desktop action for debugging or recovery."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
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
        }

    async def execute(self, action_type: str, **kwargs: Any) -> str:
        if guard := self._guard():
            return guard

        payload = dict(kwargs)
        payload["action_type"] = action_type
        try:
            parsed = parse_computer_action(payload)
        except GUIBackendError as exc:
            return f"Error: {exc}"

        try:
            tool_result = await asyncio.wait_for(
                asyncio.to_thread(self.backend.execute_action, parsed, self.step_timeout_seconds),
                timeout=self.step_timeout_seconds,
            )
            observation = await self._observe_once("act")
        except (GUIBackendError, asyncio.TimeoutError) as exc:
            return f"Error: {exc}"

        lines = [
            f"Executed: {describe_action(parsed)}",
            f"Result: {tool_result}",
            f"Foreground app: {observation.foreground_app or 'Unknown'}",
            f"Screenshot: {observation.screenshot_path}",
        ]
        return "\n".join(lines)
