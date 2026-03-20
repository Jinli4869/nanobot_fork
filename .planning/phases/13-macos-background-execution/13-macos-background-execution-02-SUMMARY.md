---
phase: 13-macos-background-execution
plan: "02"
subsystem: desktop-routing
tags: [macos, background, desktop, displayinfo, mss, routing, testing]

requires:
  - phase: 13-macos-background-execution
    provides: "CGVirtualDisplayManager and macOS capability/runtime contract from Plan 01"
  - phase: 10-background-backend-wrapper
    provides: "Wrapper-owned display environment and coordinate-offset translation seam"

provides:
  - "Target-display-aware monitor selection for LocalDesktopBackend.observe()"
  - "Wrapper injection and cleanup of DisplayInfo metadata on inner desktop backends"
  - "Green routing tests proving observe and execute stay aligned on macOS isolated surfaces"

affects:
  - 13-03
  - 13-04
  - 16

tech-stack:
  added: []
  patterns:
    - "Monitor selection lives in the desktop backend while global offset translation stays wrapper-owned"
    - "Background wrappers pass immutable DisplayInfo metadata into inner backends through a narrow optional seam"

key-files:
  created: []
  modified:
    - opengui/backends/background.py
    - opengui/backends/desktop.py
    - tests/test_opengui_p13_macos_display.py
    - tests/test_opengui_p4_desktop.py

key-decisions:
  - "Added configure_target_display() as a narrow optional hook on LocalDesktopBackend instead of pushing display-manager knowledge deeper into action execution."
  - "Kept coordinate offset application exclusively in BackgroundDesktopBackend so monitor selection and absolute coordinate translation remain single-purpose responsibilities."
  - "Expanded the desktop mss mock helper to exercise non-primary monitor capture without disturbing existing Linux-path tests."

patterns-established:
  - "Observe path chooses monitor_index from DisplayInfo when configured, otherwise it preserves the primary-monitor default"
  - "Wrapper lifecycle injects target-display metadata on preflight and clears it on shutdown to avoid stale background state leaking into later foreground runs"

requirements-completed:
  - MAC-03
  - MAC-01

duration: 5min
completed: "2026-03-20"
---

# Phase 13 Plan 02 Summary

**macOS background capture and input now share one target-surface contract through monitor-aware observe routing and wrapper-owned offset translation**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-20T15:18:21Z
- **Completed:** 2026-03-20T15:23:05Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added `configure_target_display()` and monitor-index-aware screenshot capture to `LocalDesktopBackend`.
- Wired `BackgroundDesktopBackend` to inject active `DisplayInfo` metadata before inner preflight and clear it during shutdown.
- Proved observe/execute alignment with green macOS routing tests while preserving the existing desktop regression set.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add target-display-aware observe behavior to LocalDesktopBackend** - `35054dc` (`feat`)
2. **Task 2: Inject DisplayInfo from the wrapper and prove observe/execute alignment** - `06116c1` (`feat`)

## Files Created/Modified
- `opengui/backends/desktop.py` - adds target display storage, `configure_target_display()`, and monitor-index-aware screenshot capture
- `tests/test_opengui_p4_desktop.py` - extends the mss helper and adds primary-vs-configured monitor coverage
- `opengui/backends/background.py` - injects and clears target-display metadata around wrapper lifecycle events
- `tests/test_opengui_p13_macos_display.py` - adds wrapper-routing tests for preflight ordering and offset-aligned execution

## Decisions Made

- Monitor selection moved only into `observe()` so action coordinate resolution remains unchanged inside the local desktop backend.
- The wrapper owns all absolute offset translation, keeping the inner backend unaware of global macOS display offsets.
- Target-display metadata is cleared on shutdown so later non-background runs cannot inherit stale monitor routing.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

The initial helper extraction in `background.py` satisfied the runtime behavior but missed the plan's literal acceptance grep for `configure_target_display(self._display_info)` and `configure_target_display(None)`. The calls were inlined immediately and the targeted pytest command was rerun green.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 13 now has a stable target-surface routing seam across capture and input. Wave 3 can build on this by exposing the macOS backend selection and runtime messaging through CLI and nanobot entry points.

## Self-Check: PASSED

- `opengui/backends/desktop.py` - FOUND
- `opengui/backends/background.py` - FOUND
- `tests/test_opengui_p4_desktop.py` - FOUND
- `tests/test_opengui_p13_macos_display.py` - FOUND

---
*Phase: 13-macos-background-execution*
*Completed: 2026-03-20*
