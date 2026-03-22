"""TreeRouter: walks AND/OR/ATOM plan trees and dispatches ATOM nodes by capability type."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Capability priority for OR-node ordering (lower value = tried first)
# ---------------------------------------------------------------------------

_CAPABILITY_PRIORITY: dict[str, int] = {"mcp": 0, "tool": 1, "gui": 2, "api": 3}


# ---------------------------------------------------------------------------
# Route resolution tables
# ---------------------------------------------------------------------------

# Maps planner route_id (tool.* form) to the ToolRegistry key used at dispatch.
_ROUTE_ID_TO_TOOL_NAME: dict[str, str] = {
    "tool.exec_shell":       "exec",
    "tool.filesystem.read":  "read_file",
    "tool.filesystem.write": "write_file",
    "tool.filesystem.edit":  "edit_file",
    "tool.filesystem.list":  "list_dir",
    "tool.web.search":       "web_search",
    "tool.web.fetch":        "web_fetch",
}

# Maps registry tool name to the single instruction-derived parameter key.
# Tools absent from this map require structured multi-parameter input and
# cannot be driven from an instruction string alone (e.g. write_file, edit_file).
_INSTRUCTION_PARAM: dict[str, str] = {
    "exec":       "command",
    "read_file":  "path",
    "list_dir":   "path",
    "web_search": "query",
    "web_fetch":  "url",
}


def _resolve_route(
    route_id: str,
    registry: Any,
) -> tuple[str, str | None] | None:
    """Map a planner route_id to (registry_tool_name, primary_param_key).

    Returns ``None`` when the route_id is unrecognized or the required tool is
    absent from the registry.  Returns ``(tool_name, None)`` for multi-parameter
    tools (write_file, edit_file) that cannot be driven by instruction text alone.

    Local tool routes follow the ``tool.*`` prefix convention.
    MCP routes follow the ``mcp.{server}.{tool}`` convention and resolve to the
    registry key ``mcp_{server}_{tool}`` with ``"input"`` as the primary parameter.
    """
    # Local tool routes
    if route_id in _ROUTE_ID_TO_TOOL_NAME:
        tool_name = _ROUTE_ID_TO_TOOL_NAME[route_id]
        if not registry.has(tool_name):
            return None
        param_key = _INSTRUCTION_PARAM.get(tool_name)  # None for multi-param tools
        return (tool_name, param_key)

    # MCP routes: mcp.{server}.{tool} -> mcp_{server}_{tool}
    if route_id.startswith("mcp."):
        suffix = route_id[4:]
        parts = suffix.split(".", 1)
        if len(parts) == 2:
            tool_name = f"mcp_{parts[0]}_{parts[1]}"
            if not registry.has(tool_name):
                return None
            return (tool_name, "input")

    return None


# ---------------------------------------------------------------------------
# Result / context data structures
# ---------------------------------------------------------------------------


@dataclass
class NodeResult:
    """Result of executing a single plan tree node."""

    success: bool
    output: str = ""
    error: str | None = None
    trace_paths: list[str] = field(default_factory=list)


@dataclass
class RouterContext:
    """Mutable context threaded through the tree during execution.

    Holds references to the executors that ATOM nodes dispatch to, plus
    a running list of completed ATOM instructions (used for replanning).
    """

    task: str
    completed: list[str] = field(default_factory=list)
    gui_agent: Any = None
    tool_registry: Any = None
    mcp_client: Any = None


# ---------------------------------------------------------------------------
# TreeRouter
# ---------------------------------------------------------------------------


class TreeRouter:
    """Walk an AND/OR/ATOM plan tree and dispatch each ATOM to its executor.

    Dispatch table (by :pyattr:`PlanNode.capability`):

    * **gui** — ``GuiAgent.run(instruction)`` with ``max_retries=1``
    * **tool** — placeholder (full wiring in Phase 3)
    * **mcp** — placeholder (full wiring in Phase 3)
    * **api** — not yet implemented

    AND nodes execute children in parallel via :func:`asyncio.gather`, bounded
    by a ``max_concurrency`` semaphore (default 3).  Each child receives its own
    snapshot of ``context.completed`` to prevent shared-list mutation during
    concurrent execution.  After gather completes, all per-child completed lists
    are merged back into ``context.completed`` in child order.

    On any AND-child failure, replanning is attempted if budget remains.

    OR nodes try children in **mcp > tool > gui > api** priority order until
    one succeeds.  If all alternatives fail, replanning is attempted before
    reporting failure.
    """

    def __init__(
        self,
        planner: Any = None,
        max_replans: int = 2,
        max_concurrency: int = 3,
    ) -> None:
        """
        Args:
            planner: Optional :class:`TaskPlanner` used for replanning after
                     failures.
            max_replans: Maximum number of replan attempts allowed across the
                         whole tree execution.
            max_concurrency: Maximum number of AND children executed
                             concurrently.  Defaults to 3.  Set to 1 for
                             strictly sequential (useful in tests and
                             environments with limited parallelism).
        """
        self._planner = planner
        self._max_replans = max_replans
        self._max_concurrency = max_concurrency
        self._replan_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, node: Any, context: RouterContext) -> NodeResult:
        """Recursively execute a :class:`PlanNode` tree."""
        from nanobot.agent.planner import PlanNode

        if not isinstance(node, PlanNode):
            return NodeResult(success=False, error=f"Expected PlanNode, got {type(node)}")

        if node.node_type == "atom":
            return await self._dispatch_atom(node, context)
        if node.node_type == "and":
            return await self._execute_and(node, context)
        if node.node_type == "or":
            return await self._execute_or(node, context)
        return NodeResult(success=False, error=f"Unknown node type: {node.node_type}")

    # ------------------------------------------------------------------
    # Composite-node handlers
    # ------------------------------------------------------------------

    async def _execute_and(self, node: Any, context: RouterContext) -> NodeResult:
        """AND: parallel execution bounded by a concurrency semaphore.

        Each child receives a snapshot copy of ``context.completed`` so that
        sibling executions cannot observe each other's intermediate writes.
        After all children complete, their completed lists are merged into
        ``context.completed`` in child index order.

        If any child fails, a replan attempt is made (subject to budget).
        All partial outputs and trace paths from successful children are
        preserved regardless of failure.
        """
        sem = asyncio.Semaphore(self._max_concurrency)
        n = len(node.children)

        all_outputs: list[str] = [""] * n
        all_traces: list[list[str]] = [[] for _ in range(n)]
        child_completed: list[list[str]] = [[] for _ in range(n)]
        child_results: list[NodeResult | None] = [None] * n

        async def _run_child(idx: int, child: Any) -> None:
            async with sem:
                # Each child gets an isolated snapshot of completed so that
                # parallel siblings cannot mutate each other's view.
                child_ctx = RouterContext(
                    task=context.task,
                    completed=list(context.completed),
                    gui_agent=context.gui_agent,
                    tool_registry=context.tool_registry,
                    mcp_client=context.mcp_client,
                )
                result = await self.execute(child, child_ctx)
                child_results[idx] = result
                all_traces[idx] = list(result.trace_paths)
                if result.success:
                    all_outputs[idx] = result.output
                    if child.node_type == "atom":
                        child_completed[idx].append(child.instruction)

        await asyncio.gather(
            *[_run_child(i, c) for i, c in enumerate(node.children)],
            return_exceptions=False,
        )

        # Merge per-child completed lists into the shared context in child order
        # so the sequence is deterministic regardless of execution order.
        for cc in child_completed:
            context.completed.extend(cc)

        merged_traces: list[str] = [t for traces in all_traces for t in traces]
        merged_outputs: str = "\n".join(o for o in all_outputs if o)

        # Check for failures and attempt replan on the first one found.
        for i, result in enumerate(child_results):
            if result is None or result.success:
                continue
            if self._planner is not None and self._replan_count < self._max_replans:
                replan_result = await self._try_replan_and(
                    node=node,
                    failed_index=i,
                    failed_child=node.children[i],
                    context=context,
                    all_outputs=[o for o in all_outputs if o],
                    all_traces=merged_traces,
                )
                if replan_result is not None:
                    merged_traces.extend(replan_result.trace_paths)
                    if replan_result.success:
                        continue
            return NodeResult(
                success=False,
                output=merged_outputs,
                error=result.error or f"AND child {i} failed",
                trace_paths=merged_traces,
            )

        return NodeResult(success=True, output=merged_outputs, trace_paths=merged_traces)

    async def _execute_or(self, node: Any, context: RouterContext) -> NodeResult:
        """OR: try children in priority order (mcp > tool > gui) until one succeeds.

        Children are sorted by capability priority before iteration so that
        the most capable (lowest-latency / highest-fidelity) executor is
        always tried first regardless of the planner's output order.  Within
        the same capability tier the original child order is preserved via a
        stable sort.
        """
        all_traces: list[str] = []
        last_error: str | None = None

        # Stable sort by capability priority; ties preserve original order.
        sorted_children = sorted(
            node.children,
            key=lambda c: _CAPABILITY_PRIORITY.get(getattr(c, "capability", "gui"), 99),
        )

        for child in sorted_children:
            result = await self.execute(child, context)
            all_traces.extend(result.trace_paths)
            if result.success:
                if child.node_type == "atom":
                    context.completed.append(child.instruction)
                return NodeResult(success=True, output=result.output, trace_paths=all_traces)
            last_error = result.error

        # All children failed — attempt replan if budget remains.
        if self._planner is not None and self._replan_count < self._max_replans:
            self._replan_count += 1
            try:
                new_plan = await self._planner.replan(
                    context.task,
                    completed=context.completed,
                    failed="All OR alternatives failed",
                    remaining=[],
                )
                replan_result = await self.execute(new_plan, context)
                all_traces.extend(replan_result.trace_paths)
                return replan_result
            except Exception as exc:
                logger.warning("Replanning after OR failure failed: %s", exc)

        return NodeResult(
            success=False,
            error=last_error or "All OR children failed",
            trace_paths=all_traces,
        )

    # ------------------------------------------------------------------
    # ATOM dispatch
    # ------------------------------------------------------------------

    async def _dispatch_atom(self, node: Any, context: RouterContext) -> NodeResult:
        """Route an ATOM node to the appropriate executor by capability type."""
        capability = node.capability
        instruction = node.instruction
        logger.info("Dispatching ATOM: capability=%s, instruction=%r", capability, instruction)

        try:
            if capability == "gui":
                return await self._run_gui(instruction, context)
            if capability == "tool":
                return await self._run_tool(instruction, context)
            if capability == "mcp":
                return await self._run_mcp(instruction, context)
            if capability == "api":
                return NodeResult(success=False, error="API capability not yet implemented")
            return NodeResult(success=False, error=f"Unknown capability: {capability}")
        except Exception as exc:
            logger.error("ATOM dispatch failed: %s", exc)
            return NodeResult(success=False, error=str(exc))

    async def _run_gui(self, instruction: str, context: RouterContext) -> NodeResult:
        """Dispatch to ``GuiAgent.run()`` for GUI tasks."""
        if context.gui_agent is None:
            return NodeResult(success=False, error="No GuiAgent configured for GUI dispatch")
        result = await context.gui_agent.run(instruction, max_retries=1)
        return NodeResult(
            success=result.success,
            output=result.summary,
            error=result.error,
            trace_paths=[result.trace_path] if getattr(result, "trace_path", None) else [],
        )

    async def _run_tool(self, instruction: str, context: RouterContext) -> NodeResult:
        """Dispatch to ToolRegistry — placeholder until Phase 3."""
        if context.tool_registry is None:
            return NodeResult(success=False, error="No ToolRegistry configured for tool dispatch")
        return NodeResult(success=True, output=f"Tool executed: {instruction}")

    async def _run_mcp(self, instruction: str, context: RouterContext) -> NodeResult:
        """Dispatch to MCP client — placeholder until Phase 3."""
        if context.mcp_client is None:
            return NodeResult(success=False, error="No MCP client configured")
        return NodeResult(success=True, output=f"MCP executed: {instruction}")

    # ------------------------------------------------------------------
    # Replan helpers
    # ------------------------------------------------------------------

    async def _try_replan_and(
        self,
        node: Any,
        failed_index: int,
        failed_child: Any,
        context: RouterContext,
        all_outputs: list[str],
        all_traces: list[str],
    ) -> NodeResult | None:
        """Attempt to replan after an AND-child failure.

        Returns the result of executing the new plan, or *None* if replanning
        itself raised an exception.
        """
        self._replan_count += 1
        remaining = [
            c.instruction for c in node.children[failed_index + 1:] if c.node_type == "atom"
        ]
        failed_instruction = (
            failed_child.instruction
            if failed_child.node_type == "atom"
            else str(failed_child.to_dict())
        )
        try:
            new_plan = await self._planner.replan(
                context.task,
                completed=context.completed,
                failed=failed_instruction,
                remaining=remaining,
            )
            return await self.execute(new_plan, context)
        except Exception as exc:
            logger.warning("Replanning failed: %s", exc)
            return None
