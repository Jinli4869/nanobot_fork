---
phase: 14-windows-isolated-desktop-execution
plan: "05"
subsystem: infra
tags: [windows, win32, desktop, worker-rpc, isolated-execution]
requires:
  - phase: 12-background-runtime-contracts
    provides: shared isolated-runtime leasing and backend-name dispatch
provides:
  - real Win32 alternate-desktop handle ownership
  - worker-routed Windows observe/execute/list-apps RPC
  - deterministic worker-first cleanup ordering for isolated Windows runs
affects: [phase-16-host-integration-and-verification, windows-background-execution]
tech-stack:
  added: []
  patterns: [ctypes Win32 wrappers, JSON-lines worker RPC, worker-before-desktop cleanup]
key-files:
  created: []
  modified:
    - opengui/backends/displays/win32desktop.py
    - opengui/backends/windows_worker.py
    - opengui/backends/windows_isolated.py
    - tests/test_opengui_p14_windows_desktop.py
key-decisions:
  - "Windows isolated desktop runs now treat the child worker as the only desktop IO boundary; the parent backend no longer observes or executes against the host desktop."
  - "Win32 support probing now uses session, input-desktop, and create-desktop API checks instead of hard-coded Windows availability booleans."
patterns-established:
  - "Windows alternate-desktop lifecycle is owned by Win32DesktopManager via patchable wrapper methods so non-Windows CI can validate handle semantics safely."
  - "WindowsIsolatedBackend shutdown always sends worker shutdown, waits/stops the process, closes pipes, unlinks control state, then releases the desktop handle."
requirements-completed: [WIN-01, WIN-03]
duration: 4min
completed: 2026-03-21
---

# Phase 14 Plan 05: Windows Worker Desktop Routing Summary

**Real Win32 desktop ownership with worker-routed observe/execute/list-apps calls and deterministic worker-before-desktop cleanup**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-21T02:10:12+08:00
- **Completed:** 2026-03-21T02:14:40+08:00
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added red-phase coverage for real desktop-handle ownership, JSON-line worker RPC behavior, parent-backend IO isolation, and shutdown ordering.
- Replaced the synthetic Windows desktop manager with patchable Win32 wrappers for desktop creation, closing, input-desktop probing, and session detection.
- Implemented a functioning worker command loop and routed isolated Windows observe/execute/list-apps calls through worker RPC with explicit cleanup ordering.

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend the Phase 14 test suite with real desktop-handle and worker-routing contracts** - `ae4b6bb` (test)
2. **Task 2: Implement the real Win32 desktop lifecycle and worker-routed Windows isolated backend** - `7deb329` (feat)

**Plan metadata:** Pending final docs commit

## Files Created/Modified

- `opengui/backends/displays/win32desktop.py` - Owns real Win32 desktop handles and probes interactive-session support via Win32 APIs.
- `opengui/backends/windows_worker.py` - Launches the Windows child with live pipes and services JSON-line observe/execute/list-apps/shutdown commands.
- `opengui/backends/windows_isolated.py` - Routes isolated desktop IO through worker RPC and enforces worker-stop then desktop-stop cleanup.
- `tests/test_opengui_p14_windows_desktop.py` - Encodes the real-handle, worker-loop, parent-IO isolation, and cleanup-order regression contracts.

## Decisions Made

- Windows isolated desktop IO now belongs exclusively to the child worker so the parent backend cannot accidentally act on the user’s primary desktop.
- The Windows desktop support probe now validates real session/input/create-desktop prerequisites before advertising isolated support.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- One red-phase assertion incorrectly expected `desktop_name` to remain populated after `stop()`. The test was corrected during Task 2 because the plan requires manager state to clear after close is attempted.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Windows isolated execution now has the real alternate-desktop seam that later host-integration work can wire and verify.
- `WIN-02` target-app-class plumbing remains for later Phase 14/16 host-entry work; this plan intentionally focused on the execution seam and cleanup contracts.

## Self-Check: PASSED

- Found `.planning/phases/14-windows-isolated-desktop-execution/14-windows-isolated-desktop-execution-05-SUMMARY.md`
- Found task commits `ae4b6bb` and `7deb329` in git history
