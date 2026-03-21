# Roadmap: OpenGUI

## Overview

OpenGUI has shipped two milestones so far: v1.0 established the reusable GUI subagent core, and v1.1 added Linux background desktop execution through a virtual display abstraction and integration-safe wrappers. Milestone v1.2 closes the remaining cross-platform background-execution work, and milestone v1.3 expands the nanobot host surface with an isolated local web workspace.

## Milestones

- ✅ **v1.0 Core Foundations** — Phases 1-8 (shipped 2026-03-19)
- ✅ **v1.1 Background Execution** — Phases 9-11 (shipped 2026-03-20) — [Archive](/Users/jinli/Documents/Personal/nanobot_fork/.planning/milestones/v1.1-ROADMAP.md)
- ○ **v1.2 Cross-Platform Background Execution** — Phases 12-16 (closeout in progress)
- ○ **v1.3 Nanobot Web Workspace** — Phases 17-20 (in progress)

## Current Milestone: v1.3 Nanobot Web Workspace

**Goal:** Add a local-first browser workspace for nanobot that combines chat and operations in one app while keeping the new FastAPI + React + Vite stack isolated under `nanobot/tui`.

**Requirements:** 11 mapped / 11 total

| Phase | Name | Goal | Requirements | Success Criteria |
|-------|------|------|--------------|------------------|
| 17 | Web Runtime Boundary | Establish an isolated FastAPI service shell, local-first web runtime defaults, and adapter contracts under `nanobot/tui` without destabilizing existing nanobot or OpenGUI flows. | ISO-01, ISO-02 | 4 |
| 18 | Chat Workspace | Expose session-backed chat APIs and streaming updates so the browser can create, continue, and recover nanobot conversations. | CHAT-01, CHAT-02, CHAT-03 | 4 |
| 19 | Operations Console | Surface task launch, runtime status, and trace/log inspection for supported nanobot and OpenGUI workflows. | OPS-01, OPS-02, OPS-03 | 4 |
| 20 | Web App Integration and Verification | Deliver the React/Vite workspace shell, unify chat and operations navigation, and ship runnable entrypoints and regression coverage. | WEB-01, WEB-02, SHIP-01 | 4 |

## Phase Details

### Phase 17: Web Runtime Boundary

**Goal:** Establish an isolated FastAPI service shell, local-first web runtime defaults, and adapter contracts under `nanobot/tui` without destabilizing existing nanobot or OpenGUI flows.

**Depends on:** Phase 16
**Requirements:** ISO-01, ISO-02
**Plans:** 2/2 plans complete

Plans:
- [x] 17-01-PLAN.md — Define `nanobot/tui` package layout, FastAPI app shell, and shared adapter contracts
- [x] 17-02-PLAN.md — Add local-first config, startup wiring, and regression-safe integration seams

**Success criteria:**
1. Web backend code lives primarily under `nanobot/tui` with only thin shared shims elsewhere when truly necessary.
2. FastAPI startup, shutdown, and config loading can run without breaking the current CLI and channel entry points.
3. Local-first defaults bind safely and document the boundary between browser UI, web API, and existing runtime code.
4. Adapter contracts for chat, task launch, and runtime inspection are explicit enough to support the React app without deep imports.

### Phase 18: Chat Workspace

**Goal:** Expose session-backed chat APIs and streaming updates so the browser can create, continue, and recover nanobot conversations.

**Depends on:** Phase 17
**Requirements:** CHAT-01, CHAT-02, CHAT-03
**Plans:** 3/3 plans complete

Plans:
- [x] 18-01-PLAN.md — Reuse nanobot session state through chat-focused FastAPI endpoints
- [x] 18-02-PLAN.md — Add streaming transport for assistant output and progress events
- [x] 18-03-PLAN.md — Verify reconnect and session recovery behavior

**Success criteria:**
1. A browser user can start a new chat session and continue it without touching the terminal.
2. Assistant text and progress events stream incrementally into the web client instead of appearing only at the end.
3. Refreshing or reconnecting the page preserves recent session history from backend state.
4. Existing CLI chat behavior remains intact and testable.

### Phase 19: Operations Console

**Goal:** Surface task launch, runtime status, and trace/log inspection for supported nanobot and OpenGUI workflows.

**Depends on:** Phases 17-18
**Requirements:** OPS-01, OPS-02, OPS-03
**Plans:** 2/3 plans complete

Plans:
- [x] 19-01-PLAN.md — Define status and inspection endpoints for sessions, runs, and recent failures
- [x] 19-02-PLAN.md — Add web-triggerable task launch flows for supported nanobot and OpenGUI actions
- [ ] 19-03-PLAN.md — Expose structured traces and logs with regression-safe filtering

**Success criteria:**
1. The browser can show current runtime state for sessions, background runs, and recent failures.
2. Users can launch supported tasks from the operations console with explicit, validated parameters.
3. Web-triggered runs expose logs or traces that are useful for diagnosis without requiring terminal access.
4. Sensitive or noisy internals stay filtered behind stable inspection contracts.

### Phase 20: Web App Integration and Verification

**Goal:** Deliver the React/Vite workspace shell, unify chat and operations navigation, and ship runnable entrypoints and regression coverage.

**Depends on:** Phases 18-19
**Requirements:** WEB-01, WEB-02, SHIP-01
**Plans:** 0/0 plans complete

Plans:
- [ ] 20-01-PLAN.md — Build the React/Vite shell for chat and operations navigation
- [ ] 20-02-PLAN.md — Wire the production/dev entrypoints between FastAPI and the frontend build
- [ ] 20-03-PLAN.md — Add end-to-end smoke coverage and documentation for web startup

**Success criteria:**
1. A user can open a single web app and move between chat and operations without losing context.
2. The React/Vite frontend and FastAPI backend can run in development and packaged modes with documented commands.
3. Regression coverage proves the web surface works without regressing existing CLI-first behavior.
4. The milestone closes with a verification pass and manual smoke path for local browser usage.

## Phase Ordering Rationale

- Phase 17 comes first because the web surface needs a clean boundary under `nanobot/tui` before any UI code or API growth begins.
- Chat comes before operations because browser chat is the narrowest host-facing vertical slice and reuses more existing session behavior.
- Operations follows once the web runtime and chat transport are stable enough to support broader task launch and inspection flows.
- Integration and verification are last so the React/Vite shell and packaged entrypoints validate the final contracts rather than an intermediate prototype.

## Archived Phase Ranges

- v1.0: Phases 1-8
- v1.1: Phases 9-11

## Progress

| Milestone | Phase Range | Status | Shipped |
|-----------|-------------|--------|---------|
| v1.0 Core Foundations | 1-8 | Complete | 2026-03-19 |
| v1.1 Background Execution | 9-11 | Complete | 2026-03-20 |
| v1.2 Cross-Platform Background Execution | 12-16 | Closeout In Progress | — |
| v1.3 Nanobot Web Workspace | 17-20 | In Progress | — |

---
*Roadmap defined: 2026-03-21*
*Last updated: 2026-03-21 after executing Phase 19 operations console plan 02*
