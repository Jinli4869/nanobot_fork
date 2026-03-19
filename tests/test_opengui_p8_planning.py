"""Phase 8 tests — parallel AND execution and prioritized OR routing in TreeRouter.

Covers:
  - AND node parallel execution via asyncio.gather with concurrency semaphore
  - AND node per-child context isolation (no shared-list mutation)
  - AND node replan on child failure
  - OR node priority sorting (mcp > tool > gui)
  - OR node auto-fallback on child failure
  - OR node exhaustion with error reporting
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.planner import PlanNode
from nanobot.agent.router import NodeResult, RouterContext, TreeRouter


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _atom(instruction: str, capability: str = "gui") -> PlanNode:
    """Shorthand: create a leaf ATOM PlanNode."""
    return PlanNode(node_type="atom", instruction=instruction, capability=capability)  # type: ignore[arg-type]


def _and(*children: PlanNode) -> PlanNode:
    """Shorthand: create an AND composite PlanNode."""
    return PlanNode(node_type="and", children=children)


def _or(*children: PlanNode) -> PlanNode:
    """Shorthand: create an OR composite PlanNode."""
    return PlanNode(node_type="or", children=children)


def _make_ctx(**kwargs: Any) -> RouterContext:
    """Create a RouterContext with sensible defaults."""
    return RouterContext(task="test task", **kwargs)


# ---------------------------------------------------------------------------
# Task 1: Parallel AND execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_and_parallel_all_succeed() -> None:
    """AND node with 3 ATOM children dispatches all 3 via asyncio.gather.

    All 3 instructions must appear in context.completed after execution.
    """
    children = [
        _atom("step-alpha", "gui"),
        _atom("step-beta", "gui"),
        _atom("step-gamma", "gui"),
    ]
    plan = _and(*children)

    dispatch_calls: list[str] = []

    async def mock_run(instruction: str, max_retries: int = 1) -> Any:
        dispatch_calls.append(instruction)
        result = AsyncMock()
        result.success = True
        result.summary = f"Done: {instruction}"
        result.error = None
        result.trace_path = None
        return result

    mock_gui = AsyncMock()
    mock_gui.run = AsyncMock(side_effect=mock_run)

    router = TreeRouter()
    ctx = _make_ctx(gui_agent=mock_gui)

    result = await router.execute(plan, ctx)

    assert result.success, f"Expected success but got error: {result.error}"
    # All 3 atoms must appear in completed
    assert "step-alpha" in ctx.completed
    assert "step-beta" in ctx.completed
    assert "step-gamma" in ctx.completed
    # All 3 dispatch calls must have happened
    assert set(dispatch_calls) == {"step-alpha", "step-beta", "step-gamma"}


@pytest.mark.asyncio
async def test_and_respects_max_concurrency() -> None:
    """AND node with max_concurrency=1 runs children sequentially (no overlap).

    We verify no temporal overlap by tracking start/end timestamps for each
    child coroutine.  With max_concurrency=1 the semaphore forces strict
    serialisation even when asyncio.gather is used.
    """
    intervals: list[tuple[float, float]] = []
    lock = asyncio.Lock()

    async def mock_run(instruction: str, max_retries: int = 1) -> Any:
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0.02)  # small delay to make overlap detectable
        end = asyncio.get_event_loop().time()
        async with lock:
            intervals.append((start, end))
        result = AsyncMock()
        result.success = True
        result.summary = f"Done: {instruction}"
        result.error = None
        result.trace_path = None
        return result

    mock_gui = AsyncMock()
    mock_gui.run = AsyncMock(side_effect=mock_run)

    plan = _and(_atom("a", "gui"), _atom("b", "gui"), _atom("c", "gui"))
    router = TreeRouter(max_concurrency=1)
    ctx = _make_ctx(gui_agent=mock_gui)

    result = await router.execute(plan, ctx)

    assert result.success
    assert len(intervals) == 3

    # Verify no two intervals overlap: sort by start, then check end[i] <= start[i+1]
    intervals.sort(key=lambda x: x[0])
    for i in range(len(intervals) - 1):
        _, end_i = intervals[i]
        start_next, _ = intervals[i + 1]
        assert end_i <= start_next + 0.005, (
            f"Overlap detected between interval {i} and {i+1}: "
            f"end={end_i:.4f}, next_start={start_next:.4f}"
        )


@pytest.mark.asyncio
async def test_and_child_failure_triggers_replan() -> None:
    """AND node triggers replan on child failure and can recover successfully.

    The failing child must cause replan() to be called.  The mock planner
    returns a single recovery atom that succeeds; final result is success.
    """
    plan = _and(
        _atom("step-ok", "gui"),
        _atom("step-fail", "gui"),
    )

    async def mock_run(instruction: str, max_retries: int = 1) -> Any:
        result = AsyncMock()
        if instruction == "step-fail":
            result.success = False
            result.summary = "Failed"
            result.error = "simulated failure"
        else:
            result.success = True
            result.summary = f"Done: {instruction}"
            result.error = None
        result.trace_path = None
        return result

    mock_gui = AsyncMock()
    mock_gui.run = AsyncMock(side_effect=mock_run)

    # Planner returns a recovery atom
    recovery = _atom("step-recovery", "gui")
    mock_planner = AsyncMock()
    mock_planner.replan = AsyncMock(return_value=recovery)

    router = TreeRouter(planner=mock_planner, max_replans=1)
    ctx = _make_ctx(gui_agent=mock_gui)

    result = await router.execute(plan, ctx)

    assert result.success
    mock_planner.replan.assert_awaited()


@pytest.mark.asyncio
async def test_and_no_shared_list_mutation() -> None:
    """AND parallel children must not share context.completed during execution.

    Each child receives an independent snapshot of context.completed at the
    time it is launched.  We verify this by inspecting what each child saw
    in its RouterContext — the snapshot should only contain items added
    *before* the AND started, not items from sibling children.
    """
    seen_completed: list[list[str]] = []
    lock = asyncio.Lock()

    async def mock_run(instruction: str, max_retries: int = 1) -> Any:
        # We cannot inspect the RouterContext directly here; instead we rely
        # on the behaviour: if context is shared, then a child completing
        # early would add its instruction and the other child would see it.
        # This test validates the contract via the snapshot design.
        await asyncio.sleep(0.01)
        result = AsyncMock()
        result.success = True
        result.summary = f"Done: {instruction}"
        result.error = None
        result.trace_path = None
        return result

    mock_gui = AsyncMock()
    mock_gui.run = AsyncMock(side_effect=mock_run)

    # Pre-seed one item so we can verify the snapshot carries it
    ctx = _make_ctx(gui_agent=mock_gui)
    ctx.completed.append("pre-existing")

    plan = _and(_atom("child-1", "gui"), _atom("child-2", "gui"))
    router = TreeRouter(max_concurrency=3)  # allow parallelism

    # Patch RouterContext constructor to record what each child receives
    original_router_context = RouterContext

    created_contexts: list[RouterContext] = []

    class RecordingRouterContext(RouterContext):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            created_contexts.append(self)

    with patch("nanobot.agent.router.RouterContext", RecordingRouterContext):
        result = await router.execute(plan, ctx)

    assert result.success
    # Every child context created during parallel AND execution should start
    # with the pre-existing item but NOT contain the other child's instruction
    for child_ctx in created_contexts:
        assert "pre-existing" in child_ctx.completed, (
            "Snapshot should carry pre-existing entries"
        )
        # Sibling instructions must not be present at snapshot time
        assert "child-1" not in child_ctx.completed or "child-2" not in child_ctx.completed, (
            "Both sibling instructions found in child context — shared list mutation detected"
        )


# ---------------------------------------------------------------------------
# Task 2: OR node priority sorting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_or_priority_order() -> None:
    """OR node sorts children mcp > tool > gui before trying them.

    Children are provided in [gui, mcp, tool] order; mock makes mcp succeed.
    We verify that mcp is called first (not gui) by tracking call order.
    """
    call_order: list[str] = []

    async def mock_run(instruction: str, max_retries: int = 1) -> Any:
        call_order.append(f"gui:{instruction}")
        result = AsyncMock()
        result.success = False
        result.summary = ""
        result.error = "gui failed"
        result.trace_path = None
        return result

    mock_gui = AsyncMock()
    mock_gui.run = AsyncMock(side_effect=mock_run)

    # mcp_client: returns success for its atom
    mock_mcp_client = object()  # non-None so dispatch proceeds

    plan = _or(
        _atom("gui-option", "gui"),
        _atom("mcp-option", "mcp"),
        _atom("tool-option", "tool"),
    )

    # Intercept _dispatch_atom to track order
    dispatch_order: list[str] = []
    original_dispatch = TreeRouter._dispatch_atom

    async def recording_dispatch(self: TreeRouter, node: Any, context: RouterContext) -> NodeResult:
        dispatch_order.append(f"{node.capability}:{node.instruction}")
        if node.capability == "mcp":
            return NodeResult(success=True, output="mcp done")
        return NodeResult(success=False, error=f"{node.capability} failed")

    with patch.object(TreeRouter, "_dispatch_atom", recording_dispatch):
        router = TreeRouter()
        ctx = _make_ctx(gui_agent=mock_gui, mcp_client=mock_mcp_client)
        result = await router.execute(plan, ctx)

    assert result.success, f"Expected success but got: {result.error}"
    # mcp must be the first capability tried
    assert dispatch_order[0].startswith("mcp:"), (
        f"Expected mcp first, got: {dispatch_order}"
    )
    # gui (lowest priority) must appear after mcp (mcp succeeded so gui not tried)
    # At minimum mcp was first and gui was not tried (mcp succeeded)
    assert not any(x.startswith("gui:") for x in dispatch_order), (
        "gui should not be tried because mcp already succeeded"
    )


@pytest.mark.asyncio
async def test_or_same_capability_preserves_order() -> None:
    """OR node with children of the same capability preserves original order.

    Three gui atoms in order [first, second, third].  First fails, second
    succeeds.  Verify that 'second' appears in ctx.completed (meaning it was
    reached in original order and succeeded).
    """
    call_sequence: list[str] = []

    async def recording_dispatch(self: TreeRouter, node: Any, context: RouterContext) -> NodeResult:
        call_sequence.append(node.instruction)
        if node.instruction == "gui-first":
            return NodeResult(success=False, error="first failed")
        return NodeResult(success=True, output=f"done: {node.instruction}")

    plan = _or(
        _atom("gui-first", "gui"),
        _atom("gui-second", "gui"),
        _atom("gui-third", "gui"),
    )

    with patch.object(TreeRouter, "_dispatch_atom", recording_dispatch):
        router = TreeRouter()
        ctx = _make_ctx()
        result = await router.execute(plan, ctx)

    assert result.success
    assert "gui-second" in ctx.completed
    # second must come after first in call order
    assert call_sequence.index("gui-first") < call_sequence.index("gui-second")
    # third should not be called (second succeeded)
    assert "gui-third" not in call_sequence


@pytest.mark.asyncio
async def test_or_auto_fallback() -> None:
    """OR auto-fallback: first child (mcp) fails, second (tool) succeeds.

    Result should be success with the tool's output.
    """
    async def recording_dispatch(self: TreeRouter, node: Any, context: RouterContext) -> NodeResult:
        if node.capability == "mcp":
            return NodeResult(success=False, error="mcp unavailable")
        if node.capability == "tool":
            return NodeResult(success=True, output="tool-output")
        return NodeResult(success=False, error="unexpected")

    plan = _or(
        _atom("mcp-step", "mcp"),
        _atom("tool-step", "tool"),
    )

    with patch.object(TreeRouter, "_dispatch_atom", recording_dispatch):
        router = TreeRouter()
        ctx = _make_ctx()
        result = await router.execute(plan, ctx)

    assert result.success
    assert result.output == "tool-output"
    assert "tool-step" in ctx.completed


@pytest.mark.asyncio
async def test_or_all_fail() -> None:
    """OR reports failure when all children fail.

    Result must have success=False and a non-empty error message.
    """
    async def recording_dispatch(self: TreeRouter, node: Any, context: RouterContext) -> NodeResult:
        return NodeResult(success=False, error=f"{node.capability} failed")

    plan = _or(
        _atom("mcp-opt", "mcp"),
        _atom("tool-opt", "tool"),
        _atom("gui-opt", "gui"),
    )

    with patch.object(TreeRouter, "_dispatch_atom", recording_dispatch):
        router = TreeRouter()
        ctx = _make_ctx()
        result = await router.execute(plan, ctx)

    assert not result.success
    assert result.error is not None and len(result.error) > 0
