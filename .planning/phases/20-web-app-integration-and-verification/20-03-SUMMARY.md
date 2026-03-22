---
phase: 20-web-app-integration-and-verification
plan: "03"
subsystem: infra
tags: [packaging, fastapi, react, hatch, console-script, regression, docs]
requires:
  - phase: 20-02
    provides: static serving seam, typed browser client, and built frontend asset contract
provides:
  - canonical packaged startup seam for the web workspace
  - packaged frontend asset inclusion for wheel and sdist builds
  - closeout docs and manual smoke guidance for dev and built modes
affects: [phase-20-closeout, packaging, local-browser-workspace, nanobot-cli]
tech-stack:
  added: []
  patterns:
    - `python -m nanobot.tui` stays the canonical startup seam, with `nanobot-tui` as a thin script alias
    - packaged frontend assets resolve through the explicit `nanobot.tui.web` package boundary
key-files:
  created:
    - nanobot/tui/web/__init__.py
    - tests/test_tui_p20_entrypoints.py
    - .planning/phases/20-web-app-integration-and-verification/20-MANUAL-SMOKE.md
    - .planning/phases/20-web-app-integration-and-verification/20-03-SUMMARY.md
  modified:
    - nanobot/tui/__main__.py
    - nanobot/tui/static.py
    - pyproject.toml
    - tests/test_tui_p17_config.py
    - tests/test_commands.py
    - nanobot/tui/web/src/app/shell.test.tsx
    - tests/test_tui_p20_static.py
    - README.md
key-decisions:
  - "The canonical web runtime remains `python -m nanobot.tui`; `nanobot-tui` is an alias, not a replacement for the existing `nanobot` CLI."
  - "Packaged frontend asset lookup resolves from `nanobot.tui.web` so `importlib.resources` can find built files safely after installation."
patterns-established:
  - "Future packaged browser assets should be included through Hatch metadata and resolved via package resources rather than cwd-relative paths."
  - "Phase closeout docs should keep dev mode and built mode as two explicit supported workflows."
requirements-completed: [WEB-01, WEB-02, SHIP-01]
duration: 6min
completed: 2026-03-22
---

# Phase 20 Plan 03: Web App Integration and Verification Summary

**The web workspace now has a packaged startup seam, shipped frontend assets, and explicit local runbook coverage for both dev and built modes**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-22T10:31:00+08:00
- **Completed:** 2026-03-22T10:37:08+08:00
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Updated the canonical TUI startup seam so `python -m nanobot.tui` serves the runtime routes and packaged frontend shell together.
- Added package metadata and regression coverage for `nanobot-tui`, packaged frontend assets, and preserved `nanobot` CLI behavior.
- Documented the supported dev and built workflows and added a phase-local manual smoke checklist for real browser validation.

## Task Commits

Each task was committed atomically:

1. **Task 1: Preserve the canonical startup seam and package the built frontend assets** - `2a2761b` (`feat(20-03): package the web runtime entrypoint`)
2. **Task 2: Add final integrated regressions, startup docs, and the real-browser smoke checklist** - `55218d4` (`docs(20-03): add web workspace smoke guidance`)

## Files Created/Modified

- `nanobot/tui/__main__.py` - Enables runtime routes and frontend serving through the canonical module entry.
- `nanobot/tui/web/__init__.py` - Makes the web asset directory a package for resource lookup.
- `nanobot/tui/static.py` - Resolves built assets from `nanobot.tui.web` instead of a looser parent package path.
- `pyproject.toml` - Adds the `nanobot-tui` script and includes built frontend assets in wheel and sdist metadata.
- `tests/test_tui_p20_entrypoints.py` - Verifies startup wiring, package metadata, and resource-package importability.
- `tests/test_commands.py` - Confirms the existing `nanobot` and `opengui` CLI scripts remain intact.
- `README.md` - Documents the supported dev and built web workspace startup flows.
- `.planning/phases/20-web-app-integration-and-verification/20-MANUAL-SMOKE.md` - Defines the real-browser and CLI smoke path for Phase 20 closeout.

## Decisions Made

- Preserved `python -m nanobot.tui` as the canonical web runtime seam so the web workspace extends the Phase 17 boundary instead of inventing a second primary entrypoint.
- Kept the existing `nanobot` CLI untouched while adding `nanobot-tui` as a dedicated web shell alias.
- Scoped the packaging change to frontend assets and resource lookup only, avoiding wider CLI or runtime refactors.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used the documented `.venv` pytest fallback for the Phase 20 regression slice**
- **Found during:** Task 2 (Add final integrated regressions, startup docs, and the real-browser smoke checklist)
- **Issue:** The environment remains unable to complete `uv run --extra dev pytest ...` because of the previously observed optional native dependency build issue.
- **Fix:** Reused the documented fallback `.venv/bin/python -m pytest ...` with the same Phase 17-20 regression file list.
- **Files modified:** None
- **Verification:** `.venv/bin/python -m pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py tests/test_tui_p20_static.py tests/test_tui_p20_entrypoints.py tests/test_commands.py -q` passed with 75 tests green.
- **Committed in:** `55218d4`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The fallback was necessary to complete regression coverage honestly on this machine. No scope creep.

## Issues Encountered

- The local `uv run --extra dev` path is still blocked by an unrelated optional native build dependency, so final verification used the documented `.venv` fallback.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 20 implementation is complete and fully regression-tested.
- Real browser confirmation is still required through `20-MANUAL-SMOKE.md` before the phase can be marked fully passed in verification.

## Self-Check: PASSED

- Summary file exists.
- Task commits `2a2761b` and `55218d4` exist in git history.
- README, manual smoke, entrypoint tests, and packaged asset metadata all exist in the workspace.

---
*Phase: 20-web-app-integration-and-verification*
*Completed: 2026-03-22*
