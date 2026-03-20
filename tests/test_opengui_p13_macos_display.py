"""Phase 13 Wave 0 placeholders for macOS background execution contracts."""

from __future__ import annotations

import pytest

try:
    import opengui.backends.background_runtime as runtime
    from opengui.backends.displays.cgvirtualdisplay import CGVirtualDisplayManager
    from opengui.backends.virtual_display import DisplayInfo

    _IMPORTS_OK = True
except ImportError:
    runtime = None
    CGVirtualDisplayManager = None
    DisplayInfo = None
    _IMPORTS_OK = False


@pytest.mark.xfail(strict=True, reason="Phase 13 macOS background contracts not implemented yet")
def test_probe_macos_virtual_display_available() -> None:
    expected_backend_name = "cgvirtualdisplay"
    assert expected_backend_name == "cgvirtualdisplay"
    assert runtime is None or hasattr(runtime, "probe_isolated_background_support")
    pytest.fail("phase 13 placeholder")


@pytest.mark.xfail(strict=True, reason="Phase 13 macOS background contracts not implemented yet")
def test_probe_reports_macos_version_unsupported() -> None:
    expected_reason_code = "macos_version_unsupported"
    assert expected_reason_code.endswith("unsupported")
    assert runtime is None or hasattr(runtime, "resolve_run_mode")
    pytest.fail("phase 13 placeholder")


@pytest.mark.xfail(strict=True, reason="Phase 13 macOS background contracts not implemented yet")
def test_probe_reports_actionable_permission_remediation() -> None:
    expected_reason_code = "macos_screen_recording_denied"
    expected_remediation = "System Settings"
    assert expected_reason_code.startswith("macos_")
    assert "Settings" in expected_remediation
    pytest.fail("phase 13 placeholder")


@pytest.mark.xfail(strict=True, reason="Phase 13 macOS background contracts not implemented yet")
@pytest.mark.asyncio
async def test_cgvirtualdisplay_manager_returns_display_info() -> None:
    expected_type_name = "DisplayInfo"
    assert expected_type_name == "DisplayInfo"
    assert DisplayInfo is None or DisplayInfo.__name__ == "DisplayInfo"
    assert CGVirtualDisplayManager is None or CGVirtualDisplayManager.__name__ == "CGVirtualDisplayManager"
    pytest.fail("phase 13 placeholder")


@pytest.mark.xfail(strict=True, reason="Phase 13 macOS background contracts not implemented yet")
@pytest.mark.asyncio
async def test_cgvirtualdisplay_manager_stop_is_idempotent() -> None:
    cleanup_contract = "idempotent cleanup"
    assert cleanup_contract.endswith("cleanup")
    assert _IMPORTS_OK in {True, False}
    pytest.fail("phase 13 placeholder")
