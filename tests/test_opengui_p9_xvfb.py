"""Phase 9 Wave-0 stubs — XvfbDisplayManager error paths and lifecycle.

All tests are marked xfail via module-level pytestmark; Plan 02 will replace
each stub with real assertions.  Imports are guarded because XvfbNotFoundError
and XvfbCrashedError are not defined until Plan 02 Task 1.

Requirements covered:
  VDISP-04: XvfbDisplayManager (start/stop, error types, auto-increment)
"""
from __future__ import annotations

import pytest

try:
    from opengui.backends.displays.xvfb import (
        XvfbCrashedError,
        XvfbDisplayManager,
        XvfbNotFoundError,
    )
    from opengui.backends.virtual_display import DisplayInfo, VirtualDisplayManager

    _IMPORTS_OK = True
except ImportError:
    _IMPORTS_OK = False

pytestmark = [
    pytest.mark.skipif(not _IMPORTS_OK, reason="Wave 0: error types not yet defined"),
    pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 02"),
]

# ---------------------------------------------------------------------------
# VDISP-04: XvfbDisplayManager — isinstance, start, error paths
# ---------------------------------------------------------------------------


async def test_xvfb_isinstance_check() -> None:
    assert False, "stub"


async def test_xvfb_start_returns_display_info() -> None:
    assert False, "stub"


async def test_xvfb_start_custom_dimensions() -> None:
    assert False, "stub"


async def test_xvfb_not_found_error() -> None:
    assert False, "stub"


async def test_xvfb_start_timeout() -> None:
    assert False, "stub"


async def test_xvfb_auto_increment() -> None:
    assert False, "stub"


async def test_xvfb_auto_increment_all_locked() -> None:
    assert False, "stub"


async def test_xvfb_crash_detection() -> None:
    assert False, "stub"


async def test_xvfb_stop_never_started() -> None:
    assert False, "stub"


async def test_xvfb_stop_idempotent() -> None:
    assert False, "stub"


async def test_xvfb_stop_terminates_process() -> None:
    assert False, "stub"


async def test_xvfb_stderr_is_piped() -> None:
    assert False, "stub"
