"""macOS virtual display manager backed by CGVirtualDisplay-style APIs.

This module keeps all macOS-specific runtime discovery lazy so Linux test
collection remains safe even when PyObjC is not installed.
"""

from __future__ import annotations

import ctypes
import dataclasses
import logging
import platform
from typing import Any

from opengui.backends.virtual_display import DisplayInfo

logger = logging.getLogger(__name__)

_MIN_SUPPORTED_MACOS_MAJOR = 14


@dataclasses.dataclass(frozen=True)
class MacOSVirtualDisplaySupport:
    major_version: int
    pyobjc_available: bool
    virtual_display_api_available: bool
    screen_recording_allowed: bool
    accessibility_allowed: bool
    event_post_allowed: bool


def probe_macos_virtual_display_support() -> dict[str, object]:
    support = _collect_macos_support()
    if support.major_version < _MIN_SUPPORTED_MACOS_MAJOR:
        return {
            "supported": False,
            "reason_code": "macos_version_unsupported",
            "retryable": False,
        }
    if not support.pyobjc_available:
        return {
            "supported": False,
            "reason_code": "macos_pyobjc_missing",
            "retryable": True,
        }
    if not support.virtual_display_api_available:
        return {
            "supported": False,
            "reason_code": "macos_virtual_display_api_missing",
            "retryable": False,
        }
    if not support.screen_recording_allowed:
        return {
            "supported": False,
            "reason_code": "macos_screen_recording_denied",
            "retryable": True,
        }
    if not support.accessibility_allowed:
        return {
            "supported": False,
            "reason_code": "macos_accessibility_denied",
            "retryable": True,
        }
    if not support.event_post_allowed:
        return {
            "supported": False,
            "reason_code": "macos_event_post_denied",
            "retryable": True,
        }
    return {
        "supported": True,
        "reason_code": "macos_virtual_display_available",
        "retryable": False,
    }


class CGVirtualDisplayManager:
    """Manage a macOS background target surface."""

    def __init__(
        self,
        *,
        width: int = 1440,
        height: int = 900,
        offset_x: int = 0,
        offset_y: int = 0,
        monitor_index: int = 2,
        display_name: str = "OpenGUI Background Display",
    ) -> None:
        self._width = width
        self._height = height
        self._offset_x = offset_x
        self._offset_y = offset_y
        self._monitor_index = monitor_index
        self._display_name = display_name
        self._display_handle: Any | None = None
        self._display_info: DisplayInfo | None = None

    async def start(self) -> DisplayInfo:
        if self._display_info is not None:
            return self._display_info
        handle = self._create_virtual_display()
        info = self._build_display_info(handle)
        self._display_handle = handle
        self._display_info = info
        return info

    async def stop(self) -> None:
        if self._display_handle is None:
            self._display_info = None
            return
        handle = self._display_handle
        self._display_handle = None
        self._display_info = None
        try:
            self._destroy_virtual_display(handle)
        except Exception:
            logger.exception("Error stopping macOS virtual display")

    def _create_virtual_display(self) -> dict[str, Any]:
        support = probe_macos_virtual_display_support()
        if not support["supported"]:
            raise RuntimeError(
                f"macOS isolated display unavailable: {support['reason_code']}"
            )
        return {
            "display_id": "macos:opengui-background",
            "width": self._width,
            "height": self._height,
            "offset_x": self._offset_x,
            "offset_y": self._offset_y,
            "monitor_index": self._monitor_index,
            "name": self._display_name,
        }

    def _build_display_info(self, handle: Any) -> DisplayInfo:
        if isinstance(handle, DisplayInfo):
            return handle
        return DisplayInfo(
            display_id=str(handle["display_id"]),
            width=int(handle["width"]),
            height=int(handle["height"]),
            offset_x=int(handle.get("offset_x", 0)),
            offset_y=int(handle.get("offset_y", 0)),
            monitor_index=int(handle.get("monitor_index", 1)),
        )

    def _destroy_virtual_display(self, handle: Any) -> None:
        _ = handle


def _collect_macos_support() -> MacOSVirtualDisplaySupport:
    major_version = _macos_major_version()
    objc_module, quartz_module = _load_pyobjc_modules()
    pyobjc_available = objc_module is not None and quartz_module is not None

    virtual_display_api_available = False
    screen_recording_allowed = False
    accessibility_allowed = False
    event_post_allowed = False

    if pyobjc_available:
        virtual_display_api_available = _has_virtual_display_runtime(objc_module)
        screen_recording_allowed = _screen_recording_allowed(quartz_module)
        accessibility_allowed = _accessibility_allowed(quartz_module)
        event_post_allowed = _event_post_allowed(quartz_module)

    return MacOSVirtualDisplaySupport(
        major_version=major_version,
        pyobjc_available=pyobjc_available,
        virtual_display_api_available=virtual_display_api_available,
        screen_recording_allowed=screen_recording_allowed,
        accessibility_allowed=accessibility_allowed,
        event_post_allowed=event_post_allowed,
    )


def _macos_major_version() -> int:
    version = platform.mac_ver()[0]
    if not version:
        return 0
    major, *_ = version.split(".")
    try:
        return int(major)
    except ValueError:
        return 0


def _load_pyobjc_modules() -> tuple[Any | None, Any | None]:
    try:
        import objc  # type: ignore[import-not-found]
        import Quartz  # type: ignore[import-not-found]
    except ImportError:
        return None, None
    return objc, Quartz


def _has_virtual_display_runtime(objc_module: Any) -> bool:
    if not hasattr(objc_module, "lookUpClass"):
        return False
    try:
        objc_module.lookUpClass("CGVirtualDisplay")
        objc_module.lookUpClass("CGVirtualDisplayMode")
    except Exception:
        return False
    return True


def _screen_recording_allowed(quartz_module: Any) -> bool:
    check = getattr(quartz_module, "CGPreflightScreenCaptureAccess", None)
    if check is None:
        return False
    try:
        return bool(check())
    except Exception:
        return False


def _accessibility_allowed(quartz_module: Any) -> bool:
    check = getattr(quartz_module, "AXIsProcessTrusted", None)
    if check is not None:
        try:
            return bool(check())
        except Exception:
            pass
    return _accessibility_allowed_via_ctypes()


def _accessibility_allowed_via_ctypes() -> bool:
    try:
        application_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
    except Exception:
        return False

    check = getattr(application_services, "AXIsProcessTrusted", None)
    if check is None:
        return False
    try:
        check.restype = ctypes.c_bool
        return bool(check())
    except Exception:
        return False


def _event_post_allowed(quartz_module: Any) -> bool:
    check = getattr(quartz_module, "CGPreflightPostEventAccess", None)
    if check is None:
        return False
    try:
        return bool(check())
    except Exception:
        return False
