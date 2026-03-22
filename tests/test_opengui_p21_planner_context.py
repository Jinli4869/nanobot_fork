from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


@dataclass
class _DummyTool(Tool):
    _name: str
    _description: str = "test tool"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def _catalog():
    from nanobot.agent.capabilities import CapabilityCatalog, RouteSummary

    return CapabilityCatalog(
        routes=(
            RouteSummary(
                route_id="tool.exec_shell",
                capability="tool",
                kind="shell",
                summary="Run local shell commands",
                use_for=("system toggles",),
                avoid_for=("visual workflows",),
                availability="ready",
            ),
            RouteSummary(
                route_id="gui.desktop",
                capability="gui",
                kind="desktop",
                summary="Operate apps through the GUI subagent",
                use_for=("visual workflows",),
                avoid_for=("direct host commands",),
                availability="ready",
            ),
        )
    )


def _write_memory(workspace: Path, *, memory: str = "", history: str = "") -> None:
    memory_dir = workspace / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text(memory, encoding="utf-8")
    (memory_dir / "HISTORY.md").write_text(history, encoding="utf-8")


def test_capability_catalog_builder_allowlists_live_routes() -> None:
    from nanobot.agent.capabilities import CapabilityCatalogBuilder

    registry = ToolRegistry()
    for tool_name in (
        "gui_task",
        "exec",
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
        "web_search",
        "web_fetch",
        "mcp_demo_lookup",
        "message",
        "spawn",
        "cron",
    ):
        registry.register(_DummyTool(tool_name))

    catalog = CapabilityCatalogBuilder().build(
        tool_registry=registry,
        gui_available=True,
        exec_enabled=True,
    )

    route_ids = [route.route_id for route in catalog.routes]
    assert route_ids == [
        "gui.desktop",
        "tool.exec_shell",
        "tool.filesystem.read",
        "tool.filesystem.write",
        "tool.filesystem.edit",
        "tool.filesystem.list",
        "tool.web.search",
        "tool.web.fetch",
        "mcp.demo.lookup",
    ]
    assert "message" not in route_ids
    assert "spawn" not in route_ids
    assert "cron" not in route_ids


def test_planning_context_wraps_catalog() -> None:
    from nanobot.agent.capabilities import CapabilityCatalog, PlanningContext, RouteSummary

    catalog = CapabilityCatalog(
        routes=(
            RouteSummary(
                route_id="tool.exec_shell",
                capability="tool",
                kind="shell",
                summary="Run local shell commands",
                use_for=("system toggles",),
                avoid_for=("visual workflows",),
                availability="ready",
            ),
        )
    )

    planning_context = PlanningContext(catalog=catalog)

    assert planning_context.catalog is catalog
    assert planning_context.catalog.routes[0].route_id == "tool.exec_shell"


def test_task_planner_catalog_prompt_mentions_route_metadata() -> None:
    from nanobot.agent.capabilities import PlanningContext
    from nanobot.agent.planner import TaskPlanner, _CREATE_PLAN_TOOL

    planner = TaskPlanner(llm=object())
    planning_context = PlanningContext(catalog=_catalog())

    prompt = planner._build_system_prompt(planning_context=planning_context)

    assert "tool.exec_shell" in prompt
    assert "gui.desktop" in prompt
    assert "route_id" in prompt
    assert "route_reason" in prompt
    assert "fallback_route_ids" in prompt
    assert "tool.exec_shell" in str(_CREATE_PLAN_TOOL)
    assert "route_id" in str(_CREATE_PLAN_TOOL)


def test_memory_hint_extractor_excludes_unrelated_narrative_memory(tmp_path: Path) -> None:
    from nanobot.agent.planning_memory import PlanningMemoryHintExtractor

    _write_memory(
        tmp_path,
        memory=(
            "User prefers concise updates.\n"
            "tool.exec_shell worked for disabling bluetooth on macOS.\n"
            "General note: the user likes green tea.\n"
        ),
        history=(
            "[2026-03-22 09:00] shell route succeeded for bluetooth toggle.\n\n"
            "[2026-03-22 09:05] fallback to gui.desktop when shell failed to open System Settings."
        ),
    )

    hints = PlanningMemoryHintExtractor(tmp_path).build(
        task="Disable Bluetooth on this Mac",
        catalog=_catalog(),
    )

    rendered = [hint.to_prompt_line() for hint in hints]
    assert rendered
    assert any(hint.route_id == "tool.exec_shell" for hint in hints)
    assert any("fallback" in line.lower() for line in rendered)
    assert all("concise updates" not in line for line in rendered)
    assert all("green tea" not in line for line in rendered)


def test_memory_hint_guardrail_serialization_caps_count_and_length() -> None:
    from nanobot.agent.planning_memory import PlanningMemoryHint, serialize_memory_hints

    hints = tuple(
        PlanningMemoryHint(
            route_id="tool.exec_shell",
            note=f"tool.exec_shell worked for bluetooth toggle attempt {index}: " + ("x" * 220),
        )
        for index in range(7)
    )

    rendered = serialize_memory_hints(hints)

    assert len(rendered) == 5
    assert all(len(line) <= 160 for line in rendered)
    assert sum(len(line) for line in rendered) <= 900


def test_memory_hint_extractor_returns_empty_tuple_without_route_evidence(tmp_path: Path) -> None:
    from nanobot.agent.planning_memory import PlanningMemoryHintExtractor

    _write_memory(
        tmp_path,
        memory="User prefers concise updates.\nKeep answers short.\n",
        history="[2026-03-22 10:00] Discussed grocery shopping and tea preferences.",
    )

    hints = PlanningMemoryHintExtractor(tmp_path).build(
        task="Disable Bluetooth on this Mac",
        catalog=_catalog(),
    )

    assert hints == ()
