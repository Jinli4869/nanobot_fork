---
phase: 10-background-backend-wrapper
plan: "02"
subsystem: backends
tags: [virtual-display, background-backend, lifecycle-guard, async-context-manager, DISPLAY-env, idempotent-shutdown]

requires:
  - phase: 10-background-backend-wrapper/10-01
    provides: "14-test TDD RED suite for BackgroundDesktopBackend covering BGND-01 through BGND-04"
  - phase: 09-virtual-display-protocol
    provides: DisplayInfo, VirtualDisplayManager, NoOpDisplayManager

provides:
  - "Production BackgroundDesktopBackend satisfying DeviceBackend protocol via structural conformance"
  - "Lifecycle guard (_assert_started) raising RuntimeError on observe/execute before preflight"
  - "Async context manager (__aenter__/__aexit__) calling preflight/shutdown automatically"
  - "DISPLAY env save/restore using _SENTINEL sentinel to distinguish unset from None"
  - "Idempotent shutdown with _stopped flag and exception suppression from display_manager.stop()"

affects:
  - 11  # Phase 11 wires BackgroundDesktopBackend into CLI and nanobot config

tech-stack:
  added: []
  patterns:
    - "Sentinel pattern: _SENTINEL = object() distinguishes 'never set' from None for env var restore"
    - "TYPE_CHECKING import for DeviceBackend eliminates type:ignore[union-attr] on delegation calls"
    - "Idempotent shutdown with boolean flag + warning log + exception suppression for best-effort cleanup"
    - "Async context manager delegates to preflight/shutdown — no duplicated lifecycle logic"

key-files:
  created:
    - opengui/backends/background.py
  modified: []

key-decisions:
  - "_SENTINEL: object = object() with explicit type annotation used over bare _SENTINEL = object() — equally correct, better typed"
  - "DeviceBackend imported under TYPE_CHECKING only — avoids circular import risk while enabling correct type annotations"
  - "shutdown() suppresses all exceptions from display_manager.stop() (logger.exception) then always sets _stopped = True and restores env — cleanup never propagates"
  - "No started property added — _display_info is None check in _assert_started is the sole lifecycle gate"

patterns-established:
  - "Sentinel for optional env var save: _original_display: str | None | object = _SENTINEL tracks pre-preflight state before any mutation"
  - "Structural protocol conformance: no class BackgroundDesktopBackend(DeviceBackend) — duck typing via matching method signatures only"

requirements-completed:
  - BGND-01
  - BGND-02
  - BGND-03
  - BGND-04

duration: 3min
completed: "2026-03-20"
---

# Phase 10 Plan 02: BackgroundDesktopBackend Production Implementation Summary

**Production BackgroundDesktopBackend with lifecycle guard, async context manager, sentinel-based DISPLAY env save/restore, and idempotent error-suppressing shutdown — all 14 BGND tests green**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-20T10:17:02Z
- **Completed:** 2026-03-20T10:20:07Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Rewrote `opengui/backends/background.py` from 95-line draft to 178-line production implementation
- Added `_assert_started()` lifecycle guard that raises `RuntimeError("call preflight() or use async with before observe/execute")` when `observe()`/`execute()` called before `preflight()`
- Added `__aenter__`/`__aexit__` for async context manager support with automatic preflight/shutdown
- Implemented sentinel-based DISPLAY save/restore: `_original_display` initialized to `_SENTINEL`, set to `os.environ.get("DISPLAY")` at preflight, restored or deleted at shutdown
- Implemented idempotent `shutdown()` with `_stopped: bool` guard, `logger.warning` on repeat calls, and `try/except Exception` suppressing `display_manager.stop()` failures
- Fixed `inner` type annotation from `inner: object` to `inner: DeviceBackend` under `TYPE_CHECKING` — removed all `# type: ignore[union-attr]` comments
- All 14 BGND tests pass; 663 total tests green, zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Refine BackgroundDesktopBackend with all locked decisions** - `6f2778d` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `opengui/backends/background.py` — 178-line production BackgroundDesktopBackend with full lifecycle management, structural DeviceBackend conformance, sentinel DISPLAY save/restore, and idempotent shutdown

## Decisions Made

- Used `_SENTINEL: object = object()` (with explicit type annotation) rather than bare `_SENTINEL = object()`. Both are semantically identical; the annotated form is preferable for type checkers and clarity.
- `DeviceBackend` imported under `TYPE_CHECKING` only. This avoids potential circular import issues (interfaces.py already imports from virtual_display.py) while providing full type annotations for the `inner` parameter.
- `shutdown()` catches `Exception` broadly (not just specific types) to match the "best-effort cleanup" contract — unknown exceptions from a crashed Xvfb process should not propagate to callers.
- Did not add a public `started` property — the plan left this to discretion, and the `_assert_started()` guard provides all necessary lifecycle enforcement internally.

## Deviations from Plan

None — plan executed exactly as written. The `_SENTINEL: object = object()` annotation form is a minor stylistic improvement over the plan's suggested `_SENTINEL = object()`, but is fully compatible with all acceptance criteria.

## Issues Encountered

None — the draft had clean separation of concerns; refinement was straightforward. All 14 tests passed on first implementation attempt.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `BackgroundDesktopBackend` is production-ready for Phase 11 wiring
- Phase 11 can instantiate `BackgroundDesktopBackend(LocalDesktopBackend(), XvfbDisplayManager(...))` from CLI and nanobot config
- `GuiAgent` calls `backend.preflight()` before the loop and reads `backend.platform` — both are correctly delegated

## Self-Check: PASSED

- `opengui/backends/background.py` — FOUND
- `.planning/phases/10-background-backend-wrapper/10-02-SUMMARY.md` — FOUND
- Commit `6f2778d` — FOUND

---
*Phase: 10-background-backend-wrapper*
*Completed: 2026-03-20*
