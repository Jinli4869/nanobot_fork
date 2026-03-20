"""Windows-specific isolated backend with explicit worker lifecycle ownership."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import pathlib
import tempfile
from typing import TYPE_CHECKING, Any

from opengui.backends import background_runtime
from opengui.backends.displays.win32desktop import Win32DesktopManager
from opengui.backends.virtual_display import DisplayInfo
from opengui.backends.windows_worker import launch_windows_worker

if TYPE_CHECKING:
    from opengui.action import Action
    from opengui.interfaces import DeviceBackend
    from opengui.observation import Observation

logger = logging.getLogger(__name__)

_BACKEND_NAME = "windows_isolated_desktop"
_NOT_STARTED_MSG = "call preflight() or use async with before observe/execute"


class WindowsIsolatedBackend:
    """Own the Windows alternate-desktop worker lifecycle for one run."""

    def __init__(
        self,
        inner: DeviceBackend,
        display_manager: Win32DesktopManager,
        run_metadata: dict[str, str] | None = None,
    ) -> None:
        self._inner = inner
        self._display_manager = display_manager
        self._display_info: DisplayInfo | None = None
        self._worker_process: Any | None = None
        self._worker_control_path: str | None = None
        self._target_display_configured = False
        self._stopped = False
        self._lease_cm: Any | None = None
        self.runtime_coordinator = background_runtime.GLOBAL_BACKGROUND_RUNTIME_COORDINATOR
        self._run_metadata = {
            "owner": "windows-isolated-backend",
            "task": "unknown",
            **(run_metadata or {}),
        }

    async def __aenter__(self) -> WindowsIsolatedBackend:
        await self.preflight()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.shutdown()

    @property
    def platform(self) -> str:
        return self._inner.platform

    async def preflight(self) -> None:
        if self._display_info is not None and not self._stopped:
            return

        self._stopped = False
        self._lease_cm = self.runtime_coordinator.lease(self._run_metadata, logger=logger)
        await self._lease_cm.__aenter__()
        try:
            self._display_info = await self._display_manager.start()
            configure_target_display = self._resolve_configure_target_display()
            if callable(configure_target_display):
                configure_target_display(self._display_info)
                self._target_display_configured = True
            await self._start_worker_session(self._display_info)
            await self._inner.preflight()
            logger.info(
                "windows isolated backend ready: owner=%s task=%s backend_name=%s display_id=%s desktop_name=%s",
                self._run_metadata.get("owner", "unknown"),
                self._run_metadata.get("task", "unknown"),
                _BACKEND_NAME,
                self._display_info.display_id,
                self._display_manager.desktop_name,
            )
        except asyncio.CancelledError:
            if self._display_info is not None:
                await self.shutdown("cancelled")
            else:
                await self._release_runtime_lease()
            raise
        except Exception:
            if self._display_info is not None:
                await self.shutdown("startup_failed")
            else:
                await self._release_runtime_lease()
            raise

    async def observe(
        self,
        screenshot_path: pathlib.Path,
        timeout: float = 5.0,
    ) -> Observation:
        self._assert_started()
        try:
            return await self._observe_via_worker(screenshot_path, timeout)
        except asyncio.CancelledError:
            await self.shutdown("cancelled")
            raise

    async def execute(
        self,
        action: Action,
        timeout: float = 5.0,
    ) -> str:
        self._assert_started()
        try:
            return await self._execute_via_worker(action, timeout)
        except asyncio.CancelledError:
            await self.shutdown("cancelled")
            raise

    async def list_apps(self) -> list[str]:
        self._assert_started()
        return await self._inner.list_apps()

    async def shutdown(self, cleanup_reason: str = "normal") -> None:
        if self._stopped:
            return

        self._stopped = True
        display_id = self._display_info.display_id if self._display_info is not None else "unknown"
        try:
            await self._stop_worker_session(cleanup_reason)
        except Exception:
            logger.exception(
                "windows isolated backend worker cleanup failed: cleanup_reason=%s backend_name=%s",
                cleanup_reason,
                _BACKEND_NAME,
            )
        try:
            await self._stop_display_manager()
        finally:
            self._clear_target_display()
            logger.info(
                "windows isolated backend cleanup: cleanup_reason=%s display_id=%s backend_name=%s",
                cleanup_reason,
                display_id,
                _BACKEND_NAME,
            )
            self._display_info = None
            await self._release_runtime_lease()

    def _assert_started(self) -> None:
        if self._display_info is None:
            raise RuntimeError(_NOT_STARTED_MSG)

    async def _start_worker_session(self, display_info: DisplayInfo) -> None:
        if self._worker_process is not None:
            return

        fd, control_path = tempfile.mkstemp(prefix="opengui-windows-worker-", suffix=".json")
        os.close(fd)
        self._worker_control_path = control_path
        self._worker_process = launch_windows_worker(
            desktop_name=self._display_manager.desktop_name,
            width=display_info.width,
            height=display_info.height,
            control_path=control_path,
        )
        logger.info(
            "windows isolated backend worker launched: backend_name=%s display_id=%s desktop_name=%s "
            "lpDesktop=%s control_path=%s",
            _BACKEND_NAME,
            display_info.display_id,
            self._display_manager.desktop_name,
            f"WinSta0\\{self._display_manager.desktop_name}",
            control_path,
        )

    async def _observe_via_worker(
        self,
        screenshot_path: pathlib.Path,
        timeout: float,
    ) -> Observation:
        return await self._inner.observe(screenshot_path, timeout)

    async def _execute_via_worker(
        self,
        action: Action,
        timeout: float,
    ) -> str:
        return await self._inner.execute(action, timeout)

    async def _stop_worker_session(self, cleanup_reason: str) -> None:
        _ = cleanup_reason
        process = self._worker_process
        self._worker_process = None
        if process is not None:
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                terminate()
            wait = getattr(process, "wait", None)
            if callable(wait):
                try:
                    result = wait(timeout=1)
                except TypeError:
                    result = wait()
                if inspect.isawaitable(result):
                    await result
        control_path = self._worker_control_path
        self._worker_control_path = None
        if control_path and os.path.exists(control_path):
            os.unlink(control_path)

    def _resolve_configure_target_display(self) -> Any | None:
        if "configure_target_display" in vars(self._inner):
            configure_target_display = vars(self._inner)["configure_target_display"]
            return configure_target_display if callable(configure_target_display) else None
        if inspect.isclass(type(self._inner)) and "configure_target_display" in vars(type(self._inner)):
            configure_target_display = getattr(self._inner, "configure_target_display", None)
            return configure_target_display if callable(configure_target_display) else None
        return None

    def _clear_target_display(self) -> None:
        configure_target_display = self._resolve_configure_target_display()
        if callable(configure_target_display) and self._target_display_configured:
            configure_target_display(None)
        self._target_display_configured = False

    async def _stop_display_manager(self) -> None:
        try:
            await self._display_manager.stop()
        except Exception:
            logger.exception("windows isolated backend display cleanup failed")

    async def _release_runtime_lease(self) -> None:
        if self._lease_cm is None:
            return
        lease_cm = self._lease_cm
        self._lease_cm = None
        await lease_cm.__aexit__(None, None, None)
