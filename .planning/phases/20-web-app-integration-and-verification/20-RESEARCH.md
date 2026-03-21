# Phase 20: Web App Integration and Verification - Research

**Researched:** 2026-03-21
**Domain:** React/Vite SPA integration, FastAPI static serving, packaged entrypoints, and regression coverage for the nanobot web workspace
**Confidence:** HIGH

<user_constraints>
## User Constraints

No `20-CONTEXT.md` exists for this phase. This research therefore treats the following as authoritative constraints:
- `.planning/ROADMAP.md` Phase 20 goal, plans, and success criteria
- `.planning/REQUIREMENTS.md` requirements `WEB-01`, `WEB-02`, and `SHIP-01`
- `.planning/STATE.md` decisions already locked by Phases 17-19
- `.planning/phases/17-web-runtime-boundary/17-RESEARCH.md`
- `.planning/phases/18-chat-workspace/18-RESEARCH.md`
- `.planning/phases/19-operations-console/19-RESEARCH.md`
- `.planning/phases/18-chat-workspace/*-SUMMARY.md`
- `.planning/phases/19-operations-console/*-SUMMARY.md`
- The explicit user request to keep roadmap, requirements, state, prior phase research, and existing `nanobot/tui` code authoritative
- The explicit user request to evaluate whether the roadmap's proposed 3-plan split is still the best executable split

### Locked Decisions
- Keep the web stack primarily under `nanobot/tui`; Phase 20 should consume the Phase 17-19 backend contracts rather than reopen them.
- Existing CLI-first behavior must continue to work without requiring the web surface.
- Chat durability remains backed by `SessionManager`, chat streaming remains SSE-based, and operations inspection remains run-id-addressed.
- The first shipped web release is local-first and localhost-safe by default.
- Phase 20 must deliver a single web app surface that lets the user move between chat and operations without losing active workspace context.

### Claude's Discretion
- The exact frontend package layout under `nanobot/tui`.
- Whether chat/operations context lives in route params, query params, React context, or a small state helper, provided navigation does not reset the active workspace.
- Whether dev ergonomics use a dedicated console script, `python -m nanobot.tui`, or both, provided packaged mode is documented and reliable.
- Whether frontend server state uses plain hooks or a standard cache layer, provided polling/revalidation and mutation invalidation stay maintainable.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| WEB-01 | User can open a browser-based nanobot workspace served from the local app instead of relying on terminal-only interaction | Add a React/Vite SPA under `nanobot/tui`, serve built assets from FastAPI in packaged mode, and expose a stable root-shell route |
| WEB-02 | User can switch between chat and operations views inside one web app without losing the active workspace context | Use one SPA shell with route-backed chat and operations views plus shared workspace state keyed by session/run identifiers |
| SHIP-01 | User can start the web workspace through documented development and packaged entrypoints without breaking existing CLI usage | Keep `python -m nanobot.tui`/`nanobot-tui` as backend entrypoints, run Vite separately in dev with proxying, and ship built frontend assets inside the package for packaged mode |
</phase_requirements>

## Summary

Phases 17-19 already completed the hard backend work. `nanobot/tui` now exposes browser-safe chat, SSE streaming, runtime inspection, typed task launch, and filtered trace/log APIs. Phase 20 should not reopen those contracts. The remaining job is to put a real SPA shell on top of them, wire development and packaged serving modes cleanly, and prove the new web surface does not regress the existing CLI-first workflow.

The most important technical fact from the current repo state is that packaged delivery is not solved yet. `nanobot/tui/__main__.py` can already start the FastAPI backend, but `pyproject.toml` currently ships Python files only. If Phase 20 adds a Vite app without updating Hatch include rules and runtime asset discovery, `SHIP-01` will fail in installed/package mode even if development works locally.

**Primary recommendation:** Keep the roadmap's 3-plan split. It is still the right executable split, but tighten it around the actual seams now visible in the repo: `20-01` frontend shell and navigation, `20-02` dev/prod asset serving and entrypoints, `20-03` regression coverage plus docs/manual smoke.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `react` / `react-dom` | `19.2.x` (`react.dev` latest docs; `19.2.1` releases listed Dec 2025) | SPA view layer and DOM rendering | Current React baseline with stable client APIs and modern concurrent behavior |
| `vite` | `8.0.1` | Frontend dev server and production bundler | Current official Vite docs are on `v8.0.1`; ideal for a local-first SPA with fast dev proxying and static builds |
| `@vitejs/plugin-react` | `5.0.2` | Vite React integration and Fast Refresh | Official/default React plugin for Vite |
| `react-router` | `7.13.1` | In-app navigation and URL-backed workspace context | Current stable router with first-class browser routing and strong testing ergonomics |
| `fastapi` | repo pin `>=0.110.0,<1.0.0` (`0.135.1` verified in Phase 18 research on 2026-03-21) | Existing backend API and packaged static serving host | Already the Phase 17-19 backend seam; no reason to change |
| `uvicorn[standard]` | repo pin `>=0.30.0,<1.0.0` (`0.42.0` verified in Phase 18 research on 2026-03-21) | Existing ASGI runtime | Already wired and tested in `nanobot.tui.__main__` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@tanstack/react-query` | `v5` | Server-state cache, polling, mutation invalidation | Recommended for runtime polling, session lists, and launch/inspection refresh without ad hoc `useEffect` sprawl |
| `vitest` | `4.0.17` | Frontend unit/integration tests | Vite-native test runner; current stable site shows `v4.0.17` |
| `@testing-library/react` | `16.3.0` | React component/integration tests | Standard user-focused React testing utilities |
| Browser `EventSource` | Web standard | Chat SSE transport client | Matches the existing GET SSE backend contract exactly |
| `importlib.resources` | stdlib | Resolve packaged frontend assets at runtime | Avoids fragile cwd-based or `__file__`-relative path assumptions in installed wheels |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `react-router` with browser history | Hash-based navigation | Easier static hosting, but unnecessary once FastAPI provides SPA fallback and worse URLs/state semantics |
| TanStack Query | Plain `fetch` + local `useEffect` hooks | Smaller dependency surface, but polling/invalidation/load states will sprawl across chat and operations quickly |
| Packaged prebuilt `dist/` assets | Build frontend on end-user startup | Simpler release pipeline, but violates `SHIP-01` reliability and makes packaged mode depend on local Node/npm |
| FastAPI-served built SPA + Vite dev proxy | Manual HTML injection via Vite manifest | Useful for server-rendered backends, but overkill for this SPA and easier to get wrong |

**Installation:**
```bash
uv pip install -e ".[web,dev]"
npm --prefix nanobot/tui/web install
```

**Version verification:**
- `react.dev` lists latest React docs version as `19.2`, and the React versions page lists `v19.2.1` releases in December 2025.
- `vite.dev` current docs are `v8.0.1`; Vite announced stable Vite 8 on 2026-03-12.
- `reactrouter.com` changelog lists `v7.13.1` dated 2026-02-23.
- `vitest.dev` homepage shows stable `v4.0.17`.
- `@vitejs/plugin-react` npm page/search snippet shows `5.0.2` published 9 days before research.
- `@testing-library/react` npm page/search snippet shows `16.3.0`.

## Recommended Plan Split

The roadmap's proposed 3-plan split is still the best executable split.

### Plan 20-01: React/Vite shell for chat + operations navigation
Focus:
- Create `nanobot/tui/web/` with Vite + React + TypeScript
- Build one shell layout with shared nav and route-backed chat/operations screens
- Add typed frontend API helpers against existing `/chat`, `/runtime`, `/tasks`, and trace/log routes
- Preserve workspace context via URL state plus shared query/cache state

Primary outputs:
- `nanobot/tui/web/package.json`
- `nanobot/tui/web/vite.config.ts`
- `nanobot/tui/web/src/...`
- Frontend tests for navigation and context retention

### Plan 20-02: Production/dev entrypoints between FastAPI and frontend build
Focus:
- Serve built SPA assets from FastAPI in packaged mode
- Add SPA fallback routing without breaking API routes
- Add Vite dev proxy config for the existing backend paths instead of changing backend URL shapes
- Ship a discoverable backend entrypoint such as `nanobot-tui` while preserving `python -m nanobot.tui`
- Update Hatch include/sdist rules so built frontend assets are actually packaged

Primary outputs:
- FastAPI static mount/fallback wiring
- Runtime asset lookup helper using `importlib.resources`
- `pyproject.toml` packaging changes
- Entry-point docs and tests

### Plan 20-03: End-to-end smoke coverage + startup docs
Focus:
- Add frontend shell regression tests
- Add Python integration tests for served SPA assets and entrypoint behavior
- Re-run/extend CLI regression coverage
- Write startup docs plus a manual local-browser smoke path

Primary outputs:
- Frontend test suite
- Python regression tests
- `20-MANUAL-SMOKE.md` and startup documentation

## Architecture Patterns

### Recommended Project Structure
```text
nanobot/tui/
├── __main__.py
├── app.py
├── static.py               # asset discovery + SPA fallback helpers
├── web/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── app/
│   │   │   ├── router.tsx
│   │   │   ├── shell.tsx
│   │   │   └── providers.tsx
│   │   ├── features/
│   │   │   ├── chat/
│   │   │   └── operations/
│   │   └── lib/
│   │       ├── api/
│   │       ├── sse/
│   │       └── workspace-context/
│   └── dist/              # built assets for packaged mode
└── routes/
    ├── chat.py
    ├── runtime.py
    ├── tasks.py
    └── traces.py
```

### Pattern 1: One SPA Shell, Existing Backend Routes
**What:** Keep the browser as one React app served at `/`, but do not refactor the existing Phase 17-19 backend paths.
**When to use:** Entire Phase 20.
**Why:** Current tests and backend contracts already assume `/chat`, `/runtime`, `/tasks`, and `/runtime/runs/{run_id}/...`; changing them now creates avoidable regressions.
**Example:**
```ts
// Source:
// - local repo: existing FastAPI routes under nanobot/tui/routes/*
// - Vite proxy docs: https://vite.dev/config/server-options
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: {
      "/health": "http://127.0.0.1:18791",
      "/chat": "http://127.0.0.1:18791",
      "/sessions": "http://127.0.0.1:18791",
      "/runtime": "http://127.0.0.1:18791",
      "/tasks": "http://127.0.0.1:18791",
    },
  },
})
```

### Pattern 2: URL-Backed Workspace Context
**What:** Put durable workspace identity in the URL.
**When to use:** Active chat session and active operations run/detail selection.
**Why:** This prevents context loss when navigating between views and avoids inventing a second browser-only state model.
**Example:**
```tsx
// Source:
// - React Router createBrowserRouter docs: https://reactrouter.com/api/data-routers/createBrowserRouter
const router = createBrowserRouter([
  {
    path: "/",
    Component: WorkspaceShell,
    children: [
      { index: true, Component: ChatRoute },
      { path: "chat/:sessionId", Component: ChatRoute },
      { path: "operations", Component: OperationsRoute },
    ],
  },
]);
```

Use the route to hold the chat session id and query/search params for the currently selected run or diagnostics panel. Keep only truly ephemeral UI chrome in local component state.

### Pattern 3: Native `EventSource` for Chat Streaming
**What:** Consume the existing Phase 18 GET SSE route with browser-native `EventSource`.
**When to use:** `GET /chat/sessions/{session_id}/events`.
**Why:** The backend is already SSE-based, and MDN documents `EventSource` as the standard unidirectional browser API for this transport.
**Example:**
```ts
// Source:
// - MDN EventSource: https://developer.mozilla.org/en-US/docs/Web/API/EventSource/EventSource
// - local repo: nanobot/tui/routes/chat.py
export function connectChatEvents(
  sessionId: string,
  onEvent: (event: ChatEvent) => void,
): () => void {
  const stream = new EventSource(`/chat/sessions/${sessionId}/events`);
  const forward = (evt: MessageEvent<string>) => onEvent(JSON.parse(evt.data));

  stream.addEventListener("message.accepted", forward as EventListener);
  stream.addEventListener("progress", forward as EventListener);
  stream.addEventListener("assistant.final", forward as EventListener);
  stream.addEventListener("complete", forward as EventListener);
  stream.addEventListener("error", forward as EventListener);

  return () => stream.close();
}
```

### Pattern 4: Serve Built Assets, Do Not Rebuild at Runtime
**What:** In packaged mode, FastAPI should serve a prebuilt `dist/` tree already included in the Python package.
**When to use:** `SHIP-01` packaged startup.
**Why:** Node/npm should be a development dependency for the web workspace, not a runtime dependency for end users starting the packaged app.
**Example:**
```python
# Source:
# - FastAPI StaticFiles docs: https://fastapi.tiangolo.com/tutorial/static-files/
# - local repo pattern: nanobot/utils/helpers.py uses importlib.resources.files(...)
# Inference: add explicit SPA fallback after API routes and static mounts.
from importlib.resources import files as pkg_files
from fastapi.staticfiles import StaticFiles

dist_dir = pkg_files("nanobot") / "tui" / "web" / "dist"
app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")
```

Inference from the sources: `StaticFiles` handles mounted asset paths cleanly, but SPA fallback for browser routes like `/chat/abc` still needs an explicit `index.html` response route registered after the API routers.

### Anti-Patterns to Avoid
- **Reopening Phase 17-19 backend contracts:** Phase 20 should consume them, not redesign them.
- **Adding an `/api` prefix to existing backend routes in this phase:** this would ripple through tests and current route consumers for no user benefit.
- **Building the frontend on first user startup:** brittle, slow, and violates packaged-mode reliability.
- **Keeping active chat/run context only in component-local state:** navigation or refresh will reset the workspace.
- **Using permissive CORS instead of a dev proxy:** unnecessary and less safe for the local-first default.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dev backend/frontend wiring | Global `fetch` URL rewrites or permissive CORS hacks | Vite `server.proxy` | Official dev-server path proxying keeps the backend contract unchanged |
| Browser chat stream client | Polling loop or WebSocket rewrite | Native `EventSource` | Backend already speaks SSE and the browser has a standard client |
| Static asset serving | Manual HTML string/template injection | FastAPI/Starlette `StaticFiles` + explicit SPA fallback | Less moving parts for a SPA with static assets |
| Server-state cache | Per-component `useEffect` fetch logic everywhere | TanStack Query | Runtime polling, invalidation, and refetch rules get complex fast |
| Packaged asset lookup | cwd-based relative paths | `importlib.resources.files("nanobot")` | Installed wheels should not depend on the caller's working directory |

**Key insight:** Phase 20 should hand-roll almost nothing except the thin integration seam between the existing FastAPI backend and a standard SPA toolchain.

## Common Pitfalls

### Pitfall 1: Frontend Builds Work in the Repo but Not in the Wheel
**What goes wrong:** packaged mode starts FastAPI successfully, but `/` 404s or serves no frontend because `dist/` was never included in the wheel/sdist.
**Why it happens:** `pyproject.toml` currently includes Python files and a few markdown/shell assets only.
**How to avoid:** add frontend source and built assets to Hatch include rules, and resolve them via package resources at runtime.
**Warning signs:** `python -m nanobot.tui` works from the repo checkout but fails after install.

### Pitfall 2: SPA Fallback Breaks API Routes
**What goes wrong:** the catch-all route starts returning `index.html` for `/runtime` or `/tasks/runs`.
**Why it happens:** static fallback is registered too broadly or before API routers.
**How to avoid:** register API routers first, mount static assets explicitly, and only fallback to `index.html` for non-API browser paths.
**Warning signs:** JSON API tests suddenly return HTML.

### Pitfall 3: Navigation Loses Context
**What goes wrong:** switching from chat to operations clears the active session or selected run.
**Why it happens:** context only lives in component-local state.
**How to avoid:** put durable workspace identity in route params/search params and let cached data repopulate views.
**Warning signs:** route transitions require hidden global singletons or imperative back-filling.

### Pitfall 4: Dev Mode and Packaged Mode Drift
**What goes wrong:** the app works through the Vite dev server but breaks when served by FastAPI, or vice versa.
**Why it happens:** frontend code uses absolute dev URLs or assumes a different path base than packaged mode.
**How to avoid:** keep API calls relative and use the Vite proxy only in development.
**Warning signs:** environment-specific `if (import.meta.env.DEV)` branching spreads through feature code.

### Pitfall 5: Verification Stops at the Backend
**What goes wrong:** Phase 20 only re-runs the Phase 17-19 pytest slice and never actually proves the SPA shell or navigation behavior.
**Why it happens:** the repo is Python-first, so frontend tests are easy to underinvest in.
**How to avoid:** add a small frontend test suite for shell navigation/context retention plus Python integration tests for static serving and entrypoints.
**Warning signs:** the only evidence for `WEB-01`/`WEB-02` is manual clicking.

### Pitfall 6: Vite Localhost Safety Gets Loosened Accidentally
**What goes wrong:** dev config exposes the frontend on LAN/public interfaces without intent.
**Why it happens:** developers use `--host` or `server.host=true` casually.
**How to avoid:** keep `127.0.0.1`/`localhost` defaults and use explicit opt-in for anything broader.
**Warning signs:** Vite config uses `host: true`, `0.0.0.0`, `allowedHosts: true`, or `cors: true` without a clear reason.

## Code Examples

Verified patterns from official sources and current repo constraints:

### Vite Dev Proxy Against the Existing FastAPI Backend
```ts
// Source:
// https://vite.dev/config/server-options
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/health": "http://127.0.0.1:18791",
      "/chat": "http://127.0.0.1:18791",
      "/sessions": "http://127.0.0.1:18791",
      "/runtime": "http://127.0.0.1:18791",
      "/tasks": "http://127.0.0.1:18791",
    },
  },
});
```

### Browser Router for One Shell with Chat and Operations
```tsx
// Source:
// https://reactrouter.com/api/data-routers/createBrowserRouter
import { createBrowserRouter, Outlet, RouterProvider } from "react-router";

function Shell() {
  return (
    <div className="workspace-shell">
      <SidebarNav />
      <main>
        <Outlet />
      </main>
    </div>
  );
}

const router = createBrowserRouter([
  {
    path: "/",
    Component: Shell,
    children: [
      { index: true, Component: ChatHome },
      { path: "chat/:sessionId", Component: ChatHome },
      { path: "operations", Component: OperationsHome },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
```

### FastAPI Static Mount for Packaged Assets
```python
# Source:
# https://fastapi.tiangolo.com/tutorial/static-files/
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
```

For this repo, infer one additional integration step: after mounting assets and registering the existing API routers, return `index.html` for unmatched non-API browser paths so browser refreshes on `/chat/:sessionId` or `/operations` keep working.

### TanStack Query Provider for Shared Server State
```tsx
// Source:
// https://tanstack.com/query/latest/docs/framework/react/overview
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const queryClient = new QueryClient();

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Vite 6/7 with older Node baselines | Vite 8 docs current at `v8.0.1` | 2026-03-12 | New projects should expect Node `20.19+` or `22.12+` for frontend development |
| React 18 docs as the latest baseline | React 19.2 docs are current | 2025 | Use React 19 client APIs and current typings/templates |
| React Router v6 as the default assumption | React Router v7 is the current line; `v7.13.1` is current in official changelog | 2024-11 onward | Prefer v7 route APIs and stay on the maintained line with recent security fixes |
| Vitest Browser Mode marked experimental | Vitest 4 blog states Browser Mode is stable | 2025-10 | Full browser automation is available later if needed, but Phase 20 can stay lighter with RTL/jsdom plus manual smoke |

**Deprecated/outdated:**
- Building SPAs around permissive dev CORS instead of a proxy.
- HashRouter as the default answer for packaged apps that already control the backend.
- Runtime frontend builds on end-user startup for local packaged apps.
- Rewriting backend routes just to make the frontend "look cleaner".

## Open Questions

1. **Should Phase 20 add TanStack Query now, or keep the first frontend pass on plain hooks?**
   - What we know: the SPA needs chat history loading, runtime polling, task-launch invalidation, and diagnostics fetches.
   - What's unclear: whether the team wants the extra dependency immediately.
   - Recommendation: use TanStack Query now. This phase already crosses the complexity threshold where ad hoc server-state management becomes noisy.

2. **Should packaged mode rely on `python -m nanobot.tui` only, or also add a console script?**
   - What we know: the module entrypoint already exists and is tested.
   - What's unclear: whether discoverability matters enough to add `nanobot-tui`.
   - Recommendation: keep `python -m nanobot.tui` and add `nanobot-tui` in `pyproject.toml` as a friendly alias.

3. **Should the frontend source be shipped in the wheel, or only the built `dist/` assets?**
   - What we know: packaged mode only needs built assets; dev mode uses source files.
   - What's unclear: how much source should be included in the distribution artifact.
   - Recommendation: ship the built `dist/` assets for runtime and keep source inclusion only if the project wants editable installs to preserve frontend sources in the sdist.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` 9.x + `vitest` 4.0.17 |
| Config file | [`pyproject.toml`](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml) and `nanobot/tui/web/vitest.config.ts` |
| Quick run command | `npm --prefix nanobot/tui/web run test -- --run` |
| Full suite command | `.venv/bin/python -m pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py tests/test_commands.py tests/test_tui_p20_static.py tests/test_tui_p20_entrypoints.py -q && npm --prefix nanobot/tui/web run test -- --run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WEB-01 | Opening the local app serves one browser workspace shell in both dev-facing and packaged serving modes | frontend integration + pytest API/static | `npm --prefix nanobot/tui/web run test -- --run AppShell` and `.venv/bin/python -m pytest tests/test_tui_p20_static.py::test_root_serves_spa_shell -q` | ❌ Wave 0 |
| WEB-02 | Switching between chat and operations keeps active session/run context intact | frontend integration | `npm --prefix nanobot/tui/web run test -- --run WorkspaceNavigation` | ❌ Wave 0 |
| SHIP-01 | Development and packaged startup entrypoints are documented and do not break CLI usage | pytest integration + CLI regression | `.venv/bin/python -m pytest tests/test_tui_p20_entrypoints.py tests/test_commands.py -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** relevant Vitest slice or focused pytest slice, depending on changed surface
- **Per wave merge:** one frontend run plus one focused Python integration run
- **Phase gate:** full Phase 17-20 pytest slice green, frontend tests green, and manual browser smoke completed before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `nanobot/tui/web/package.json` — frontend dependency and script baseline
- [ ] `nanobot/tui/web/vite.config.ts` — dev proxy and build config
- [ ] `nanobot/tui/web/tsconfig.json` — TypeScript compiler baseline
- [ ] `nanobot/tui/web/src/app/app-shell.test.tsx` — navigation/context retention coverage for `WEB-01`/`WEB-02`
- [ ] `tests/test_tui_p20_static.py` — FastAPI static mount and SPA fallback coverage
- [ ] `tests/test_tui_p20_entrypoints.py` — module/script startup and packaged asset discovery coverage
- [ ] `20-MANUAL-SMOKE.md` — local browser smoke path for packaged and dev startup

## Sources

### Primary (HIGH confidence)
- Local repo files loaded for this research:
  - [STATE.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/STATE.md)
  - [PROJECT.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/PROJECT.md)
  - [ROADMAP.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/ROADMAP.md)
  - [REQUIREMENTS.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/REQUIREMENTS.md)
  - [pyproject.toml](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml)
  - [app.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/app.py)
  - [__main__.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/__main__.py)
  - [dependencies.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/dependencies.py)
  - [runtime.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/services/runtime.py)
  - [tasks.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/services/tasks.py)
- FastAPI Static Files docs: https://fastapi.tiangolo.com/tutorial/static-files/
- Vite Server Options docs: https://vite.dev/config/server-options
- Vite Build docs: https://vite.dev/guide/build
- React Versions docs: https://react.dev/versions
- React DOM client docs: https://react.dev/reference/react-dom/client
- React Router `createBrowserRouter` API docs: https://reactrouter.com/api/data-routers/createBrowserRouter
- React Router changelog: https://reactrouter.com/start/start/changelog
- TanStack Query React overview: https://tanstack.com/query/latest/docs/framework/react/overview
- MDN `EventSource` docs: https://developer.mozilla.org/en-US/docs/Web/API/EventSource/EventSource

### Secondary (MEDIUM confidence)
- `@vitejs/plugin-react` npm package page/search result: https://www.npmjs.com/package/%40vitejs/plugin-react
- `@testing-library/react` npm package page/search result: https://www.npmjs.com/package/%40testing-library/react
- Vitest homepage/blog pages: https://vitest.dev/ and https://vitest.dev/blog

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - core runtime and routing choices are backed by current official docs; a few version details come from npm package pages
- Architecture: HIGH - driven by the current repo state plus official SPA/static-serving patterns
- Pitfalls: HIGH - most come directly from current repo packaging/tests plus standard Vite/FastAPI integration failure modes

**Research date:** 2026-03-21
**Valid until:** 2026-04-20
