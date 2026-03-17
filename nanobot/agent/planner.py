"""TaskPlanner: decomposes tasks into AND/OR/ATOM execution trees via a single LLM call."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

NodeType = Literal["and", "or", "atom"]
CapabilityType = Literal["gui", "tool", "mcp", "api"]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanNode:
    """A node in the AND/OR/ATOM execution tree.

    AND nodes execute all children sequentially; replanning is triggered on
    any child failure.  OR nodes try children in order until one succeeds;
    replanning is triggered only when all alternatives fail.  ATOM nodes are
    leaf tasks — they carry an ``instruction`` string and a ``capability``
    tag that tells the router which executor to use.
    """

    node_type: NodeType
    instruction: str = ""               # populated for ATOM nodes only
    capability: CapabilityType = "tool"  # populated for ATOM nodes only
    children: tuple[PlanNode, ...] = field(default_factory=tuple)  # populated for AND/OR only

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        d: dict[str, Any] = {"type": self.node_type}
        if self.node_type == "atom":
            d["instruction"] = self.instruction
            d["capability"] = self.capability
        else:
            d["children"] = [child.to_dict() for child in self.children]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanNode:
        """Deserialize from a JSON dict produced by :meth:`to_dict`."""
        node_type: NodeType = data["type"]
        if node_type == "atom":
            return cls(
                node_type="atom",
                instruction=data.get("instruction", ""),
                capability=data.get("capability", "tool"),
            )
        children = tuple(cls.from_dict(child) for child in data.get("children", []))
        return cls(node_type=node_type, children=children)


# ---------------------------------------------------------------------------
# LLM tool definition
# ---------------------------------------------------------------------------

_CREATE_PLAN_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": (
            "Decompose a user task into an AND/OR/ATOM execution tree. "
            "AND nodes execute all children sequentially. "
            "OR nodes try children until one succeeds. "
            "ATOM nodes are leaf tasks with a capability type (gui/tool/mcp/api)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tree": {
                    "type": "object",
                    "description": (
                        "Root node.  Each node has 'type' (and/or/atom). "
                        "AND/OR nodes have a 'children' array.  "
                        "ATOM nodes have 'instruction' (string) and "
                        "'capability' (gui/tool/mcp/api)."
                    ),
                }
            },
            "required": ["tree"],
        },
    },
}

# ---------------------------------------------------------------------------
# TaskPlanner
# ---------------------------------------------------------------------------

class TaskPlanner:
    """Decomposes tasks into AND/OR/ATOM execution trees via a single LLM call.

    The planner issues one LLM call with the ``create_plan`` tool forced on.
    It optionally reads SKILL.md files through a ``SkillsLoader`` to inform
    the LLM about available capabilities before requesting the decomposition.

    Usage::

        planner = TaskPlanner(llm=my_llm, skills_loader=skills)
        tree: PlanNode = await planner.plan("Turn on Wi-Fi and check weather")
    """

    def __init__(self, llm: Any, skills_loader: Any = None) -> None:
        """
        Args:
            llm: An LLM provider that exposes an async ``chat()`` method
                 accepting ``messages``, ``tools``, and ``tool_choice`` kwargs.
            skills_loader: Optional :class:`~nanobot.agent.skills.SkillsLoader`
                           instance for reading the capability registry.
        """
        self._llm = llm
        self._skills_loader = skills_loader

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def plan(self, task: str, *, context: str = "") -> PlanNode:
        """Decompose *task* into an execution tree.

        Args:
            task: The user's task description.
            context: Optional additional context (e.g. current state summary,
                     list of already-completed subtasks).

        Returns:
            Root :class:`PlanNode` of the execution tree.

        Note:
            If the LLM fails to call ``create_plan`` (e.g. model misbehaves),
            the method falls back to a single ATOM node with capability ``gui``
            so that execution can always proceed.
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(task, context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.debug("Requesting plan for task: %r", task)

        response = await self._llm.chat(
            messages=messages,
            tools=[_CREATE_PLAN_TOOL],
            tool_choice={"type": "function", "function": {"name": "create_plan"}},
        )

        if not response.tool_calls:
            logger.warning("LLM did not call create_plan; falling back to single ATOM node")
            return PlanNode(node_type="atom", instruction=task, capability="gui")

        args = response.tool_calls[0].arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                logger.warning("create_plan arguments are not valid JSON; using fallback ATOM")
                return PlanNode(node_type="atom", instruction=task, capability="gui")

        tree_data = args.get("tree", {"type": "atom", "instruction": task, "capability": "gui"})
        try:
            return PlanNode.from_dict(tree_data)
        except (KeyError, TypeError) as exc:
            logger.warning("Failed to parse plan tree: %s; using fallback ATOM", exc)
            return PlanNode(node_type="atom", instruction=task, capability="gui")

    async def replan(
        self,
        task: str,
        *,
        completed: list[str],
        failed: str,
        remaining: list[str],
    ) -> PlanNode:
        """Replan after a failure, providing context about completed and failed work.

        Args:
            task: The original top-level task.
            completed: Instructions of successfully completed subtasks.
            failed: Instruction (or description) of the subtask that failed.
            remaining: Instructions of subtasks that were not yet attempted.

        Returns:
            A new root :class:`PlanNode` for continued execution.
        """
        context_lines: list[str] = []
        if completed:
            context_lines.append("Completed subtasks:\n" + "\n".join(f"- {c}" for c in completed))
        context_lines.append(f"Failed subtask: {failed}")
        if remaining:
            context_lines.append("Remaining subtasks:\n" + "\n".join(f"- {r}" for r in remaining))
        context = "\n\n".join(context_lines)
        logger.debug("Replanning task %r after failure of %r", task, failed)
        return await self.plan(task, context=context)

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the planner system prompt, injecting the capability registry."""
        lines = [
            "You are a task planner. Decompose the user's task into an AND/OR/ATOM execution tree.",
            "",
            "Node types:",
            "- AND: all children must succeed, executed sequentially.  If one fails, replanning occurs.",
            "- OR: try children in order until one succeeds.  If all fail, replanning occurs.",
            "- ATOM: a single actionable subtask.  Must have 'instruction' (what to do) and "
            "'capability' (how to do it).",
            "",
            "Capability types:",
            "- gui: interact with a device screen (tap, type, swipe, navigate apps)",
            "- tool: use a local tool or function",
            "- mcp: call an MCP server tool",
            "- api: make a direct API call",
            "",
            "Rules:",
            "- Simple tasks should be a single ATOM (no unnecessary AND/OR wrapping).",
            "- Use AND for tasks that require sequential steps.",
            "- Use OR for tasks with alternative approaches.",
            "- Each ATOM instruction should be a clear, focused, single-step subgoal.",
            "- Choose the capability type based on the available capabilities listed below.",
        ]

        # Inject summary lines from SKILL.md files when a loader is available.
        if self._skills_loader is not None:
            try:
                skills = self._skills_loader.list_skills()
                if skills:
                    lines.extend(["", "Available capabilities:"])
                    for skill_info in skills:
                        content = self._skills_loader.load_skill(skill_info["name"])
                        if content:
                            # Use first non-empty lines as a lightweight summary.
                            summary_lines = [ln for ln in content.splitlines() if ln.strip()][:3]
                            summary = " ".join(summary_lines)
                            lines.append(f"- {skill_info['name']}: {summary}")
            except Exception as exc:  # pragma: no cover — graceful degradation
                logger.warning("Failed to load skills for planner prompt: %s", exc)

        lines.extend(["", "Call the create_plan tool with your decomposition."])
        return "\n".join(lines)

    def _build_user_prompt(self, task: str, context: str) -> str:
        """Build the user prompt, optionally including prior-execution context."""
        parts = [f"Task: {task}"]
        if context:
            parts.extend(["", "Context:", context])
        return "\n".join(parts)
