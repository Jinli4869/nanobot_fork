---
phase: 17-web-runtime-boundary
plan: "01"
subsystem: api
tags: [fastapi, nanobot-tui, contracts, sessions, runtime]
requires: []
provides:
  - isolated FastAPI app shell under nanobot/tui
  - typed read-only contracts for sessions, runtime inspection, and task capability metadata
  - browser-facing health and read-only route surface guarded behind explicit app construction
affects: [phase-17-web-runtime-boundary, phase-18-chat-workspace, phase-19-operations-console]
tech-stack:
  added: [fastapi, uvicorn]
  patterns:
    - health-only default app factory with opt-in read-only browser routes
    - contract-plus-service adapter layer that reuses existing nanobot persistence instead of copying runtime logic
key-files:
  created:
    - nanobot/tui/app.py
    - nanobot/tui/contracts.py
    - nanobot/tui/dependencies.py
    - nanobot/tui/routes/sessions.py
    - nanobot/tui/routes/runtime.py
    - nanobot/tui/routes/tasks.py
    - tests/test_tui_p17_runtime.py
    - .planning/phases/17-web-runtime-boundary/17-web-runtime-boundary-01-SUMMARY.md
  modified:
    - pyproject.toml
key-decisions:
  - "The `nanobot.tui.create_app()` factory stays health-only by default, and the runnable module entry opts into the read-only browser seams explicitly."
  - "Session, runtime, and task metadata stay behind typed contracts and thin services so the web layer can reuse existing nanobot behavior without booting AgentLoop or channel startup."
patterns-established:
  - "Future web routes should depend on contract-backed services, not direct CLI/runtime construction."
  - "Read-only browser seams can be introduced under `nanobot/tui` without expanding the existing CLI entry points."
requirements-completed: [ISO-01]
duration: 99min
completed: 2026-03-21
---

# Phase 17 Plan 01: Web Runtime Boundary Summary

**An isolated `nanobot/tui` FastAPI shell now exposes health plus opt-in read-only session, runtime, and task-capability seams without booting the CLI, channels, or GUI runtime**

## Performance

- **Duration:** 99 min
- **Started:** 2026-03-21T10:40:43Z
- **Completed:** 2026-03-21T12:20:00Z
- **Tasks:** 2
- **Files modified:** 19

## Accomplishments

- Added the new `nanobot/tui` package with an import-safe FastAPI factory and health endpoint.
- Introduced typed session, runtime-inspection, and task-launch contracts plus adapter services and schemas for later browser work.
- Added Wave 0/Phase 17 runtime tests and minimal Python dependency wiring for FastAPI and uvicorn.

## Task Commits

Each task was completed in the same atomic implementation pass for this plan:

1. **Task 1: Create Wave 0 runtime tests and dependency hooks for the isolated TUI backend** - `bbb9ad6` (`feat(17-01): add isolated tui backend shell`)
2. **Task 2: Implement the `nanobot/tui` app shell and typed contracts** - `bbb9ad6` (`feat(17-01): add isolated tui backend shell`)

**Plan metadata:** recorded in the follow-up Phase 17 docs update commit.

## Files Created/Modified

- `pyproject.toml` - Added `web`/`dev` dependency seams for FastAPI and uvicorn verification.
- `nanobot/tui/app.py` - Added the isolated app factory with default health-only behavior and opt-in read-only routes.
- `nanobot/tui/contracts.py` - Added typed contracts for session metadata, runtime inspection, and future task launch capability.
- `nanobot/tui/dependencies.py` - Added lazy dependency builders that reuse existing nanobot services without booting runtime orchestration.
- `nanobot/tui/routes/*.py` - Added health, sessions, runtime, and tasks read-only route modules.
- `nanobot/tui/schemas/*.py` - Added response models for browser-facing session/runtime/task payloads.
- `nanobot/tui/services/*.py` - Added contract-backed service adapters for route handlers.
- `tests/test_tui_p17_runtime.py` - Added isolated import, typed-contract, and read-only route regression coverage.

## Decisions Made

- Kept the default app factory minimal so Wave 1 isolation guarantees remain testable even after read-only browser routes land.
- Reused `SessionManager.list_sessions()` through a contract/service seam instead of creating a separate TUI persistence layer.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `uv run` proved unstable in the local sandbox because the environment was missing a working `pip` path and `uv` cache access. The fix was to bootstrap `pip` inside `.venv`, install `fastapi`, and run the Phase 17 tests directly with `.venv/bin/python -m pytest`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The browser-facing backend boundary is now in place under `nanobot/tui`, so Phase 18 can add chat-focused APIs without reopening the CLI/runtime coupling question.

## Self-Check: PASSED

- Found `nanobot/tui/` FastAPI app, route, schema, and service files.
- Verified `tests/test_tui_p17_runtime.py` passed.
- Confirmed the plan work landed in commit `bbb9ad6`.
