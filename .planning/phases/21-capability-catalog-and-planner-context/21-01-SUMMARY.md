---
phase: 21-capability-catalog-and-planner-context
plan: "01"
subsystem: planner
tags: [planner, routing, tool-registry, mcp, testing]
requires:
  - phase: 20-web-app-integration-and-verification
    provides: packaged nanobot runtime and stable planner/loop seams
provides:
  - live planner-time capability catalog built from the current tool registry
  - backward-compatible plan-node route metadata fields
  - route-aware planner prompt guidance and human-readable planning logs
affects: [22-route-aware-tool-and-mcp-dispatch, 23-routing-memory-feedback-and-verification]
tech-stack:
  added: []
  patterns: [last-responsible-moment planning context assembly, allowlisted route summaries, optional route metadata]
key-files:
  created:
    - nanobot/agent/capabilities.py
    - tests/test_opengui_p21_planner_context.py
  modified:
    - nanobot/agent/planner.py
    - nanobot/agent/loop.py
    - tests/test_opengui_p8_planning.py
key-decisions:
  - "PlanningContext now wraps planner-only inputs so future memory hints can extend planning without another planner API break."
  - "Capability catalogs are built from an allowlisted live route inventory instead of dumping raw tool schemas into the planner prompt."
  - "Route metadata stays optional on PlanNode and is exposed in logs only; router dispatch behavior remains unchanged until Phase 22."
patterns-established:
  - "Build planner context immediately before TaskPlanner.plan() from the live ToolRegistry and runtime config."
  - "Surface route identity in both prompt guidance and formatted plan trees while preserving legacy plan payload compatibility."
requirements-completed: [CAP-01]
duration: 24min
completed: 2026-03-22
---

# Phase 21 Plan 01: Capability Catalog And Planner Context Summary

**Planner-time route cataloging with optional PlanNode route metadata and route-aware decomposition logs**

## Performance

- **Duration:** 24 min
- **Started:** 2026-03-22T07:31:00Z
- **Completed:** 2026-03-22T07:54:59Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Added `CapabilityCatalogBuilder`, `RouteSummary`, `CapabilityCatalog`, and `PlanningContext` so the planner can reason over live route summaries instead of coarse capability labels alone.
- Extended `PlanNode` with optional `route_id`, `route_reason`, and `fallback_route_ids` while preserving legacy payload parsing and serialization.
- Wired `AgentLoop._plan_and_execute()` to build planner context from the live registry, pass it into `TaskPlanner.plan(...)`, and expose route labels in formatted planning logs.

## Task Commits

Each task was committed atomically:

1. **Task 1: Define the capability-catalog contracts and failing route-selection coverage** - `b179d56` (test), `ce9b6bf` (feat)
2. **Task 2: Build the live catalog and wire route metadata into planner prompts and logs** - `c873d59` (test), `f19e365` (feat)

## Files Created/Modified
- `nanobot/agent/capabilities.py` - planner-only route summary DTOs, prompt serialization helpers, and live catalog builder
- `nanobot/agent/planner.py` - optional route metadata on `PlanNode` plus `planning_context` prompt plumbing and route-aware tool guidance
- `nanobot/agent/loop.py` - live planning-context construction and route-aware plan tree formatting
- `tests/test_opengui_p21_planner_context.py` - Phase 21 catalog and planner-prompt coverage
- `tests/test_opengui_p8_planning.py` - regression coverage for route metadata compatibility and route-aware planner logging

## Decisions Made
- `TaskPlanner.plan(...)` now accepts `planning_context` directly instead of reusing the broader agent context path, keeping the planner prompt bounded and phase-local.
- Planner routes are serialized as compact summaries with stable IDs like `gui.desktop`, `tool.exec_shell`, and `mcp.<server>.<tool>`, which keeps prompt text inspectable and deterministic.
- Route-aware logging is limited to planner visibility in this phase; execution continues to dispatch only by coarse capability type.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `git add` intermittently hit a transient `.git/index.lock` during staging. The lock cleared on immediate retry and did not require any repository cleanup or code changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- CAP-01 is now satisfied with live route inventory, backward-compatible plan metadata, and inspectable planner logs.
- The `PlanningContext` seam is ready for Phase 21-02 to add bounded routing-memory hints without changing the planner entrypoint again.

## Self-Check: PASSED
- Found summary file on disk.
- Verified task commits `b179d56`, `ce9b6bf`, `c873d59`, and `f19e365` in git history.
