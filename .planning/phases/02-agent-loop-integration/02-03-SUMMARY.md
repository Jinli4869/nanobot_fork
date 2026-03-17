---
phase: 02-agent-loop-integration
plan: 03
status: complete
started: 2026-03-17
completed: 2026-03-17
---

## What was built

Created the main-agent-level TaskPlanner and TreeRouter for AND/OR/ATOM task decomposition and dispatch.

### Task 1: TaskPlanner module

- `PlanNode` frozen dataclass with `node_type` (and/or/atom), `instruction`, `capability`, `children`
- Full `to_dict()`/`from_dict()` serialization roundtrip
- `_CREATE_PLAN_TOOL` definition for LLM function calling
- `TaskPlanner.plan()` — single LLM call with forced `create_plan` tool, fallback to single ATOM on failure
- `TaskPlanner.replan()` — provides completed/failed/remaining context for replanning after failure
- Injects SKILL.md capability registry into system prompt when SkillsLoader is available

### Task 2: TreeRouter module

- `NodeResult` dataclass with success/output/error/trace_paths
- `RouterContext` dataclass with task, completed list, and executor references (gui_agent, tool_registry, mcp_client)
- `TreeRouter.execute()` — recursive tree walker dispatching by node type
- AND semantics: sequential execution, fail-fast with optional replan
- OR semantics: try alternatives, replan if all fail
- `_dispatch_atom()` routes by capability: gui→GuiAgent.run(), tool→placeholder, mcp→placeholder
- Shared replan budget (default 2) across entire tree execution

## Key files

### key-files.created
- `nanobot/agent/planner.py` — TaskPlanner with AND/OR/ATOM tree decomposition
- `nanobot/agent/router.py` — TreeRouter with capability-type dispatch

### key-files.modified
- (none)

## Commits
- `4e68724` feat(02-03): add TaskPlanner with AND/OR/ATOM tree decomposition
- `9046466` feat(02-03): add TreeRouter with capability-type dispatch and replanning

## Deviations
None.

## Self-Check: PASSED
- [x] TaskPlanner.plan() returns PlanNode tree via LLM create_plan tool
- [x] TaskPlanner.replan() accepts completed/failed/remaining context
- [x] PlanNode.from_dict()/to_dict() round-trip correctly
- [x] TreeRouter.execute() recursively walks AND/OR/ATOM trees
- [x] ATOM dispatch routes gui→GuiAgent, tool→ToolRegistry, mcp→MCP
- [x] AND: sequential, fail-fast with optional replan
- [x] OR: try alternatives, replan if all fail
