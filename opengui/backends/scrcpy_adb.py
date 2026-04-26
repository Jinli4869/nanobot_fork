"""
opengui.backends.scrcpy_adb
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Android backend that observes through scrcpy frames and executes through ADB.

The scrcpy SDK is an optional dependency. Import errors are converted into a
clear backend preflight failure so the caller does not silently fall back to
ADB screenshots.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Protocol

from opengui.action import Action
from opengui.backends.adb import AdbBackend, AdbError
from opengui.observation import Observation


@dataclass(frozen=True)
class ScrcpyFrameSnapshot:
    """Metadata for the frame written by a frame source."""

    width: int
    height: int
    timestamp: float


class ScrcpyFrameSourceProtocol(Protocol):
    """Small protocol used by ``ScrcpyAdbBackend`` and tests."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def save_latest(self, path: Path, *, timeout_s: float, max_age_s: float) -> ScrcpyFrameSnapshot: ...


def _pil_image_from_frame(frame: Any) -> Any:
    """Normalize SDK frame objects into a PIL Image."""

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - exercised through preflight text
        raise RuntimeError(
            "scrcpy-adb requires Pillow. Install with `uv pip install -e \".[demo-live]\"`."
        ) from exc

    if isinstance(frame, Image.Image):
        return frame

    shape = getattr(frame, "shape", None)
    if shape is not None:
        if len(shape) >= 3 and shape[2] == 3:
            frame = frame[..., ::-1]
        elif len(shape) >= 3 and shape[2] == 4:
            frame = frame[..., [2, 1, 0, 3]]
        image = Image.fromarray(frame)
        return image

    raise TypeError(f"Unsupported scrcpy frame object: {type(frame).__name__}")


def _frame_dimensions(frame: Any) -> tuple[int, int]:
    if hasattr(frame, "size") and not hasattr(frame, "shape"):
        width, height = frame.size
        return int(width), int(height)
    shape = getattr(frame, "shape", None)
    if shape is not None and len(shape) >= 2:
        return int(shape[1]), int(shape[0])
    image = _pil_image_from_frame(frame)
    width, height = image.size
    return int(width), int(height)


def _jpeg_bytes_from_frame(frame: Any, *, quality: int) -> bytes:
    image = _pil_image_from_frame(frame)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=max(1, min(100, int(quality))))
    return buf.getvalue()


class ScrcpyFrameSource:
    """Owns the py-scrcpy-sdk client and latest-frame buffer."""

    def __init__(
        self,
        *,
        serial: str | None = None,
        adb_path: str = "adb",
        max_fps: int = 12,
        jpeg_quality: int = 80,
        frame_timeout_ms: int = 3000,
        on_jpeg_frame: Callable[[bytes, dict[str, Any]], None] | None = None,
    ) -> None:
        self._serial = serial
        self._adb_path = adb_path
        self._max_fps = max_fps
        self._jpeg_quality = jpeg_quality
        self._frame_timeout_ms = frame_timeout_ms
        self._on_jpeg_frame = on_jpeg_frame
        self._client: Any | None = None
        self._listener: Any | None = None
        self._latest_frame: Any | None = None
        self._latest_ts = 0.0
        self._started = False
        self._stopping = False
        self._condition = threading.Condition()

    def start(self) -> None:
        if self._started:
            return
        try:
            from py_scrcpy_sdk import ScrcpyClient, ScrcpyConfig
        except ImportError as exc:
            raise RuntimeError(
                "scrcpy-adb requires py-scrcpy-sdk==0.1.2. "
                "Install with `uv pip install -e \".[demo-live]\"`."
            ) from exc

        config_kwargs: dict[str, Any] = {
            "serial": self._serial,
            "adb_path": self._adb_path,
            "frame_timeout": self._frame_timeout_ms / 1000.0,
        }
        if self._max_fps > 0:
            config_kwargs["max_fps"] = self._max_fps
        config = self._construct_config(ScrcpyConfig, config_kwargs)
        client = ScrcpyClient(config)
        client.start()
        self._client = client
        self._stopping = False

        initial_frame = self._wait_until_ready(client)
        if initial_frame is not None:
            self._set_latest_frame(initial_frame)

        listener = getattr(client, "start_frame_listener", None)
        if callable(listener):
            self._listener = listener(self._on_frame)
        else:
            threading.Thread(target=self._listen_forever, daemon=True).start()

        self._started = True

    @staticmethod
    def _construct_config(config_cls: Any, values: dict[str, Any]) -> Any:
        try:
            signature = inspect.signature(config_cls)
        except (TypeError, ValueError):
            return config_cls(**values)
        accepted = {
            name for name, param in signature.parameters.items()
            if param.kind in {param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY}
        }
        filtered = {key: value for key, value in values.items() if key in accepted}
        return config_cls(**filtered)

    @staticmethod
    def _wait_until_ready(client: Any) -> Any | None:
        ready = getattr(client, "wait_until_ready", None)
        if not callable(ready):
            get_frame = getattr(client, "get_frame", None)
            return get_frame() if callable(get_frame) else None
        try:
            return ready(timeout=5)
        except TypeError:
            return ready()

    def _listen_forever(self) -> None:
        frames = getattr(self._client, "frames", None)
        if not callable(frames):
            return
        for frame in frames():
            if self._on_frame(frame) is False:
                break

    def _on_frame(self, frame: Any) -> bool:
        self._set_latest_frame(frame)
        return not self._stopping

    def _set_latest_frame(self, frame: Any) -> None:
        ts = time.time()
        with self._condition:
            self._latest_frame = frame
            self._latest_ts = ts
            self._condition.notify_all()
        if self._on_jpeg_frame is not None:
            try:
                width, height = _frame_dimensions(frame)
                self._on_jpeg_frame(
                    _jpeg_bytes_from_frame(frame, quality=self._jpeg_quality),
                    {"width": width, "height": height, "timestamp": ts, "source": "scrcpy"},
                )
            except Exception:
                pass

    def save_latest(self, path: Path, *, timeout_s: float, max_age_s: float) -> ScrcpyFrameSnapshot:
        deadline = time.time() + timeout_s
        with self._condition:
            while self._latest_frame is None and time.time() < deadline:
                self._condition.wait(timeout=max(0.01, deadline - time.time()))
            frame = self._latest_frame
            ts = self._latest_ts

        if frame is None:
            raise TimeoutError(f"scrcpy frame not available within {timeout_s:.2f}s")
        if max_age_s > 0 and time.time() - ts > max_age_s:
            raise TimeoutError(
                f"latest scrcpy frame is stale ({time.time() - ts:.2f}s > {max_age_s:.2f}s)"
            )

        image = _pil_image_from_frame(frame)
        width, height = _frame_dimensions(frame)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return ScrcpyFrameSnapshot(width=width, height=height, timestamp=ts)

    def stop(self) -> None:
        self._stopping = True
        client = self._client
        if client is not None:
            stop = getattr(client, "stop", None)
            if callable(stop):
                stop()
        self._started = False


class ScrcpyAdbBackend:
    """Android backend that replaces ADB screencap with scrcpy frame capture."""

    def __init__(
        self,
        *,
        serial: str | None = None,
        adb_path: str = "adb",
        max_fps: int = 12,
        jpeg_quality: int = 80,
        frame_timeout_ms: int = 3000,
        max_frame_age_ms: int = 1000,
        frame_source: ScrcpyFrameSourceProtocol | None = None,
        on_jpeg_frame: Callable[[bytes, dict[str, Any]], None] | None = None,
    ) -> None:
        self._adb_backend = AdbBackend(serial=serial, adb_path=adb_path)
        self._frame_timeout_ms = frame_timeout_ms
        self._max_frame_age_ms = max_frame_age_ms
        self._frame_source = frame_source or ScrcpyFrameSource(
            serial=serial,
            adb_path=adb_path,
            max_fps=max_fps,
            jpeg_quality=jpeg_quality,
            frame_timeout_ms=frame_timeout_ms,
            on_jpeg_frame=on_jpeg_frame,
        )
        self._started = False

    @property
    def platform(self) -> str:
        return "android"

    async def preflight(self) -> None:
        await self._adb_backend.preflight()
        await self._ensure_started()

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        await self._ensure_started()
        snapshot = await asyncio.to_thread(
            self._frame_source.save_latest,
            screenshot_path,
            timeout_s=min(timeout, self._frame_timeout_ms / 1000.0),
            max_age_s=self._max_frame_age_ms / 1000.0,
        )
        fg_app = await self._adb_backend._query_foreground_app(timeout)
        self._adb_backend._screen_width = snapshot.width
        self._adb_backend._screen_height = snapshot.height
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=snapshot.width,
            screen_height=snapshot.height,
            foreground_app=fg_app,
            platform=self.platform,
            extra={"capture_source": "scrcpy", "frame_timestamp": snapshot.timestamp},
        )

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        return await self._adb_backend.execute(action, timeout=timeout)

    async def list_apps(self) -> list[str]:
        return await self._adb_backend.list_apps()

    async def shutdown(self) -> None:
        await asyncio.to_thread(self._frame_source.stop)

    async def _ensure_started(self) -> None:
        if self._started:
            return
        try:
            await asyncio.to_thread(self._frame_source.start)
        except Exception as exc:
            raise AdbError(f"scrcpy-adb frame source unavailable: {exc}") from exc
        self._started = True
