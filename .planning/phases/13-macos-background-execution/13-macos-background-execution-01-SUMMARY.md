---
phase: 13-macos-background-execution
plan: "01"
subsystem: background-runtime
tags: [macos, cgvirtualdisplay, pyobjc, runtime, testing]

requires:
  - phase: 12-background-runtime-contracts
    provides: "Shared probe, remediation, and mode-resolution contract for background runs"
  - phase: 09-virtual-display-protocol
    provides: "DisplayInfo and VirtualDisplayManager abstraction used by macOS display lifecycle"

provides:
  - "macOS capability probing with stable reason codes and remediation text"
  - "A concrete CGVirtualDisplayManager surface for isolated macOS background execution"
  - "Green Phase 13 contract tests for probe and manager lifecycle behavior"
  - "macOS-only PyObjC dependency markers in desktop/dev extras"

affects:
  - 13-02
  - 13-03
  - 14

tech-stack:
  added: []
  patterns:
    - "Lazy macOS runtime imports keep Linux CI safe while adding platform-specific behavior"
    - "Patchable helper boundaries for host-specific runtime probing and virtual-display lifecycle tests"

key-files:
  created:
    - opengui/backends/displays/cgvirtualdisplay.py
  modified:
    - opengui/backends/background_runtime.py
    - opengui/backends/displays/__init__.py
    - pyproject.toml
    - tests/test_opengui_p13_macos_display.py

key-decisions:
  - "Extended the shared runtime contract with macOS-specific reason codes while preserving the Linux Xvfb branch unchanged."
  - "Implemented CGVirtualDisplayManager with lazy macOS imports and patchable internal lifecycle helpers so Phase 13 tests stay CI-safe off macOS."
  - "Added PyObjC packages behind darwin environment markers in optional dependencies instead of forcing them on all platforms."

patterns-established:
  - "macOS host capability checks flow through background_runtime.py, not through CLI or nanobot-specific platform branching"
  - "Platform-native display managers expose DisplayInfo metadata and keep their OS-specific discovery isolated behind internal helper methods"

requirements-completed:
  - MAC-01
  - MAC-02

duration: 12min
completed: "2026-03-20"
---

# Phase 13 Plan 01 Summary

**macOS background capability probing now resolves through shared runtime reason codes, a concrete `CGVirtualDisplayManager`, and green contract tests that stay safe off macOS hosts**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-20T15:05:00Z
- **Completed:** 2026-03-20T15:17:16Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Added Wave 0 contract tests for Phase 13 and promoted them to green coverage.
- Extended `background_runtime.py` with macOS probe dispatch, stable macOS reason codes, and remediation mapping.
- Added `CGVirtualDisplayManager` plus macOS-only dependency markers in `pyproject.toml`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Wave 0 macOS contract tests before production edits** - `6c5c717` (`test`)
2. **Task 2: Implement macOS probe taxonomy, dependency markers, and CGVirtualDisplayManager** - `9fd83cf` (`feat`)

## Files Created/Modified
- `opengui/backends/displays/cgvirtualdisplay.py` - new macOS isolated-display manager surface with lazy runtime helpers
- `opengui/backends/background_runtime.py` - macOS probe dispatch and remediation reason-code support
- `opengui/backends/displays/__init__.py` - exports `CGVirtualDisplayManager`
- `pyproject.toml` - adds darwin-gated PyObjC extras for desktop/dev installs
- `tests/test_opengui_p13_macos_display.py` - green contract coverage for supported, unsupported, remediation, and manager lifecycle behavior

## Decisions Made

- macOS support is reported through the existing shared probe contract instead of adding ad hoc host-entry logic.
- `CGVirtualDisplayManager` keeps Quartz/PyObjC access lazy and patchable so Linux collection and CI remain stable.
- Environment markers are the packaging boundary for PyObjC dependencies, avoiding cross-platform install churn.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

The earlier delegated executor stalled after creating the Wave 0 test file, so execution fell back inline. No codework was lost; the partial test scaffold was verified, committed, and then promoted to green in the normal task flow.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 13 now has a real macOS isolated-display contract and test seam. Wave 2 can build directly on this by injecting `DisplayInfo` into the inner desktop backend and aligning monitor capture with wrapper offset translation.

## Self-Check: PASSED

- `opengui/backends/displays/cgvirtualdisplay.py` - FOUND
- `opengui/backends/background_runtime.py` - FOUND
- `tests/test_opengui_p13_macos_display.py` - FOUND

---
*Phase: 13-macos-background-execution*
*Completed: 2026-03-20*
