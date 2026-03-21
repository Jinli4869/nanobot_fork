---
phase: 18-chat-workspace
plan: "01"
subsystem: api
tags: [fastapi, nanobot-tui, chat, session-manager, agent-loop]
requires:
  - phase: 17-web-runtime-boundary
    provides: isolated FastAPI shell, localhost-first TUI runtime config, and contract-backed browser seams
provides:
  - session-backed chat create/read/send endpoints under `nanobot/tui`
  - browser chat service that reuses `SessionManager` and `AgentLoop.process_direct()`
  - explicit runtime factory seam for provider, bus, cron, and agent-loop construction without Typer routing
affects: [phase-18-chat-workspace, phase-19-operations-console, phase-20-web-app-integration-and-verification]
tech-stack:
  added: []
  patterns:
    - browser chat routes depend on a thin service adapter instead of CLI commands
    - runtime-enabled TUI apps opt into mutable chat routes while health-only mode stays unchanged
key-files:
  created:
    - nanobot/tui/routes/chat.py
    - nanobot/tui/services/chat.py
    - nanobot/tui/schemas/chat.py
    - tests/test_tui_p18_chat.py
    - .planning/phases/18-chat-workspace/18-chat-workspace-01-SUMMARY.md
  modified:
    - nanobot/tui/app.py
    - nanobot/tui/contracts.py
    - nanobot/tui/dependencies.py
    - nanobot/tui/routes/__init__.py
    - nanobot/tui/schemas/__init__.py
    - nanobot/tui/services/__init__.py
key-decisions:
  - "Browser chat sessions are persisted under `tui:{session_id}` so the web API never collides with `cli:direct`."
  - "The chat service and the runtime factory share one `SessionManager` instance so persisted transcript reads stay authoritative after `process_direct()` writes."
patterns-established:
  - "Future browser mutations should reuse `get_chat_runtime_factory()` instead of reconstructing providers or cron services inside route handlers."
  - "Web chat behavior stays inside `nanobot/tui`, with FastAPI dependencies bridging into existing nanobot runtime objects."
requirements-completed: [CHAT-01]
duration: 5min
completed: 2026-03-21
---

# Phase 18 Plan 01: Chat Workspace Summary

**Session-backed browser chat routes now create `tui:` conversations, reuse `AgentLoop.process_direct()`, and recover transcript history from `SessionManager`**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-21T13:29:52Z
- **Completed:** 2026-03-21T13:34:45Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Added typed browser chat schemas and route expectations for session create, history read, and follow-up message submission.
- Implemented `ChatWorkspaceService` as a thin adapter over `SessionManager` and an injected `AgentLoop` runtime factory.
- Wired chat routes into runtime-enabled TUI app instances without changing `nanobot/cli/commands.py` or introducing Typer routing.

## Task Commits

Each task was committed atomically:

1. **Task 1: Define chat contracts, schemas, and Wave 0 route expectations** - `8b486b1` (`test(18-01): add failing browser chat route coverage`)
2. **Task 2: Implement chat workspace service, dependencies, routes, and app wiring** - `e60cebc` (`feat(18-01): add session-backed tui chat routes`)

**Plan metadata:** recorded in the follow-up docs commit.

## Files Created/Modified

- `nanobot/tui/contracts.py` - Added the browser chat contract placeholder to the Phase 17 contract layer.
- `nanobot/tui/dependencies.py` - Added `get_chat_runtime_factory()` and `get_chat_workspace_service()` with shared session-manager wiring.
- `nanobot/tui/routes/chat.py` - Added create/read/send browser chat endpoints.
- `nanobot/tui/services/chat.py` - Added the session-backed chat adapter over `SessionManager` and `AgentLoop.process_direct()`.
- `nanobot/tui/schemas/chat.py` - Added typed request/response payloads for browser chat sessions and messages.
- `tests/test_tui_p18_chat.py` - Added route-level coverage for `tui:` session keys, persisted transcript reads, and direct-chat runtime reuse.

## Decisions Made

- Kept browser chat under a dedicated `tui:` namespace so persisted session recovery stays isolated from existing CLI conversations.
- Reused the Phase 17 dependency pattern instead of calling CLI commands or booting Typer flows from the browser path.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The plan’s `uv run --extra dev pytest ...` commands were blocked locally by a `python-olm` build dependency (`cmake`/`gmake` missing). Verification used the documented `.venv/bin/python -m pytest ...` fallback from `18-VALIDATION.md`.
- Parallel `git add` calls created transient `.git/index.lock` files, so staging was retried sequentially. No user files were reverted or removed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 18 now has the create/read/send chat API foundation needed for streaming transport work in `18-02`.
- The chat routes already preserve the Phase 17 boundary, so later browser features can continue to build under `nanobot/tui` without reopening CLI coupling.

## Self-Check: PASSED

- Found `.planning/phases/18-chat-workspace/18-chat-workspace-01-SUMMARY.md`.
- Confirmed task commits `8b486b1` and `e60cebc` exist in git history.
