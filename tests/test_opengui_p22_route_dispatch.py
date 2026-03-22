"""Phase 22 tests — route resolver and real ToolRegistry dispatch in TreeRouter.

Covers:
  - _resolve_route() mapping local tool route IDs to (tool_name, param_key) pairs
  - _resolve_route() handling MCP route IDs via mcp.{server}.{tool} convention
  - _resolve_route() returning None for unknown or unavailable routes
  - _run_tool() dispatching tool atoms through ToolRegistry.execute()
  - _run_mcp() dispatching mcp atoms through ToolRegistry.execute()
  - NodeResult(success=False) diagnostics for no-route-id atoms and multi-param routes
  - Dispatch logging of planned_route and resolved_route fields
  - _dispatch_atom passing full PlanNode (not just instruction) to _run_tool/_run_mcp
"""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.planner import PlanNode
from nanobot.agent.router import NodeResult, RouterContext, TreeRouter, _resolve_route
from nanobot.agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _make_mock_registry(tool_names: list[str]) -> ToolRegistry:
    """Return a ToolRegistry with mock Tool stubs for each given name.

    Each stub has its .name attribute set to the provided name and is
    registered directly into registry._tools so that registry.has() works
    without needing a real Tool instance.
    """
    registry = ToolRegistry()
    for name in tool_names:
        mock_tool = MagicMock()
        mock_tool.name = name
        registry._tools[name] = mock_tool
    return registry


def _make_tool_atom(
    route_id: str | None,
    instruction: str = "test instruction",
) -> PlanNode:
    """Shorthand: create a tool-capability ATOM PlanNode."""
    return PlanNode(
        node_type="atom",
        instruction=instruction,
        capability="tool",
        route_id=route_id,
    )


def _make_mcp_atom(
    route_id: str | None,
    instruction: str = "test mcp instruction",
) -> PlanNode:
    """Shorthand: create an mcp-capability ATOM PlanNode."""
    return PlanNode(
        node_type="atom",
        instruction=instruction,
        capability="mcp",
        route_id=route_id,
    )


def _make_ctx(tool_registry: Any = None, mcp_client: Any = None) -> RouterContext:
    """Create a RouterContext with specified executors."""
    return RouterContext(task="test task", tool_registry=tool_registry, mcp_client=mcp_client)


# ---------------------------------------------------------------------------
# Task 1: _resolve_route — local tool routes
# ---------------------------------------------------------------------------


def test_resolve_tool_route_exec_shell() -> None:
    """_resolve_route maps tool.exec_shell to ("exec", "command")."""
    registry = _make_mock_registry(["exec"])
    result = _resolve_route("tool.exec_shell", registry)
    assert result == ("exec", "command")


def test_resolve_tool_route_read_file() -> None:
    """_resolve_route maps tool.filesystem.read to ("read_file", "path")."""
    registry = _make_mock_registry(["read_file"])
    result = _resolve_route("tool.filesystem.read", registry)
    assert result == ("read_file", "path")


def test_resolve_tool_route_list_dir() -> None:
    """_resolve_route maps tool.filesystem.list to ("list_dir", "path")."""
    registry = _make_mock_registry(["list_dir"])
    result = _resolve_route("tool.filesystem.list", registry)
    assert result == ("list_dir", "path")


def test_resolve_tool_route_web_search() -> None:
    """_resolve_route maps tool.web.search to ("web_search", "query")."""
    registry = _make_mock_registry(["web_search"])
    result = _resolve_route("tool.web.search", registry)
    assert result == ("web_search", "query")


def test_resolve_tool_route_web_fetch() -> None:
    """_resolve_route maps tool.web.fetch to ("web_fetch", "url")."""
    registry = _make_mock_registry(["web_fetch"])
    result = _resolve_route("tool.web.fetch", registry)
    assert result == ("web_fetch", "url")


def test_resolve_tool_route_write_file_not_instruction_friendly() -> None:
    """_resolve_route maps tool.filesystem.write to ("write_file", None) — multi-param route."""
    registry = _make_mock_registry(["write_file"])
    result = _resolve_route("tool.filesystem.write", registry)
    assert result == ("write_file", None)


def test_resolve_tool_route_edit_file_not_instruction_friendly() -> None:
    """_resolve_route maps tool.filesystem.edit to ("edit_file", None) — multi-param route."""
    registry = _make_mock_registry(["edit_file"])
    result = _resolve_route("tool.filesystem.edit", registry)
    assert result == ("edit_file", None)


# ---------------------------------------------------------------------------
# Task 1: _resolve_route — MCP routes
# ---------------------------------------------------------------------------


def test_resolve_mcp_route() -> None:
    """_resolve_route maps mcp.demo.lookup to ("mcp_demo_lookup", "input")."""
    registry = _make_mock_registry(["mcp_demo_lookup"])
    result = _resolve_route("mcp.demo.lookup", registry)
    assert result == ("mcp_demo_lookup", "input")


def test_resolve_mcp_route_unavailable() -> None:
    """_resolve_route returns None when mcp.demo.lookup is not in an empty registry."""
    registry = _make_mock_registry([])
    result = _resolve_route("mcp.demo.lookup", registry)
    assert result is None


# ---------------------------------------------------------------------------
# Task 1: _resolve_route — unknown and missing routes
# ---------------------------------------------------------------------------


def test_resolve_unknown_route() -> None:
    """_resolve_route returns None for a completely unknown route_id."""
    registry = _make_mock_registry(["exec", "read_file"])
    result = _resolve_route("unknown.route", registry)
    assert result is None


def test_resolve_tool_route_not_in_registry() -> None:
    """_resolve_route returns None when tool.exec_shell maps to 'exec' but exec is absent."""
    registry = _make_mock_registry([])
    result = _resolve_route("tool.exec_shell", registry)
    assert result is None


# ---------------------------------------------------------------------------
# Task 2: _run_tool — real ToolRegistry dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_dispatch_exec_shell() -> None:
    """Tool atom with route_id=tool.exec_shell dispatches to registry.execute("exec", {"command": ...})."""
    registry = _make_mock_registry(["exec"])
    registry._tools["exec"].execute = AsyncMock(return_value="total 42")
    # Patch registry.execute via AsyncMock to track calls
    registry.execute = AsyncMock(return_value="total 42")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_tool_atom("tool.exec_shell", "ls -la")
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_tool(node, ctx)

    assert result.success is True
    registry.execute.assert_awaited_once_with("exec", {"command": "ls -la"})
    assert "42" in result.output


@pytest.mark.asyncio
async def test_tool_dispatch_no_route_id() -> None:
    """Tool atom with route_id=None returns NodeResult(success=False) with 'No route_id' error."""
    registry = _make_mock_registry(["exec"])
    router = TreeRouter()
    node = _make_tool_atom(None, "do something")
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_tool(node, ctx)

    assert result.success is False
    assert result.error is not None
    assert "No route_id" in result.error


@pytest.mark.asyncio
async def test_tool_dispatch_multi_param_route() -> None:
    """Tool atom with route_id=tool.filesystem.write returns failure with 'structured parameters'."""
    registry = _make_mock_registry(["write_file"])
    router = TreeRouter()
    node = _make_tool_atom("tool.filesystem.write", "write hello to test.txt")
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_tool(node, ctx)

    assert result.success is False
    assert result.error is not None
    assert "structured parameters" in result.error


@pytest.mark.asyncio
async def test_tool_dispatch_unavailable_route() -> None:
    """Tool atom with route_id pointing to absent tool returns NodeResult(success=False)."""
    registry = _make_mock_registry([])  # empty registry
    router = TreeRouter()
    node = _make_tool_atom("tool.exec_shell", "ls")
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_tool(node, ctx)

    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_mcp_dispatch_success() -> None:
    """MCP atom dispatches to registry.execute("mcp_demo_lookup", {"input": ...}) and returns success."""
    registry = _make_mock_registry(["mcp_demo_lookup"])
    registry.execute = AsyncMock(return_value="user found: 42")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_mcp_atom("mcp.demo.lookup", "find user 42")
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_mcp(node, ctx)

    assert result.success is True
    registry.execute.assert_awaited_once_with("mcp_demo_lookup", {"input": "find user 42"})
    assert "42" in result.output


@pytest.mark.asyncio
async def test_mcp_dispatch_no_route_id() -> None:
    """MCP atom with route_id=None returns NodeResult(success=False) with 'No route_id' error."""
    registry = _make_mock_registry(["mcp_demo_lookup"])
    router = TreeRouter()
    node = _make_mcp_atom(None)
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_mcp(node, ctx)

    assert result.success is False
    assert result.error is not None
    assert "No route_id" in result.error


@pytest.mark.asyncio
async def test_mcp_dispatch_unavailable_route() -> None:
    """MCP atom with route_id not in registry returns NodeResult(success=False)."""
    registry = _make_mock_registry([])  # no mcp_demo_lookup
    router = TreeRouter()
    node = _make_mcp_atom("mcp.demo.lookup", "find user 42")
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_mcp(node, ctx)

    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_tool_dispatch_registry_error_string() -> None:
    """registry.execute returning 'Error: ...' string causes NodeResult(success=False)."""
    registry = _make_mock_registry(["exec"])
    registry.execute = AsyncMock(return_value="Error: something failed")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_tool_atom("tool.exec_shell", "bad command")
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_tool(node, ctx)

    assert result.success is False
    assert result.error is not None
    assert "something failed" in result.error


@pytest.mark.asyncio
async def test_dispatch_atom_passes_node_to_run_tool() -> None:
    """_dispatch_atom passes the full PlanNode (not just instruction) to _run_tool."""
    registry = _make_mock_registry(["exec"])
    registry.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

    received_nodes: list[Any] = []

    original_run_tool = TreeRouter._run_tool

    async def capturing_run_tool(self: TreeRouter, node: Any, context: RouterContext) -> NodeResult:
        received_nodes.append(node)
        return await original_run_tool(self, node, context)

    router = TreeRouter()
    node = _make_tool_atom("tool.exec_shell", "ls -la")
    ctx = _make_ctx(tool_registry=registry)

    # Patch _run_tool on the instance to capture arguments
    router._run_tool = lambda n, c: capturing_run_tool(router, n, c)  # type: ignore[method-assign]

    await router._dispatch_atom(node, ctx)

    assert len(received_nodes) == 1
    assert received_nodes[0] is node
    assert received_nodes[0].route_id == "tool.exec_shell"


@pytest.mark.asyncio
async def test_dispatch_atom_passes_node_to_run_mcp() -> None:
    """_dispatch_atom passes the full PlanNode (not just instruction) to _run_mcp."""
    registry = _make_mock_registry(["mcp_demo_lookup"])
    registry.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

    received_nodes: list[Any] = []

    original_run_mcp = TreeRouter._run_mcp

    async def capturing_run_mcp(self: TreeRouter, node: Any, context: RouterContext) -> NodeResult:
        received_nodes.append(node)
        return await original_run_mcp(self, node, context)

    router = TreeRouter()
    node = _make_mcp_atom("mcp.demo.lookup", "find user 42")
    ctx = _make_ctx(tool_registry=registry)

    router._run_mcp = lambda n, c: capturing_run_mcp(router, n, c)  # type: ignore[method-assign]

    await router._dispatch_atom(node, ctx)

    assert len(received_nodes) == 1
    assert received_nodes[0] is node
    assert received_nodes[0].route_id == "mcp.demo.lookup"


@pytest.mark.asyncio
async def test_dispatch_logging_planned_route(caplog: pytest.LogCaptureFixture) -> None:
    """Dispatching a tool atom logs 'planned_route=tool.exec_shell'."""
    registry = _make_mock_registry(["exec"])
    registry.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_tool_atom("tool.exec_shell", "ls -la")
    ctx = _make_ctx(tool_registry=registry)

    with caplog.at_level(logging.INFO, logger="nanobot.agent.router"):
        await router._run_tool(node, ctx)

    assert any("planned_route=tool.exec_shell" in record.message for record in caplog.records), (
        f"Expected 'planned_route=tool.exec_shell' in log records, got: {[r.message for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_dispatch_logging_resolved_route(caplog: pytest.LogCaptureFixture) -> None:
    """Dispatching a tool atom logs 'resolved_route=tool.exec_shell' and 'tool=exec'."""
    registry = _make_mock_registry(["exec"])
    registry.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_tool_atom("tool.exec_shell", "ls -la")
    ctx = _make_ctx(tool_registry=registry)

    with caplog.at_level(logging.INFO, logger="nanobot.agent.router"):
        await router._run_tool(node, ctx)

    messages = [record.message for record in caplog.records]
    assert any("resolved_route=tool.exec_shell" in msg for msg in messages), (
        f"Expected 'resolved_route=tool.exec_shell' in log messages, got: {messages}"
    )
    assert any("tool=exec" in msg for msg in messages), (
        f"Expected 'tool=exec' in log messages, got: {messages}"
    )


# ---------------------------------------------------------------------------
# Task 1 (Plan 02): _dispatch_with_fallback — fallback chain dispatch
# ---------------------------------------------------------------------------


def _make_fallback_atom(
    route_id: str | None,
    fallback_route_ids: tuple[str, ...] = (),
    capability: str = "tool",
    instruction: str = "test instruction",
) -> PlanNode:
    """Shorthand: create a PlanNode with fallback_route_ids."""
    return PlanNode(
        node_type="atom",
        instruction=instruction,
        capability=capability,
        route_id=route_id,
        fallback_route_ids=fallback_route_ids,
    )


def _make_ctx_with_gui(
    tool_registry: Any = None,
    gui_agent: Any = None,
) -> RouterContext:
    """Create a RouterContext with both tool_registry and gui_agent."""
    return RouterContext(task="test task", tool_registry=tool_registry, gui_agent=gui_agent)


@pytest.mark.asyncio
async def test_fallback_primary_succeeds() -> None:
    """Primary route succeeds: fallback is never tried."""
    registry = _make_mock_registry(["exec", "web_search"])
    registry.execute = AsyncMock(return_value="exec output")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_fallback_atom(
        route_id="tool.exec_shell",
        fallback_route_ids=("tool.web.search",),
        instruction="ls -la",
    )
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_tool(node, ctx)

    assert result.success is True
    assert "exec output" in result.output
    # Should only call execute once (for exec, not web_search)
    registry.execute.assert_awaited_once_with("exec", {"command": "ls -la"})


@pytest.mark.asyncio
async def test_fallback_primary_fails_secondary_succeeds() -> None:
    """Primary route returns error string: fallback web_search succeeds."""
    registry = _make_mock_registry(["exec", "web_search"])

    call_log: list[str] = []

    async def execute_side_effect(tool_name: str, params: dict) -> str:
        call_log.append(tool_name)
        if tool_name == "exec":
            return "Error: command not found"
        return "search results"

    registry.execute = AsyncMock(side_effect=execute_side_effect)  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_fallback_atom(
        route_id="tool.exec_shell",
        fallback_route_ids=("tool.web.search",),
        instruction="list processes",
    )
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_tool(node, ctx)

    assert result.success is True
    assert "search results" in result.output
    assert call_log == ["exec", "web_search"]


@pytest.mark.asyncio
async def test_fallback_primary_unavailable_secondary_succeeds() -> None:
    """Primary MCP route not in registry: falls through to exec tool."""
    # Only exec is registered; mcp_demo_lookup is absent
    registry = _make_mock_registry(["exec"])
    registry.execute = AsyncMock(return_value="exec ok")  # type: ignore[method-assign]

    router = TreeRouter()
    node = PlanNode(
        node_type="atom",
        instruction="do something",
        capability="mcp",
        route_id="mcp.demo.lookup",
        fallback_route_ids=("tool.exec_shell",),
    )
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_mcp(node, ctx)

    assert result.success is True
    assert "exec ok" in result.output
    registry.execute.assert_awaited_once_with("exec", {"command": "do something"})


@pytest.mark.asyncio
async def test_fallback_all_fail() -> None:
    """All routes fail: NodeResult(success=False) listing all tried routes."""
    registry = _make_mock_registry(["exec", "web_search"])
    registry.execute = AsyncMock(return_value="Error: everything failed")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_fallback_atom(
        route_id="tool.exec_shell",
        fallback_route_ids=("tool.web.search",),
        instruction="do impossible thing",
    )
    ctx = _make_ctx(tool_registry=registry)

    result = await router._run_tool(node, ctx)

    assert result.success is False
    assert result.error is not None
    # Error message should mention tried routes
    assert "tool.exec_shell" in result.error or "tried" in result.error


@pytest.mark.asyncio
async def test_fallback_gui_desktop_delegates_to_run_gui() -> None:
    """gui.desktop fallback delegates to _run_gui when gui_agent is available."""
    registry = _make_mock_registry(["exec"])
    registry.execute = AsyncMock(return_value="Error: shell failed")  # type: ignore[method-assign]

    mock_gui_result = MagicMock()
    mock_gui_result.success = True
    mock_gui_result.summary = "GUI did the task"
    mock_gui_result.error = None
    mock_gui_result.trace_path = None

    mock_gui = AsyncMock()
    mock_gui.run = AsyncMock(return_value=mock_gui_result)

    router = TreeRouter()
    node = _make_fallback_atom(
        route_id="tool.exec_shell",
        fallback_route_ids=("gui.desktop",),
        instruction="open browser",
    )
    ctx = _make_ctx_with_gui(tool_registry=registry, gui_agent=mock_gui)

    result = await router._run_tool(node, ctx)

    assert result.success is True
    assert "GUI did the task" in result.output
    mock_gui.run.assert_awaited_once_with("open browser", max_retries=1)


@pytest.mark.asyncio
async def test_fallback_gui_desktop_skipped_when_no_gui_agent() -> None:
    """gui.desktop fallback is skipped with diagnostic when gui_agent is None."""
    registry = _make_mock_registry(["exec"])
    registry.execute = AsyncMock(return_value="Error: shell failed")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_fallback_atom(
        route_id="tool.exec_shell",
        fallback_route_ids=("gui.desktop",),
        instruction="open browser",
    )
    ctx = _make_ctx(tool_registry=registry)  # no gui_agent

    result = await router._run_tool(node, ctx)

    assert result.success is False
    assert result.error is not None
    # Error should mention GUI unavailability or list tried routes
    assert "gui" in result.error.lower() or "tried" in result.error.lower()


@pytest.mark.asyncio
async def test_fallback_logging_fallback_taken(caplog: pytest.LogCaptureFixture) -> None:
    """When fallback route succeeds, log entry contains 'fallback_taken='."""
    registry = _make_mock_registry(["exec", "web_search"])

    async def execute_side_effect(tool_name: str, params: dict) -> str:
        if tool_name == "exec":
            return "Error: failed"
        return "fallback output"

    registry.execute = AsyncMock(side_effect=execute_side_effect)  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_fallback_atom(
        route_id="tool.exec_shell",
        fallback_route_ids=("tool.web.search",),
        instruction="search for something",
    )
    ctx = _make_ctx(tool_registry=registry)

    with caplog.at_level(logging.INFO, logger="nanobot.agent.router"):
        result = await router._run_tool(node, ctx)

    assert result.success is True
    messages = [record.message for record in caplog.records]
    assert any("fallback_taken=" in msg for msg in messages), (
        f"Expected 'fallback_taken=' in log messages, got: {messages}"
    )


@pytest.mark.asyncio
async def test_fallback_logging_all_tried(caplog: pytest.LogCaptureFixture) -> None:
    """When all routes fail, log entries show each route attempted."""
    registry = _make_mock_registry(["exec", "web_search"])
    registry.execute = AsyncMock(return_value="Error: all broken")  # type: ignore[method-assign]

    router = TreeRouter()
    node = _make_fallback_atom(
        route_id="tool.exec_shell",
        fallback_route_ids=("tool.web.search",),
        instruction="impossible task",
    )
    ctx = _make_ctx(tool_registry=registry)

    with caplog.at_level(logging.INFO, logger="nanobot.agent.router"):
        result = await router._run_tool(node, ctx)

    assert result.success is False
    messages = [record.message for record in caplog.records]
    # Should have logged attempts for both routes
    assert any("tool.exec_shell" in msg for msg in messages), (
        f"Expected 'tool.exec_shell' in logs, got: {messages}"
    )


@pytest.mark.asyncio
async def test_multi_param_route_falls_back() -> None:
    """Multi-param route (write_file) is skipped and falls back to gui.desktop."""
    registry = _make_mock_registry(["write_file"])

    mock_gui_result = MagicMock()
    mock_gui_result.success = True
    mock_gui_result.summary = "GUI wrote the file"
    mock_gui_result.error = None
    mock_gui_result.trace_path = None

    mock_gui = AsyncMock()
    mock_gui.run = AsyncMock(return_value=mock_gui_result)

    router = TreeRouter()
    node = _make_fallback_atom(
        route_id="tool.filesystem.write",
        fallback_route_ids=("gui.desktop",),
        instruction="write hello to test.txt",
    )
    ctx = _make_ctx_with_gui(tool_registry=registry, gui_agent=mock_gui)

    result = await router._run_tool(node, ctx)

    assert result.success is True
    assert "GUI wrote the file" in result.output
    mock_gui.run.assert_awaited_once_with("write hello to test.txt", max_retries=1)
