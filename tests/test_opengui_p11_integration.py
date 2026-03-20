"""Phase 11 integration tests: GuiConfig background fields and GuiSubagentTool wrapping.

Requirements covered:
  INTG-02: GuiConfig schema validates background + backend constraint at config load time
  INTG-04: GuiSubagentTool.execute() wraps backend in BackgroundDesktopBackend on Linux
  TEST-V11-01: All new tests pass without a real Xvfb binary
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from pydantic import ValidationError

from nanobot.config.schema import GuiConfig

# ---------------------------------------------------------------------------
# GuiConfig schema tests
# ---------------------------------------------------------------------------


def test_guiconfig_background_fields_defaults() -> None:
    """GuiConfig() has background=False, display_num=None, display_width=1280, display_height=720."""
    cfg = GuiConfig()
    assert cfg.background is False
    assert cfg.display_num is None
    assert cfg.display_width == 1280
    assert cfg.display_height == 720


def test_guiconfig_background_with_local() -> None:
    """GuiConfig(backend='local', background=True) succeeds and background is True."""
    cfg = GuiConfig(backend="local", background=True)
    assert cfg.background is True


def test_guiconfig_background_requires_local() -> None:
    """GuiConfig(backend='adb', background=True) raises ValidationError mentioning 'local'."""
    with pytest.raises(ValidationError, match="background mode requires backend='local'"):
        GuiConfig(backend="adb", background=True)


def test_guiconfig_background_rejects_dryrun() -> None:
    """GuiConfig(backend='dry-run', background=True) raises ValidationError."""
    with pytest.raises(ValidationError, match="background mode requires backend='local'"):
        GuiConfig(backend="dry-run", background=True)


def test_guiconfig_camel_case_aliases() -> None:
    """GuiConfig accepts camelCase aliases for background display fields."""
    cfg = GuiConfig(backend="local", background=True, displayWidth=1920, displayHeight=1080, displayNum=42)
    assert cfg.display_width == 1920
    assert cfg.display_height == 1080
    assert cfg.display_num == 42


# ---------------------------------------------------------------------------
# GuiSubagentTool.execute() wrapping tests
# ---------------------------------------------------------------------------


def _make_gui_tool(background: bool = False, **config_kwargs: Any) -> Any:
    """Build a GuiSubagentTool with mocked internals for execute() wrapping tests.

    Patches _build_backend and _get_skill_library so no real opengui backend is
    instantiated. The returned tool has gui_config.background set to the given value.
    """
    from nanobot.agent.tools.gui import GuiSubagentTool

    gui_config = GuiConfig(backend="local", background=background, **config_kwargs)

    mock_provider = MagicMock()
    mock_provider.api_key = "fake-key"
    mock_provider.api_base = None
    mock_provider.extra_headers = None

    mock_backend = MagicMock()
    mock_backend.platform = "linux"

    mock_skill_lib = MagicMock()

    with (
        patch.object(GuiSubagentTool, "_build_backend", return_value=mock_backend),
        patch.object(GuiSubagentTool, "_get_skill_library", return_value=mock_skill_lib),
    ):
        tool = GuiSubagentTool(
            gui_config=gui_config,
            provider=mock_provider,
            model="test-model",
            workspace=Path("/tmp/test_workspace"),
        )

    return tool


@pytest.mark.asyncio
async def test_gui_tool_execute_background_wraps_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux, execute() with gui_config.background=True wraps backend in BackgroundDesktopBackend."""
    # Force platform to linux
    monkeypatch.setattr(sys, "platform", "linux")

    tool = _make_gui_tool(background=True)
    inner_backend = tool._backend

    # Build mocks for BackgroundDesktopBackend and XvfbDisplayManager
    mock_xvfb_cls = MagicMock()
    mock_xvfb_instance = MagicMock()
    mock_xvfb_cls.return_value = mock_xvfb_instance

    mock_bg_instance = MagicMock()
    mock_bg_instance.platform = "linux"
    mock_bg_instance.shutdown = AsyncMock()

    mock_bg_cls = MagicMock(return_value=mock_bg_instance)

    canned_result = json.dumps({"success": True, "summary": "done", "trace_path": None, "steps_taken": 1, "error": None})

    with (
        patch("nanobot.agent.tools.gui.GuiSubagentTool._run_task", new=AsyncMock(return_value=canned_result)) as mock_run_task,
        patch(
            "opengui.backends.background_runtime.probe_isolated_background_support",
            return_value=MagicMock(supported=True, reason_code="xvfb_available"),
        ),
        patch("opengui.backends.background.BackgroundDesktopBackend", mock_bg_cls),
        patch("opengui.backends.displays.xvfb.XvfbDisplayManager", mock_xvfb_cls),
    ):
        result = await tool.execute("test task")

    assert result == canned_result
    # BackgroundDesktopBackend must have been constructed with inner backend and xvfb manager
    mock_bg_cls.assert_called_once_with(
        inner_backend,
        mock_xvfb_instance,
        run_metadata={"owner": "nanobot", "task": "test task", "model": "test-model"},
    )
    mock_bg_instance.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_gui_tool_execute_background_nonlinux_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fallback acknowledgement keeps the raw backend path and logs the resolved mode."""
    monkeypatch.setattr(sys, "platform", "darwin")

    tool = _make_gui_tool(background=True)
    raw_backend = tool._backend

    canned_result = json.dumps({"success": True, "summary": "done", "trace_path": None, "steps_taken": 1, "error": None})

    with (
        patch("nanobot.agent.tools.gui.GuiSubagentTool._run_task", new=AsyncMock(return_value=canned_result)) as mock_run_task,
        patch(
            "opengui.backends.background_runtime.probe_isolated_background_support",
            return_value=MagicMock(
                supported=False,
                reason_code="platform_unsupported",
                retryable=False,
                host_platform="macos",
                backend_name=None,
                sys_platform="darwin",
            ),
        ),
        caplog.at_level(logging.WARNING, logger="nanobot.agent.tools.gui"),
    ):
        result = await tool.execute("test task", acknowledge_background_fallback=True)

    assert result == canned_result
    called_backend = mock_run_task.call_args[0][0]
    assert called_backend is raw_backend
    assert "background runtime resolved:" in caplog.text
    assert "mode=fallback" in caplog.text


@pytest.mark.asyncio
async def test_gui_tool_execute_no_background() -> None:
    """With gui_config.background=False, execute() calls _run_task with the raw backend."""
    tool = _make_gui_tool(background=False)
    raw_backend = tool._backend

    canned_result = json.dumps({"success": True, "summary": "ok", "trace_path": None, "steps_taken": 0, "error": None})

    with patch("nanobot.agent.tools.gui.GuiSubagentTool._run_task", new=AsyncMock(return_value=canned_result)) as mock_run_task:
        result = await tool.execute("test task")

    assert result == canned_result
    # _run_task must be called with the unwrapped raw backend
    mock_run_task.assert_called_once()
    called_backend = mock_run_task.call_args[0][0]
    assert called_backend is raw_backend


@pytest.mark.asyncio
async def test_gui_tool_requires_ack_for_background_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tool = _make_gui_tool(background=True)
    raw_backend = tool._backend
    monkeypatch.setattr(sys, "platform", "darwin")

    with patch(
        "opengui.backends.background_runtime.probe_isolated_background_support",
        return_value=MagicMock(
            supported=False,
            reason_code="platform_unsupported",
            retryable=False,
            host_platform="macos",
            backend_name=None,
            sys_platform="darwin",
        ),
    ):
        with patch("nanobot.agent.tools.gui.GuiSubagentTool._run_task", new=AsyncMock()) as mock_run_task:
            with caplog.at_level(logging.WARNING, logger="nanobot.agent.tools.gui"):
                payload = json.loads(await tool.execute("open settings"))

            assert payload["success"] is False
            assert "resolved to fallback" in payload["summary"]
            assert "platform_unsupported" in payload["summary"]
            assert "Run without background isolation on this host until a supported isolated backend exists." in payload["summary"]
            assert "acknowledge_background_fallback=true" in payload["summary"]
            assert "background_mode" not in payload
            mock_run_task.assert_not_awaited()
            assert "mode=fallback" in caplog.text
            assert "reason=platform_unsupported" in caplog.text

        with patch(
            "nanobot.agent.tools.gui.GuiSubagentTool._run_task",
            new=AsyncMock(return_value=json.dumps({"success": True, "summary": "done", "trace_path": None, "steps_taken": 1, "error": None})),
        ) as mock_run_task:
            await tool.execute("open settings", acknowledge_background_fallback=True)
            assert mock_run_task.await_count == 1
            assert mock_run_task.await_args.args[0] is raw_backend


@pytest.mark.asyncio
async def test_gui_tool_reports_busy_waiting_metadata_for_serialized_background_runs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import opengui.backends.background_runtime as runtime
    from opengui.backends.virtual_display import DisplayInfo

    tool = _make_gui_tool(background=True)
    inner_backend = AsyncMock()
    type(inner_backend).platform = PropertyMock(return_value="linux")
    inner_backend.preflight = AsyncMock()
    inner_backend.observe = AsyncMock()
    inner_backend.execute = AsyncMock(return_value="ok")
    inner_backend.list_apps = AsyncMock(return_value=[])
    tool._backend = inner_backend

    fresh_coordinator = runtime.BackgroundRuntimeCoordinator()
    monkeypatch.setattr(runtime, "GLOBAL_BACKGROUND_RUNTIME_COORDINATOR", fresh_coordinator)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        runtime,
        "probe_isolated_background_support",
        lambda **_: runtime.IsolationProbeResult(
            supported=True,
            reason_code="xvfb_available",
            retryable=False,
            host_platform="linux",
            backend_name="xvfb",
            sys_platform="linux",
        ),
    )

    class FakeXvfbDisplayManager:
        def __init__(self, display_num: int = 99, width: int = 1280, height: int = 720) -> None:
            self.display_num = display_num
            self.width = width
            self.height = height

        async def start(self) -> DisplayInfo:
            return DisplayInfo(display_id=":99", width=self.width, height=self.height)

        async def stop(self) -> None:
            return None

    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_run_task(active_backend: Any, task: str, **kwargs: Any) -> str:
        await active_backend.preflight()
        if task == "first":
            first_started.set()
            await release_first.wait()
        else:
            await first_started.wait()
        return json.dumps({"success": True, "summary": task, "trace_path": None, "steps_taken": 1, "error": None})

    with (
        patch("opengui.backends.displays.xvfb.XvfbDisplayManager", FakeXvfbDisplayManager),
        patch("nanobot.agent.tools.gui.GuiSubagentTool._run_task", new=AsyncMock(side_effect=fake_run_task)),
        caplog.at_level(logging.WARNING, logger="opengui.backends.background_runtime"),
    ):
        first_task = asyncio.create_task(tool.execute("first", acknowledge_background_fallback=True))
        await first_started.wait()
        second_task = asyncio.create_task(tool.execute("second", acknowledge_background_fallback=True))
        await asyncio.sleep(0.05)
        release_first.set()
        await asyncio.gather(first_task, second_task)

    busy_messages = [record.message for record in caplog.records if record.message.startswith("background runtime busy:")]
    assert busy_messages
    assert "waiting_owner=nanobot" in busy_messages[0]
    assert "active_owner=nanobot" in busy_messages[0]
    assert "active_task=first" in busy_messages[0]
