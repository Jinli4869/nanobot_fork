"""Phase 14 Windows isolated desktop contract coverage."""

from __future__ import annotations

from importlib import import_module
from typing import Any
from unittest.mock import AsyncMock

import pytest

import opengui.backends.background_runtime as runtime
from opengui.backends.virtual_display import DisplayInfo


def _load_win32desktop_module() -> Any:
    try:
        return import_module("opengui.backends.displays.win32desktop")
    except ModuleNotFoundError as exc:  # pragma: no cover - red phase expectation
        pytest.fail(f"win32desktop module missing: {exc}")


def _windows_probe_from_support(support: dict[str, object]) -> runtime.IsolationProbeResult:
    return runtime.IsolationProbeResult(
        supported=bool(support["supported"]),
        reason_code=str(support["reason_code"]),
        retryable=bool(support["retryable"]),
        host_platform="windows",
        backend_name="windows_isolated_desktop",
        sys_platform="win32",
    )


def test_probe_windows_isolated_desktop_available(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = runtime.IsolationProbeResult(
        supported=True,
        reason_code="windows_isolated_desktop_available",
        retryable=False,
        host_platform="windows",
        backend_name="windows_isolated_desktop",
        sys_platform="win32",
    )

    def _probe(raw_platform: str, *, target_app_class: str | None = None) -> runtime.IsolationProbeResult:
        assert raw_platform == "win32"
        assert target_app_class == "classic-win32"
        return expected

    monkeypatch.setattr(runtime, "_probe_windows_isolated_support", _probe)

    result = runtime.probe_isolated_background_support(
        sys_platform="win32",
        target_app_class="classic-win32",
    )

    assert result == expected


def test_probe_reports_non_interactive_windows_context(monkeypatch: pytest.MonkeyPatch) -> None:
    win32desktop = _load_win32desktop_module()
    support_state = win32desktop.WindowsIsolatedDesktopSupport(
        interactive_session=False,
        input_desktop_available=True,
        create_desktop_available=True,
        reason_code="windows_non_interactive_session",
    )
    monkeypatch.setattr(
        win32desktop,
        "_collect_windows_isolated_desktop_support",
        lambda: support_state,
    )

    support = win32desktop.probe_windows_isolated_desktop_support()
    decision = runtime.resolve_run_mode(
        _windows_probe_from_support(support),
        require_isolation=True,
        require_acknowledgement_for_fallback=False,
    )

    assert support["supported"] is False
    assert support["reason_code"] == "windows_non_interactive_session"
    assert "Session 0" in decision.message


def test_probe_reports_unsupported_app_class_with_actionable_message() -> None:
    win32desktop = _load_win32desktop_module()

    support = win32desktop.probe_windows_isolated_desktop_support(target_app_class="uwp")
    decision = runtime.resolve_run_mode(
        _windows_probe_from_support(support),
        require_isolation=True,
        require_acknowledgement_for_fallback=False,
    )

    assert support["supported"] is False
    assert support["reason_code"] == "windows_app_class_unsupported"
    assert "classic Win32" in decision.message
    assert "UWP" in decision.message
    assert "DirectX" in decision.message


@pytest.mark.asyncio
async def test_win32desktop_manager_returns_display_info(monkeypatch: pytest.MonkeyPatch) -> None:
    win32desktop = _load_win32desktop_module()

    class _FakeUUID:
        hex = "0123456789abcdef0123456789abcdef"

    manager = win32desktop.Win32DesktopManager(width=1600, height=900)
    launched_desktop = AsyncMock()

    monkeypatch.setattr(win32desktop.uuid, "uuid4", lambda: _FakeUUID())
    monkeypatch.setattr(manager, "_create_desktop_handle", lambda: object())

    info = await manager.start()
    await launched_desktop(f"WinSta0\\{manager.desktop_name}")

    assert info == DisplayInfo(
        display_id="windows_isolated_desktop:OpenGUI-Background-01234567",
        width=1600,
        height=900,
        offset_x=0,
        offset_y=0,
        monitor_index=1,
    )
    assert manager.desktop_name == "OpenGUI-Background-01234567"
    launched_desktop.assert_awaited_once_with("WinSta0\\OpenGUI-Background-01234567")


@pytest.mark.asyncio
async def test_win32desktop_manager_stop_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    win32desktop = _load_win32desktop_module()
    manager = win32desktop.Win32DesktopManager()
    closed_handles: list[object] = []
    handle = object()

    monkeypatch.setattr(manager, "_create_desktop_handle", lambda: handle)
    monkeypatch.setattr(manager, "_close_desktop_handle", lambda target: closed_handles.append(target))

    await manager.start()
    await manager.stop()
    await manager.stop()

    assert closed_handles == [handle]
