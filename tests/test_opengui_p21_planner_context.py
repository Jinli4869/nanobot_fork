from __future__ import annotations

from dataclasses import dataclass
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
    from nanobot.agent.capabilities import CapabilityCatalog, PlanningContext, RouteSummary
    from nanobot.agent.planner import TaskPlanner, _CREATE_PLAN_TOOL

    planner = TaskPlanner(llm=object())
    planning_context = PlanningContext(
        catalog=CapabilityCatalog(
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
    )

    prompt = planner._build_system_prompt(planning_context=planning_context)

    assert "tool.exec_shell" in prompt
    assert "gui.desktop" in prompt
    assert "route_id" in prompt
    assert "route_reason" in prompt
    assert "fallback_route_ids" in prompt
    assert "tool.exec_shell" in str(_CREATE_PLAN_TOOL)
    assert "route_id" in str(_CREATE_PLAN_TOOL)
