"""Phase 9 Plan 01 tests — VirtualDisplayManager protocol, DisplayInfo, NoOpDisplayManager.

Requirements covered:
  VDISP-01: VirtualDisplayManager protocol (importable, isinstance, async methods)
  VDISP-02: DisplayInfo frozen dataclass (fields, defaults, immutability)
  VDISP-03: NoOpDisplayManager (start/stop behaviour, idempotency, no subprocess)
"""
from __future__ import annotations

import dataclasses
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from opengui.backends.virtual_display import NoOpDisplayManager
from opengui.interfaces import DisplayInfo, VirtualDisplayManager

# ---------------------------------------------------------------------------
# VDISP-01: protocol importability and async shape
# ---------------------------------------------------------------------------


async def test_protocol_importable() -> None:
    """VirtualDisplayManager is importable from interfaces; NoOpDisplayManager satisfies it."""
    mgr = NoOpDisplayManager()
    assert isinstance(mgr, VirtualDisplayManager)


async def test_protocol_methods_are_async() -> None:
    """VirtualDisplayManager.start() and stop() are coroutine functions."""
    mgr = NoOpDisplayManager()
    assert inspect.iscoroutinefunction(mgr.start)
    assert inspect.iscoroutinefunction(mgr.stop)


# ---------------------------------------------------------------------------
# VDISP-02: DisplayInfo frozen dataclass
# ---------------------------------------------------------------------------


async def test_display_info_frozen() -> None:
    """DisplayInfo is immutable — assigning any attribute raises FrozenInstanceError."""
    di = DisplayInfo(display_id=":99", width=1920, height=1080)
    with pytest.raises(dataclasses.FrozenInstanceError):
        di.width = 100  # type: ignore[misc]


async def test_display_info_field_names() -> None:
    """DisplayInfo declares the exact fields required by the locked protocol decision."""
    field_names = [f.name for f in dataclasses.fields(DisplayInfo)]
    assert field_names == [
        "display_id",
        "width",
        "height",
        "offset_x",
        "offset_y",
        "monitor_index",
    ]


async def test_display_info_defaults() -> None:
    """Optional fields default to the locked values: offset_x=0, offset_y=0, monitor_index=1."""
    di = DisplayInfo(display_id=":99", width=1920, height=1080)
    assert di.offset_x == 0
    assert di.offset_y == 0
    assert di.monitor_index == 1


# ---------------------------------------------------------------------------
# VDISP-03: NoOpDisplayManager behaviour
# ---------------------------------------------------------------------------


async def test_noop_start_returns_display_info() -> None:
    """NoOpDisplayManager.start() returns a DisplayInfo with expected defaults."""
    info = await NoOpDisplayManager().start()
    assert isinstance(info, DisplayInfo)
    assert info.display_id == "noop"
    assert info.width == 1920
    assert info.height == 1080


async def test_noop_custom_dimensions() -> None:
    """NoOpDisplayManager respects custom width/height constructor arguments."""
    info = await NoOpDisplayManager(width=800, height=600).start()
    assert info.width == 800
    assert info.height == 600


async def test_noop_stop_is_idempotent() -> None:
    """Calling stop() multiple times must not raise."""
    mgr = NoOpDisplayManager()
    await mgr.stop()
    await mgr.stop()  # second call — must not raise


async def test_noop_start_no_subprocess() -> None:
    """NoOpDisplayManager.start() must not spawn any subprocess."""
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        await NoOpDisplayManager().start()
        mock_exec.assert_not_called()
