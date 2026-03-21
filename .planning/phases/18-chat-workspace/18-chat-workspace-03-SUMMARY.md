---
phase: 18-chat-workspace
plan: 03
subsystem: api
tags: [fastapi, sse, session-manager, pytest, cli-regression]
requires:
  - phase: 18-chat-workspace
    provides: "Session-backed chat routes and transient SSE transport from plans 18-01 and 18-02"
provides:
  - "Reconnect-safe SSE replay from Last-Event-ID"
  - "Refresh-time transcript recovery from SessionManager-backed session history"
  - "CLI regression coverage proving direct chat still uses the legacy process_direct path"
affects: [phase-19-operations-console, phase-20-web-app-integration, chat-recovery, cli]
tech-stack:
  added: []
  patterns: ["Persist durable chat history in SessionManager and keep broker replay transport-only", "Protect CLI invariants with regression tests instead of changing command behavior"]
key-files:
  created: []
  modified: [nanobot/tui/routes/chat.py, nanobot/tui/services/event_stream.py, tests/test_tui_p18_chat.py, tests/test_tui_p18_streaming.py, tests/test_commands.py]
key-decisions:
  - "Browser reconnect recovery remains split by concern: SessionManager supplies transcript state, while the SSE broker only replays transient transport events after Last-Event-ID."
  - "CLI safety stayed test-driven; tests now assert the unchanged cli:direct process_direct call shape instead of broadening nanobot/cli/commands.py."
patterns-established:
  - "Reconnect pattern: use durable GET /chat/sessions/{session_id} for history and cursor-based SSE replay only for in-flight transport gaps."
  - "Regression pattern: when browser work risks terminal drift, extend tests/test_commands.py before considering CLI production edits."
requirements-completed: [CHAT-03]
duration: 6min
completed: 2026-03-21
---

# Phase 18 Plan 03: Chat Workspace Summary

**SessionManager-backed transcript recovery with Last-Event-ID SSE replay and locked CLI direct-chat regression coverage**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-21T13:46:00Z
- **Completed:** 2026-03-21T13:52:18Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Browser refresh now rebuilds recent transcript state from persisted `tui:` sessions instead of depending on the transient event broker.
- SSE reconnects can resume from `Last-Event-ID`, replaying only the remaining transport tail for a session.
- CLI direct chat stayed unchanged and is now regression-tested for the legacy `process_direct("hello", "cli:direct", on_progress=...)` invocation shape.

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement reconnect-safe transcript recovery and event replay semantics** - `e750d15` (feat)
2. **Task 2: Lock the CLI regression boundary and rerun the full Phase 18 validation slice** - `a80973e` (test)

## Files Created/Modified
- `nanobot/tui/routes/chat.py` - Reads `Last-Event-ID` and passes the cursor into SSE subscriptions.
- `nanobot/tui/services/event_stream.py` - Replays only the backlog after a known event id while preserving live fanout behavior.
- `tests/test_tui_p18_chat.py` - Covers persisted transcript recovery after a browser refresh.
- `tests/test_tui_p18_streaming.py` - Covers reconnect replay semantics after `Last-Event-ID`.
- `tests/test_commands.py` - Asserts the CLI still uses the unchanged direct-chat invocation boundary.

## Decisions Made

- Durable browser chat recovery continues to come from `SessionManager`; the broker was not promoted into a durable store.
- SSE reconnect support uses `Last-Event-ID` against the in-memory backlog instead of adding broader route/runtime architecture.
- CLI protection stayed in tests, consistent with the plan constraint to avoid production edits in `nanobot/cli/commands.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Switched validation to the documented local pytest fallback**
- **Found during:** Task 1 verification
- **Issue:** `uv run --extra dev pytest ...` tried to build `python-olm` and failed locally because optional native build tools were unavailable.
- **Fix:** Used the phase's documented fallback command, `.venv/bin/python -m pytest ...`, for both Task 1 verification and the full closeout slice.
- **Files modified:** None
- **Verification:** Task 1 slice passed; full Phase 17/18 validation slice passed with 49 tests green.
- **Committed in:** `e750d15`, `a80973e` (verification for task commits)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Verification command changed for local execution only. Implementation scope and shipped behavior stayed on-plan.

## Issues Encountered

- Parallel `git add` calls briefly contended on `.git/index.lock`; restaging serially resolved it without changing repository content.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 18 is closed with reconnect-safe chat recovery, transient SSE replay, and explicit CLI isolation evidence.
- Phase 19 can build operations endpoints on the existing `nanobot/tui` boundary without reopening chat durability or CLI architecture.

## Self-Check: PASSED
