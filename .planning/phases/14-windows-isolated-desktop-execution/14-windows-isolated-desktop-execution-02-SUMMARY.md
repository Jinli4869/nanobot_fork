---
phase: 14-windows-isolated-desktop-execution
plan: 02
subsystem: backend
tags: [windows, isolated-desktop, lpDesktop, lifecycle]
requires:
  - phase: 14-01
    provides: Windows probe taxonomy and Win32DesktopManager lifecycle contract
provides:
  - WindowsIsolatedBackend with explicit worker/session cleanup ownership
  - launch_windows_worker helper that binds child creation to WinSta0\\{desktop_name}
  - Phase 14 lifecycle tests for launch routing, observe/execute reuse, cancellation, and startup failure
affects: [phase-14, cli, nanobot, windows]
tech-stack:
  added: []
  patterns: [dedicated Windows isolated backend, worker launch seam, explicit cleanup reasons]
key-files:
  created:
    - opengui/backends/windows_isolated.py
    - opengui/backends/windows_worker.py
  modified:
    - tests/test_opengui_p14_windows_desktop.py
key-decisions:
  - "Windows isolated runs use a dedicated backend instead of BackgroundDesktopBackend so worker launch, routing, and cleanup stay desktop-aware."
  - "The worker launch seam is import-safe on non-Windows hosts but still encodes STARTUPINFO.lpDesktop for Windows process creation."
patterns-established:
  - "Windows isolated lifecycle owns runtime lease, desktop manager, worker session, and target-display cleanup in one object."
  - "Cancellation and startup failures map to explicit cleanup_reason values and rely on idempotent shutdown."
requirements-completed: [WIN-01, WIN-03]
duration: 6 min
completed: 2026-03-20
---

# Phase 14 Plan 02: Windows Isolated Desktop Execution Summary

**Windows isolated backend lifecycle with lpDesktop worker launch, target-desktop routing helpers, and deterministic cleanup reasons**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-20T16:37:28Z
- **Completed:** 2026-03-20T16:43:38Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added RED lifecycle coverage for named-desktop worker launch, shared target-desktop routing, cancellation cleanup, and startup-failure cleanup.
- Implemented `WindowsIsolatedBackend` as the Windows-specific isolated execution seam with runtime lease ownership, worker session helpers, readiness logging, and idempotent shutdown.
- Added `launch_windows_worker()` with `STARTUPINFO.lpDesktop` wiring and kept the module import-safe on non-Windows hosts so CI can exercise the contract.

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend the Phase 14 test file with Windows isolated backend lifecycle coverage** - `7d8c873` (`test`)
2. **Task 2: Implement `WindowsIsolatedBackend` with explicit cleanup reasons and target-surface logging** - `720fe38` (`feat`)

## Files Created/Modified
- `opengui/backends/windows_isolated.py` - Dedicated Windows isolated backend with worker/session lifecycle ownership.
- `opengui/backends/windows_worker.py` - Worker launch helper that binds child creation to `lpDesktop`.
- `tests/test_opengui_p14_windows_desktop.py` - Phase 14 lifecycle coverage for launch routing and cleanup behavior.

## Decisions Made
- Used a Windows-only backend instead of extending `BackgroundDesktopBackend`, because alternate-desktop ownership and worker launch are not process-global display concerns.
- Logged `backend_name`, `display_id`, `desktop_name`, `lpDesktop`, and `cleanup_reason` directly from the isolated backend so later CLI and nanobot wiring can surface the same metadata.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- A transient `.git/index.lock` appeared when staging and committing in parallel. Retrying the commit sequentially resolved it without modifying repo state.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Windows isolated lifecycle ownership is in place and verified by the Phase 14 desktop slice (`9 passed`).
- Phase 14-03 can now wire CLI and nanobot through `WindowsIsolatedBackend` and reuse the cleanup/logging contract.

## Self-Check: PASSED

- Found summary file at `.planning/phases/14-windows-isolated-desktop-execution/14-windows-isolated-desktop-execution-02-SUMMARY.md`.
- Verified task commits `7d8c873` and `720fe38` exist in git history.
