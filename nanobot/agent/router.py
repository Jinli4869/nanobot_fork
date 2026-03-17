"""TreeRouter: walks AND/OR/ATOM plan trees and dispatches ATOM nodes by capability type."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


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

    AND nodes execute children sequentially. On failure the router may
    trigger replanning through an optional :class:`TaskPlanner`.

    OR nodes try children in order until one succeeds. If all fail,
    replanning is attempted before reporting failure.
    """

    def __init__(self, planner: Any = None, max_replans: int = 2) -> None:
        self._planner = planner
        self._max_replans = max_replans
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
        """AND: all children sequentially, fail-fast with optional replan."""
        all_outputs: list[str] = []
        all_traces: list[str] = []

        for i, child in enumerate(node.children):
            result = await self.execute(child, context)
            all_traces.extend(result.trace_paths)

            if result.success:
                all_outputs.append(result.output)
                if child.node_type == "atom":
                    context.completed.append(child.instruction)
                continue

            # Child failed — attempt replan if budget remains.
            if self._planner is not None and self._replan_count < self._max_replans:
                replan_result = await self._try_replan_and(
                    node, i, child, context, all_outputs, all_traces,
                )
                if replan_result is not None:
                    all_traces.extend(replan_result.trace_paths)
                    if replan_result.success:
                        all_outputs.append(replan_result.output)
                        continue

            return NodeResult(
                success=False,
                output="\n".join(all_outputs),
                error=result.error or f"AND child {i} failed",
                trace_paths=all_traces,
            )

        return NodeResult(success=True, output="\n".join(all_outputs), trace_paths=all_traces)

    async def _execute_or(self, node: Any, context: RouterContext) -> NodeResult:
        """OR: try children until one succeeds."""
        all_traces: list[str] = []
        last_error: str | None = None

        for child in node.children:
            result = await self.execute(child, context)
            all_traces.extend(result.trace_paths)
            if result.success:
                if child.node_type == "atom":
                    context.completed.append(child.instruction)
                return NodeResult(success=True, output=result.output, trace_paths=all_traces)
            last_error = result.error

        # All children failed — attempt replan.
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
        """Attempt to replan after an AND-child failure.  Returns *None* on replan error."""
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
