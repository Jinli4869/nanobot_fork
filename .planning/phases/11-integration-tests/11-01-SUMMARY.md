---
phase: 11-integration-tests
plan: 01
subsystem: cli
tags: [argparse, background, xvfb, cli, testing]

# Dependency graph
requires:
  - phase: 10-background-backend-wrapper
    provides: BackgroundDesktopBackend async context manager wrapper
  - phase: 09-virtual-display-protocol
    provides: XvfbDisplayManager and VirtualDisplayManager protocol
provides:
  - "--background flag in parse_args() with --display-num, --width, --height"
  - "BackgroundDesktopBackend wrapping in run_cli() on Linux; warning fallback on non-Linux"
  - "BackgroundConfig dataclass and CliConfig.background fields"
  - "_execute_agent() helper extracted from run_cli() for clean code organization"
  - "7 new CLI background tests covering parsing, validation, and integration paths"
affects: [11-02, nanobot-gui-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level None placeholder (BackgroundDesktopBackend = None) enabling monkeypatching in tests"
    - "sys.platform check for Linux-only feature with graceful warning fallback"
    - "Lazy import inside conditional block: `from opengui.backends.background import BackgroundDesktopBackend as bg_cls`"
    - "TDD: write tests after implementation when implementation already done from plan spec"

key-files:
  created: []
  modified:
    - opengui/cli.py
    - tests/test_opengui_p5_cli.py

key-decisions:
  - "--background rejects both --backend adb and --dry-run with parser.error() — two separate validation checks needed because --dry-run is a flag separate from --backend"
  - "sys.platform used directly (already imported at top of cli.py) rather than via local import"
  - "_execute_agent() extracted as a standalone async function to eliminate code duplication between background and non-background paths"
  - "XvfbDisplayManager patched via opengui.backends.displays.xvfb module attribute so run_cli's local import picks it up"

patterns-established:
  - "Background mode integration test pattern: FakeBackgroundBackend + FakeXvfbDisplayManager + monkeypatch sys.platform to 'linux'"
  - "Non-Linux fallback test: caplog.at_level(WARNING) to assert 'Linux-only' appears in warning messages"

requirements-completed: [INTG-01, INTG-03, TEST-V11-01]

# Metrics
duration: 4min
completed: 2026-03-20
---

# Phase 11 Plan 01: CLI Background Flag Integration Summary

**--background flag wired into opengui/cli.py with XvfbDisplayManager wrapping on Linux, graceful fallback on macOS/Windows, and 7 comprehensive tests without a real Xvfb binary**

## Performance

- **Duration:** 4 min (212s)
- **Started:** 2026-03-20T11:11:46Z
- **Completed:** 2026-03-20T11:15:18Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added `--background`, `--display-num`, `--width`, `--height` argparse flags to `parse_args()` with validation that rejects incompatible backends
- Added `BackgroundConfig` dataclass and `background`/`background_config` fields to `CliConfig`
- Extracted `_execute_agent()` helper to remove duplication between background and non-background paths in `run_cli()`
- `run_cli()` wraps `LocalDesktopBackend` in `BackgroundDesktopBackend(inner, XvfbDisplayManager(...))` on Linux; logs warning and skips on macOS/Windows
- 7 new tests covering flag parsing, rejection of incompatible backends, backend resolution, Linux wrapping, non-Linux fallback, and CLI arg forwarding to XvfbDisplayManager

## Task Commits

Each task was committed atomically:

1. **Task 1: Add --background CLI flags, CliConfig fields, and wrapping logic** - `28d11f1` (feat)
2. **Task 2: Add background CLI tests to test_opengui_p5_cli.py** - `1921225` (test)

**Plan metadata:** (docs: complete plan — to be committed)

_Note: TDD task 2 went straight to green since Task 1 implementation was complete from plan spec_

## Files Created/Modified
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py` - Added BackgroundDesktopBackend placeholder, BackgroundConfig dataclass, 4 CLI flags, post-parse validation, updated resolve_backend_name(), extracted _execute_agent(), added background wrapping in run_cli()
- `/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_cli.py` - Added 7 new tests: test_cli_parses_background_flags, test_cli_background_rejects_adb, test_cli_background_rejects_dry_run, test_cli_background_implies_local, test_run_cli_background_wraps_backend, test_run_cli_background_nonlinux_fallback, test_run_cli_background_uses_cli_args

## Decisions Made
- Two separate `parser.error()` calls needed: `args.backend in ("adb", "dry-run")` catches explicit `--backend` values; `args.dry_run` check catches `--dry-run` flag (which doesn't set `args.backend = "dry-run"`)
- Used `sys.platform` directly (already imported top-level) rather than re-importing as `_sys` inside the function
- XvfbDisplayManager patched at module attribute level (`opengui.backends.displays.xvfb.XvfbDisplayManager`) so the `from ... import XvfbDisplayManager` inside `run_cli()` picks up the monkeypatched version

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- CLI --background flag is fully wired and tested
- All 15 CLI tests pass (8 pre-existing + 7 new), no regressions
- Ready for Phase 11 Plan 02 (nanobot GuiConfig background integration)
- Pre-existing failure in `test_tool_validation.py::test_exec_head_tail_truncation` is unrelated to this phase (confirmed pre-existing)

---
## Self-Check: PASSED

- opengui/cli.py: FOUND
- tests/test_opengui_p5_cli.py: FOUND
- 11-01-SUMMARY.md: FOUND
- Commit 28d11f1 (Task 1): FOUND
- Commit 1921225 (Task 2): FOUND

---
*Phase: 11-integration-tests*
*Completed: 2026-03-20*
