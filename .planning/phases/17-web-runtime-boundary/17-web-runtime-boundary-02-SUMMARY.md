---
phase: 17-web-runtime-boundary
plan: "02"
subsystem: infra
tags: [config, uvicorn, localhost, typer, regression]
requires:
  - phase: 17-web-runtime-boundary
    provides: isolated FastAPI shell and typed browser-facing contracts
provides:
  - dedicated local-first TUI runtime config in the shared nanobot schema
  - import-safe `python -m nanobot.tui` startup seam
  - CLI regression coverage proving gateway defaults remain separate from the TUI web runtime
affects: [phase-17-web-runtime-boundary, phase-18-chat-workspace, phase-20-web-app-integration-and-verification]
tech-stack:
  added: []
  patterns:
    - dedicated tui config section instead of reusing gateway host/port defaults
    - module-entry startup that builds the app through create_app and only calls uvicorn at runtime
key-files:
  created:
    - nanobot/tui/config.py
    - nanobot/tui/__main__.py
    - tests/test_tui_p17_config.py
    - .planning/phases/17-web-runtime-boundary/17-web-runtime-boundary-02-SUMMARY.md
  modified:
    - nanobot/config/schema.py
    - tests/test_commands.py
key-decisions:
  - "The new web runtime gets its own `tui` config section with localhost defaults instead of inheriting `gateway.host`/`gateway.port`."
  - "The first runnable entrypoint is `python -m nanobot.tui`, not a new Typer subcommand, so existing CLI flows stay untouched in Phase 17."
patterns-established:
  - "Shared config growth for browser features should extend `Config` with dedicated sections rather than overloading existing server settings."
  - "CLI regressions should assert that TUI settings do not bleed into gateway defaults."
requirements-completed: [ISO-01, ISO-02]
duration: 38min
completed: 2026-03-21
---

# Phase 17 Plan 02: Web Runtime Boundary Summary

**The TUI backend now starts from a dedicated localhost-first module entry, with a separate `tui` config surface and regression coverage proving the existing gateway and agent flows still behave as before**

## Performance

- **Duration:** 38 min
- **Started:** 2026-03-21T12:20:00Z
- **Completed:** 2026-03-21T12:57:31Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added `TuiConfig` to the shared nanobot schema with safe localhost defaults and a thin normalization helper for runtime startup.
- Added `nanobot.tui.__main__` so the FastAPI app can start via `python -m nanobot.tui` without importing or mutating existing CLI flows.
- Added config and command regressions proving the gateway port remains distinct from the new TUI runtime port.

## Task Commits

This plan landed as one narrow integration commit after the app-shell foundation was already in place:

1. **Task 1: Add dedicated local-first TUI config schema and validation coverage** - `27ad088` (`feat(17-02): add local-first tui runtime config`)
2. **Task 2: Expose read-only browser seams and wire import-safe startup for the TUI backend** - `27ad088` (`feat(17-02): add local-first tui runtime config`)

**Plan metadata:** recorded in the follow-up Phase 17 docs update commit.

## Files Created/Modified

- `nanobot/config/schema.py` - Added `TuiConfig` with localhost-safe defaults and explicit runtime fields.
- `nanobot/tui/config.py` - Added normalization helpers for host, port, reload, and log level.
- `nanobot/tui/__main__.py` - Added the import-safe module entry that builds the app through `create_app(...)` and only calls uvicorn at runtime.
- `tests/test_tui_p17_config.py` - Added coverage for config loading, localhost defaults, startup wiring, and import safety.
- `tests/test_commands.py` - Added gateway/TUI separation regressions to keep existing CLI semantics stable.

## Decisions Made

- Chose a dedicated `tui` config section over reusing `gateway` so future web app work can evolve independently from the existing server path.
- Kept `python -m nanobot.tui` as the Phase 17 startup seam rather than expanding the Typer command tree before the browser feature set is settled.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- FastAPI initially rejected a `Request | None` dependency signature during test collection. The fix was to keep dependency providers plain and request-free at this phase boundary, which preserved the planned isolation while making the route layer FastAPI-native.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 18 can now build chat APIs on a runnable localhost-first backend, and the CLI/gateway regression coverage already protects the existing host entry points from accidental web-runtime bleed-through.

## Self-Check: PASSED

- Found `nanobot/config/schema.py`, `nanobot/tui/config.py`, and `nanobot/tui/__main__.py`.
- Verified `tests/test_tui_p17_config.py`, `tests/test_tui_p17_runtime.py`, `tests/test_config_paths.py`, and `tests/test_commands.py` all passed.
- Confirmed the plan work landed in commit `27ad088`.
