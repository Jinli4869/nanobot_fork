"""Phase 9 Wave-0 stubs — VirtualDisplayManager protocol, DisplayInfo, NoOpDisplayManager.

All tests are marked xfail; Plan 01 will replace each stub with real assertions.

Requirements covered:
  VDISP-01: VirtualDisplayManager protocol (importable, async methods)
  VDISP-02: DisplayInfo frozen dataclass (fields, defaults)
  VDISP-03: NoOpDisplayManager (start/stop behaviour, no subprocess)
"""
from __future__ import annotations

import pytest

from opengui.backends.virtual_display import (
    DisplayInfo,
    NoOpDisplayManager,
    VirtualDisplayManager,
)

# ---------------------------------------------------------------------------
# VDISP-01: protocol importability and async shape
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_protocol_importable() -> None:
    assert False, "stub"


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_protocol_methods_are_async() -> None:
    assert False, "stub"


# ---------------------------------------------------------------------------
# VDISP-02: DisplayInfo frozen dataclass
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_display_info_frozen() -> None:
    assert False, "stub"


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_display_info_field_names() -> None:
    assert False, "stub"


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_display_info_defaults() -> None:
    assert False, "stub"


# ---------------------------------------------------------------------------
# VDISP-03: NoOpDisplayManager behaviour
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_noop_start_returns_display_info() -> None:
    assert False, "stub"


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_noop_custom_dimensions() -> None:
    assert False, "stub"


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_noop_stop_is_idempotent() -> None:
    assert False, "stub"


@pytest.mark.xfail(reason="Wave 0 stub — implementation in Plan 01")
async def test_noop_start_no_subprocess() -> None:
    assert False, "stub"
