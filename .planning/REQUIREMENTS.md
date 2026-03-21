# Requirements: OpenGUI

**Defined:** 2026-03-21
**Core Value:** Any host agent can spawn a GUI subagent to complete device tasks autonomously.

## v1 Requirements

Requirements for milestone v1.3: Nanobot Web Workspace.

### Web App Shell

- [ ] **WEB-01**: User can open a browser-based nanobot workspace served from the local app instead of relying on terminal-only interaction
- [ ] **WEB-02**: User can switch between chat and operations views inside one web app without losing the active workspace context

### Chat Workspace

- [x] **CHAT-01**: User can start a new nanobot conversation and send follow-up messages from the web UI
- [ ] **CHAT-02**: User sees streamed assistant responses and progress updates in the web UI as they happen
- [ ] **CHAT-03**: User can refresh or reconnect the page and recover recent session history from backend state

### Operations Console

- [ ] **OPS-01**: User can inspect runtime status for sessions, background GUI runs, and recent failures from the web UI
- [ ] **OPS-02**: User can launch supported nanobot or OpenGUI tasks from the web UI with explicit task parameters
- [ ] **OPS-03**: User can inspect structured logs or event traces for web-triggered runs without dropping to the terminal

### Isolation and Delivery

- [ ] **ISO-01**: The web backend lives under `nanobot/tui` and reaches existing nanobot or OpenGUI behavior through thin adapter boundaries instead of broad core-runtime refactors
- [ ] **ISO-02**: The first web release defaults to local-first safe access patterns such as localhost binding and explicit config, without adding mandatory cloud dependencies
- [ ] **SHIP-01**: User can start the web workspace through documented development and packaged entrypoints without breaking existing CLI usage

## v2 Requirements

### Multi-User and Remote Access

- **AUTH-01**: User can protect the web workspace with first-class authentication suitable for non-local or multi-user deployment
- **AUTH-02**: Operators can manage multiple users or roles inside the same web workspace instance

### Richer Browser Operations

- **OBS-01**: User can watch a live browser-rendered viewer for active GUI runs instead of relying only on status and logs
- **TRACE-01**: User can replay completed runs visually with screenshots, actions, and tool events

## Out of Scope

| Feature | Reason |
|---------|--------|
| Replacing the existing CLI and chat-channel surfaces | The web workspace is an added surface, not a rewrite of proven host entry points |
| Broadly refactoring core nanobot or OpenGUI runtime modules to fit the web UI | Violates the isolation goal for work under `nanobot/tui` |
| Multi-user auth, internet-facing hosting, or cloud tenancy in v1.3 | Expands scope beyond the requested local-first web milestone |
| A full live remote desktop viewer in the browser | Better treated as a later milestone after chat and operations basics ship |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ISO-01 | Phase 17 | Pending |
| ISO-02 | Phase 17 | Pending |
| CHAT-01 | Phase 18 | Complete |
| CHAT-02 | Phase 18 | Pending |
| CHAT-03 | Phase 18 | Pending |
| OPS-01 | Phase 19 | Pending |
| OPS-02 | Phase 19 | Pending |
| OPS-03 | Phase 19 | Pending |
| WEB-01 | Phase 20 | Pending |
| WEB-02 | Phase 20 | Pending |
| SHIP-01 | Phase 20 | Pending |

**Coverage:**
- v1 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-21*
*Last updated: 2026-03-21 after executing Phase 18 chat workspace plan 01*
