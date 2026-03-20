"""Windows isolated desktop support and lifecycle helpers.

This module stays import-safe on non-Windows hosts so contract tests can run in
CI while Phase 14 builds out the real worker-backed execution seam.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import sys
import uuid
from typing import Any

from opengui.backends.virtual_display import DisplayInfo

logger = logging.getLogger(__name__)

_UNSUPPORTED_APP_CLASSES = {"uwp", "directx", "gpu-heavy", "electron-gpu"}


@dataclasses.dataclass(frozen=True)
class WindowsIsolatedDesktopSupport:
    interactive_session: bool
    input_desktop_available: bool
    create_desktop_available: bool
    reason_code: str


def probe_windows_isolated_desktop_support(*, target_app_class: str | None = None) -> dict[str, object]:
    normalized_app_class = (target_app_class or "").strip().lower()
    if normalized_app_class in _UNSUPPORTED_APP_CLASSES:
        return {
            "supported": False,
            "reason_code": "windows_app_class_unsupported",
            "retryable": False,
        }

    support = _collect_windows_isolated_desktop_support()
    if not support.interactive_session:
        return {
            "supported": False,
            "reason_code": "windows_non_interactive_session",
            "retryable": False,
        }
    if not support.input_desktop_available:
        return {
            "supported": False,
            "reason_code": "windows_input_desktop_unavailable",
            "retryable": True,
        }
    if not support.create_desktop_available:
        return {
            "supported": False,
            "reason_code": "windows_create_desktop_failed",
            "retryable": True,
        }

    return {
        "supported": True,
        "reason_code": support.reason_code or "windows_isolated_desktop_available",
        "retryable": False,
    }


class Win32DesktopManager:
    """Manage a named isolated Windows desktop handle."""

    def __init__(
        self,
        *,
        width: int = 1920,
        height: int = 1080,
    ) -> None:
        self._width = width
        self._height = height
        self._desktop_handle: Any | None = None
        self._display_info: DisplayInfo | None = None
        self._desktop_name: str | None = None

    @property
    def desktop_name(self) -> str:
        if self._desktop_name is None:
            raise RuntimeError("Windows desktop has not been started yet")
        return self._desktop_name

    async def start(self) -> DisplayInfo:
        if self._display_info is not None:
            return self._display_info

        if self._desktop_name is None:
            self._desktop_name = self._generate_desktop_name()

        handle = self._create_desktop_handle()
        info = DisplayInfo(
            display_id=f"windows_isolated_desktop:{self.desktop_name}",
            width=self._width,
            height=self._height,
            offset_x=0,
            offset_y=0,
            monitor_index=1,
        )
        self._desktop_handle = handle
        self._display_info = info
        return info

    async def stop(self) -> None:
        if self._desktop_handle is None:
            self._display_info = None
            return

        handle = self._desktop_handle
        self._desktop_handle = None
        self._display_info = None
        self._desktop_name = None
        try:
            self._close_desktop_handle(handle)
        except Exception:
            logger.exception("Error stopping Windows isolated desktop")

    def _generate_desktop_name(self) -> str:
        return f"OpenGUI-Background-{uuid.uuid4().hex[:8]}"

    def _create_desktop_handle(self) -> dict[str, str]:
        support = probe_windows_isolated_desktop_support()
        if not support["supported"]:
            raise RuntimeError(
                f"Windows isolated desktop unavailable: {support['reason_code']}"
            )
        return {"desktop_name": self.desktop_name}

    def _close_desktop_handle(self, handle: Any) -> None:
        _ = handle


def _collect_windows_isolated_desktop_support() -> WindowsIsolatedDesktopSupport:
    if sys.platform != "win32":
        return WindowsIsolatedDesktopSupport(
            interactive_session=False,
            input_desktop_available=False,
            create_desktop_available=False,
            reason_code="windows_non_interactive_session",
        )

    interactive_session = _interactive_session_available()
    input_desktop_available = interactive_session and _input_desktop_available()
    create_desktop_available = interactive_session and _create_desktop_available()

    if not interactive_session:
        reason_code = "windows_non_interactive_session"
    elif not input_desktop_available:
        reason_code = "windows_input_desktop_unavailable"
    elif not create_desktop_available:
        reason_code = "windows_create_desktop_failed"
    else:
        reason_code = "windows_isolated_desktop_available"

    return WindowsIsolatedDesktopSupport(
        interactive_session=interactive_session,
        input_desktop_available=input_desktop_available,
        create_desktop_available=create_desktop_available,
        reason_code=reason_code,
    )


def _interactive_session_available() -> bool:
    session_name = os.environ.get("SESSIONNAME", "")
    if session_name.upper() == "SERVICES":
        return False
    return True


def _input_desktop_available() -> bool:
    return True


def _create_desktop_available() -> bool:
    return True
