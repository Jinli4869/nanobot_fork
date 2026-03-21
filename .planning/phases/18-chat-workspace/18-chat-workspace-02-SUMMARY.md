---
phase: 18-chat-workspace
plan: "02"
subsystem: api
tags: [fastapi, sse, chat, session-manager, tdd]
requires:
  - phase: 18-01
    provides: Session-backed chat routes and service seams under nanobot/tui
provides:
  - Browser-friendly GET SSE stream for chat session events
  - In-process broker for ordered progress, final, error, and completion events
  - Regression coverage for typed event envelopes and transport ordering
affects: [18-03, nanobot/tui, browser-chat]
tech-stack:
  added: []
  patterns: [Transient in-process SSE broker, POST mutation plus GET event stream]
key-files:
  created: [nanobot/tui/services/event_stream.py]
  modified: [nanobot/tui/dependencies.py, nanobot/tui/routes/chat.py, nanobot/tui/services/chat.py, tests/test_tui_p18_streaming.py]
key-decisions:
  - "Keep browser streaming inside nanobot/tui with a transient broker while SessionManager remains the durable source of truth."
  - "Use POST /chat/sessions/{session_id}/messages plus GET /chat/sessions/{session_id}/events instead of a streaming POST transport."
patterns-established:
  - "Chat runs publish typed message.accepted, progress, assistant.final, error, and complete events through a shared app-local broker."
  - "SSE endpoints can replay transient backlog from the broker while persisted transcript recovery still comes from SessionManager."
requirements-completed: [CHAT-02]
duration: 10min
completed: 2026-03-21
---

# Phase 18 Plan 02: Chat Workspace Summary

**Real-time browser chat updates via FastAPI SSE, with ordered progress and final assistant events emitted from the existing direct-chat runtime path**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-21T13:36:00Z
- **Completed:** 2026-03-21T13:45:54Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- Added a transient `EventStreamBroker` under `nanobot/tui` to fan out typed chat events per browser session.
- Wired `ChatWorkspaceService` to publish `message.accepted`, `progress`, `assistant.final`, `error`, and `complete` events while reusing `AgentLoop.process_direct()`.
- Exposed `GET /chat/sessions/{session_id}/events` as an SSE endpoint and covered the transport with Phase 18 streaming tests.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add streaming tests and typed SSE event models** - `3b7d7e1` (test)
2. **Task 2: Implement the in-memory event broker and SSE chat stream** - `8527a9a` (feat)

## Files Created/Modified
- `nanobot/tui/services/event_stream.py` - In-process broker with per-session replay buffer and subscriber cleanup.
- `nanobot/tui/routes/chat.py` - Adds the SSE event endpoint alongside the existing session and message routes.
- `nanobot/tui/services/chat.py` - Publishes ordered progress/final/error events from the direct chat runtime callback path.
- `nanobot/tui/dependencies.py` - Shares a single app-local broker instance with the chat service and routes.
- `tests/test_tui_p18_streaming.py` - Verifies typed event ordering and the GET + SSE transport contract.

## Decisions Made

- Kept the broker transient and process-local so session durability still comes from `SessionManager`.
- Preserved a browser-native GET SSE stream rather than introducing WebSockets or POST-streaming transport.
- Terminated the SSE iterator on `complete` so tests and browser consumers receive a clean terminal event.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Switched to the documented `.venv` pytest fallback**
- **Found during:** Task 1
- **Issue:** `uv run --extra dev pytest ...` failed in the local environment because `python-olm` required missing build tooling (`cmake`/`gmake`).
- **Fix:** Used the phase validation document's `.venv/bin/python -m pytest ...` fallback for all verification in this plan.
- **Files modified:** None
- **Verification:** Red and green test slices both completed successfully with the fallback command.
- **Committed in:** `3b7d7e1`

**2. [Rule 1 - Bug] Adjusted SSE output formatting for the current FastAPI stack**
- **Found during:** Task 2
- **Issue:** `EventSourceResponse` in this environment did not serialize `ServerSentEvent` objects and crashed while encoding the stream response.
- **Fix:** Kept `EventSourceResponse` but emitted preformatted SSE text chunks, preserving the GET SSE contract and event metadata.
- **Files modified:** `nanobot/tui/routes/chat.py`
- **Verification:** `tests/test_tui_p18_streaming.py` and `tests/test_tui_p18_chat.py` pass.
- **Committed in:** `8527a9a`

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes were necessary to complete verification and keep the SSE transport working on the current stack. No scope creep.

## Issues Encountered

- `fastapi.sse.EventSourceResponse` behaved differently than expected under the installed stack and needed text-framed SSE output instead of `ServerSentEvent` objects.
- The default `uv run --extra dev` path is not currently reliable on this machine because of an unrelated native build dependency.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 18 now has stable browser chat mutation and streaming seams for reconnect/recovery work in `18-03`.
- The transient broker exposes recent run events without becoming a durable source of truth, so recovery can stay centered on `SessionManager`.

## Self-Check: PASSED

- Summary file exists.
- Task commits `3b7d7e1` and `8527a9a` exist in git history.
- Key implementation files referenced in this summary exist in the workspace.

---
*Phase: 18-chat-workspace*
*Completed: 2026-03-21*
