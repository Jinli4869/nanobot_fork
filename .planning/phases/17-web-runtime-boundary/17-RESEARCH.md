# Phase 17: Web Runtime Boundary - Research

**Researched:** 2026-03-21
**Domain:** Local-first web runtime boundary for nanobot using FastAPI, with future React/Vite integration isolated under `nanobot/tui`
**Confidence:** HIGH

<user_constraints>
## User Constraints

No `17-CONTEXT.md` exists for this phase. This research therefore treats the following as authoritative constraints:
- `.planning/ROADMAP.md` Phase 17 goal and success criteria
- `.planning/REQUIREMENTS.md` requirements `ISO-01` and `ISO-02`
- `.planning/STATE.md` and `.planning/PROJECT.md` decisions already locked by Phases 12-16
- The explicit user request to use `FastAPI + React + Vite`
- The explicit user request to keep the work under `nanobot/tui` as much as possible and avoid polluting the native nanobot codebase

### Locked Decisions
- The web stack should live primarily under `nanobot/tui`; any edits outside that tree must be thin shims, configuration additions, or entrypoint wiring.
- This phase is a runtime-boundary phase, not a visual design phase. The React/Vite UI itself is not the center of gravity yet.
- Existing CLI, channel, and background GUI flows must keep working without requiring the web surface.
- Existing session persistence via `nanobot/session/manager.py` should remain the source of truth for chat history instead of introducing a second storage format.
- Existing host/runtime semantics for OpenGUI should remain in `opengui` and `nanobot.agent.tools.gui`; the web layer should adapt them rather than fork them.
- The first release is local-first and should default to localhost-safe serving behavior with explicit configuration.

### Claude's Discretion
- The exact Python package layout under `nanobot/tui` as long as responsibilities remain explicit and low-coupling.
- Whether the web app factory is exposed through `python -m nanobot.tui`, a Typer subcommand later, or both, provided Phase 17 stays focused on runtime seams.
- Whether adapter seams are expressed as service classes, dependency-provider functions, or a small facade module, provided React/Vite never imports core nanobot modules directly.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ISO-01 | The web backend lives under `nanobot/tui` and reaches existing nanobot or OpenGUI behavior through thin adapter boundaries instead of broad core-runtime refactors | Define package boundaries, app factory, API routers, and service/adaptor modules that reuse existing runtime objects without rewriting them |
| ISO-02 | The first web release defaults to local-first safe access patterns such as localhost binding and explicit config, without adding mandatory cloud dependencies | Add dedicated `tui/web` config defaults, local bind host/port behavior, and startup seams that do not auto-open network exposure |
</phase_requirements>

## Summary

Phase 17 should behave like a foundation phase for a future web product surface, not like a full-stack feature phase. The most important architectural move is to create a **stable backend boundary** that future phases can build on:

1. `nanobot/tui` owns the web-facing code:
   - FastAPI app factory
   - route registration
   - dependency wiring
   - thin service/adaptor modules
2. Existing nanobot and OpenGUI modules remain the system of record:
   - `nanobot.session.manager.SessionManager` for persisted chat sessions
   - `nanobot.agent.loop.AgentLoop` for core direct-chat execution
   - `nanobot.agent.tools.gui.GuiSubagentTool` and `opengui/*` for GUI automation semantics
3. Cross-boundary changes outside `nanobot/tui` should be minimal and explicit:
   - new config schema for web defaults
   - optional dependency group(s)
   - possibly one CLI/module entry seam later

This phase should **not** yet implement the full browser chat or operations experience. Instead it should ensure the future UI has a clean, testable backend to talk to. That means success in Phase 17 looks like:
- `create_app()` works
- backend config is local-first
- routers/dependencies are isolated
- adapter seams to sessions/runtime are explicit
- imports do not force broad nanobot runtime side effects just to construct the web app

## Existing Code Surface

### Useful Reuse Points
- `nanobot/session/manager.py`
  - Already provides stable persisted chat session listing and retrieval semantics
  - Suitable source for future `/sessions` and session metadata endpoints
- `nanobot/agent/loop.py`
  - Central execution engine for direct agent interactions
  - Likely needs an adapter/facade rather than being imported directly inside route functions
- `nanobot/config/loader.py` and `nanobot/config/schema.py`
  - Natural place for a minimal `TuiConfig` / `WebConfig` addition
  - Should remain the single config source rather than inventing a separate YAML/TOML tree for the web app
- `nanobot/agent/tools/gui.py`
  - Stable boundary for future web-triggered GUI tasks
  - Important to keep web orchestration host-facing and JSON-friendly

### Current Gaps
- No HTTP application object exists in the repo today
- No web-serving config section exists in `Config`
- No frontend asset directory or Node workspace exists
- No app-factory tests or HTTP route tests exist
- `pyproject.toml` does not yet include `fastapi` / `uvicorn`

## Recommended Architecture

### Package Layout

Recommended Phase 17 layout:

```text
nanobot/tui/
  __init__.py
  __main__.py              # optional dev/module startup seam
  app.py                   # FastAPI app factory
  config.py                # web-specific config normalization
  dependencies.py          # request-scoped dependency builders
  services/
    __init__.py
    sessions.py            # thin wrappers around SessionManager
    runtime.py             # host/runtime inspection facade
  routes/
    __init__.py
    health.py              # health/ping/version
    sessions.py            # read-only session metadata surface
    runtime.py             # runtime status shell for later ops phase
  schemas/
    __init__.py
    sessions.py
    runtime.py
```

What should **not** happen in Phase 17:
- Route handlers instantiating `AgentLoop` ad hoc with duplicated config logic
- React/Vite files mixed into existing Python package roots outside `nanobot/tui`
- Introducing a second session store or a web-only persistence layer
- Adding frontend-specific business logic directly into `nanobot/cli/commands.py`

### Service Boundary Pattern

Prefer:
- routes -> dependency providers -> service adapters -> existing nanobot/OpenGUI modules

Avoid:
- routes -> direct imports of half the runtime graph

This keeps the future React client decoupled from backend internals and makes Phase 17 testable with focused API/app-factory coverage.

## Standard Stack

### Core
| Library | Version Direction | Purpose | Why |
|---------|-------------------|---------|-----|
| `fastapi` | current stable 0.11x+ | HTTP app + dependency injection + response models | Best fit for a typed local-first backend shell |
| `uvicorn[standard]` | current stable 0.3x+ | Development and packaged ASGI serving | Lowest-friction runtime for a local app |
| `pydantic` | existing repo 2.12+ | Request/response schema consistency | Already a first-class dependency |
| `httpx` | existing repo 0.28+ | Useful for API tests / future internal clients | Already present in the project |

### Supporting
| Library | Version Direction | Purpose | When to Use |
|---------|-------------------|---------|-------------|
| `pytest` + `pytest-asyncio` | existing repo | App-factory and service-boundary tests | Default testing path |
| `starlette.testclient` or `httpx.AsyncClient` | bundled via FastAPI/Starlette | API route tests | Phase 17 route smoke coverage |
| Node + Vite + React | future phase setup | Frontend workspace under `nanobot/tui/web/` | Mentioned now, but most implementation belongs to later phases |

### Dependency Strategy

Best fit for this repo:
- add a new optional dependency group such as `web = ["fastapi", "uvicorn[standard]"]`
- keep frontend Node dependencies inside `nanobot/tui/web/package.json` later
- do **not** force Node tooling into the Python package install path for Phase 17

This honors the isolation goal and avoids making every nanobot install pay the React/Vite cost immediately.

## Recommended Plan Split

### Plan 17-01: Package Boundary, App Shell, and Adapter Contracts
Focus:
- add `nanobot/tui` package skeleton
- implement `create_app()` with minimal routers
- define response schemas and dependency seams
- expose read-only session/runtime adapter contracts
- seed tests that prove app construction stays isolated

Primary outputs:
- `nanobot/tui/app.py`
- route/dependency/service skeletons
- focused tests for app construction and adapter isolation

### Plan 17-02: Local-First Config and Startup Wiring
Focus:
- add minimal config schema for web host/port/local-first behavior
- wire startup helpers without breaking current CLI/channel flows
- define development launch seam
- ensure safe defaults such as `127.0.0.1`
- add regression tests around config loading and startup

Primary outputs:
- config schema additions
- startup module or internal launcher
- regression tests proving existing CLI remains unaffected

## Patterns to Follow

### Pattern 1: App Factory First
Create a pure-ish `create_app(config, workspace, provider_factory?)` seam or equivalent that can be imported and tested without booting the whole CLI runtime.

**Why:** This is the cleanest way to protect Phase 17 from devolving into hard-to-test startup spaghetti.

### Pattern 2: Read-Only Endpoints Before Mutating Endpoints
Use read-only health/session/runtime endpoints first, even if they are simple. This locks shape and dependency flow without prematurely coupling to write-heavy chat/task behavior.

**Why:** It proves the boundary without dragging Phase 18/19 work into Phase 17.

### Pattern 3: Config Additions Must Be Narrow
Add a dedicated config object for the web runtime, for example:
- host
- port
- enabled
- dev mode / static asset mode later

Do not mix web-only behavior into unrelated `gateway` or `gui` fields.

**Why:** Reusing existing config plumbing is good; overloading unrelated config sections is how drift starts.

### Pattern 4: Keep Future Frontend Static Serving Optional
Design the app factory so serving a built React app can be layered in later, but do not make that mandatory for Phase 17 startup.

**Why:** Phase 17 is about backend boundary stability, not bundled SPA delivery.

## Anti-Patterns to Avoid

- **Creating a second nanobot runtime just for web requests:** leads to duplicated config, provider, and session semantics
- **Putting FastAPI code in `nanobot/cli/` or `opengui/cli.py`:** breaks the isolation goal
- **Binding to `0.0.0.0` by default:** violates the local-first safety requirement
- **Committing React/Vite scaffolding before backend seams exist:** risks designing the API from the UI inward
- **Adding broad global state to route handlers:** makes later streaming/chat work brittle

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Chat session persistence | New database or JSON format | `nanobot.session.manager.SessionManager` | Existing persisted format already works |
| Config loading | Separate web config loader | `nanobot.config.loader.load_config()` plus a narrow web config section | Keeps one source of truth |
| Runtime task semantics | Web-only GUI orchestration rules | existing nanobot/OpenGUI adapters | Prevents host drift |
| Dev HTTP serving | Custom socket server | FastAPI + Uvicorn | Standard, testable, low ceremony |

## Common Pitfalls

### Pitfall 1: Route Handlers Become Integration Dumps
**What goes wrong:** endpoints instantiate providers, loops, session managers, and GUI helpers inline.
**How to avoid:** force route handlers through dependency functions and narrow service objects.

### Pitfall 2: Phase 17 Accidentally Becomes Phase 18
**What goes wrong:** the team starts implementing streaming chat or full task launch before boundary tests are stable.
**How to avoid:** keep Phase 17 focused on app factory, config, routers, and adapter seams only.

### Pitfall 3: Config Defaults Leak Network Exposure
**What goes wrong:** a helpful default uses `0.0.0.0` or auto-enables a remote-access assumption.
**How to avoid:** default to localhost and explicit opt-in for anything broader.

### Pitfall 4: FastAPI Import Path Pulls in Heavy Runtime Side Effects
**What goes wrong:** importing the app triggers channel startup, MCP connections, or CLI initialization.
**How to avoid:** keep `create_app()` dependency-driven and lazily instantiate runtime-heavy objects.

## Validation Architecture

Phase 17 is best executed as a two-plan phase:

1. **Plan 01:** establish `nanobot/tui` package structure, FastAPI app factory, read-only skeleton routes, and thin service/adaptor contracts with Wave 0 tests.
2. **Plan 02:** add local-first config defaults, startup/module wiring, and regression coverage that proves CLI/channel flows remain unaffected.

### Recommended Automated Coverage
- New tests:
  - `tests/test_tui_p17_runtime.py`
  - `tests/test_tui_p17_config.py`
- Likely touched existing tests:
  - `tests/test_commands.py`
  - `tests/test_session_manager_history.py`
  - `tests/test_config_paths.py`

### Minimum Behaviors to Lock
- `create_app()` can construct the web runtime without starting unrelated services
- route registration is isolated under `nanobot/tui`
- session/runtime adapters reuse existing nanobot objects rather than duplicating logic
- default host binding is local-first
- adding web config does not change CLI defaults or existing channel behavior
- the frontend can be layered in later without reworking the backend boundary
