---
phase: 14-windows-isolated-desktop-execution
plan: "06"
subsystem: host-integration
tags: [windows, cli, nanobot, background, isolated-desktop, testing]

requires:
  - phase: 14-windows-isolated-desktop-execution
    provides: "Real Win32 desktop ownership and worker-routed isolated execution"
  - phase: 12-background-runtime-contracts
    provides: "Shared runtime probe, reason codes, and mode-resolution contract"
provides:
  - "CLI forwards explicit and default Windows target_app_class values into the shared isolated probe"
  - "Nanobot forwards the same target_app_class contract before resolving background mode"
  - "Phase 14 regression coverage proves windows_app_class_unsupported ordering without regressing Linux or macOS"
affects: [15, 16]

tech-stack:
  added: []
  patterns:
    - "Windows host entry points derive probe-only app-class hints before resolve_run_mode() and keep backend dispatch keyed on probe.backend_name"
    - "Regression fixtures for Windows isolated execution must expose worker stdin/stdout pipes because preflight validates the live worker contract"

key-files:
  created: []
  modified:
    - opengui/cli.py
    - nanobot/agent/tools/gui.py
    - tests/test_opengui_p5_cli.py
    - tests/test_opengui_p11_integration.py

key-decisions:
  - "CLI and nanobot both default omitted Windows app-class hints to classic-win32 only for background local runs on win32 hosts."
  - "Unsupported Windows app classes stay on the shared remediation path: CLI warns before agent start, while nanobot returns its existing JSON failure shape before any task execution."
  - "Task 2 fixed a stale regression fixture instead of broadening runtime behavior because the failure was a test contract mismatch, not a runtime defect."

patterns-established:
  - "Host entry points pass Windows-only probe hints into background_runtime without reintroducing raw platform dispatch after mode resolution."
  - "Windows preflight tests should model the worker pipe contract directly so metadata and cleanup assertions exercise the real startup path."

requirements-completed:
  - WIN-01
  - WIN-02
  - WIN-03

duration: 3min
completed: "2026-03-20"
---

# Phase 14 Plan 06 Summary

**Windows app-class probing now reaches the shared runtime from both CLI and nanobot, and the full Phase 14 regression slice stays green with the worker-backed Windows path**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-20T18:23:11Z
- **Completed:** 2026-03-20T18:26:04Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added a CLI `--target-app-class` flag and a Windows-only default of `classic-win32` for background local runs before mode resolution.
- Exposed the same `target_app_class` contract through `GuiSubagentTool.execute()` and its schema while preserving nanobot's background JSON failure semantics.
- Reran the full four-file Phase 14 regression slice and fixed the only failure by aligning a stale Windows worker test fixture with the current pipe contract.

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire explicit Windows app-class propagation through CLI and nanobot** - `3444da7` (`test`), `05ea7af` (`feat`)
2. **Task 2: Run and stabilize the Phase 14 gap-closure regression slice** - `8f7aa3d` (`test`)

## Files Created/Modified
- `opengui/cli.py` - adds `--target-app-class`, resolves the Windows default probe hint, and forwards `target_app_class` into the shared probe.
- `nanobot/agent/tools/gui.py` - adds `target_app_class` to the tool schema and forwards the resolved value into the shared probe before mode resolution.
- `tests/test_opengui_p5_cli.py` - covers explicit/default CLI propagation and aligns the Windows metadata fixture with the worker pipe contract.
- `tests/test_opengui_p11_integration.py` - covers nanobot propagation plus pre-agent `windows_app_class_unsupported` failure ordering.

## Decisions Made

- Default `classic-win32` only when the host is `win32`, background mode is enabled, and the host entry point is still targeting the local backend.
- Keep unsupported Windows app classes on the shared runtime remediation path instead of adding CLI- or nanobot-specific branching after probe resolution.
- Treat the Task 2 failure as a stale test fixture and fix the test, because the runtime requirement for worker stdin/stdout pipes was already the correct contract.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated the stale Windows metadata regression fixture to satisfy the live worker pipe contract**
- **Found during:** Task 2
- **Issue:** `test_run_cli_logs_windows_target_surface_metadata` faked a worker process without `stdin`/`stdout`, so `WindowsIsolatedBackend.preflight()` failed before the metadata assertions could run.
- **Fix:** Added minimal writable `stdin`, readable `stdout`, and closable pipe stubs to the CLI Windows metadata test fixture.
- **Files modified:** `tests/test_opengui_p5_cli.py`
- **Verification:** `uv run pytest tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q`
- **Committed in:** `8f7aa3d`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The deviation stayed inside the planned regression task and kept the shared Windows runtime behavior unchanged.

## Issues Encountered

- A parallel `git add` briefly contended on `.git/index.lock`; retrying serially showed the lock was transient and no user changes were affected.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 14 is closed with both host entry points reaching the Windows app-class probe path in real runs.
- Phase 15 can build intervention/handoff behavior on top of a green Windows, macOS, Linux, CLI, and nanobot regression baseline.

## Self-Check: PASSED

- `FOUND: .planning/phases/14-windows-isolated-desktop-execution/14-windows-isolated-desktop-execution-06-SUMMARY.md`
- `FOUND: 3444da7`
- `FOUND: 05ea7af`
- `FOUND: 8f7aa3d`

---
*Phase: 14-windows-isolated-desktop-execution*
*Completed: 2026-03-20*
