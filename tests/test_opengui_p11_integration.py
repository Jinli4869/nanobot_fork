"""Phase 11 integration tests: GuiConfig background fields and GuiSubagentTool wrapping.

Requirements covered:
  INTG-02: GuiConfig schema validates background + backend constraint at config load time
  INTG-04: GuiSubagentTool.execute() wraps backend in BackgroundDesktopBackend on Linux
  TEST-V11-01: All new tests pass without a real Xvfb binary
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
    mock_bg_instance.__aenter__ = AsyncMock(return_value=mock_bg_instance)
    mock_bg_instance.__aexit__ = AsyncMock(return_value=None)
    mock_bg_instance.platform = "linux"

    mock_bg_cls = MagicMock(return_value=mock_bg_instance)

    canned_result = json.dumps({"success": True, "summary": "done", "trace_path": None, "steps_taken": 1, "error": None})

    with (
        patch("nanobot.agent.tools.gui.GuiSubagentTool._run_task", new=AsyncMock(return_value=canned_result)) as mock_run_task,
        patch("opengui.backends.background.BackgroundDesktopBackend", mock_bg_cls),
        patch("opengui.backends.displays.xvfb.XvfbDisplayManager", mock_xvfb_cls),
    ):
        result = await tool.execute("test task")

    assert result == canned_result
    # BackgroundDesktopBackend must have been constructed with inner backend and xvfb manager
    mock_bg_cls.assert_called_once_with(inner_backend, mock_xvfb_instance)


@pytest.mark.asyncio
async def test_gui_tool_execute_background_nonlinux_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On non-Linux, execute() with gui_config.background=True logs warning and runs in foreground."""
    # Do not override sys.platform — we are on macOS/darwin in CI
    monkeypatch.setattr(sys, "platform", "darwin")

    tool = _make_gui_tool(background=True)

    canned_result = json.dumps({"success": True, "summary": "done", "trace_path": None, "steps_taken": 1, "error": None})

    with (
        patch("nanobot.agent.tools.gui.GuiSubagentTool._run_task", new=AsyncMock(return_value=canned_result)),
        caplog.at_level(logging.WARNING, logger="nanobot.agent.tools.gui"),
    ):
        result = await tool.execute("test task")

    assert result == canned_result
    # Warning must mention that Xvfb is Linux-only
    assert "Linux-only" in caplog.text


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
