---
phase: 02-agent-loop-integration
plan: "00"
subsystem: testing
tags: [pytest, xfail, stubs, tdd, wave0]

# Dependency graph
requires: []
provides:
  - "tests/test_opengui_p2_integration.py: 8 xfail stubs for AGENT-04/05/06, SKILL-08, TRAJ-03, TEST-05"
  - "tests/test_opengui_p2_memory.py: 2 xfail stubs for MEM-05"
affects:
  - 02-01
  - 02-02
  - 02-03
  - 02-04

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave 0 xfail stubs: pytest.mark.xfail(strict=False) + pytest.fail() body for pre-implementation placeholders"

key-files:
  created:
    - tests/test_opengui_p2_integration.py
    - tests/test_opengui_p2_memory.py
  modified: []

key-decisions:
  - "strict=False on xfail allows both xfail (stub present) and xpass (real implementation) to pass CI"
  - "pytest.fail() inside each stub ensures actual failure rather than silent skip — tests fail as expected failures"
  - "async def test_ functions with tmp_path fixture match Phase 2 async-first design pattern"

patterns-established:
  - "Wave 0 stubs pattern: create failing tests before any production code to enforce TDD compliance across waves"

requirements-completed: [TEST-05, AGENT-04, AGENT-05, AGENT-06, MEM-05, SKILL-08, TRAJ-03]

# Metrics
duration: 2min
completed: 2026-03-17
---

# Phase 2 Plan 00: Wave 0 Test Stubs Summary

**10 xfail pytest stubs covering all Phase 2 requirements (AGENT-04/05/06, MEM-05, SKILL-08, TRAJ-03, TEST-05) created before any production code**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-17T11:31:49Z
- **Completed:** 2026-03-17T11:31:56Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Created `tests/test_opengui_p2_integration.py` with 8 xfail stubs covering GuiAgent integration requirements: memory injection (AGENT-04), skill path selection (AGENT-05), free exploration fallback (AGENT-05), trajectory recording (AGENT-06/TRAJ-03), task planner decomposition (AGENT-04), router dispatch (AGENT-04/05/06), router replan on failure (AGENT-04), and full end-to-end flow (TEST-05)
- Created `tests/test_opengui_p2_memory.py` with 2 xfail stubs covering POLICY-always-included rule and memory context formatting (MEM-05)
- All 10 stubs collected by pytest, report XFAIL (not error, not skip, not pass), satisfying Nyquist compliance for Waves 1-3

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test stub files for all Phase 2 requirements** - `17a2777` (test)

**Plan metadata:** _(pending final commit)_

## Files Created/Modified

- `tests/test_opengui_p2_integration.py` - 8 async xfail stub tests for GuiAgent and main-agent integration requirements
- `tests/test_opengui_p2_memory.py` - 2 async xfail stub tests for MemoryStore/injection requirements

## Decisions Made

- Used `strict=False` on `@pytest.mark.xfail` so stubs report XFAIL when pytest.fail() is hit, and will also pass (XPASS allowed) when real implementations replace the stubs in Waves 1-3
- Used `pytest.fail("Not implemented — awaiting plan 02-0X + 02-04")` body to produce a concrete failure with informative message, rather than pytest.skip() which would silently skip
- Both files are async (async def) to match the Phase 2 async-first design pattern established in Phase 1

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 1-3 plans (02-01 through 02-04) can reference these stub files in their automated verify commands
- All 10 stubs will be made green by their corresponding plans:
  - 02-01 (Wave 1): memory format migration
  - 02-02 (Wave 2): GuiAgent integration (memory injection, skill path, trajectory)
  - 02-03 (Wave 2): TaskPlanner + TreeRouter (planner decompose, router dispatch/replan)
  - 02-04 (Wave 3): Full integration test (test_full_flow_with_mock_llm)
- No blockers for Wave 1 execution

---
*Phase: 02-agent-loop-integration*
*Completed: 2026-03-17*
