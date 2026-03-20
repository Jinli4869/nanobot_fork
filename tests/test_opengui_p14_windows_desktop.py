"""Phase 14 Windows isolated desktop contract coverage."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from importlib import import_module
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from opengui.action import Action
import opengui.backends.background_runtime as runtime
from opengui.backends.virtual_display import DisplayInfo
from opengui.observation import Observation


def _load_win32desktop_module() -> Any:
    try:
        return import_module("opengui.backends.displays.win32desktop")
    except ModuleNotFoundError as exc:  # pragma: no cover - red phase expectation
        pytest.fail(f"win32desktop module missing: {exc}")


def _load_windows_isolated_module() -> Any:
    try:
        return import_module("opengui.backends.windows_isolated")
    except ModuleNotFoundError as exc:  # pragma: no cover - red phase expectation
        pytest.fail(f"windows_isolated module missing: {exc}")


def _windows_probe_from_support(support: dict[str, object]) -> runtime.IsolationProbeResult:
    return runtime.IsolationProbeResult(
        supported=bool(support["supported"]),
        reason_code=str(support["reason_code"]),
        retryable=bool(support["retryable"]),
        host_platform="windows",
        backend_name="windows_isolated_desktop",
        sys_platform="win32",
    )


def _make_windows_display_info() -> DisplayInfo:
    return DisplayInfo(
        display_id="windows_isolated_desktop:OpenGUI-Background-1",
        width=1280,
        height=720,
        offset_x=0,
        offset_y=0,
        monitor_index=1,
    )


def _make_windows_manager(display_info: DisplayInfo | None = None) -> AsyncMock:
    manager = AsyncMock()
    manager.start = AsyncMock(return_value=display_info or _make_windows_display_info())
    manager.stop = AsyncMock()
    manager.desktop_name = "OpenGUI-Background-1"
    return manager


def _make_windows_inner() -> AsyncMock:
    inner = AsyncMock()
    type(inner).platform = PropertyMock(return_value="windows")
    inner.preflight = AsyncMock()
    inner.list_apps = AsyncMock(return_value=[])
    inner.configure_target_display = MagicMock()
    return inner


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


@pytest.mark.asyncio
async def test_windows_isolated_backend_launches_worker_on_named_desktop(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    windows_isolated = _load_windows_isolated_module()
    display_info = _make_windows_display_info()
    manager = _make_windows_manager(display_info)
    inner = _make_windows_inner()
    backend = windows_isolated.WindowsIsolatedBackend(
        inner,
        manager,
        run_metadata={"owner": "phase14-test", "task": "launch"},
    )
    launch_calls: list[dict[str, object]] = []

    def _launch_windows_worker(**kwargs: object) -> object:
        launch_calls.append(dict(kwargs))
        return object()

    monkeypatch.setattr(windows_isolated, "launch_windows_worker", _launch_windows_worker)
    monkeypatch.setattr(backend, "_stop_worker_session", AsyncMock())
    caplog.set_level(logging.INFO)

    try:
        await backend.preflight()
    finally:
        await backend.shutdown()

    assert launch_calls == [
        {
            "desktop_name": "OpenGUI-Background-1",
            "width": 1280,
            "height": 720,
            "control_path": launch_calls[0]["control_path"],
        }
    ]
    assert isinstance(launch_calls[0]["control_path"], str)
    inner.configure_target_display.assert_any_call(display_info)
    assert "windows isolated backend ready:" in caplog.text
    assert "backend_name=windows_isolated_desktop" in caplog.text
    assert "display_id=windows_isolated_desktop:OpenGUI-Background-1" in caplog.text
    assert r"lpDesktop=WinSta0\OpenGUI-Background-1" in caplog.text


@pytest.mark.asyncio
async def test_windows_isolated_backend_observe_and_execute_use_target_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows_isolated = _load_windows_isolated_module()
    display_info = _make_windows_display_info()
    manager = _make_windows_manager(display_info)
    inner = _make_windows_inner()
    backend = windows_isolated.WindowsIsolatedBackend(inner, manager)

    monkeypatch.setattr(windows_isolated, "launch_windows_worker", lambda **_: object())
    observe_mock = AsyncMock(
        return_value=Observation(
            screenshot_path="/tmp/windows-shot.png",
            screen_width=display_info.width,
            screen_height=display_info.height,
            platform="windows",
            extra={"display_id": display_info.display_id},
        )
    )
    execute_mock = AsyncMock(return_value=f"executed:{display_info.display_id}")
    stop_mock = AsyncMock()
    monkeypatch.setattr(backend, "_observe_via_worker", observe_mock)
    monkeypatch.setattr(backend, "_execute_via_worker", execute_mock)
    monkeypatch.setattr(backend, "_stop_worker_session", stop_mock)

    try:
        await backend.preflight()
        observation = await backend.observe(pathlib.Path("/tmp/windows-shot.png"))
        result = await backend.execute(Action(action_type="tap", x=10.0, y=20.0))
    finally:
        await backend.shutdown()

    assert observation.extra["display_id"] == display_info.display_id
    assert result == f"executed:{display_info.display_id}"
    observe_mock.assert_awaited_once_with(pathlib.Path("/tmp/windows-shot.png"), 5.0)
    execute_mock.assert_awaited_once_with(Action(action_type="tap", x=10.0, y=20.0), 5.0)
    inner.configure_target_display.assert_any_call(display_info)
    inner.configure_target_display.assert_any_call(None)


@pytest.mark.asyncio
async def test_windows_isolated_backend_cleans_up_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    windows_isolated = _load_windows_isolated_module()
    display_info = _make_windows_display_info()
    manager = _make_windows_manager(display_info)
    inner = _make_windows_inner()
    backend = windows_isolated.WindowsIsolatedBackend(inner, manager)

    monkeypatch.setattr(backend, "_start_worker_session", AsyncMock())
    monkeypatch.setattr(
        backend,
        "_observe_via_worker",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    stop_mock = AsyncMock()
    monkeypatch.setattr(backend, "_stop_worker_session", stop_mock)
    caplog.set_level(logging.INFO)

    await backend.preflight()

    with pytest.raises(asyncio.CancelledError):
        await backend.observe(pathlib.Path("/tmp/windows-shot.png"))

    await backend.shutdown()

    stop_mock.assert_awaited_once_with("cancelled")
    manager.stop.assert_awaited_once()
    inner.configure_target_display.assert_any_call(None)
    assert "windows isolated backend cleanup:" in caplog.text
    assert "cleanup_reason=cancelled" in caplog.text


@pytest.mark.asyncio
async def test_windows_isolated_backend_cleans_up_after_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    windows_isolated = _load_windows_isolated_module()
    display_info = _make_windows_display_info()
    manager = _make_windows_manager(display_info)
    inner = _make_windows_inner()
    backend = windows_isolated.WindowsIsolatedBackend(inner, manager)

    monkeypatch.setattr(
        backend,
        "_start_worker_session",
        AsyncMock(side_effect=RuntimeError("worker launch failed")),
    )
    stop_mock = AsyncMock()
    monkeypatch.setattr(backend, "_stop_worker_session", stop_mock)
    caplog.set_level(logging.INFO)

    with pytest.raises(RuntimeError, match="worker launch failed"):
        await backend.preflight()

    await backend.shutdown()

    stop_mock.assert_awaited_once_with("startup_failed")
    manager.stop.assert_awaited_once()
    inner.configure_target_display.assert_any_call(display_info)
    inner.configure_target_display.assert_any_call(None)
    assert "windows isolated backend cleanup:" in caplog.text
    assert "cleanup_reason=startup_failed" in caplog.text
