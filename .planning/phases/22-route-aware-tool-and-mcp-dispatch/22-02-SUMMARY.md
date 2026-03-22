---
phase: 22-route-aware-tool-and-mcp-dispatch
plan: 02
subsystem: nanobot/agent/router
tags: [fallback-dispatch, observability, routing, tdd, regression]
dependency_graph:
  requires: [22-01]
  provides: [fallback-chain-dispatch, gui-desktop-delegation, dispatch-observability]
  affects: [nanobot/agent/router.py]
tech_stack:
  added: []
  patterns: [fallback-chain, sentinel-route-id, tdd-red-green]
key_files:
  created: [tests/test_opengui_p22_route_dispatch.py (extended)]
  modified:
    - nanobot/agent/router.py
    - tests/test_opengui_p22_route_dispatch.py
    - tests/test_opengui_agent_loop.py
    - tests/test_opengui_p2_integration.py
decisions:
  - "_dispatch_with_fallback is shared between _run_tool and _run_mcp: once fallbacks are declared, the capability boundary is advisory and the best available route wins"
  - "gui.desktop is a sentinel route_id that delegates to _run_gui, not a registry entry; skipped with diagnostic when gui_agent is None"
  - "Multi-param routes (param_key=None) are silently skipped with a warning so the chain continues; prevents instruction-only dispatch for write_file/edit_file"
  - "_run_tool and _run_mcp delegate only when fallback_route_ids is non-empty to preserve the simple direct-dispatch path for atoms without fallbacks"
metrics:
  duration: 7 min
  completed: 2026-03-22
  tasks: 2
  files: 4
---

# Phase 22 Plan 02: Fallback Chain Dispatch and Regression Fix Summary

**One-liner:** Fallback chain dispatch via `_dispatch_with_fallback` wiring `gui.desktop` delegation, multi-param skip, and `planned_route`/`resolved_route`/`fallback_taken` observability into `_run_tool`/`_run_mcp`.

## Tasks Completed

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Implement `_dispatch_with_fallback` and wire into `_run_tool`/`_run_mcp` (TDD) | `3d3fed1`, `9fdabcf` | `nanobot/agent/router.py`, `tests/test_opengui_p22_route_dispatch.py` |
| 2 | Update Phase 8 regression tests and run full suite | `8e2134c` | `tests/test_opengui_agent_loop.py`, `tests/test_opengui_p2_integration.py` |

## What Was Built

### `_dispatch_with_fallback` method (router.py)

New method on `TreeRouter` that:
1. Collects `[route_id] + list(fallback_route_ids)` into a priority chain
2. Iterates route-by-route; tries each in order until one succeeds
3. Handles `gui.desktop` as a special sentinel — delegates to `_run_gui` if `gui_agent` is available, skips with diagnostic otherwise
4. Skips multi-param routes (`param_key is None`) so `write_file`/`edit_file` fall through to the next alternative
5. Logs `planned_route=`, `resolved_route=`, and `fallback_taken=` at every decision point
6. Returns structured `NodeResult(success=False)` listing all tried routes on exhaustion

### Dispatch delegation

Both `_run_tool` and `_run_mcp` now delegate to `_dispatch_with_fallback` when `node.fallback_route_ids` is non-empty. The simple (no-fallback) direct-dispatch path is preserved for atoms without fallbacks to avoid overhead.

### Observability

Every dispatch now logs:
- `planned_route=<route_id> fallbacks=[...]` at chain start
- `resolved_route=<route_id> tool=<tool_name>` for each successful resolution
- `fallback_taken=<route_id> (primary was <primary>)` when a non-primary route succeeds
- `route unavailable` / `requires structured parameters` / `failed: <output>` for skipped routes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed stale `_run_tool`/`_run_mcp` signature in regression tests**

- **Found during:** Task 2 full suite run
- **Issue:** Phase 22-01 changed `_run_tool`/`_run_mcp` from `(instruction: str, context)` to `(node: Any, context)`, but two pre-existing tests had stale fake functions still using the old `instruction: str` parameter. The test in `test_opengui_agent_loop.py` was already broken by 22-01 and was a latent regression.
- **Fix:**
  - `test_opengui_agent_loop.py::test_router_dispatches_planner_atoms_by_capability`: Updated `fake_tool` and `fake_mcp` to accept `node: Any` and use `node.instruction`
  - `test_opengui_p2_integration.py::test_router_dispatches_gui_and_tool_atoms`: Patched `_run_tool` at method level since the test is about AND-node routing behavior, not dispatch internals
- **Files modified:** `tests/test_opengui_agent_loop.py`, `tests/test_opengui_p2_integration.py`
- **Commits:** `8e2134c`

## Test Results

| Suite | Tests | Status |
|-------|-------|--------|
| `test_opengui_p22_route_dispatch.py` | 32 | PASS |
| `test_opengui_p8_planning.py` | 17 | PASS |
| `test_opengui_p21_planner_context.py` | 7 | PASS |
| Full project suite | 901 | PASS |

## Self-Check: PASSED

- `nanobot/agent/router.py` contains `async def _dispatch_with_fallback`
- `nanobot/agent/router.py` contains `route_id == "gui.desktop"` check
- `nanobot/agent/router.py` contains `context.gui_agent is None` guard
- `nanobot/agent/router.py` contains `param_key is None` check
- `nanobot/agent/router.py` `_run_tool` contains `self._dispatch_with_fallback(node, context)` call
- `nanobot/agent/router.py` `_run_mcp` contains `self._dispatch_with_fallback(node, context)` call
- Log strings `planned_route=`, `resolved_route=`, `fallback_taken=` all present
- 9 test functions with "fallback" in name + `test_multi_param_route_falls_back`
- Full suite: 901 passed
