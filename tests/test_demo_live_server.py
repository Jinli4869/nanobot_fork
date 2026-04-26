from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from demo.live_server import (
    IOS_FRAME_SOURCE,
    IosMjpegFrameSource,
    LiveRunManager,
    create_app,
    iter_mjpeg_frames_from_chunks,
)
from nanobot.config.schema import Config


class FakeRuntime:
    def __init__(self, captured: dict[str, Any]) -> None:
        self.captured = captured
        self.closed = False

    async def process_direct(self, content: str, **kwargs: Any) -> Any:
        self.captured["prompt"] = content
        await kwargs["on_event"]({
            "type": "gui_step",
            "event": {
                "step_index": 0,
                "action": {"action_type": "tap", "x": 1, "y": 2},
                "model_output": "tap",
            },
        })
        await kwargs["on_event"]({
            "type": "tool_call",
            "tool": "gui_task",
            "arguments": {"task": content},
        })
        await kwargs["on_event"]({
            "type": "tool_result",
            "tool": "gui_task",
            "result": '{"success": true, "summary": "ok", "steps_taken": 1}',
        })
        return type("Result", (), {"content": "done"})()

    async def close_mcp(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_live_run_manager_streams_agent_and_gui_events(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_runtime_factory(config: Config, run: Any) -> FakeRuntime:
        captured["workspace"] = config.workspace_path
        captured["backend"] = config.gui.backend if config.gui else None
        return FakeRuntime(captured)

    manager = LiveRunManager(
        runtime_factory=fake_runtime_factory,
        live_workspace=tmp_path / "live-workspace",
    )
    run = await manager.start_run(task="open settings", serial="emulator-5554")

    seen = []
    for _ in range(6):
        item = await asyncio.wait_for(run.queue.get(), timeout=2)
        if item.kind == "json":
            seen.append(item.payload["type"])
        if item.payload.get("type") == "run_complete":
            break

    assert "run_started" in seen
    assert "gui_step" in seen
    assert "tool_call" in seen
    assert "tool_result" in seen
    assert "run_complete" in seen
    assert captured["workspace"] == tmp_path / "live-workspace"
    assert captured["backend"] == "adb"
    assert "第一步必须调用 gui_task" in captured["prompt"]
    assert "backend 必须是 adb" in captured["prompt"]
    assert "用户任务：open settings" in captured["prompt"]


@pytest.mark.asyncio
async def test_live_run_manager_keeps_gui_backend_selectable(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_runtime_factory(config: Config, run: Any) -> FakeRuntime:
        captured["backend"] = config.gui.backend if config.gui else None
        return FakeRuntime(captured)

    manager = LiveRunManager(
        runtime_factory=fake_runtime_factory,
        live_workspace=tmp_path / "live-workspace",
    )
    run = await manager.start_run(
        task="open settings",
        serial="emulator-5554",
        gui_backend="scrcpy-adb",
    )

    while True:
        item = await asyncio.wait_for(run.queue.get(), timeout=2)
        if item.kind == "json" and item.payload.get("type") == "run_complete":
            break

    assert captured["backend"] == "scrcpy-adb"
    assert "backend 必须是 scrcpy-adb" in captured["prompt"]


@pytest.mark.asyncio
async def test_live_run_manager_supports_ios_backend(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_runtime_factory(config: Config, run: Any) -> FakeRuntime:
        captured["backend"] = config.gui.backend if config.gui else None
        return FakeRuntime(captured)

    manager = LiveRunManager(
        runtime_factory=fake_runtime_factory,
        live_workspace=tmp_path / "live-workspace",
    )
    run = await manager.start_run(
        task="open settings",
        platform="ios",
        serial=None,
        gui_backend="ios",
    )

    while True:
        item = await asyncio.wait_for(run.queue.get(), timeout=2)
        if item.kind == "json" and item.payload.get("type") == "run_complete":
            break

    assert captured["backend"] == "ios"
    assert "iOS demo 执行约束" in captured["prompt"]
    assert "WebDriverAgent" in captured["prompt"]


@pytest.mark.asyncio
async def test_mjpeg_parser_extracts_split_jpeg_frames() -> None:
    frame_a = b"\xff\xd8frame-a\xff\xd9"
    frame_b = b"\xff\xd8frame-b\xff\xd9"

    async def chunks():
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame_a[:4]
        yield frame_a[4:] + b"\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        yield frame_b[:5]
        yield frame_b[5:] + b"\r\n--frame--\r\n"

    frames = [frame async for frame in iter_mjpeg_frames_from_chunks(chunks())]

    assert frames == [frame_a, frame_b]


@pytest.mark.asyncio
async def test_ios_mjpeg_frame_source_emits_metadata_and_stops() -> None:
    jpeg = _jpeg_bytes(width=3, height=2)
    captured: list[tuple[bytes, dict[str, Any]]] = []
    source: IosMjpegFrameSource

    async def chunks():
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg
        yield b"\r\n--frame--\r\n"

    def on_frame(frame: bytes, metadata: dict[str, Any]) -> None:
        captured.append((frame, metadata))
        source.stop()

    source = IosMjpegFrameSource(
        mjpeg_url="http://127.0.0.1:9100",
        frame_timeout_ms=100,
        on_jpeg_frame=on_frame,
        stream_factory=chunks,
    )

    await source.run()

    assert captured[0][0] == jpeg
    assert captured[0][1]["source"] == IOS_FRAME_SOURCE
    assert captured[0][1]["platform"] == "ios"
    assert captured[0][1]["width"] == 3
    assert captured[0][1]["height"] == 2


@pytest.mark.asyncio
async def test_ios_mjpeg_frame_source_times_out_without_frame() -> None:
    async def chunks():
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        await asyncio.sleep(0.05)

    source = IosMjpegFrameSource(
        mjpeg_url="http://127.0.0.1:9100",
        frame_timeout_ms=1,
        on_jpeg_frame=lambda _frame, _metadata: None,
        stream_factory=chunks,
    )

    with pytest.raises(TimeoutError, match="iOS MJPEG frame not available"):
        await source.run()


def test_live_frame_preview_serves_ios_mjpeg_source() -> None:
    jpeg = _jpeg_bytes(width=4, height=5)

    class FakeIosMjpegFrameSource:
        def __init__(self, *, on_jpeg_frame: Any, **_: Any) -> None:
            self._on_jpeg_frame = on_jpeg_frame
            self.stopped = False

        async def run(self) -> None:
            self._on_jpeg_frame(
                jpeg,
                {
                    "width": 4,
                    "height": 5,
                    "timestamp": 1.0,
                    "source": IOS_FRAME_SOURCE,
                    "platform": "ios",
                },
            )
            await asyncio.sleep(0.01)

        def stop(self) -> None:
            self.stopped = True

    app = create_app(ios_mjpeg_source_factory=FakeIosMjpegFrameSource)
    client = TestClient(app)

    with client.websocket_connect(f"/api/live/frames?source={IOS_FRAME_SOURCE}") as websocket:
        metadata = websocket.receive_json()
        frame = websocket.receive_bytes()

    assert metadata["type"] == "frame_meta"
    assert metadata["source"] == IOS_FRAME_SOURCE
    assert metadata["platform"] == "ios"
    assert metadata["width"] == 4
    assert metadata["height"] == 5
    assert frame == jpeg


def _jpeg_bytes(*, width: int, height: int) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color=(255, 0, 0)).save(buf, format="JPEG")
    return buf.getvalue()
