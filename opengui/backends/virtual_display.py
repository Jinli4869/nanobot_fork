"""Virtual display abstractions for background GUI execution.

Defines :class:`DisplayInfo` (immutable display metadata),
:class:`VirtualDisplayManager` (async lifecycle protocol), and
:class:`NoOpDisplayManager` (passthrough for testing / Android).
"""

from __future__ import annotations

import dataclasses
import typing


@dataclasses.dataclass(frozen=True)
class DisplayInfo:
    """Immutable metadata for a virtual display."""

    display_id: str  # e.g. ":99" for Xvfb, desktop handle for Windows
    width: int
    height: int
    offset_x: int = 0  # global coordinate offset (macOS CGVirtualDisplay)
    offset_y: int = 0
    monitor_index: int = 1  # mss monitor index


@typing.runtime_checkable
class VirtualDisplayManager(typing.Protocol):
    """Async lifecycle protocol for virtual display backends."""

    async def start(self) -> DisplayInfo: ...

    async def stop(self) -> None: ...


class NoOpDisplayManager:
    """Passthrough manager for testing and backends that need no virtual display."""

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
    ) -> None:
        self._width = width
        self._height = height

    async def start(self) -> DisplayInfo:
        return DisplayInfo(
            display_id="noop",
            width=self._width,
            height=self._height,
        )

    async def stop(self) -> None:
        pass
