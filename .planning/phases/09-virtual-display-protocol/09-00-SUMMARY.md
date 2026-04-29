---
phase: 09-virtual-display-protocol
plan: "00"
subsystem: testing
tags: [pytest, xfail, virtual-display, xvfb, tdd, wave-0]

# Dependency graph
requires: []
provides:
  - xfail test stubs for VirtualDisplayManager protocol (9 tests)
  - xfail/skip test stubs for XvfbDisplayManager error paths (12 tests)
  - test scaffolding enabling TDD in Plans 01 and 02
affects:
  - 09-01 (will replace xfail stubs with real assertions)
  - 09-02 (will replace xfail stubs with real Xvfb assertions)

# Tech tracking
tech-stack:
  added: []
  patterns: [Wave-0 xfail stub pattern — create test files before production code, guarded imports via try/except for modules not yet wired]

key-files:
  created:
    - tests/test_opengui_p9_virtual_display.py
    - tests/test_opengui_p9_xvfb.py
  modified: []

key-decisions:
  - "Use direct imports (no guard) in virtual_display stub file because draft virtual_display.py already exists with required classes"
  - "Use guarded try/except imports in xvfb stub file because XvfbNotFoundError and XvfbCrashedError are not defined until Plan 02 Task 1"
  - "module-level pytestmark with skipif + xfail for xvfb file so skipped tests don't surface as errors when error types missing"

patterns-established:
  - "Wave-0 stub pattern: create test files with @pytest.mark.xfail stubs before writing any production code to satisfy Nyquist sampling"
  - "Guarded imports with _IMPORTS_OK flag + pytestmark skipif for test files whose imports depend on not-yet-implemented code"

requirements-completed: [VDISP-01, VDISP-02, VDISP-03, VDISP-04]

# Metrics
duration: 0min
completed: 2026-03-20
---

# Phase 09 Plan 00: Virtual Display Wave-0 Stub Summary

**21 pytest xfail/skip stubs across two test files establishing TDD scaffold for VirtualDisplayManager protocol, DisplayInfo dataclass, NoOpDisplayManager, and XvfbDisplayManager before any production code is written.**

## Performance

- **Duration:** 0 min (files already created in prior commit)
- **Started:** 2026-03-20T07:19:11Z
- **Completed:** 2026-03-20T07:19:11Z
- **Tasks:** 1 of 1
- **Files modified:** 2

## Accomplishments

- Created `tests/test_opengui_p9_virtual_display.py` with 9 xfail stubs covering VDISP-01 (protocol), VDISP-02 (DisplayInfo), and VDISP-03 (NoOpDisplayManager)
- Created `tests/test_opengui_p9_xvfb.py` with 12 skip/xfail stubs covering VDISP-04 (XvfbDisplayManager error paths and lifecycle)
- All 21 tests run clean: 9 xfailed + 12 skipped — zero errors, zero unexpected failures

## Task Commits

1. **Task 1: Create xfail test stubs for virtual_display.py and xvfb.py** - `6583154` (test)

**Plan metadata:** (this commit)

## Files Created/Modified

- `tests/test_opengui_p9_virtual_display.py` - 9 xfail stubs for protocol importability, DisplayInfo fields/defaults/frozen, and NoOpDisplayManager start/stop behaviour
- `tests/test_opengui_p9_xvfb.py` - 12 skip/xfail stubs for XvfbDisplayManager isinstance check, start/stop lifecycle, error types, auto-increment display selection, and crash detection

## Decisions Made

- Used direct imports (without guard) in the virtual_display test file because `opengui/backends/virtual_display.py` already exists with the required classes at Wave-0 time.
- Used guarded `try/except` imports in the xvfb test file because `XvfbNotFoundError` and `XvfbCrashedError` are not defined until Plan 02 Task 1 — the guard plus `pytestmark` `skipif` prevents collection errors.
- Applied `pytestmark` (module-level) for xvfb tests instead of per-function decorators, which cleanly combines `skipif` and `xfail` in one place.

## Deviations from Plan

None - plan executed exactly as written. Test stub files were created in the prior commit `6583154` (which predates this execution context due to previous planning work). Verification confirmed all 21 tests produce xfail/skip results with no errors.

## Issues Encountered

- Pre-existing failure in `tests/test_tool_validation.py::test_exec_head_tail_truncation` due to `python` command not available on macOS (only `python3`). This is a pre-existing environment issue unrelated to Phase 09 changes. Logged to deferred items, not fixed.

## Next Phase Readiness

- Wave-0 scaffolding complete: Plans 01 and 02 can now replace stubs with real assertions without creating test files from scratch
- `tests/test_opengui_p9_virtual_display.py` ready for Plan 01 to fill in protocol/DisplayInfo/NoOp assertions
- `tests/test_opengui_p9_xvfb.py` ready for Plan 02 to fill in XvfbDisplayManager assertions once error types are defined

---
*Phase: 09-virtual-display-protocol*
*Completed: 2026-03-20*
