"""Phase 13 macOS background execution contract coverage."""

from __future__ import annotations

from typing import Any

import pytest

import opengui.backends.background_runtime as runtime
from opengui.backends.displays.cgvirtualdisplay import CGVirtualDisplayManager
from opengui.backends.virtual_display import DisplayInfo


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
