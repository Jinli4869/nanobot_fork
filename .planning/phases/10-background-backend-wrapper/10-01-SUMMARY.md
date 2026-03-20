---
phase: 10-background-backend-wrapper
plan: "01"
subsystem: testing
tags: [pytest-asyncio, AsyncMock, TDD, virtual-display, background-backend]

requires:
  - phase: 09-virtual-display-protocol
    provides: DisplayInfo, VirtualDisplayManager, NoOpDisplayManager (imported by test file)

provides:
  - "14-test TDD RED suite for BackgroundDesktopBackend covering BGND-01 through BGND-04"
  - "AsyncMock fixture factories _make_mock_manager and _make_mock_inner"
  - "Lifecycle guard, context manager, idempotent shutdown, DISPLAY env, and offset tests"

affects:
  - 10-02  # Plan 02 implements production code that makes these tests GREEN

tech-stack:
  added: []
  patterns:
    - "TDD RED: test file authored before production code is modified; tests that cover missing features fail immediately"
    - "_make_mock_manager/_make_mock_inner helper factories instead of pytest fixtures for inline flexibility"
    - "monkeypatch-free DISPLAY env tests using explicit try/finally save-restore"

key-files:
  created:
    - tests/test_opengui_p10_background.py
  modified: []

key-decisions:
  - "14 tests written (plan frontmatter said 13 — acceptance criteria list had 14 named functions including test_shutdown_stops_manager; implemented all)"
  - "test_display_env_restored_after_shutdown uses try/finally with original-value save to avoid test pollution without monkeypatch"
  - "pytest.raises match string uses escaped regex for '()' to match literal 'call preflight() or use async with before observe/execute'"

patterns-established:
  - "TDD RED pattern: create test file with failing tests before modifying production code"
  - "Helper factory functions (not pytest fixtures) return AsyncMock with PropertyMock for protocol-typed mocks"

requirements-completed:
  - BGND-01
  - BGND-02
  - BGND-03
  - BGND-04

duration: 4min
completed: "2026-03-20"
---

# Phase 10 Plan 01: BackgroundDesktopBackend Test Suite Summary

**14-test TDD RED suite for BackgroundDesktopBackend using AsyncMock factories, covering lifecycle guards, async context manager, DISPLAY env management, coordinate offsets, and idempotent error-suppressing shutdown**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-20T10:10:39Z
- **Completed:** 2026-03-20T10:14:23Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `tests/test_opengui_p10_background.py` with all required test functions covering BGND-01 through BGND-04
- Confirmed TDD RED state: 5 tests fail against current draft (lifecycle guard, context manager, idempotent shutdown, error suppression), 9 pass for already-implemented behavior
- Established `_make_mock_manager` and `_make_mock_inner` helper factories with correct PropertyMock pattern for `platform` attribute

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test file with all BGND test cases** - `22f1643` (test)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `tests/test_opengui_p10_background.py` — 285-line async test suite with 14 test functions organized into 4 BGND sections

## Decisions Made

- Implemented 14 tests (plan frontmatter listed "13" but the acceptance criteria enumerated 14 distinct function names — all were implemented)
- Used `try/finally` with saved `original = os.environ.get("DISPLAY")` for BGND-02 tests rather than `monkeypatch`, keeping tests consistent with Phase 9 style (no pytest fixture parameters in plain async test functions)
- `pytest.raises(RuntimeError, match="call preflight\\(\\) or use async with before observe/execute")` — regex-escaped parentheses to match the literal message string the production code will raise

## Deviations from Plan

None — plan executed exactly as written. The 14th test function (`test_shutdown_stops_manager`) was included because it appears explicitly in the plan's acceptance criteria despite the frontmatter count of 13.

## Issues Encountered

- Plan frontmatter `truths` stated "13 test functions" but acceptance criteria listed 14 named functions including `test_shutdown_stops_manager`, `test_shutdown_idempotent`, and `test_shutdown_suppresses_stop_error` as three distinct functions. Implemented all 14 as specified in the acceptance criteria — this is the authoritative source.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 02 can now implement `BackgroundDesktopBackend` production code against these 14 failing tests
- Required changes for GREEN: add lifecycle sentinel `_started: bool`, `__aenter__`/`__aexit__`, idempotent shutdown with `_stopped: bool`, DISPLAY env save/restore in `preflight()`/`shutdown()`, error suppression in `shutdown()`

## Self-Check: PASSED

- `tests/test_opengui_p10_background.py` — FOUND
- `10-01-SUMMARY.md` — FOUND
- Commit `22f1643` — FOUND

---
*Phase: 10-background-backend-wrapper*
*Completed: 2026-03-20*
