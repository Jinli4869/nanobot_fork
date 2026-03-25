---
phase: quick
plan: 260325-l2b
subsystem: agent/planning
tags: [planner, routing, gui, adb, capabilities, backend-aware]
dependency_graph:
  requires: []
  provides: [PlanningContext.active_gui_route, backend-aware CapabilityCatalogBuilder, gui.adb router dispatch]
  affects: [nanobot/agent/capabilities.py, nanobot/agent/loop.py, nanobot/agent/planner.py, nanobot/agent/router.py]
tech_stack:
  added: []
  patterns: [backend-derived route sentinel, planner directive injection, router GUI sentinel expansion]
key_files:
  created: []
  modified:
    - nanobot/agent/capabilities.py
    - nanobot/agent/loop.py
    - nanobot/agent/planner.py
    - nanobot/agent/router.py
    - tests/test_opengui_p21_planner_context.py
decisions:
  - "PlanningContext.active_gui_route carries the session's GUI route_id; empty string means planner uses self-judgment (no regression)"
  - "CapabilityCatalogBuilder.build() accepts gui_backend kwarg; gui_backend='adb' overrides route_id/kind/summary in the loop without changing _ROUTE_SPECS class constant"
  - "active_gui_route derivation: adb->gui.adb, local/dry-run->gui.desktop (local does NOT produce gui.local)"
  - "Router _dispatch_with_fallback handles gui.adb sentinel same as gui.desktop via set membership check"
  - "Planner prompt directive is unambiguous: names the concrete route_id and prohibits other gui.* alternatives"
metrics:
  duration: 4 min
  completed: 2026-03-25
  tasks: 3
  files_changed: 5
---

# Phase quick Plan 260325-l2b: Planner PlanningContext Active Backend P Summary

**One-liner:** Backend-aware GUI route selection so planner emits `gui.adb` vs `gui.desktop` based on `GuiConfig.backend`, with explicit prompt directive and router sentinel expansion.

## What Was Built

The planner previously always emitted `gui.desktop` for GUI subtasks because it had no awareness of which backend was active. This caused GUI subtasks to be routed incorrectly when the target was an Android device via ADB.

Three layers were updated to propagate backend awareness:

1. **PlanningContext** (`nanobot/agent/capabilities.py`) - Added `active_gui_route: str = ""` field. `CapabilityCatalogBuilder.build()` accepts `gui_backend` kwarg. When `gui_backend="adb"`, the gui_task route is emitted as `gui.adb` with ADB-specific kind/summary.

2. **AgentLoop** (`nanobot/agent/loop.py`) - Reads `self._gui_config.backend`, passes it to `CapabilityCatalogBuilder`, derives `active_gui_route` (adb->gui.adb, local/dry-run->gui.desktop), and passes it into `PlanningContext`.

3. **TaskPlanner** (`nanobot/agent/planner.py`) - Injects "Active GUI route" directive into the system prompt when `active_gui_route` is set, giving an unambiguous override for all GUI subtasks.

4. **TreeRouter** (`nanobot/agent/router.py`) - `_dispatch_with_fallback` now handles `gui.adb` as a GUI sentinel alongside `gui.desktop`, delegating both to `_run_gui`. Log messages use the actual route_id.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 4704cff | feat: add active_gui_route to PlanningContext and backend-aware catalog |
| 2 | 326f00a | feat: wire active_gui_route through AgentLoop and inject planner directive |
| 3 | b2b7daf | test: add regression tests for active_gui_route planner and catalog behavior |

## Tests

14 tests pass (7 pre-existing + 7 new):

New tests added to `tests/test_opengui_p21_planner_context.py`:
- `test_capability_catalog_builder_adb_backend_emits_gui_adb_route` - adb backend emits gui.adb not gui.desktop
- `test_capability_catalog_builder_local_backend_emits_gui_desktop_route` - local backend emits gui.desktop
- `test_capability_catalog_builder_default_backend_emits_gui_desktop_route` - default (omitted kwarg) emits gui.desktop
- `test_planning_context_active_gui_route_defaults_empty` - active_gui_route defaults to ""
- `test_planner_prompt_includes_active_gui_route_directive` - prompt contains "Active GUI route" and "route_id='gui.adb'"
- `test_planner_prompt_omits_active_gui_route_when_empty` - no directive when active_gui_route is empty
- `test_router_dispatches_gui_adb_sentinel_to_run_gui` - router calls gui_agent.run() for gui.adb atoms

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- [x] `nanobot/agent/capabilities.py` - modified, PlanningContext has active_gui_route field
- [x] `nanobot/agent/loop.py` - modified, passes gui_backend and active_gui_route
- [x] `nanobot/agent/planner.py` - modified, injects "Active GUI route" directive
- [x] `nanobot/agent/router.py` - modified, handles gui.adb sentinel
- [x] `tests/test_opengui_p21_planner_context.py` - modified, 7 new tests all pass
- [x] Commits 4704cff, 326f00a, b2b7daf exist in git log
- [x] 14/14 tests pass in test_opengui_p21_planner_context.py
- [x] Pre-existing test failure (test_gui_tool_builds_memory_retriever_from_default_opengui_dir) confirmed pre-dates this plan, logged as out-of-scope
