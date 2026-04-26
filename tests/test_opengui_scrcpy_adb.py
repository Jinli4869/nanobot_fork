from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import opengui.cli as cli
from nanobot.config.schema import GuiConfig
from opengui.action import Action
from opengui.backends.scrcpy_adb import (
    ScrcpyAdbBackend,
    ScrcpyFrameSnapshot,
    _pil_image_from_frame,
)


class FakeFrameSource:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def save_latest(self, path: Path, *, timeout_s: float, max_age_s: float) -> ScrcpyFrameSnapshot:
        Image.new("RGB", (320, 640), color=(10, 20, 30)).save(path)
        return ScrcpyFrameSnapshot(width=320, height=640, timestamp=123.0)


class FakeAdbDelegate:
    def __init__(self) -> None:
        self.executed = []
        self._screen_width = 0
        self._screen_height = 0

    async def preflight(self) -> None:
        return None

    async def _query_foreground_app(self, timeout: float) -> str:
        return "com.example.app"

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        self.executed.append(action)
        return "delegated"

    async def list_apps(self) -> list[str]:
        return ["com.example.app"]


@pytest.mark.asyncio
async def test_scrcpy_adb_observe_writes_frame_and_reports_metadata(tmp_path: Path) -> None:
    frame_source = FakeFrameSource()
    backend = ScrcpyAdbBackend(frame_source=frame_source)
    fake_adb = FakeAdbDelegate()
    backend._adb_backend = fake_adb  # type: ignore[assignment]

    screenshot_path = tmp_path / "screen.png"
    observation = await backend.observe(screenshot_path)

    assert frame_source.started is True
    assert screenshot_path.exists()
    assert observation.screen_width == 320
    assert observation.screen_height == 640
    assert observation.foreground_app == "com.example.app"
    assert observation.extra["capture_source"] == "scrcpy"
    assert fake_adb._screen_width == 320
    assert fake_adb._screen_height == 640


@pytest.mark.asyncio
async def test_scrcpy_adb_execute_and_list_apps_delegate_to_adb() -> None:
    backend = ScrcpyAdbBackend(frame_source=FakeFrameSource())
    fake_adb = FakeAdbDelegate()
    backend._adb_backend = fake_adb  # type: ignore[assignment]

    action = Action(action_type="tap", x=1, y=2)
    assert await backend.execute(action) == "delegated"
    assert fake_adb.executed == [action]
    assert await backend.list_apps() == ["com.example.app"]


def test_gui_config_accepts_scrcpy_adb_backend_and_camel_case_fields() -> None:
    config = GuiConfig.model_validate({
        "backend": "scrcpy-adb",
        "scrcpy": {
            "maxFps": 8,
            "jpegQuality": 70,
            "frameTimeoutMs": 1500,
            "maxFrameAgeMs": 500,
        },
    })

    assert config.backend == "scrcpy-adb"
    assert config.scrcpy.max_fps == 8
    assert config.scrcpy.jpeg_quality == 70
    assert config.scrcpy.frame_timeout_ms == 1500
    assert config.scrcpy.max_frame_age_ms == 500


def test_gui_config_accepts_ios_mjpeg_fields() -> None:
    config = GuiConfig.model_validate({
        "backend": "ios",
        "ios": {
            "wdaUrl": "http://localhost:8100",
            "mjpegUrl": "http://127.0.0.1:9100",
            "mjpegFrameTimeoutMs": 2500,
        },
    })

    assert config.ios.wda_url == "http://localhost:8100"
    assert config.ios.mjpeg_url == "http://127.0.0.1:9100"
    assert config.ios.mjpeg_frame_timeout_ms == 2500


def test_cli_builds_scrcpy_adb_backend_from_config() -> None:
    config = cli.CliConfig(
        provider=cli.ProviderConfig(base_url="http://localhost:1/v1", model="m"),
        adb=cli.AdbConfig(serial="emulator-5554", adb_path="/tmp/adb"),
        scrcpy=cli.ScrcpyConfig(
            max_fps=7,
            jpeg_quality=65,
            frame_timeout_ms=1200,
            max_frame_age_ms=400,
        ),
    )

    backend = cli.build_backend("scrcpy-adb", config)

    assert isinstance(backend, ScrcpyAdbBackend)
    assert backend._frame_timeout_ms == 1200
    assert backend._max_frame_age_ms == 400
    assert backend._frame_source._adb_path == "/tmp/adb"  # type: ignore[attr-defined]
    assert backend._frame_source._frame_timeout_ms == 1200  # type: ignore[attr-defined]


def test_scrcpy_numpy_frames_are_converted_from_bgr_to_rgb() -> None:
    np = pytest.importorskip("numpy")
    frame = np.array([[[0, 0, 255]]], dtype=np.uint8)

    image = _pil_image_from_frame(frame)

    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (255, 0, 0)
