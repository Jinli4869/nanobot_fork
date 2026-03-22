---
phase: 20-web-app-integration-and-verification
plan: "02"
subsystem: ui
tags: [fastapi, static-files, react, vite-proxy, sse, tdd, nanobot-tui]
requires:
  - phase: 20-01
    provides: React/Vite workspace shell and URL-backed workspace state
provides:
  - FastAPI static asset discovery and SPA deep-link fallback for built frontend assets
  - explicit frontend API base resolution shared by fetch and SSE transport
  - route components that consume typed chat and runtime client contracts
affects: [20-03, packaged-startup, browser-workspace, nanobot/tui]
tech-stack:
  added: []
  patterns:
    - built frontend serving stays opt-in behind `serve_frontend=True`
    - Vite dev mode uses a single `/api` proxy that rewrites to the existing FastAPI route family
key-files:
  created:
    - nanobot/tui/static.py
    - nanobot/tui/web/src/lib/api/client.test.ts
    - nanobot/tui/web/src/lib/chat-events.ts
    - nanobot/tui/web/src/features/chat/ChatWorkspaceRoute.tsx
    - nanobot/tui/web/src/features/operations/OperationsWorkspaceRoute.tsx
    - nanobot/tui/web/src/features/workspace-routes.test.tsx
    - tests/test_tui_p20_static.py
    - .planning/phases/20-web-app-integration-and-verification/20-web-app-integration-and-verification-02-SUMMARY.md
  modified:
    - nanobot/tui/app.py
    - nanobot/tui/web/vite.config.ts
    - nanobot/tui/web/src/app/router.tsx
    - nanobot/tui/web/src/app/shell.test.tsx
    - nanobot/tui/web/src/lib/api/client.ts
key-decisions:
  - "Built frontend serving remains an explicit runtime opt-in so the default TUI app path stays safe for health-only tests and imports."
  - "Frontend fetches and EventSource streams share one base-resolution helper so dev mode and built mode hit the same backend contract."
patterns-established:
  - "Frontend browser views should consume typed helpers from `src/lib/api/client.ts` rather than issuing ad hoc fetch calls."
  - "SPA deep links are served only for browser shell routes while existing API endpoints keep their exact semantics."
requirements-completed: [WEB-01, SHIP-01]
duration: 18min
completed: 2026-03-22
---

# Phase 20 Plan 02: Web App Integration and Verification Summary

**The web shell now talks to FastAPI through one explicit typed bridge, and built frontend assets can be served with safe SPA fallback behavior**

## Performance

- **Duration:** 18 min
- **Started:** 2026-03-22T10:14:00+08:00
- **Completed:** 2026-03-22T10:31:55+08:00
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- Added TDD coverage for static frontend serving, deep-link fallback behavior, and explicit frontend API base resolution.
- Implemented `nanobot/tui/static.py` plus `serve_frontend` app wiring so built assets can be served without changing the health-only default app seam.
- Moved chat and operations routes onto typed fetch/SSE helpers so dev mode and built mode share one browser client contract.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add static-serving and development-bridge regression coverage** - `f5e8f33` (`feat(20-02): add static frontend serving foundation`)
2. **Task 2: Implement SPA fallback, typed client wiring, and chat/operations route integration** - `0383ac1` (`feat(20-02): wire typed frontend route integration`)

## Files Created/Modified

- `tests/test_tui_p20_static.py` - Covers `/`, `/chat/...`, `/operations?...`, API bypass behavior, and missing-build guidance.
- `nanobot/tui/static.py` - Resolves built asset locations via `importlib.resources` and installs SPA fallback routes only when assets exist.
- `nanobot/tui/app.py` - Adds explicit frontend serving opt-in while keeping the default app path import-safe and health-only.
- `nanobot/tui/web/src/lib/api/client.ts` - Defines typed browser DTOs plus shared API base/path/URL resolution helpers.
- `nanobot/tui/web/src/lib/chat-events.ts` - Reuses the same resolved base to connect EventSource chat streaming in dev and built mode.
- `nanobot/tui/web/src/features/chat/ChatWorkspaceRoute.tsx` - Reads typed chat session data and wires SSE readiness into the chat route.
- `nanobot/tui/web/src/features/operations/OperationsWorkspaceRoute.tsx` - Reads typed runtime inspection data from the same frontend client seam.
- `nanobot/tui/web/src/features/workspace-routes.test.tsx` - Proves both routes consume the shared typed client contract and preserve session/run context.

## Decisions Made

- Preserved the existing backend route family and rewrote only the Vite proxy prefix, avoiding new `/api/*` endpoints on the server.
- Centralized API base resolution so fetch and EventSource use the same dev-mode and served-mode contract.
- Kept SPA fallback scoped to browser shell routes instead of broad catch-all behavior that could shadow API endpoints.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used the documented local pytest fallback for the Phase 20 static tests**
- **Found during:** Task 1 (Add static-serving and development-bridge regression coverage)
- **Issue:** `uv run --extra dev pytest tests/test_tui_p20_static.py -q` could not complete locally because the optional `python-olm` dependency required missing native build tools.
- **Fix:** Switched verification to the documented fallback `.venv/bin/python -m pytest tests/test_tui_p20_static.py -q` after the frontend build and test slice succeeded.
- **Files modified:** None
- **Verification:** `.venv/bin/python -m pytest tests/test_tui_p20_static.py -q` passed with 4 tests green.
- **Committed in:** `f5e8f33`

**2. [Rule 1 - Bug] Stabilized the route-integration assertion around async client rendering**
- **Found during:** Task 2 (Implement SPA fallback, typed client wiring, and chat/operations route integration)
- **Issue:** The new route-level test asserted the chat transcript status before React Query had finished applying the fetched session payload.
- **Fix:** Updated the test to wait for the rendered client state before asserting the loaded transcript and runtime labels.
- **Files modified:** `nanobot/tui/web/src/features/workspace-routes.test.tsx`
- **Verification:** `npm --prefix nanobot/tui/web run test -- --run --reporter=dot` passed with all 5 frontend tests green.
- **Committed in:** `0383ac1`

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes were necessary to keep the regression slice reliable on the current machine and frontend stack. No scope creep.

## Issues Encountered

- The local optional-dependency toolchain still blocks `uv run --extra dev pytest ...`, so Phase 20 verification continues to rely on the documented `.venv` fallback.
- The route integration test needed an explicit async wait because the new typed client flow renders after query resolution, not synchronously.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The packaged startup plan can now assume a real frontend bundle and a stable FastAPI serving seam exist.
- Chat and operations already consume one typed browser contract, so Phase 20 closeout can focus on packaged entrypoints, regression coverage, and operator docs.

## Self-Check: PASSED

- Summary file exists.
- Task commits `f5e8f33` and `0383ac1` exist in git history.
- Key implementation and regression files referenced in this summary exist in the workspace.

---
*Phase: 20-web-app-integration-and-verification*
*Completed: 2026-03-22*
