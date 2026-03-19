---
phase: 08-dead-export-cleanup
plan: 02
subsystem: agent
tags: [asyncio, semaphore, parallel, priority, router, planner, tdd]

requires:
  - phase: 08-dead-export-cleanup-01
    provides: TreeRouter, PlanNode, RouterContext types established

provides:
  - Parallel AND execution via asyncio.gather bounded by configurable semaphore
  - Per-child RouterContext isolation (snapshot, no shared-list mutation)
  - OR node priority sorting: mcp > tool > gui with stable tie-breaking
  - 8 new tests covering parallel AND and prioritized OR behaviors

affects:
  - 08-03 (AgentLoop integration — depends on TreeRouter parallel AND and OR priority)

tech-stack:
  added: [asyncio (stdlib, imported for gather + Semaphore)]
  patterns:
    - Semaphore-bounded asyncio.gather for parallel subtask execution
    - Per-child context snapshot to prevent mutation during concurrent execution
    - Module-level priority dict for stable capability ordering

key-files:
  created:
    - tests/test_opengui_p8_planning.py
  modified:
    - nanobot/agent/router.py

key-decisions:
  - "max_concurrency defaults to 3 so production workloads get parallelism without overwhelming executors"
  - "Per-child RouterContext snapshot (list copy) prevents shared-list mutation; merge happens in index order after gather for deterministic completed list"
  - "Stable sort on capability priority preserves planner output order within the same capability tier"
  - "asyncio.gather(return_exceptions=False) used so unhandled exceptions propagate rather than silently swallowing failures"

patterns-established:
  - "Semaphore pattern: asyncio.Semaphore wraps each child coroutine inside gather for backpressure control"
  - "Snapshot isolation: RouterContext(completed=list(context.completed)) gives each child a clean slate"
  - "Ordered merge: per-child completed lists merged after gather in child index order for reproducibility"

requirements-completed: []

duration: 4min
completed: 2026-03-19
---

# Phase 8 Plan 02: Enhanced TreeRouter — Parallel AND and Prioritized OR Summary

**asyncio.gather-based parallel AND execution with semaphore concurrency control and mcp > tool > gui priority sorting for OR nodes in TreeRouter**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-19T12:05:24Z
- **Completed:** 2026-03-19T12:09:21Z
- **Tasks:** 2 (TDD — each had RED commit + GREEN commit)
- **Files modified:** 2

## Accomplishments

- AND nodes now execute all children concurrently via `asyncio.gather` bounded by a `max_concurrency` semaphore (default 3)
- Each AND child receives an isolated `RouterContext` snapshot so sibling executions cannot see each other's in-progress `completed` entries; lists merged back in index order after gather
- OR nodes sort children by capability priority (`mcp=0 > tool=1 > gui=2 > api=3`) using a stable sort before iterating, so the best executor is always tried first regardless of planner output order
- 8 new tests covering: parallel all-succeed, max_concurrency=1 serialisation, failure-triggers-replan, no-shared-list-mutation, OR priority ordering, same-capability order preservation, auto-fallback, all-fail error reporting

## Task Commits

1. **RED tests (Tasks 1 + 2)** - `684aa4d` (test)
2. **GREEN implementation (Tasks 1 + 2)** - `e49a328c` (feat)

## Files Created/Modified

- `nanobot/agent/router.py` — Added `import asyncio`, `_CAPABILITY_PRIORITY` dict, `max_concurrency` param, parallel `_execute_and`, sorted `_execute_or`
- `tests/test_opengui_p8_planning.py` — 8 new tests for parallel AND and prioritized OR behaviors

## Decisions Made

- `max_concurrency=3` as default: low enough to avoid overwhelming downstream executors, high enough to benefit most multi-step plans
- Per-child `RouterContext` snapshot (shallow `list(context.completed)`) chosen over deep copy for efficiency — `completed` is a flat list of strings so shallow copy is sufficient
- `asyncio.gather(return_exceptions=False)` so uncaught child exceptions surface immediately rather than silently polluting the results list
- Stable sort on `_CAPABILITY_PRIORITY` preserves planner-intended order within same capability tier

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `StopIteration` in `test_or_priority_order` test**
- **Found during:** Task 2 (GREEN phase — first test run)
- **Issue:** `next(i for i, x in enumerate(...))` inside an `async def` raises `RuntimeError: coroutine raised StopIteration` in Python 3.7+ when the generator is exhausted inside an async coroutine
- **Fix:** Replaced `next()` generator expression with a direct `assert dispatch_order[0].startswith("mcp:")` check plus `assert not any(x.startswith("gui:") ...)` — conceptually equivalent but generator-free
- **Files modified:** `tests/test_opengui_p8_planning.py`
- **Verification:** `pytest tests/test_opengui_p8_planning.py -x -q` passes 8/8
- **Committed in:** e49a328c (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — Bug in test)
**Impact on plan:** Minor test-code fix only; no production code affected.

## Issues Encountered

- One pre-existing test ordering flakiness observed when running the full suite in a particular collection order: `test_opengui_p8_trajectory.py::test_planner_router_exported_from_agent_package` sometimes failed due to import side-effects from test discovery order. Verified the test passes in isolation and in direct pairing — not caused by our changes; pre-existing cross-test contamination unrelated to this plan.

## Next Phase Readiness

- TreeRouter now provides parallel AND execution and prioritized OR — both are prerequisites for Phase 8 Plan 03 (AgentLoop integration)
- `max_concurrency` parameter is surfaced on `TreeRouter.__init__` so AgentLoop can configure it via dependency injection

---
*Phase: 08-dead-export-cleanup*
*Completed: 2026-03-19*

## Self-Check: PASSED

All files verified:
- `nanobot/agent/router.py` — exists
- `tests/test_opengui_p8_planning.py` — exists
- `.planning/phases/08-dead-export-cleanup/08-02-SUMMARY.md` — exists
- Commit `684aa4d` (RED tests) — exists
- Commit `e49a328c` (GREEN implementation) — exists
