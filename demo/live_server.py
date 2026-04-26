#!/usr/bin/env python3
"""Sidecar server for the real-time OpenGUI Android demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Literal
from uuid import uuid4

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.cli.commands import _make_provider, _resolve_gui_runtime
from nanobot.config.loader import load_config
from nanobot.config.paths import get_cron_dir
from nanobot.config.schema import Config, GuiConfig
from nanobot.cron.service import CronService
from nanobot.session.manager import SessionManager

DEMO_ROOT = Path(__file__).resolve().parent
DEFAULT_LIVE_WORKSPACE = Path(tempfile.gettempdir()) / "nanobot_live_demo_workspace"
ANDROID_FRAME_SOURCE = "android-scrcpy"
IOS_FRAME_SOURCE = "ios-mjpeg"
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


async def iter_mjpeg_frames_from_chunks(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Extract JPEG frames from an MJPEG byte stream."""
    buffer = bytearray()
    async for chunk in chunks:
        if not chunk:
            continue
        buffer.extend(chunk)
        while True:
            start = buffer.find(JPEG_SOI)
            if start < 0:
                if len(buffer) > 1:
                    del buffer[:-1]
                break
            end = buffer.find(JPEG_EOI, start + len(JPEG_SOI))
            if end < 0:
                if start > 0:
                    del buffer[:start]
                break
            frame_end = end + len(JPEG_EOI)
            frame = bytes(buffer[start:frame_end])
            del buffer[:frame_end]
            yield frame


class IosMjpegFrameSource:
    """Reads WebDriverAgent's MJPEG stream and emits JPEG frames."""

    def __init__(
        self,
        *,
        mjpeg_url: str,
        frame_timeout_ms: int = 3000,
        on_jpeg_frame: Callable[[bytes, dict[str, Any]], None],
        stream_factory: Callable[[], AsyncIterator[bytes]] | None = None,
    ) -> None:
        self._mjpeg_url = mjpeg_url
        self._frame_timeout_s = max(frame_timeout_ms, 1) / 1000.0
        self._on_jpeg_frame = on_jpeg_frame
        self._stream_factory = stream_factory
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        self._stopped = False
        frame_iter = iter_mjpeg_frames_from_chunks(self._chunk_stream())
        try:
            while not self._stopped:
                try:
                    frame = await asyncio.wait_for(
                        anext(frame_iter),
                        timeout=self._frame_timeout_s,
                    )
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(
                        f"iOS MJPEG frame not available within {self._frame_timeout_s:.2f}s"
                    ) from exc
                except StopAsyncIteration:
                    return
                width, height = _jpeg_dimensions(frame)
                self._on_jpeg_frame(
                    frame,
                    {
                        "width": width,
                        "height": height,
                        "timestamp": time.time(),
                        "source": IOS_FRAME_SOURCE,
                        "platform": "ios",
                    },
                )
        finally:
            await frame_iter.aclose()

    async def _chunk_stream(self) -> AsyncIterator[bytes]:
        if self._stream_factory is not None:
            async for chunk in self._stream_factory():
                yield chunk
            return

        timeout = httpx.Timeout(
            connect=self._frame_timeout_s,
            read=None,
            write=self._frame_timeout_s,
            pool=self._frame_timeout_s,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", self._mjpeg_url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if self._stopped:
                        return
                    yield chunk


def _jpeg_dimensions(frame: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "iOS MJPEG live preview requires Pillow. Install with "
            '`uv pip install -e ".[demo-live]"`.'
        ) from exc
    with Image.open(BytesIO(frame)) as image:
        width, height = image.size
    return int(width), int(height)


class LiveRunRequest(BaseModel):
    task: str = Field(min_length=1)
    platform: Literal["android", "ios"] = "android"
    serial: str | None = None
    gui_backend: Literal["adb", "scrcpy-adb", "ios"] = "adb"

    @model_validator(mode="after")
    def _validate_platform_backend(self) -> "LiveRunRequest":
        if self.platform == "ios" and self.gui_backend != "ios":
            raise ValueError("iOS live runs require gui_backend='ios'")
        if self.platform == "android" and self.gui_backend not in {"adb", "scrcpy-adb"}:
            raise ValueError("Android live runs require gui_backend='adb' or 'scrcpy-adb'")
        return self


class LiveRunResponse(BaseModel):
    run_id: str
    status: str


@dataclass
class LiveQueueItem:
    kind: str
    payload: Any


@dataclass
class LiveRun:
    run_id: str
    task: str
    platform: Literal["android", "ios"]
    serial: str | None
    gui_backend: Literal["adb", "scrcpy-adb", "ios"] = "adb"
    queue: asyncio.Queue[LiveQueueItem] = field(default_factory=asyncio.Queue)
    task_handle: asyncio.Task[Any] | None = None
    loop: asyncio.AbstractEventLoop | None = None
    closed: bool = False

    def publish_json_threadsafe(self, payload: dict[str, Any]) -> None:
        self._publish_threadsafe(LiveQueueItem("json", _json_safe(payload)))

    def _publish_threadsafe(self, item: LiveQueueItem) -> None:
        if self.closed or self.loop is None:
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, item)


class LiveRunManager:
    """Owns active demo runs and event fanout queues."""

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        runtime_factory: Callable[[Config, LiveRun], AgentLoop] | None = None,
        live_workspace: Path | None = None,
    ) -> None:
        self._config_path = config_path
        self._runtime_factory = runtime_factory or self._build_runtime
        self._live_workspace = live_workspace or DEFAULT_LIVE_WORKSPACE
        self._runs: dict[str, LiveRun] = {}

    async def list_devices(self) -> list[dict[str, str]]:
        proc = await asyncio.create_subprocess_exec(
            "adb",
            "devices",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "adb devices failed")
        devices: list[dict[str, str]] = []
        for line in stdout.decode(errors="replace").splitlines():
            if "\t" not in line or line.startswith("List of"):
                continue
            serial, state = line.split("\t", 1)
            devices.append({"serial": serial.strip(), "state": state.strip()})
        return devices

    async def start_run(
        self,
        *,
        task: str,
        platform: Literal["android", "ios"] = "android",
        serial: str | None,
        gui_backend: Literal["adb", "scrcpy-adb", "ios"] = "adb",
    ) -> LiveRun:
        run = LiveRun(
            run_id=uuid4().hex,
            task=task,
            platform=platform,
            serial=serial,
            gui_backend=gui_backend,
            loop=asyncio.get_running_loop(),
        )
        self._runs[run.run_id] = run
        await run.queue.put(LiveQueueItem("json", {
            "type": "run_started",
            "run_id": run.run_id,
            "task": task,
            "platform": platform,
            "serial": serial,
            "gui_backend": gui_backend,
        }))
        run.task_handle = asyncio.create_task(self._execute(run), name=f"demo-live-{run.run_id}")
        return run

    async def stop_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.closed = True
        if run.task_handle and not run.task_handle.done():
            run.task_handle.cancel()
            await asyncio.gather(run.task_handle, return_exceptions=True)
        await run.queue.put(LiveQueueItem("json", {"type": "run_cancelled", "run_id": run_id}))
        self._runs.pop(run_id, None)
        return True

    def get_run(self, run_id: str) -> LiveRun | None:
        return self._runs.get(run_id)

    async def _execute(self, run: LiveRun) -> None:
        runtime: AgentLoop | None = None
        try:
            config = self._live_config(
                run.serial,
                platform=run.platform,
                gui_backend=run.gui_backend,
            )
            runtime = self._runtime_factory(config, run)

            async def on_progress(content: str, **kwargs: Any) -> None:
                await run.queue.put(LiveQueueItem("json", {
                    "type": "assistant_progress",
                    "content": content,
                    **kwargs,
                }))

            async def on_event(event: dict[str, Any]) -> None:
                await run.queue.put(LiveQueueItem("json", _json_safe(event)))

            result = await runtime.process_direct(
                self._live_task_prompt(
                    run.task,
                    platform=run.platform,
                    gui_backend=run.gui_backend,
                ),
                session_key=f"demo-live:{run.run_id}",
                channel="demo-live",
                chat_id=run.run_id,
                on_progress=on_progress,
                on_event=on_event,
            )
            await run.queue.put(LiveQueueItem("json", {
                "type": "run_complete",
                "run_id": run.run_id,
                "content": getattr(result, "content", None),
            }))
        except asyncio.CancelledError:
            await run.queue.put(LiveQueueItem("json", {"type": "run_cancelled", "run_id": run.run_id}))
            raise
        except Exception as exc:
            await run.queue.put(LiveQueueItem("json", {
                "type": "run_error",
                "run_id": run.run_id,
                "message": str(exc),
            }))
        finally:
            if runtime is not None:
                await runtime.close_mcp()

    def _live_config(
        self,
        serial: str | None,
        *,
        platform: Literal["android", "ios"] = "android",
        gui_backend: Literal["adb", "scrcpy-adb", "ios"] = "adb",
    ) -> Config:
        config = load_config(self._config_path)
        gui = config.gui or GuiConfig()
        adb = gui.adb.model_copy(update={"serial": serial}) if platform == "android" else gui.adb
        self._live_workspace.mkdir(parents=True, exist_ok=True)
        defaults = config.agents.defaults.model_copy(
            update={"workspace": str(self._live_workspace)}
        )
        agents = config.agents.model_copy(update={"defaults": defaults})
        gui = gui.model_copy(
            deep=True,
            update={
                "backend": gui_backend,
                "adb": adb,
                "enable_planner": False,
            },
        )
        return config.model_copy(deep=True, update={"gui": gui, "agents": agents})

    @staticmethod
    def _live_task_prompt(task: str, *, platform: str, gui_backend: str) -> str:
        if platform == "ios":
            return (
                "iOS demo 执行约束：第一步必须调用 gui_task 工具，backend 必须是 ios。"
                "不要使用 exec、read_file、curl WDA、截图命令或其他普通工具替代 "
                "WebDriverAgent GUI 观察和 GUI 操作。gui_task 完成后，再向用户总结结果。\n\n"
                f"用户任务：{task}"
            )
        return (
            "Android demo 执行约束：第一步必须调用 gui_task 工具，backend 必须是 "
            f"{gui_backend}。不要使用 exec、read_file、adb shell、screencap 或其他普通工具"
            "替代 GUI 观察和 GUI 操作。gui_task 完成后，再向用户总结结果。\n\n"
            f"用户任务：{task}"
        )

    @staticmethod
    def _build_runtime(config: Config, run: LiveRun) -> AgentLoop:
        provider = _make_provider(config)
        gui_provider, gui_model = _resolve_gui_runtime(config)
        cron = CronService(get_cron_dir() / "jobs.json")

        def gui_event_callback(event: dict[str, Any]) -> None:
            event_type = event.get("type") or event.get("event")
            run.publish_json_threadsafe({
                "type": f"gui_{event_type}" if event_type else "gui_event",
                "event": event,
            })

        return AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=config.workspace_path,
            model=config.agents.defaults.model,
            max_iterations=config.agents.defaults.max_tool_iterations,
            context_window_tokens=config.agents.defaults.context_window_tokens,
            web_search_config=config.tools.web.search,
            web_proxy=config.tools.web.proxy or None,
            exec_config=config.tools.exec,
            cron_service=cron,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            session_manager=SessionManager(config.workspace_path),
            mcp_servers=config.tools.mcp_servers,
            channels_config=config.channels,
            gui_config=config.gui,
            gui_provider=gui_provider,
            gui_model=gui_model,
            gui_event_callback=gui_event_callback,
        )


def _json_safe(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def create_app(
    *,
    config_path: Path | None = None,
    ios_mjpeg_source_factory: Callable[..., IosMjpegFrameSource] | None = None,
) -> FastAPI:
    app = FastAPI(title="OpenGUI live demo", version="0.1.0")
    manager = LiveRunManager(config_path=config_path)
    app.state.live_manager = manager

    @app.get("/api/live/devices")
    async def list_live_devices() -> dict[str, Any]:
        try:
            return {"devices": await manager.list_devices()}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/live/runs", response_model=LiveRunResponse)
    async def start_live_run(payload: LiveRunRequest) -> LiveRunResponse:
        run = await manager.start_run(
            task=payload.task,
            platform=payload.platform,
            serial=payload.serial,
            gui_backend=payload.gui_backend,
        )
        return LiveRunResponse(run_id=run.run_id, status="started")

    @app.delete("/api/live/runs/{run_id}")
    async def stop_live_run(run_id: str) -> dict[str, Any]:
        stopped = await manager.stop_run(run_id)
        if not stopped:
            raise HTTPException(status_code=404, detail="live run not found")
        return {"status": "cancelled", "run_id": run_id}

    @app.websocket("/api/live/runs/{run_id}/events")
    async def live_events(websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        run = manager.get_run(run_id)
        if run is None:
            await websocket.send_json({"type": "run_error", "message": "live run not found"})
            await websocket.close(code=1008)
            return
        try:
            while True:
                item = await run.queue.get()
                await websocket.send_json(item.payload)
                if item.payload.get("type") in {"run_complete", "run_error", "run_cancelled"}:
                    break
        except WebSocketDisconnect:
            return

    @app.websocket("/api/live/frames")
    async def live_frame_preview(websocket: WebSocket) -> None:
        await websocket.accept()
        source_name = websocket.query_params.get("source") or ANDROID_FRAME_SOURCE
        serial = websocket.query_params.get("serial") or None
        queue: asyncio.Queue[LiveQueueItem] = asyncio.Queue(maxsize=4)
        loop = asyncio.get_running_loop()
        config = load_config(manager._config_path)
        gui = config.gui or GuiConfig()

        def on_jpeg_frame(frame: bytes, metadata: dict[str, Any]) -> None:
            def enqueue() -> None:
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                queue.put_nowait(LiveQueueItem("json", {"type": "frame_meta", **metadata}))
                queue.put_nowait(LiveQueueItem("bytes", frame))

            loop.call_soon_threadsafe(enqueue)

        if source_name == IOS_FRAME_SOURCE:
            source = (ios_mjpeg_source_factory or IosMjpegFrameSource)(
                mjpeg_url=gui.ios.mjpeg_url,
                frame_timeout_ms=gui.ios.mjpeg_frame_timeout_ms,
                on_jpeg_frame=on_jpeg_frame,
            )
            source_task = asyncio.create_task(source.run(), name="demo-ios-mjpeg-preview")
            try:
                while True:
                    queue_task = asyncio.create_task(queue.get())
                    done, _pending = await asyncio.wait(
                        {queue_task, source_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if queue_task in done:
                        item = queue_task.result()
                        if item.kind == "bytes":
                            await websocket.send_bytes(item.payload)
                        else:
                            await websocket.send_json(item.payload)
                        continue
                    if source_task in done:
                        queue_task.cancel()
                        source_task.result()
                        break
            except WebSocketDisconnect:
                return
            except Exception as exc:
                await websocket.send_json({"type": "run_error", "message": str(exc)})
                await websocket.close(code=1011)
            finally:
                source.stop()
                if not source_task.done():
                    source_task.cancel()
                    await asyncio.gather(source_task, return_exceptions=True)
            return

        if source_name != ANDROID_FRAME_SOURCE:
            await websocket.send_json({
                "type": "run_error",
                "message": f"unsupported live frame source: {source_name}",
            })
            await websocket.close(code=1008)
            return

        try:
            from opengui.backends.scrcpy_adb import ScrcpyFrameSource

            source = ScrcpyFrameSource(
                serial=serial,
                adb_path=getattr(gui.adb, "adb_path", "adb") or "adb",
                max_fps=gui.scrcpy.max_fps,
                jpeg_quality=gui.scrcpy.jpeg_quality,
                frame_timeout_ms=gui.scrcpy.frame_timeout_ms,
                on_jpeg_frame=lambda frame, metadata: on_jpeg_frame(
                    frame,
                    {**metadata, "platform": "android"},
                ),
            )
            await asyncio.to_thread(source.start)
            while True:
                item = await queue.get()
                if item.kind == "bytes":
                    await websocket.send_bytes(item.payload)
                else:
                    await websocket.send_json(item.payload)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await websocket.send_json({"type": "run_error", "message": str(exc)})
            await websocket.close(code=1011)
        finally:
            if "source" in locals():
                await asyncio.to_thread(source.stop)

    app.mount("/css", StaticFiles(directory=str(DEMO_ROOT / "css")), name="demo-css")
    app.mount("/js", StaticFiles(directory=str(DEMO_ROOT / "js")), name="demo-js")
    app.mount("/data", StaticFiles(directory=str(DEMO_ROOT / "data")), name="demo-data")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(DEMO_ROOT / "index.html")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpenGUI real-time demo sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18880)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    uvicorn.run(create_app(config_path=args.config), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
