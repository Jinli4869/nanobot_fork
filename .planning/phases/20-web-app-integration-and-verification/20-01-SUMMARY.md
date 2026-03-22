---
phase: 20-web-app-integration-and-verification
plan: "01"
subsystem: ui
tags: [react, vite, react-router, tanstack-query, vitest, nanobot-tui]
requires:
  - phase: 17-web-runtime-boundary
    provides: localhost-first TUI runtime seam and browser-safe FastAPI boundaries
  - phase: 18-chat-workspace
    provides: chat routes, SSE transport, and session-backed browser workflow contracts
  - phase: 19-operations-console
    provides: runtime, task launch, and trace inspection browser contracts
provides:
  - isolated React/Vite workspace under `nanobot/tui/web`
  - one shared shell for chat and operations navigation
  - URL-backed workspace state for `sessionId`, `runId`, and `panel`
affects: [20-02, 20-03, browser-workspace, nanobot/tui/web]
tech-stack:
  added: [react, vite, react-router, @tanstack/react-query, vitest, @testing-library/react]
  patterns:
    - browser workspace state stays in the URL instead of transient React-only state
    - shell chrome and route composition live entirely under `nanobot/tui/web`
key-files:
  created:
    - nanobot/tui/web/package.json
    - nanobot/tui/web/package-lock.json
    - nanobot/tui/web/tsconfig.json
    - nanobot/tui/web/vite.config.ts
    - nanobot/tui/web/index.html
    - nanobot/tui/web/src/main.tsx
    - nanobot/tui/web/src/app/providers.tsx
    - nanobot/tui/web/src/app/router.tsx
    - nanobot/tui/web/src/app/shell.tsx
    - nanobot/tui/web/src/lib/workspace-state.ts
    - nanobot/tui/web/src/app/shell.test.tsx
    - .planning/phases/20-web-app-integration-and-verification/20-web-app-integration-and-verification-01-SUMMARY.md
  modified: []
key-decisions:
  - "Phase 20 starts with a standalone `nanobot/tui/web` workspace so frontend build tooling stays isolated from the Python runtime."
  - "The active session and selected run remain encoded in route params and search params so navigation does not reset operator context."
patterns-established:
  - "Future browser views should plug into the shared shell instead of creating separate HTML entry points."
  - "Server state flows through React Query providers, while workspace identity remains URL-backed."
requirements-completed: [WEB-01, WEB-02]
duration: 22min
completed: 2026-03-22
---

# Phase 20 Plan 01: Web App Integration and Verification Summary

**A dedicated React/Vite workspace shell now hosts chat and operations inside one SPA, with URL-backed session and run context that survives navigation**

## Performance

- **Duration:** 22 min
- **Started:** 2026-03-22T00:20:00+08:00
- **Completed:** 2026-03-22T00:42:40+08:00
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- Scaffolded an isolated `nanobot/tui/web` frontend workspace with build, dev, and test scripts plus a working production bundle.
- Built a shared workspace shell with `Chat` and `Operations` routes backed by durable URL state.
- Added route-level regression coverage proving the same session id survives navigation across the SPA shell.

## Task Commits

Each task was committed atomically:

1. **Task 1: Scaffold the isolated React/Vite workspace and baseline build** - `f5a4212` (`feat(20-01): scaffold web workspace`)
2. **Task 2: Build the route-backed shell and durable workspace state** - `24ee196` (`feat(20-01): add workspace shell navigation`)

## Files Created/Modified

- `nanobot/tui/web/package.json` - Pins the frontend toolchain, scripts, and browser dependencies for the new workspace.
- `nanobot/tui/web/vite.config.ts` - Configures the local Vite host, fixed dev port, and backend proxy contract.
- `nanobot/tui/web/src/app/router.tsx` - Defines the browser router and durable chat/operations route model.
- `nanobot/tui/web/src/app/shell.tsx` - Provides the shared shell chrome, navigation, and visible workspace context.
- `nanobot/tui/web/src/lib/workspace-state.ts` - Normalizes `sessionId`, `runId`, and `panel` from route and search state.
- `nanobot/tui/web/src/app/shell.test.tsx` - Locks the shell navigation behavior so browser context persists across route changes.

## Decisions Made

- Kept the frontend boundary fully under `nanobot/tui/web` so later packaged-mode work can reuse the same app without touching the existing CLI surface.
- Used route params plus search params as the durable workspace model instead of React-only state, which keeps browser deep links and navigation stable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Downgraded Vite to the compatible major for the current React plugin stack**
- **Found during:** Task 1 (Scaffold the isolated React/Vite workspace and baseline build)
- **Issue:** `npm install` failed because `@vitejs/plugin-react@5.0.2` did not accept the originally planned Vite 8 peer range in this environment.
- **Fix:** Pinned `vite` to `7.1.9`, which satisfied the existing plugin stack and preserved the planned React/Vite architecture.
- **Files modified:** `nanobot/tui/web/package.json`, `nanobot/tui/web/package-lock.json`
- **Verification:** `npm --prefix nanobot/tui/web run build` and `npm --prefix nanobot/tui/web run test -- --run src/app/shell.test.tsx --reporter=dot` both passed after the version change.
- **Committed in:** `f5a4212`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The compatibility pin was necessary to complete the workspace bootstrap on the current machine. No scope creep.

## Issues Encountered

- The local environment required a Vite version compatible with the installed React plugin range before dependencies could install cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 20 now has a stable SPA shell ready for typed API wiring, SSE integration, and static serving work in `20-02`.
- The URL-backed workspace contract is established, so later plans can layer real backend data without redesigning navigation.

## Self-Check: PASSED

- Summary file exists.
- Task commits `f5a4212` and `24ee196` exist in git history.
- Key workspace shell files referenced in this summary exist in the repository.

---
*Phase: 20-web-app-integration-and-verification*
*Completed: 2026-03-22*
