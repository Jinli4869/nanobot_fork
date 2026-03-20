---
phase: 09-virtual-display-protocol
plan: "02"
subsystem: infra
tags: [xvfb, asyncio, subprocess, virtual-display, linux, pytest, mocking]

# Dependency graph
requires:
  - phase: 09-virtual-display-protocol/09-00
    provides: Wave-0 xfail stubs for xvfb tests (test_opengui_p9_xvfb.py)
provides:
  - Production-ready XvfbDisplayManager with error types, auto-increment, stderr pipe, crash detection
  - XvfbNotFoundError and XvfbCrashedError exception types in opengui.backends.displays.xvfb
  - Convenience re-export via opengui.backends.displays.__init__
  - 12 unit tests with fully mocked subprocess (no real Xvfb needed in CI)
affects: [10-background-execution, opengui-backends]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio.wait_for() wraps polling loop for clean timeout enforcement"
    - "stderr=asyncio.subprocess.PIPE (not DEVNULL) for crash diagnostics"
    - "Lock file pre-check (/tmp/.XN-lock) before subprocess launch for collision avoidance"
    - "returncode is not None sentinel for process liveness during socket polling"
    - "Safe stderr drain: only read after process.wait() returns"
    - "_patch_path_exists() test helper: simulates lock files and X11 sockets via pathlib.Path.exists patch"

key-files:
  created:
    - opengui/backends/displays/xvfb.py
    - opengui/backends/displays/__init__.py
  modified:
    - tests/test_opengui_p9_xvfb.py

key-decisions:
  - "XvfbCrashedError propagates directly (not caught in retry loop); only lock-file presence triggers auto-increment"
  - "TimeoutError from _try_start() propagates to caller directly — timeout is not a collision signal, no retry"
  - "_poll_socket() is a separate coroutine so asyncio.wait_for() can cancel it cleanly on timeout"
  - "stop() drains stderr after wait() for shutdown diagnostics, logged at DEBUG level if non-empty"
  - "wait() helper in test mock does NOT mutate proc.returncode — shared mock stays reusable across retry attempts"

patterns-established:
  - "AsyncMock subprocess mock with _make_process() factory: pid, returncode, stderr.read(), terminate(), wait()"
  - "Path.exists() patching via _patch_path_exists(locked_displays, socket_ready_for) for filesystem simulation"

requirements-completed: [VDISP-04]

# Metrics
duration: 5min
completed: 2026-03-20
---

# Phase 09 Plan 02: XvfbDisplayManager Summary

**XvfbDisplayManager production implementation with XvfbNotFoundError/XvfbCrashedError, lock-file auto-increment, stderr=PIPE, crash detection, and 12 unit tests using mocked asyncio subprocess**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-20T07:21:29Z
- **Completed:** 2026-03-20T07:26:22Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added XvfbNotFoundError and XvfbCrashedError exception types to xvfb.py with actionable install hint
- Refactored start() into retry loop + _try_start() + _poll_socket() with asyncio.wait_for() for timeout
- Changed stderr from DEVNULL to PIPE; crash detection in poll loop; stderr drain in stop()
- Added convenience re-export in opengui/backends/displays/__init__.py for Phase 10 consumers
- Replaced all 12 xfail stubs with full pytest-asyncio tests; full suite 642 tests green

## Task Commits

Each task was committed atomically:

1. **Task 1: Add error types, auto-increment, stderr capture, crash detection, __init__.py re-export** - `24e2626` (feat)
2. **Task 2: Fill in test implementations for XvfbDisplayManager with mocked subprocess** - `37c4bfa` (test)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `opengui/backends/displays/xvfb.py` - Production XvfbDisplayManager; XvfbNotFoundError, XvfbCrashedError; auto-increment; stderr=PIPE; crash detection; asyncio.wait_for timeout
- `opengui/backends/displays/__init__.py` - Convenience re-export of XvfbDisplayManager
- `tests/test_opengui_p9_xvfb.py` - 12 unit tests covering all VDISP-04 behaviors with mocked subprocess

## Decisions Made
- **XvfbCrashedError propagates directly**: The retry loop (auto-increment) only activates on lock file pre-check. If a process actually crashes, the error propagates directly to the caller rather than being swallowed into a RuntimeError wrapper. This keeps error semantics clean: lock collision → retry; crash → propagate.
- **TimeoutError not retried**: A startup timeout is not a collision indicator. Retrying on timeout would multiply the wait time (5 retries × timeout = 25s worst case). TimeoutError propagates directly from _try_start().
- **_poll_socket() as separate coroutine**: Enables asyncio.wait_for() to cancel the coroutine cleanly on timeout without needing manual elapsed-time tracking.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed XvfbCrashedError retry semantics**
- **Found during:** Task 2 (test_xvfb_crash_detection test)
- **Issue:** Initial implementation caught XvfbCrashedError in the retry loop, then wrapped all retries in RuntimeError. Plan spec requires XvfbCrashedError to propagate directly.
- **Fix:** Removed try/except XvfbCrashedError from retry loop; _try_start() errors propagate directly. Only lock file presence (continue statement) causes retry iteration.
- **Files modified:** opengui/backends/displays/xvfb.py
- **Verification:** test_xvfb_crash_detection passes; test_xvfb_auto_increment_all_locked still passes
- **Committed in:** 37c4bfa (Task 2 commit, xvfb.py updated alongside tests)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Fix required for correct error semantics per plan spec. No scope creep.

## Issues Encountered
- `_make_process` helper's `wait()` coroutine originally mutated `proc.returncode = 0`, causing shared mock to carry over state across retry iterations in `test_xvfb_start_timeout`. Fixed by making `wait()` return without mutation, keeping returncode at its initial value throughout test lifetime.

## User Setup Required
None - no external service configuration required. All tests mock at the asyncio.create_subprocess_exec boundary; no real Xvfb binary needed.

## Next Phase Readiness
- `from opengui.backends.displays.xvfb import XvfbDisplayManager` ready for Phase 10 (BackgroundDesktopBackend)
- `from opengui.backends.displays import XvfbDisplayManager` convenience import available
- All VDISP-04 behaviors tested and verified
- isinstance(XvfbDisplayManager(), VirtualDisplayManager) returns True

---
*Phase: 09-virtual-display-protocol*
*Completed: 2026-03-20*
