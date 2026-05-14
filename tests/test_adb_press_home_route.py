from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.agent.planner import PlanNode
from nanobot.agent.router import RouterContext, TreeRouter
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from opengui.observation import Observation
from opengui.trajectory.recorder import ExecutionPhase, TrajectoryRecorder


class _DummyTool(Tool):
    @property
    def name(self) -> str:
        return "gui_task"

    @property
    def description(self) -> str:
        return "dummy gui task"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


class _MobileGuiTool(_DummyTool):
    def __init__(self, backend: Any, trace_dir: Path) -> None:
        self._backend = backend
        self._trace_dir = trace_dir

    @property
    def mobile_native_backend(self) -> Any:
        return self._backend

    @property
    def mobile_native_trace_dir(self) -> Path:
        return self._trace_dir

    @property
    def adb_backend(self) -> Any:
        return self._backend


class _FakeAdbBackend:
    platform = "android"

    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    async def _run(self, *args: str, timeout: float = 10.0) -> str:
        del timeout
        self.commands.append(tuple(args))
        return ""

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        del timeout
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1080,
            screen_height=1920,
            foreground_app="com.android.launcher",
            platform=self.platform,
        )


class _FakeDesktopBackend:
    platform = "macos"


def _catalog_routes_for(gui_backend: str) -> list[str]:
    from nanobot.agent.capabilities import CapabilityCatalogBuilder

    registry = ToolRegistry()
    registry.register(_DummyTool())
    return [
        route.route_id
        for route in CapabilityCatalogBuilder().build(
            tool_registry=registry,
            gui_available=True,
            exec_enabled=False,
            gui_backend=gui_backend,
        ).routes
    ]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_gui_tool_exposes_android_backend_as_mobile_native(tmp_path: Path) -> None:
    from nanobot.agent.tools.gui import GuiSubagentTool

    backend = _FakeAdbBackend()
    tool = object.__new__(GuiSubagentTool)
    tool._backend = backend
    tool._workspace = tmp_path
    tool._gui_config = SimpleNamespace(artifacts_dir="gui_runs")

    assert tool.mobile_native_backend is backend
    assert tool.mobile_native_route_namespace == "adb"
    assert tool.adb_backend is backend
    assert tool.mobile_native_trace_dir == tmp_path / "gui_runs" / "mobile_native_routes"


def test_gui_tool_does_not_expose_desktop_backend_as_mobile_native(tmp_path: Path) -> None:
    from nanobot.agent.tools.gui import GuiSubagentTool

    tool = object.__new__(GuiSubagentTool)
    tool._backend = _FakeDesktopBackend()
    tool._workspace = tmp_path
    tool._gui_config = SimpleNamespace(artifacts_dir="gui_runs")

    assert tool.mobile_native_backend is None
    assert tool.mobile_native_route_namespace is None
    assert tool.adb_backend is None


def test_agent_loop_router_context_injects_mobile_native_backend(tmp_path: Path) -> None:
    from nanobot.agent.loop import AgentLoop

    backend = _FakeAdbBackend()
    loop = object.__new__(AgentLoop)
    loop.tools = ToolRegistry()
    loop.tools.register(_MobileGuiTool(backend, tmp_path))

    context = loop._build_router_context("Return home")

    assert context.task == "Return home"
    assert context.tool_registry is loop.tools
    assert context.mobile_native_backend is backend
    assert context.mobile_native_trace_dir == tmp_path
    assert context.adb_backend is backend
    assert context.adb_trace_dir == tmp_path


def test_catalog_exposes_adb_press_home_only_for_adb_backends() -> None:
    assert "adb.press_home" in _catalog_routes_for("adb")
    assert "adb.press_home" in _catalog_routes_for("scrcpy-adb")
    assert "adb.press_home" not in _catalog_routes_for("local")
    assert "adb.shell" not in _catalog_routes_for("adb")


@pytest.mark.asyncio
async def test_router_dispatches_adb_press_home_and_writes_canonical_trace(tmp_path: Path) -> None:
    backend = _FakeAdbBackend()
    router = TreeRouter()
    node = PlanNode(
        node_type="atom",
        instruction="Return to the Android home screen",
        capability="adb",
        route_id="adb.press_home",
        fallback_route_ids=("gui.adb",),
    )
    context = RouterContext(
        task="Return to the Android home screen",
        mobile_native_backend=backend,
        mobile_native_trace_dir=tmp_path,
    )

    result = await router.execute(node, context)

    assert result.success is True
    assert backend.commands == [("shell", "input", "keyevent", "HOME")]
    assert result.trace_paths

    events = _read_jsonl(Path(result.trace_paths[0]))
    step = next(event for event in events if event.get("type") == "step")
    assert step["action"] == {"action_type": "home"}
    assert step["phase"] == "adb"
    assert step["canonical_action"]["schema_version"] == "fastslow.gui.action.v1"
    assert step["canonical_action"]["route_id"] == "adb.press_home"
    assert step["canonical_action"]["executor"] == "adb"
    assert step["canonical_action"]["command"] == ["shell", "input", "keyevent", "HOME"]
    assert step["canonical_action"]["verification"]["success"] is True
    assert Path(step["canonical_action"]["verification"]["screenshot_path"]).exists()


def test_recorder_writes_canonical_action_when_provided(tmp_path: Path) -> None:
    recorder = TrajectoryRecorder(output_dir=tmp_path, task="noop", platform="android")
    trace_path = recorder.start(phase=ExecutionPhase.AGENT)

    recorder.record_step(
        action={"action_type": "wait"},
        canonical_action={"type": "noop"},
        model_output="noop",
    )
    recorder.finish(success=True)

    events = _read_jsonl(trace_path)
    step = next(event for event in events if event.get("type") == "step")
    assert step["canonical_action"] == {"type": "noop"}


def test_recorder_defaults_canonical_action_to_noop(tmp_path: Path) -> None:
    recorder = TrajectoryRecorder(output_dir=tmp_path, task="legacy call", platform="android")
    trace_path = recorder.start(phase=ExecutionPhase.AGENT)

    recorder.record_step(action={"action_type": "wait"}, model_output="legacy")
    recorder.finish(success=True)

    events = _read_jsonl(trace_path)
    step = next(event for event in events if event.get("type") == "step")
    assert step["canonical_action"] == {"type": "noop"}


def test_eval_parser_accepts_old_trace_without_canonical_action(tmp_path: Path) -> None:
    from eval.batch.metrics import parse_trace

    trace_path = tmp_path / "old_trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "metadata", "task": "old", "platform": "android"}),
                json.dumps(
                    {
                        "type": "step",
                        "step_index": 0,
                        "phase": "agent",
                        "action": {"action_type": "home"},
                        "token_usage": {"prompt_tokens": 1, "completion_tokens": 2},
                    }
                ),
                json.dumps({"type": "result", "success": True}),
            ]
        ),
        encoding="utf-8",
    )

    metrics = parse_trace(trace_path)

    assert metrics.steps == 1
    assert metrics.prompt_tokens == 1
    assert metrics.completion_tokens == 2


@pytest.mark.asyncio
async def test_router_keeps_adb_backend_alias_for_first_stage(tmp_path: Path) -> None:
    backend = _FakeAdbBackend()
    router = TreeRouter()
    node = PlanNode(
        node_type="atom",
        instruction="Return home",
        capability="adb",
        route_id="adb.press_home",
    )
    context = RouterContext(task="Return home", adb_backend=backend, adb_trace_dir=tmp_path)

    result = await router.execute(node, context)

    assert result.success is True
    assert backend.commands == [("shell", "input", "keyevent", "HOME")]
