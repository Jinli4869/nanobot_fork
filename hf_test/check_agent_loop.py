"""Focused checks for AgentLoop planning route, TaskPlanner tree quality, and TreeRouter dispatch.

Run directly:
	pytest -q hf_test/check_agent_loop.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Allow running this focused check file without installing full runtime deps.
if "tiktoken" not in sys.modules:
	_stub = types.ModuleType("tiktoken")

	class _DummyEncoding:
		@staticmethod
		def encode(text: str) -> list[int]:  # noqa: D401
			return [1] * len(text)

	_stub.get_encoding = lambda _name: _DummyEncoding()
	_stub.encoding_for_model = lambda _name: _DummyEncoding()
	sys.modules["tiktoken"] = _stub

from nanobot.agent.loop import AgentLoop
from nanobot.agent.planner import PlanNode, TaskPlanner
from nanobot.agent.router import NodeResult, RouterContext, TreeRouter
from nanobot.bus.events import InboundMessage
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path, *, gui_enabled: bool = True) -> AgentLoop:
	"""Build AgentLoop with lightweight mocks so route logic can be isolated."""
	bus = MagicMock()
	bus.publish_outbound = AsyncMock()
	bus.consume_inbound = AsyncMock()

	provider = MagicMock()
	provider.get_default_model.return_value = "test-model"
	provider.chat_with_retry = AsyncMock()

	gui_config = MagicMock() if gui_enabled else None

	# Keep tests deterministic and avoid real tool bootstrapping.
	with patch.object(AgentLoop, "_register_default_tools", lambda _self: None):
		loop = AgentLoop(
			bus=bus,
			provider=provider,
			workspace=tmp_path,
			gui_config=gui_config,
		)

	loop.memory_consolidator.maybe_consolidate_by_tokens = AsyncMock()
	loop.memory_consolidator.archive_messages = AsyncMock()
	return loop


def _inbound(content: str) -> InboundMessage:
	return InboundMessage(channel="cli", sender_id="u1", chat_id="chat1", content=content)


class _FakePlannerLLM:
	def __init__(self, response: Any) -> None:
		self._response = response

	async def chat(self, **kwargs: Any) -> Any:  # noqa: ARG002
		return self._response


# 简单短消息直接进 _run_agent_loop 不 plan
@pytest.mark.asyncio
async def test_route_simple_task_uses_direct_agent_loop(tmp_path: Path) -> None:
	"""Simple (short) message should bypass planning and go to direct loop."""
	loop = _make_loop(tmp_path, gui_enabled=True)

	with (
		patch.object(loop.context, "build_messages", return_value=[]),
		patch.object(loop, "_needs_planning", new_callable=AsyncMock) as gate,
		patch.object(loop, "_run_agent_loop", new=AsyncMock(return_value=("simple-ok", [], []))) as run_loop,
		patch.object(loop, "_plan_and_execute", new=AsyncMock(return_value=("plan-ok", [], []))) as run_plan,
	):
		resp = await loop._process_message(_inbound("hi"))

	assert resp is not None and resp.content == "simple-ok"
	gate.assert_not_awaited()
	run_loop.assert_awaited_once()
	run_plan.assert_not_awaited()

# 复杂消息当 gate = True 进 _plan_and_execute
@pytest.mark.asyncio
async def test_route_complex_task_goes_to_planner(tmp_path: Path) -> None:
	"""Complex message should route to planner branch when gate returns True."""
	loop = _make_loop(tmp_path, gui_enabled=True)

	with (
		patch.object(loop.context, "build_messages", return_value=[]),
		patch.object(loop, "_needs_planning", new=AsyncMock(return_value=True)) as gate,
		patch.object(loop, "_run_agent_loop", new=AsyncMock(return_value=("loop-ok", [], []))) as run_loop,
		patch.object(loop, "_plan_and_execute", new=AsyncMock(return_value=("plan-ok", ["task_planner"], []))) as run_plan,
	):
		resp = await loop._process_message(
			_inbound("请打开浏览器搜索这周天气并整理成待办后发给我")
		)

	assert resp is not None and resp.content == "plan-ok"
	gate.assert_awaited_once()
	run_plan.assert_awaited_once()
	run_loop.assert_not_awaited()

# 测试工具结果
@pytest.mark.asyncio
async def test_needs_planning_parses_tool_call_boolean(tmp_path: Path) -> None:
	"""_needs_planning should parse assess_complexity tool-call result correctly."""
	loop = _make_loop(tmp_path)

	loop.provider.chat_with_retry = AsyncMock(
		return_value=LLMResponse(
			content=None,
			tool_calls=[
				ToolCallRequest(id="t1", name="assess_complexity", arguments={"needs_planning": True})
			],
		)
	)
	assert await loop._needs_planning("A complex multi-step task") is True

	loop.provider.chat_with_retry = AsyncMock(
		return_value=LLMResponse(
			content=None,
			tool_calls=[
				ToolCallRequest(id="t2", name="assess_complexity", arguments={"needs_planning": False})
			],
		)
	)
	assert await loop._needs_planning("A simple task") is False

# 测试节点
@pytest.mark.asyncio
async def test_task_planner_plan_returns_expected_tree_types() -> None:
	"""Planner output should deserialize to correct node types/capabilities."""
	response = SimpleNamespace(
		tool_calls=[
			SimpleNamespace(
				arguments={
					"tree": {
						"type": "and",
						"children": [
							{"type": "atom", "instruction": "open app", "capability": "gui"},
							{"type": "atom", "instruction": "fetch data", "capability": "tool"},
						],
					}
				}
			)
		]
	)
	planner = TaskPlanner(llm=_FakePlannerLLM(response))

	tree = await planner.plan("open app and fetch data")

	assert tree.node_type == "and"
	assert len(tree.children) == 2
	assert tree.children[0].node_type == "atom"
	assert tree.children[0].capability == "gui"
	assert tree.children[1].node_type == "atom"
	assert tree.children[1].capability == "tool"


@pytest.mark.asyncio
async def test_task_planner_should_fallback_on_invalid_node_type() -> None:
	"""Expected behavior: invalid node types should fall back to a safe ATOM."""
	bad_response = SimpleNamespace(
		tool_calls=[SimpleNamespace(arguments={"tree": {"type": "atom", "children": []}})]
	)
	planner = TaskPlanner(llm=_FakePlannerLLM(bad_response))

	tree = await planner.plan("anything")

	assert tree.node_type == "atom"


@pytest.mark.asyncio
async def test_router_or_priority_routes_to_mcp_first() -> None:
	"""Router OR node should try mcp > tool > gui according to priority."""
	plan = PlanNode(
		node_type="or",
		children=(
			PlanNode(node_type="atom", instruction="gui-opt", capability="gui"),
			PlanNode(node_type="atom", instruction="mcp-opt", capability="mcp"),
			PlanNode(node_type="atom", instruction="tool-opt", capability="tool"),
		),
	)

	call_order: list[str] = []

	async def fake_dispatch(self: TreeRouter, node: PlanNode, context: RouterContext) -> NodeResult:  # noqa: ARG001
		call_order.append(f"{node.capability}:{node.instruction}")
		if node.capability == "mcp":
			return NodeResult(success=True, output="mcp-ok")
		return NodeResult(success=False, error="fail")

	with patch.object(TreeRouter, "_dispatch_atom", fake_dispatch):
		router = TreeRouter()
		result = await router.execute(plan, RouterContext(task="task", mcp_client=object(), tool_registry=object()))

	assert result.success
	assert result.output == "mcp-ok"
	assert call_order[0] == "mcp:mcp-opt"


@pytest.mark.asyncio
async def test_router_dispatches_planner_atoms_by_capability() -> None:
	"""Planner ATOM nodes should dispatch to matched router handlers."""
	plan = PlanNode(
		node_type="and",
		children=(
			PlanNode(node_type="atom", instruction="do-tool", capability="tool"),
			PlanNode(node_type="atom", instruction="do-mcp", capability="mcp"),
			PlanNode(node_type="atom", instruction="do-gui", capability="gui"),
		),
	)

	async def fake_tool(instruction: str, context: RouterContext) -> NodeResult:  # noqa: ARG001
		return NodeResult(success=True, output=f"tool:{instruction}")

	async def fake_mcp(instruction: str, context: RouterContext) -> NodeResult:  # noqa: ARG001
		return NodeResult(success=True, output=f"mcp:{instruction}")

	async def fake_gui(instruction: str, context: RouterContext) -> NodeResult:  # noqa: ARG001
		return NodeResult(success=True, output=f"gui:{instruction}")

	with (
		patch.object(TreeRouter, "_run_tool", side_effect=fake_tool),
		patch.object(TreeRouter, "_run_mcp", side_effect=fake_mcp),
		patch.object(TreeRouter, "_run_gui", side_effect=fake_gui),
	):
		router = TreeRouter(max_concurrency=1)
		ctx = RouterContext(task="task", tool_registry=object(), mcp_client=object(), gui_agent=object())
		result = await router.execute(plan, ctx)

	assert result.success
	assert "tool:do-tool" in result.output
	assert "mcp:do-mcp" in result.output
	assert "gui:do-gui" in result.output
	assert ctx.completed == ["do-tool", "do-mcp", "do-gui"]

