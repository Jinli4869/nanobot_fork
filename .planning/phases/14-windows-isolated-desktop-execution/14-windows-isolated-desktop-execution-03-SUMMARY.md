---
phase: 14-windows-isolated-desktop-execution
plan: "03"
subsystem: integration
tags: [windows, background-runtime, cli, nanobot, testing]
requires:
  - phase: 14-01
    provides: "Windows runtime probe taxonomy and Win32DesktopManager contract"
  - phase: 14-02
    provides: "WindowsIsolatedBackend worker lifecycle and cleanup metadata"
provides:
  - "CLI dispatch for windows_isolated_desktop via probe.backend_name"
  - "Nanobot dispatch for windows_isolated_desktop via probe.backend_name"
  - "Integration coverage for Windows unsupported-context remediation and cleanup metadata"
affects: [15-intervention-safety-and-handoff, 16-host-integration-and-verification]
tech-stack:
  added: []
  patterns: [probe.backend_name host dispatch, wrapped backend shutdown in finally, preserved JSON failure metadata]
key-files:
  created: []
  modified: [opengui/cli.py, nanobot/agent/tools/gui.py, tests/test_opengui_p5_cli.py, tests/test_opengui_p11_integration.py]
key-decisions:
  - "Both host entry points dispatch isolated execution from probe.backend_name instead of raw platform branching."
  - "Nanobot preserves cleanup_reason= and display_id= tokens by returning RuntimeError text through the existing background JSON failure payload."
patterns-established:
  - "Host integrations choose isolated backend wrappers from the shared runtime contract, not from sys.platform checks after probing."
  - "Windows isolated runs use WindowsIsolatedBackend directly while Linux/macOS continue through BackgroundDesktopBackend."
requirements-completed: [WIN-01, WIN-02, WIN-03]
duration: 4min
completed: 2026-03-20
---

# Phase 14 Plan 03: Windows Isolated Host Wiring Summary

**CLI and nanobot now route Windows isolated desktop runs through `WindowsIsolatedBackend`, with shared remediation ordering and cleanup metadata preserved in host-facing outputs**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-20T16:53:23Z
- **Completed:** 2026-03-20T16:57:10Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added CLI dispatch for `backend_name="windows_isolated_desktop"` with `Win32DesktopManager` and `WindowsIsolatedBackend`.
- Added nanobot dispatch for the same Windows isolated backend while preserving existing blocked/fallback JSON semantics.
- Added integration tests for Windows isolated mode, unsupported app-class/non-interactive remediation ordering, and cleanup metadata reporting.

## Task Commits

1. **Task 1: Wire the CLI through `Win32DesktopManager` and `WindowsIsolatedBackend`** - `d48abca` (test), `eb4a278` (feat)
2. **Task 2: Wire nanobot through the same Windows isolated backend and preserve JSON failure semantics** - `8c12d7c` (test), `5bed070` (feat)

**Plan metadata:** pending docs commit at summary creation

_Note: TDD tasks used test → feat commits._

## Files Created/Modified
- `opengui/cli.py` - adds Windows isolated manager selection and backend wrapping in the CLI path.
- `nanobot/agent/tools/gui.py` - adds Windows isolated manager selection, wrapper dispatch, and RuntimeError-to-JSON handling.
- `tests/test_opengui_p5_cli.py` - covers CLI Windows isolated dispatch, remediation ordering, and target-surface metadata logging.
- `tests/test_opengui_p11_integration.py` - covers nanobot Windows isolated dispatch, blocked non-interactive JSON, and cleanup metadata preservation.

## Decisions Made
- Use `probe.backend_name` as the only post-probe selection key in both host entry points so Phase 12/14 runtime contracts stay aligned.
- Keep Windows on `WindowsIsolatedBackend` directly and leave Linux/macOS on `BackgroundDesktopBackend` to preserve the existing wrapper contract where it still fits.
- Convert Windows startup `RuntimeError`s into nanobot background JSON failures without rewriting the message so cleanup diagnostics survive into the host response.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `git commit` hit a transient `.git/index.lock` twice; the lock cleared on immediate retry and no cleanup action was required.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 14 host entry points now share the Windows isolated runtime contract and are ready for the Phase 14 regression closeout plan.
- No blockers discovered for `14-04`; manual Windows smoke work remains in the next plan as intended.

## Self-Check: PASSED

- Found summary file on disk.
- Verified task commit hashes `d48abca`, `eb4a278`, `8c12d7c`, and `5bed070` in git history.
