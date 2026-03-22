"""Phase 13 macOS background execution contract coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

import opengui.backends.background_runtime as runtime
import opengui.backends.displays.cgvirtualdisplay as cgvirtualdisplay
from opengui.action import Action
from opengui.backends.background import BackgroundDesktopBackend
from opengui.backends.displays.cgvirtualdisplay import CGVirtualDisplayManager
from opengui.backends.virtual_display import DisplayInfo
from opengui.observation import Observation


def test_probe_macos_virtual_display_available() -> None:
    expected = runtime.IsolationProbeResult(
        supported=True,
        reason_code="macos_virtual_display_available",
        retryable=False,
        host_platform="macos",
        backend_name="cgvirtualdisplay",
        sys_platform="darwin",
    )

    def _probe(raw_platform: str) -> runtime.IsolationProbeResult:
        assert raw_platform == "darwin"
        return expected

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(runtime, "_probe_macos_isolated_support", _probe)
    try:
        result = runtime.probe_isolated_background_support(sys_platform="darwin")
    finally:
        monkeypatch.undo()

    assert result == expected


def test_probe_reports_macos_version_unsupported() -> None:
    probe = runtime.IsolationProbeResult(
        supported=False,
        reason_code="macos_version_unsupported",
        retryable=False,
        host_platform="macos",
        backend_name="cgvirtualdisplay",
        sys_platform="darwin",
    )

    decision = runtime.resolve_run_mode(
        probe,
        require_isolation=True,
        require_acknowledgement_for_fallback=False,
    )

    assert decision.mode == "blocked"
    assert decision.reason_code == "macos_version_unsupported"
    assert "macos_version_unsupported" in decision.message
    assert "macOS 14 or newer" in decision.message


def test_probe_reports_actionable_permission_remediation() -> None:
    probe = runtime.IsolationProbeResult(
        supported=False,
        reason_code="macos_screen_recording_denied",
        retryable=True,
        host_platform="macos",
        backend_name="cgvirtualdisplay",
        sys_platform="darwin",
    )

    decision = runtime.resolve_run_mode(
        probe,
        require_isolation=False,
        require_acknowledgement_for_fallback=False,
    )

    assert decision.mode == "fallback"
    assert decision.reason_code == "macos_screen_recording_denied"
    assert "System Settings" in decision.message
    assert "Screen Recording" in decision.message


def test_accessibility_probe_uses_quartz_symbol_when_available() -> None:
    class QuartzStub:
        @staticmethod
        def AXIsProcessTrusted() -> bool:
            return True

    assert cgvirtualdisplay._accessibility_allowed(QuartzStub) is True


def test_accessibility_probe_falls_back_to_ctypes_when_quartz_symbol_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class QuartzStub:
        pass

    monkeypatch.setattr(cgvirtualdisplay, "_accessibility_allowed_via_ctypes", lambda: True)

    assert cgvirtualdisplay._accessibility_allowed(QuartzStub) is True


def test_accessibility_probe_returns_false_when_fallback_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class QuartzStub:
        pass

    monkeypatch.setattr(cgvirtualdisplay, "_accessibility_allowed_via_ctypes", lambda: False)

    assert cgvirtualdisplay._accessibility_allowed(QuartzStub) is False


@pytest.mark.asyncio
async def test_cgvirtualdisplay_manager_returns_display_info() -> None:
    manager = CGVirtualDisplayManager(width=1440, height=900, offset_x=200, offset_y=120, monitor_index=3)
    handle = {
        "display_id": "macos:42",
        "width": 1440,
        "height": 900,
        "offset_x": 200,
        "offset_y": 120,
        "monitor_index": 3,
    }

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(manager, "_create_virtual_display", lambda: handle)
    try:
        info = await manager.start()
    finally:
        monkeypatch.undo()

    assert info == DisplayInfo(
        display_id="macos:42",
        width=1440,
        height=900,
        offset_x=200,
        offset_y=120,
        monitor_index=3,
    )


@pytest.mark.asyncio
async def test_cgvirtualdisplay_manager_stop_is_idempotent() -> None:
    manager = CGVirtualDisplayManager()
    calls: list[Any] = []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(manager, "_create_virtual_display", lambda: {"display_id": "macos:1", "width": 1440, "height": 900})
    monkeypatch.setattr(manager, "_destroy_virtual_display", lambda handle: calls.append(handle))
    try:
        await manager.start()
        await manager.stop()
        await manager.stop()
    finally:
        monkeypatch.undo()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_background_wrapper_configures_target_display_before_preflight() -> None:
    display_info = DisplayInfo(
        display_id="macos:42",
        width=1440,
        height=900,
        offset_x=200,
        offset_y=120,
        monitor_index=2,
    )
    call_order: list[str] = []

    manager = AsyncMock()
    manager.start = AsyncMock(return_value=display_info)
    manager.stop = AsyncMock(side_effect=lambda: call_order.append("stop"))

    inner = AsyncMock()
    type(inner).platform = PropertyMock(return_value="macos")
    inner.configure_target_display = MagicMock(
        side_effect=lambda info: call_order.append(
            f"configure:{'set' if info is display_info else 'clear'}"
        )
    )
    inner.preflight = AsyncMock(side_effect=lambda: call_order.append("preflight"))
    inner.observe = AsyncMock()
    inner.execute = AsyncMock(return_value="ok")

    backend = BackgroundDesktopBackend(inner, manager)
    await backend.preflight()

    assert call_order == ["configure:set", "preflight"]
    inner.configure_target_display.assert_called_once_with(display_info)

    await backend.shutdown()

    assert call_order[-2:] == ["stop", "configure:clear"]
    assert inner.configure_target_display.call_args_list[-1].args == (None,)


@pytest.mark.asyncio
async def test_background_wrapper_preflight_is_idempotent() -> None:
    display_info = DisplayInfo(
        display_id="macos:42",
        width=1440,
        height=900,
        offset_x=200,
        offset_y=120,
        monitor_index=2,
    )

    manager = AsyncMock()
    manager.start = AsyncMock(return_value=display_info)
    manager.stop = AsyncMock()

    inner = AsyncMock()
    type(inner).platform = PropertyMock(return_value="macos")
    inner.configure_target_display = MagicMock()
    inner.preflight = AsyncMock()
    inner.observe = AsyncMock()
    inner.execute = AsyncMock(return_value="ok")

    backend = BackgroundDesktopBackend(inner, manager)
    await backend.preflight()
    await backend.preflight()

    assert manager.start.await_count == 1
    assert inner.preflight.await_count == 1

    await backend.shutdown()


@pytest.mark.asyncio
async def test_macos_target_surface_routing_keeps_observe_and_execute_aligned(
    tmp_path: Path,
) -> None:
    display_info = DisplayInfo(
        display_id="macos:42",
        width=1440,
        height=900,
        offset_x=200,
        offset_y=120,
        monitor_index=2,
    )
    configured_displays: list[DisplayInfo | None] = []

    manager = AsyncMock()
    manager.start = AsyncMock(return_value=display_info)
    manager.stop = AsyncMock()

    inner = AsyncMock()
    type(inner).platform = PropertyMock(return_value="macos")

    def _configure(info: DisplayInfo | None) -> None:
        configured_displays.append(info)

    inner.configure_target_display = MagicMock(side_effect=_configure)
    inner.preflight = AsyncMock()
    inner.observe = AsyncMock(
        side_effect=lambda screenshot_path, timeout=5.0: Observation(
            screenshot_path=str(screenshot_path),
            screen_width=display_info.width,
            screen_height=display_info.height,
            foreground_app="Finder",
            platform="macos",
        )
    )
    inner.execute = AsyncMock(return_value="ok")

    backend = BackgroundDesktopBackend(inner, manager)
    await backend.preflight()

    observation = await backend.observe(tmp_path / "surface.png")
    result = await backend.execute(Action(action_type="tap", x=100.0, y=200.0))

    assert configured_displays == [display_info]
    assert observation.screen_width == 1440
    assert observation.screen_height == 900
    passed_action = inner.execute.call_args.args[0]
    assert passed_action.x == 300.0
    assert passed_action.y == 320.0
    assert result == "ok"

    await backend.shutdown()
