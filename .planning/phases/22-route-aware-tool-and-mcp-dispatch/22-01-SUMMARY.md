---
phase: 22-route-aware-tool-and-mcp-dispatch
plan: 01
subsystem: agent
tags: [router, tool-dispatch, mcp, registry, route-resolution]

# Dependency graph
requires:
  - phase: 21-capability-aware-planning
    provides: PlanNode with route_id/fallback_route_ids fields and CapabilityCatalog
  - phase: 18-chat-workspace
    provides: ToolRegistry with has() and execute() interface

provides:
  - _ROUTE_ID_TO_TOOL_NAME mapping 7 local tool route IDs to registry keys
  - _INSTRUCTION_PARAM mapping 5 single-param tools to their parameter key names
  - _resolve_route() function mapping planner route_ids to (tool_name, param_key)
  - Real _run_tool() dispatching tool atoms through ToolRegistry.execute()
  - Real _run_mcp() dispatching mcp atoms through ToolRegistry.execute()
  - Structured NodeResult failure diagnostics for unrouted/unavailable/multi-param atoms
  - 23 Phase 22 route dispatch tests

affects:
  - 22-02-PLAN.md (agent-loop wiring that calls TreeRouter with real registry)
  - any future phase that adds new tool route IDs or MCP servers

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Route resolution table pattern: _ROUTE_ID_TO_TOOL_NAME + _INSTRUCTION_PARAM dicts decouple planner IDs from registry keys"
    - "Multi-param guard: tools requiring structured input return (tool_name, None) from _resolve_route, preventing incorrect instruction-only dispatch"
    - "Unified MCP dispatch through ToolRegistry: mcp atoms use tool_registry (not mcp_client) since MCP tools are pre-wrapped as mcp_{server}_{tool} registry keys"

key-files:
  created:
    - tests/test_opengui_p22_route_dispatch.py
  modified:
    - nanobot/agent/router.py

key-decisions:
  - "Route resolution uses two lookup tables (_ROUTE_ID_TO_TOOL_NAME, _INSTRUCTION_PARAM) instead of a single combined map so that multi-param tools can be represented cleanly with a None param_key"
  - "MCP dispatch routes through context.tool_registry (not context.mcp_client) because MCPToolWrapper pre-registers mcp_{server}_{tool} keys in the shared registry — mcp_client field is kept for backward compatibility"
  - "_run_tool and _run_mcp both accept full PlanNode (not instruction string) so route_id and fallback_route_ids are available for resolution and future fallback logic"

patterns-established:
  - "Route ID format: tool.{capability}.{subtype} for local tools, mcp.{server}.{tool} for MCP tools"
  - "Error detection: output strings starting with 'Error' from ToolRegistry.execute() are surfaced as NodeResult(success=False)"

requirements-completed: [CAP-03, CAP-04]

# Metrics
duration: 4min
completed: 2026-03-22
---

# Phase 22 Plan 01: Route-Aware Tool and MCP Dispatch Summary

**Route resolution tables and real ToolRegistry dispatch replacing placeholder _run_tool/_run_mcp in TreeRouter, with 23 tests covering resolver, tool dispatch, MCP dispatch, and failure diagnostics**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-22T09:15:50Z
- **Completed:** 2026-03-22T09:19:50Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `_ROUTE_ID_TO_TOOL_NAME` (7 entries) and `_INSTRUCTION_PARAM` (5 entries) route mapping tables to `router.py`
- Implemented `_resolve_route()` handling local `tool.*` routes and `mcp.{server}.{tool}` MCP routes with registry availability checks
- Replaced placeholder `_run_tool` and `_run_mcp` with real `ToolRegistry.execute()` dispatch including structured failure diagnostics and INFO-level logging
- 23 tests covering all resolver cases, dispatch paths, logging assertions, and regression preservation of 17 existing Phase 8 tests

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Route resolver tests** - `2a2b89b` (test)
2. **Task 1 GREEN: Route tables and _resolve_route()** - `0914954` (feat)
3. **Task 2 GREEN: Real _run_tool/_run_mcp dispatch** - `b2cc9cf` (feat)

_Note: TDD tasks had separate RED/GREEN commits. REFACTOR phase not needed — code was clean after GREEN._

## Files Created/Modified

- `nanobot/agent/router.py` — Added `_ROUTE_ID_TO_TOOL_NAME`, `_INSTRUCTION_PARAM`, `_resolve_route()`, replaced placeholder `_run_tool`/`_run_mcp`, updated `_dispatch_atom` to pass full node
- `tests/test_opengui_p22_route_dispatch.py` — 23 tests: 11 resolver, 12 dispatch (tool, MCP, logging, node-passing)

## Decisions Made

- Route resolution uses two separate lookup tables instead of one combined map so that multi-parameter tools (write_file, edit_file) can be cleanly represented with a `None` param_key, avoiding a special-case code path in the dispatch logic.
- MCP dispatch goes through `context.tool_registry` (not `context.mcp_client`) because MCPToolWrapper pre-registers all MCP tools as `mcp_{server}_{tool}` keys — `mcp_client` is kept for backward compatibility but is unused in dispatch.
- Both `_run_tool` and `_run_mcp` signatures now accept the full `PlanNode` instead of `instruction: str` so route_id and fallback_route_ids are available at dispatch time without requiring callers to destructure.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Route resolution and real ToolRegistry dispatch are complete; Phase 22 Plan 02 can wire the AgentLoop to build a RouterContext with the live ToolRegistry and pass it to TreeRouter.execute().
- All 17 existing Phase 8 tests still pass — no regressions.

## Self-Check: PASSED

All files found and all commits verified.

---
*Phase: 22-route-aware-tool-and-mcp-dispatch*
*Completed: 2026-03-22*
