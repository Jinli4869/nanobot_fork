# Phase 18: Chat Workspace - Research

**Researched:** 2026-03-21
**Domain:** Session-backed browser chat APIs and live streaming transport for the nanobot TUI backend
**Confidence:** MEDIUM-HIGH

<user_constraints>
## User Constraints

No `18-CONTEXT.md` exists for this phase. This research therefore treats the following as authoritative constraints:
- `.planning/ROADMAP.md` Phase 18 goal and success criteria
- `.planning/REQUIREMENTS.md` requirements `CHAT-01`, `CHAT-02`, and `CHAT-03`
- `.planning/STATE.md` decisions already locked by Phases 12-17
- The explicit user request to keep work primarily under `nanobot/tui`
- The explicit user request to reuse existing nanobot session and agent-loop behavior through thin adapters
- The explicit user request to avoid regressing existing CLI chat behavior
- The explicit user request to focus this phase on backend chat workspace seams, not the React shell itself

### Locked Decisions
- Keep the implementation centered under `nanobot/tui`; any changes outside that tree must stay narrow and adapter-oriented.
- Reuse `nanobot.session.manager.SessionManager` as the durable source of truth for session recovery.
- Reuse `nanobot.agent.loop.AgentLoop` for actual chat execution instead of inventing a parallel chat engine.
- Keep existing CLI chat behavior intact; Phase 18 must not rewrite `nanobot.cli.commands` flows.
- Stay local-first and import-safe, following the Phase 17 FastAPI boundary and localhost-first runtime defaults.

### Claude's Discretion
- The exact API shape for session creation, message submission, history recovery, and event streaming.
- Whether transient live events are buffered by session, run, or both, provided durable history still comes from `SessionManager`.
- Whether the browser transport uses SSE only, JSON Lines, or a small hybrid, provided it stays browser-friendly and testable.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CHAT-01 | User can start a new nanobot conversation and send follow-up messages from the web UI | Add chat-specific routes and service adapters that create `tui:{session_id}` sessions and dispatch messages through `AgentLoop.process_direct()` |
| CHAT-02 | User sees streamed assistant responses and progress updates in the web UI as they happen | Use a browser-native streaming endpoint with typed events backed by an in-process event broker and FastAPI SSE primitives |
| CHAT-03 | User can refresh or reconnect the page and recover recent session history from backend state | Extend the session contract to load persisted session messages and expose recovery endpoints backed by `SessionManager` |
</phase_requirements>

## Summary

Phase 18 should stay narrow: build a web chat adapter around the runtime that already exists instead of introducing a second chat engine, a second session store, or browser-specific business logic in the CLI path. The local codebase already provides the two critical building blocks Phase 18 needs. `SessionManager` persists conversations in workspace `sessions/*.jsonl`, and `AgentLoop.process_direct()` already performs the direct-chat execution path the CLI uses, including slash-command handling, session persistence, and incremental progress callbacks.

The missing piece is a web-safe seam around that behavior. The strongest implementation pattern is:
- create browser-specific session ids mapped to `tui:{session_id}` session keys
- submit messages through a thin chat service that owns an `AgentLoop` factory
- stream live updates through SSE on a separate endpoint keyed by session or run id
- recover history from `SessionManager`, not from the transient stream buffer

**Primary recommendation:** Use a two-step transport: `POST` to create/send chat messages through `AgentLoop.process_direct()`, and `GET` SSE to stream typed progress/run events, with session recovery served from persisted `SessionManager` history.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `fastapi` | `0.135.1` | HTTP API surface, dependency injection, built-in SSE support | Already adopted in Phase 17 and now includes first-party SSE primitives |
| `uvicorn[standard]` | `0.42.0` | ASGI runtime for local development and packaged startup | Already the Phase 17 server seam and standard FastAPI runtime |
| `pydantic` | `2.12.x` | Request/response/event schema validation | Already first-class in the repo and used by current TUI schemas |
| `SessionManager` | repo-local | Durable session persistence and listing | Existing source of truth for recovery; avoids a second store |
| `AgentLoop.process_direct()` | repo-local | Chat execution path | Existing direct-chat path already used by CLI and safest thin-adapter seam |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `starlette` | `0.52.1` | Request disconnect detection and streaming response base behavior | Implicit FastAPI dependency; useful for SSE/disconnect semantics |
| `httpx` | `0.28.x` | HTTP-level tests for streaming routes if needed | Use for async transport tests or future frontend integration tests |
| `pytest` | `9.x` | Regression coverage | Existing test framework for route, service, and runtime contract tests |
| `fastapi.testclient` | bundled | Synchronous API tests | Best fit for non-streaming route tests and simple SSE smoke checks |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| GET SSE stream + POST message submit | Single POST request that streams back the response | Simpler server shape, but worse fit for browser-native `EventSource` reconnect and refresh behavior |
| Built-in FastAPI SSE | `StreamingResponse` with JSON Lines | Viable for `fetch()` streaming, but loses SSE event ids/types/reconnect semantics that help CHAT-02 and CHAT-03 |
| Thin adapter over `AgentLoop.process_direct()` | New web-specific chat orchestrator | More control, but violates the isolation goal and risks CLI drift |
| Existing session JSONL store | New DB/cache layer | Adds migration and consistency risk for no Phase 18 benefit |

**Installation:**
```bash
pip install "fastapi>=0.135.1,<1.0.0" "uvicorn[standard]>=0.42.0,<1.0.0"
```

**Version verification:** Verified on 2026-03-21 against PyPI:
- `fastapi` `0.135.1` published 2026-03-01
- `uvicorn` `0.42.0` published 2026-03-16
- `starlette` `0.52.1` published 2026-01-18

## Architecture Patterns

### Recommended Project Structure
```text
nanobot/tui/
├── contracts.py          # extend with chat-focused contract(s)
├── dependencies.py       # add loop/provider/session factory seams
├── routes/
│   ├── chat.py           # create session, get history, submit message, stream events
│   ├── sessions.py       # keep read-only list surface
│   └── runtime.py
├── schemas/
│   ├── chat.py           # request/response/event models
│   └── sessions.py
├── services/
│   ├── chat.py           # thin adapter over SessionManager + AgentLoop
│   ├── event_stream.py   # in-memory run/session event broker
│   └── sessions.py
└── app.py                # include chat router when runtime routes are enabled
```

### Pattern 1: Session-Scoped Chat Adapter
**What:** Add a `ChatWorkspaceService` that turns browser requests into nanobot session keys like `tui:{session_id}` and calls `AgentLoop.process_direct()` with a controlled `channel="tui"` / `chat_id=session_id` mapping.
**When to use:** Every create/send/recover flow in Phase 18.
**Example:**
```python
# Source inspiration:
# - local repo: nanobot.agent.loop.AgentLoop.process_direct()
# - local repo: nanobot.session.manager.SessionManager

session_key = f"tui:{session_id}"
reply = await agent_loop.process_direct(
    message.content,
    session_key=session_key,
    channel="tui",
    chat_id=session_id,
    on_progress=emit_progress,
)
```

### Pattern 2: Separate Mutation and Stream Endpoints
**What:** Use one endpoint to start work and another to observe live events. Recommended shape:
- `POST /chat/sessions`
- `GET /chat/sessions/{session_id}`
- `POST /chat/sessions/{session_id}/messages`
- `GET /chat/sessions/{session_id}/events`
**When to use:** Browser-native chat transport where reconnect and refresh matter.
**Example:**
```python
# Source inspiration:
# - FastAPI SSE docs: https://fastapi.tiangolo.com/tutorial/server-sent-events/
# - Starlette request docs: https://www.starlette.io/requests/

@router.get("/chat/sessions/{session_id}/events", response_class=EventSourceResponse)
async def stream_events(session_id: str, request: Request) -> AsyncIterable[ServerSentEvent]:
    async for event in broker.subscribe(session_id):
        if await request.is_disconnected():
            break
        yield ServerSentEvent(data=event.payload, event=event.type, id=event.id)
```

### Pattern 3: Durable Recovery from Session Files, Not Stream Buffer
**What:** Treat the event broker as transient transport only. On refresh, rebuild the transcript from persisted session messages and use the live stream only for in-flight work.
**When to use:** CHAT-03 reconnect/recovery flows.
**Example:**
```python
# Source inspiration:
# - local repo: nanobot.session.manager.SessionManager.get_or_create()

session = session_manager.get_or_create(f"tui:{session_id}")
history = session.messages
```

### Pattern 4: Typed Event Envelope
**What:** Standardize event types such as `session.created`, `message.accepted`, `progress`, `tool_hint`, `assistant.final`, `error`, and `complete`.
**When to use:** SSE output and frontend reducer logic.
**Example:**
```python
class ChatEvent(BaseModel):
    id: str
    type: Literal[
        "session.created",
        "message.accepted",
        "progress",
        "tool_hint",
        "assistant.final",
        "error",
        "complete",
    ]
    session_id: str
    run_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
```

### Anti-Patterns to Avoid
- **Web routes constructing providers and loops inline:** route functions should not own runtime boot logic.
- **Using `cli:direct` or other CLI session keys for browser chat:** creates recovery collisions and makes regressions harder to detect.
- **Treating the live event queue as the source of truth:** reconnect must work even after process-local queues are empty.
- **Adding token-stream semantics to the provider interface in this phase without need:** broad provider refactors are outside the thin-adapter constraint.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Session persistence | Web-only transcript store | `SessionManager` | Existing JSONL persistence already backs recovery and history |
| Chat execution | Web-specific chat loop | `AgentLoop.process_direct()` | Existing path already persists turns, handles slash commands, and supports progress callbacks |
| SSE framing | Manual `text/event-stream` string formatting | `fastapi.sse.EventSourceResponse` and `ServerSentEvent` | Built-in ids, event names, keep-alive, and proxy-safe headers |
| Disconnect detection | Custom socket polling | `Request.is_disconnected()` | Official Starlette request API already exposes this |
| History slicing | Browser-only transcript pruning rules | `Session.get_history()` for model input and persisted `session.messages` for UI recovery | Keeps LLM context rules and UI history grounded in one store |

**Key insight:** The only Phase 18 state that should be new is a transient event broker for live updates. Everything durable should reuse the runtime that already exists.

## Common Pitfalls

### Pitfall 1: Picking a Transport the Browser Can’t Reconnect To Cleanly
**What goes wrong:** the server streams from the same `POST` request that submits the message, but the frontend later needs automatic reconnect and history recovery.
**Why it happens:** SSE is valid over `POST` at the HTTP level, but browser-native `EventSource` is URL-based and is much easier to use against a `GET` stream.
**How to avoid:** keep submission and streaming as separate endpoints; stream with SSE `GET`.
**Warning signs:** frontend code starts falling back to ad hoc polling or has no clean reconnect path.

### Pitfall 2: Overloading Phase 18 with Provider-Level Token Streaming
**What goes wrong:** the implementation reaches into provider internals to expose token deltas across all models.
**Why it happens:** `CHAT-02` can be read as “token stream everything”, but the current stable runtime seam exposes progress callbacks and final assistant output, not generalized text deltas.
**How to avoid:** Phase 18 should stream progress and final assistant completion through a stable adapter; treat cross-provider token-delta support as a separate narrow decision if truly required.
**Warning signs:** changes start spreading through `nanobot/providers/*` and CLI chat code.

### Pitfall 3: Recovering Only Metadata, Not Actual Transcript State
**What goes wrong:** `/sessions` lists recent sessions, but refresh cannot reconstruct the message timeline.
**Why it happens:** Phase 17 only added read-only session summaries; chat recovery needs message loading too.
**How to avoid:** extend the session contract with a safe `load_session` or `get_session_messages` seam and expose a dedicated transcript endpoint.
**Warning signs:** browser refresh requires keeping a client-side cache to avoid blank chat panes.

### Pitfall 4: Letting Route Handlers Own Runtime Lifecycle
**What goes wrong:** route functions instantiate providers, cron services, and loops directly.
**Why it happens:** the happy-path code is short, so it is tempting to skip the service layer.
**How to avoid:** keep the Phase 17 pattern: routes -> dependencies -> services -> existing runtime objects.
**Warning signs:** route tests need deep monkeypatching of unrelated runtime modules.

### Pitfall 5: Forgetting In-Flight Cancellation and Disconnect Cleanup
**What goes wrong:** the browser disconnects, but the SSE task or background run keeps hanging around.
**Why it happens:** streaming code ignores disconnect checks and never unsubscribes broker queues.
**How to avoid:** check `await request.is_disconnected()` inside the stream loop and tear down subscriptions deterministically.
**Warning signs:** memory growth in long-lived dev sessions or stale run subscriptions after tab refreshes.

## Code Examples

Verified patterns from official sources:

### Browser-Friendly SSE Stream
```python
# Source:
# https://fastapi.tiangolo.com/tutorial/server-sent-events/
# https://www.starlette.io/requests/
from collections.abc import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

router = APIRouter()

@router.get("/chat/sessions/{session_id}/events", response_class=EventSourceResponse)
async def stream_chat_events(session_id: str, request: Request) -> AsyncIterable[ServerSentEvent]:
    async for event in broker.subscribe(session_id):
        if await request.is_disconnected():
            break
        yield ServerSentEvent(data=event.payload, event=event.type, id=event.id)
```

### Resume Stream with Event IDs
```python
# Source:
# https://fastapi.tiangolo.com/tutorial/server-sent-events/
from typing import Annotated

from fastapi import Header

async def stream_chat_events(
    session_id: str,
    last_event_id: Annotated[str | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    async for event in broker.subscribe(session_id, after_id=last_event_id):
        yield ServerSentEvent(data=event.payload, event=event.type, id=event.id)
```

### JSON Lines Fallback
```python
# Source:
# https://fastapi.tiangolo.com/ja/tutorial/stream-json-lines/
from starlette.responses import StreamingResponse

async def iter_jsonl():
    for item in items:
        yield item.model_dump_json() + "\n"

return StreamingResponse(iter_jsonl(), media_type="application/jsonl")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Third-party SSE helpers or raw `StreamingResponse` for event streams | First-party `fastapi.sse.EventSourceResponse` and `ServerSentEvent` | FastAPI `0.135.0` | No extra SSE dependency needed; event ids, keep-alives, and proxy-safe defaults are built in |
| One-shot REST reply for chat | Streaming event transport plus durable session replay | Current FastAPI/browser chat patterns | Better UX for long runs and cleaner reconnect semantics |
| Browser-only conversation cache | Backend-backed session recovery | Stable existing nanobot session layer | Refresh/reconnect works without trusting the client as source of truth |

**Deprecated/outdated:**
- `Hand-built SSE strings`: outdated for this phase because FastAPI now ships first-party SSE primitives.
- `WebSocket-first for simple request/stream chat`: unnecessary complexity here unless Phase 20 introduces true duplex browser control.

## Open Questions

1. **How strict is `CHAT-02` about assistant token deltas versus streamed progress plus final assistant completion?**
   - What we know: current `AgentLoop` exposes `on_progress(...)` callbacks during execution and returns the final assistant content at the end; the provider interface is not a generalized streaming text-delta API.
   - What's unclear: whether the requirement demands token-by-token text streaming or only visible incremental updates during the run.
   - Recommendation: plan Phase 18 around streamed progress plus final assistant event, and only add a new provider/loop delta seam if the user explicitly wants true token streaming.

2. **Should empty sessions be persisted immediately or only after the first message?**
   - What we know: `SessionManager` persists on `save()`, not on id generation alone.
   - What's unclear: whether the browser needs a durable session object before any message is sent.
   - Recommendation: create the session id immediately, but allow persistence on first message unless the UI requires empty-draft recovery.

3. **How much event history should the in-memory broker retain for reconnect?**
   - What we know: durable recovery must come from `SessionManager`, while transient stream replay only needs to cover in-flight reconnects.
   - What's unclear: whether a small per-session ring buffer is sufficient or whether run-scoped replay is needed.
   - Recommendation: keep a bounded in-memory replay window keyed by session or run id and rely on transcript reload for older history.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` 9.x |
| Config file | [`pyproject.toml`](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml) |
| Quick run command | `uv run pytest tests/test_tui_p18_chat_workspace.py -x` |
| Full suite command | `uv run pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat_workspace.py tests/test_commands.py -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CHAT-01 | Create a browser chat session and send follow-up messages through web APIs without touching CLI flows | unit + API | `uv run pytest tests/test_tui_p18_chat_workspace.py::test_create_and_continue_chat_session -x` | ❌ Wave 0 |
| CHAT-02 | Stream progress and terminal assistant events over the web transport during an active run | unit + API | `uv run pytest tests/test_tui_p18_chat_workspace.py::test_chat_stream_emits_progress_and_completion_events -x` | ❌ Wave 0 |
| CHAT-03 | Reconnect/refresh and recover recent transcript state from backend session data | unit + API | `uv run pytest tests/test_tui_p18_chat_workspace.py::test_chat_history_recovers_from_session_manager -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_tui_p18_chat_workspace.py -x`
- **Per wave merge:** `uv run pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat_workspace.py tests/test_commands.py -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_tui_p18_chat_workspace.py` — route, service, and streaming regression coverage for CHAT-01/02/03
- [ ] `nanobot/tui/schemas/chat.py` coverage targets — request/response/event schema validation tests
- [ ] Contract override fixtures for chat service/event broker — keeps TUI tests import-safe and isolated from real providers

## Sources

### Primary (HIGH confidence)
- Local repo: [`nanobot/agent/loop.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/loop.py) - verified direct-chat execution path, progress callback seam, and session persistence behavior
- Local repo: [`nanobot/session/manager.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/session/manager.py) - verified durable session storage, listing, and history behavior
- Local repo: [`nanobot/tui/app.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/app.py) and [`nanobot/tui/dependencies.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/dependencies.py) - verified current web boundary and dependency/service pattern
- FastAPI docs: https://fastapi.tiangolo.com/tutorial/server-sent-events/ - checked first-party SSE support, event ids, `Last-Event-ID`, POST-capable SSE, and built-in keep-alive behavior
- FastAPI docs: https://fastapi.tiangolo.com/ja/tutorial/stream-json-lines/ - checked JSON Lines streaming fallback and `application/jsonl`
- Starlette docs: https://www.starlette.io/requests/ - checked `Request.is_disconnected()` for disconnect-safe streaming
- PyPI: https://pypi.org/project/fastapi/ - verified current FastAPI release
- PyPI: https://pypi.org/project/starlette/ - verified current Starlette release

### Secondary (MEDIUM confidence)
- Uvicorn release info surfaced via PyPI search results and release history snippet - used only to confirm current server version direction
- MDN EventSource/XHR guidance surfaced via search snippet - used as supporting evidence that browser-native SSE is server-to-client and URL-driven

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - verified with current FastAPI/Starlette/PyPI docs and existing repo dependencies
- Architecture: MEDIUM - core reuse points are clear from local code, but the exact stream topology still depends on how strictly CHAT-02 is interpreted
- Pitfalls: HIGH - driven by current repo behavior plus official streaming/disconnect documentation

**Research date:** 2026-03-21
**Valid until:** 2026-04-20
