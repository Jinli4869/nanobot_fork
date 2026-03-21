# Phase 19: Operations Console - Research

**Researched:** 2026-03-21
**Domain:** Browser-safe operations APIs for nanobot runtime inspection, GUI task launch, and filtered OpenGUI trace/log exposure under `nanobot/tui`
**Confidence:** HIGH

<user_constraints>
## User Constraints

No `19-CONTEXT.md` exists for this phase. This research therefore treats the following as authoritative constraints:
- `.planning/ROADMAP.md` Phase 19 goal, roadmap bullets, and success criteria
- `.planning/REQUIREMENTS.md` requirements `OPS-01`, `OPS-02`, and `OPS-03`
- `.planning/STATE.md` decisions already locked by Phases 12-18
- `.planning/phases/17-web-runtime-boundary/17-RESEARCH.md`
- `.planning/phases/18-chat-workspace/18-RESEARCH.md`
- `.planning/phases/18-chat-workspace/18-chat-workspace-01-SUMMARY.md`
- `.planning/phases/18-chat-workspace/18-chat-workspace-02-SUMMARY.md`
- `.planning/phases/18-chat-workspace/18-chat-workspace-03-SUMMARY.md`
- The explicit user constraint to keep work primarily under `nanobot/tui`
- The explicit user constraint to avoid broad refactors to `nanobot` or `opengui` core paths
- The explicit user constraint to focus on stable browser-safe inspection/launch contracts, parameter validation, and filtered trace/log exposure
- The explicit user request to recommend a 3-plan split aligned with roadmap bullets if justified

### Locked Decisions
- Keep Phase 19 centered under `nanobot/tui`; edits outside that tree should stay thin and host-facing.
- Do not broaden the web milestone into a rewrite of `opengui.cli`, `opengui.agent`, or core nanobot runtime modules.
- Build on the Phase 17/18 pattern: routes -> dependencies -> services -> typed contracts/adapters.
- Preserve Phase 18 chat boundaries: `SessionManager` remains the durable session source, and the in-process event broker remains transient transport state.
- Treat browser inspection as filtered and contract-backed, not as raw filesystem browsing.
- Keep web-triggered task launch narrow and explicit, with validated parameters only.

### Claude's Discretion
- Exact route shapes for runtime status, run listing, run detail, trace detail, and launch endpoints.
- Exact internal service split between runtime aggregation, launch orchestration, and artifact reading.
- Whether active run updates use polling-only APIs or optionally reuse the existing SSE/event broker pattern, provided the contract remains browser-safe and testable.
- Whether supported launch types are represented as one discriminated union request or a small fixed set of endpoints, provided arbitrary task execution is not exposed.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| OPS-01 | User can inspect runtime status for sessions, background GUI runs, and recent failures from the web UI | Add a runtime aggregation service that merges `SessionManager` metadata, app-local active run registry state, and filtered summaries from persisted OpenGUI traces |
| OPS-02 | User can launch supported nanobot or OpenGUI tasks from the web UI with explicit task parameters | Add typed launch request schemas and a launch service that exposes only a narrow, validated GUI-task surface instead of arbitrary CLI/subprocess execution |
| OPS-03 | User can inspect structured logs or event traces for web-triggered runs without dropping to the terminal | Add artifact-reader services that parse existing JSONL traces and return filtered summaries/events/log lines through stable DTOs |
</phase_requirements>

## Summary

Phase 19 should not invent a second operations runtime. The repo already has the pieces needed for a safe browser-facing console: `SessionManager` persists session metadata under workspace `sessions/*.jsonl`; `GuiSubagentTool.execute()` already returns a structured JSON payload with `success`, `summary`, `trace_path`, `steps_taken`, and `error`; and OpenGUI already writes stable JSONL artifacts in `opengui_runs/**/trace_*.jsonl` and per-attempt `trace.jsonl`. The right move is to wrap those existing surfaces behind narrow `nanobot/tui` contracts rather than exposing raw files or calling CLI commands from routes.

The core Phase 19 pattern should be an operations registry plus artifact reader. Active web-triggered runs need a small app-local registry keyed by `run_id` so the browser can see launch status immediately. Completed and historical state should come from persisted JSONL artifacts, not from process memory. That matches the Phase 18 durability split: transient state for in-flight UX, persisted state for recovery and inspection.

**Primary recommendation:** Implement Phase 19 as three plans matching the roadmap: `19-01` runtime/run status aggregation, `19-02` typed task launch for a very small set of supported GUI workflows, and `19-03` filtered trace/log APIs that read existing OpenGUI artifacts but never expose raw prompt/model payloads or arbitrary file paths.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `fastapi` | `>=0.110.0,<1.0.0` in repo; `0.135.1` verified in Phase 18 research on 2026-03-21 | HTTP routes, DI, response models | Existing web backend stack under `nanobot/tui` |
| `pydantic` | `>=2.12.0,<3.0.0` | Strict request/response validation for launch and inspection contracts | Already the repo-wide schema layer |
| `uvicorn[standard]` | `>=0.30.0,<1.0.0` in repo; `0.42.0` verified in Phase 18 research on 2026-03-21 | Local ASGI runtime | Existing Phase 17 runtime seam |
| `SessionManager` | repo-local | Durable session inspection | Existing source of truth for workspace sessions |
| `GuiSubagentTool` | repo-local | Narrow nanobot-hosted GUI launch path | Already enforces the host-facing JSON result contract |
| `TrajectoryRecorder` + OpenGUI JSONL traces | repo-local | Durable run history and filtered diagnostics | Existing structured artifact format; no new store needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `fastapi.testclient` | bundled | Route-level API tests | Default for Phase 19 endpoint coverage |
| `httpx` | `>=0.28.0,<1.0.0` | Async client tests if polling/SSE behavior needs async checks | Optional for transport-specific tests |
| `pytest` | `>=9.0.0,<10.0.0` | Regression coverage | Existing project test framework |
| `loguru` | `>=0.7.3,<1.0.0` | Existing runtime logging | Only for server-side logs, not as the browser inspection contract |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `GuiSubagentTool` launch adapter | `opengui.cli.run_cli()` subprocess or CLI-equivalent wrapper | Worse parameter safety, harder testing, more drift from browser contracts |
| JSONL artifact reader | New DB or cache for run history | More moving parts for no v1.3 benefit |
| Filtered DTOs for trace/log reads | Raw file browser or direct JSONL download | Faster to ship, but violates browser-safety and filtering constraints |
| Typed task kinds | Free-form `task_type + params: dict[str, Any]` passthrough | Simpler to code, but weak validation and easy scope creep |

**Installation:**
```bash
uv pip install -e ".[web,dev]"
```

**Version verification:** For Phase 19 planning, use repo-pinned ranges from [pyproject.toml](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml) and the FastAPI/Uvicorn versions already verified in [18-RESEARCH.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/phases/18-chat-workspace/18-RESEARCH.md). No additional package changes are required for the recommended approach.

## Architecture Patterns

### Recommended Project Structure
```text
nanobot/tui/
├── contracts.py              # extend with ops runtime/launch/trace contracts
├── dependencies.py           # add operation registry + launch/artifact service providers
├── routes/
│   ├── runtime.py            # expand into operations status/read APIs
│   ├── tasks.py              # add typed POST launch routes
│   └── traces.py             # new filtered trace/log inspection routes
├── schemas/
│   ├── runtime.py            # active run, failure, and aggregate status models
│   ├── tasks.py              # discriminated launch request/response models
│   └── traces.py             # filtered event/log DTOs
└── services/
    ├── runtime.py            # aggregate sessions + active runs + recent failures
    ├── tasks.py              # launch orchestration and app-local run registry updates
    ├── traces.py             # read/parse/filter persisted JSONL artifacts
    └── operations_registry.py # process-local active run state
```

### Pattern 1: Split Active State from Durable State
**What:** Keep a small app-local registry for in-flight browser-launched runs, but use persisted artifacts for completed history and failure inspection.
**When to use:** All OPS-01 runtime status and OPS-03 trace/log detail flows.
**Example:**
```python
# Source:
# - nanobot/session/manager.py
# - opengui/trajectory/recorder.py
# - opengui/agent.py

class RunRegistryEntry(BaseModel):
    run_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    task_kind: Literal[
        "nanobot_open_url",
        "nanobot_open_settings",
        "opengui_launch_app",
        "opengui_open_settings",
    ]
    started_at: str
    trace_path: str | None = None  # internal only; browser APIs stay run_id-addressed

# Merge:
# - SessionManager.list_sessions() for workspace sessions
# - in-memory registry for active web runs
# - parsed trace_*.jsonl files for recent failures/completions
```

### Pattern 2: Launch Only Typed Task Kinds
**What:** Model launch requests as a discriminated union with a very small, fixed set of supported task kinds.
**When to use:** OPS-02 launch APIs.
**Example:**
```python
# Source inspiration:
# - nanobot/agent/tools/gui.py
# - opengui/cli.py

class NanobotOpenUrlLaunchRequest(BaseModel):
    kind: Literal["nanobot_open_url"]
    url: HttpUrl
    require_background_isolation: bool = False
    acknowledge_background_fallback: bool = False
    target_app_class: Literal["classic-win32", "uwp", "directx", "gpu-heavy", "electron-gpu"] | None = None

class NanobotOpenSettingsLaunchRequest(BaseModel):
    kind: Literal["nanobot_open_settings"]
    panel: Literal["network", "display", "privacy", "bluetooth"]
    require_background_isolation: bool = False
    acknowledge_background_fallback: bool = False

class OpenGuiLaunchAppRequest(BaseModel):
    kind: Literal["opengui_launch_app"]
    app_id: Literal["calculator", "notepad", "settings", "terminal"]
    backend: Literal["dry-run", "local"] | None = None

class OpenGuiOpenSettingsRequest(BaseModel):
    kind: Literal["opengui_open_settings"]
    panel: Literal["network", "display", "privacy", "bluetooth"]
    backend: Literal["dry-run", "local"] | None = None
```

The browser contract must stay explicit even if the server-side adapter internally translates one of these operations into existing nanobot/OpenGUI task text. Public APIs should reject any free-form `task`, `prompt`, `command`, or `argv` field.

### Pattern 3: Return Stable Inspection DTOs, Not Raw Artifacts
**What:** Parse existing JSONL traces into browser-safe summaries and filtered event lists.
**When to use:** OPS-01 recent-failure summaries and OPS-03 run detail endpoints.
**Example:**
```python
# Source:
# - opengui/trajectory/recorder.py
# - opengui/agent.py

SAFE_TRACE_EVENT_TYPES = {
    "metadata",
    "attempt_start",
    "attempt_result",
    "attempt_exception",
    "retry",
    "step",
    "result",
}

def to_browser_event(raw: dict[str, Any]) -> OperationTraceEvent:
    return OperationTraceEvent(
        event_type=raw.get("type") or raw.get("event", "unknown"),
        timestamp=raw.get("timestamp"),
        step_index=raw.get("step_index") or raw.get("at_step"),
        status=raw.get("status"),
        summary=_truncate(raw.get("action_summary") or raw.get("error_message"), 240),
        success=raw.get("success"),
        done=raw.get("done"),
    )
```

Browser-safe inspection should be allowlist-based and run-id addressed:
- Allowed event types: `metadata`, `attempt_start`, `attempt_result`, `attempt_exception`, `retry`, `step`, `result`
- Allowed event fields: `event_id`, `event_type`, `timestamp`, `step_index`, `status`, `summary`, `success`, `done`, `retry_count`
- Allowed log fields: `timestamp`, `level`, `code`, `message`
- Explicit exclusions: `prompt`, `model_output`, raw tool arguments, screenshot paths, artifact paths, raw trace blobs
- Truncation: `summary` and `message` should be capped to a short browser-safe length such as 240 characters

### Pattern 4: Keep Route Handlers Thin
**What:** Keep all launch logic, artifact scanning, and filtering in services.
**When to use:** Every runtime/task/trace route.
**Example:**
```python
@router.post("/operations/runs", response_model=LaunchRunResponse)
async def launch_run(
    payload: LaunchRunRequest,
    service: TaskLaunchService = Depends(get_task_launch_service),
) -> LaunchRunResponse:
    return await service.launch(payload)
```

### Anti-Patterns to Avoid
- **Calling `opengui.cli.run_cli()` or shelling out from routes:** CLI parsing is not the browser contract.
- **Surfacing raw `trace.jsonl` or `trace_*.jsonl` content verbatim:** step payloads may include screenshot paths, model output, or future noisy fields.
- **One generic “run anything” endpoint:** this will immediately violate the explicit-parameter constraint.
- **Using process memory as the only run history store:** refresh/restart would erase diagnostics.
- **Expanding Phase 19 into live screenshot streaming or remote desktop:** explicitly out of scope until later milestones.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Run durability | New operation database | Existing JSONL artifacts in `opengui_runs` plus app-local registry for active state | Current artifact model already records metadata, step, retry, and result events |
| Browser launch safety | Free-form dict passthrough | Pydantic discriminated launch models | Prevents arbitrary runtime mutation and makes UI contracts explicit |
| Runtime status | `ps`, grepping logs, or CLI stdout parsing | Aggregated status service over `SessionManager`, active registry, and parsed traces | More stable and testable |
| GUI execution | New web-only OpenGUI orchestrator | Thin adapter over `GuiSubagentTool.execute()` first; optional direct OpenGUI adapter only if still contract-backed | Reuses the host-visible JSON result contract |
| Trace filtering | Regex-only text scraping | Structured JSONL parsing with allowlisted fields/event types | Easier to keep browser-safe as artifacts evolve |

**Key insight:** Phase 19 should add an operations API surface, not a new runtime. The repo already emits structured data; the missing work is aggregation, validation, and filtering.

## Common Pitfalls

### Pitfall 1: Mixing Session Inspection and Run Inspection into One Unstable Object
**What goes wrong:** one endpoint tries to expose sessions, chat state, GUI launches, failures, and raw traces in one loosely typed payload.
**Why it happens:** Phase 19 touches multiple “operations” concepts at once.
**How to avoid:** keep three layers distinct: session summaries, run summaries, and run trace/log detail.
**Warning signs:** response models start using `dict[str, Any]` for most fields.

### Pitfall 2: Exposing Sensitive or Noisy Trace Fields
**What goes wrong:** browser APIs leak screenshot paths, prompt snapshots, model responses, or future secret-bearing fields.
**Why it happens:** the trace files are structured JSON already, so it is tempting to proxy them directly.
**How to avoid:** use an allowlist; expose event summaries, status, timestamps, step indexes, and scrubbed tool/action summaries only.
**Warning signs:** API payloads contain `prompt`, `model_response`, raw `arguments`, or filesystem paths.

### Pitfall 3: Over-Broad Launch Scope
**What goes wrong:** the first launch API accepts arbitrary nanobot prompts, subprocess commands, or CLI flags.
**Why it happens:** “operations console” sounds generic.
**How to avoid:** keep Phase 19 launch scope to web-triggerable GUI tasks only, with explicit typed parameters.
**Warning signs:** launch requests start carrying opaque `extra_args`, `command`, or unrestricted backend overrides.

### Pitfall 4: Treating Existing Artifact Layout as a Public API
**What goes wrong:** frontend code starts depending on current directory names like `open_system_settings_1774084119308_0`.
**Why it happens:** artifact paths are already present and readable.
**How to avoid:** treat filesystem layout as internal; return stable `run_id`, `status`, `task`, `started_at`, and filtered event/log DTOs.
**Warning signs:** route responses expose raw directory names as primary identifiers.

### Pitfall 5: Launching Work Synchronously in the Request Path
**What goes wrong:** `POST /operations/runs` blocks until the GUI task finishes.
**Why it happens:** `GuiSubagentTool.execute()` already returns a structured result, so inlining it is easy.
**How to avoid:** launch work in a background task or app-managed async task, immediately persist registry state, and let status/trace endpoints reflect progress.
**Warning signs:** request timeouts on long tasks or no distinct queued/running state.

## Code Examples

Verified patterns from existing repo surfaces:

### Existing Durable Session Surface
```python
# Source: /Users/jinli/Documents/Personal/nanobot_fork/nanobot/session/manager.py
manager = SessionManager(workspace)
items = manager.list_sessions()
# -> key, created_at, updated_at, path
```

### Existing Web-Safe GUI Result Contract
```python
# Source: /Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py
payload = json.loads(await gui_tool.execute(task="open system settings"))

# Stable fields already returned today:
# - success
# - summary
# - trace_path
# - steps_taken
# - error
```

### Existing Trace Shapes That Phase 19 Can Parse
```json
// Source:
// - /Users/jinli/Documents/Personal/nanobot_fork/opengui/trajectory/recorder.py
// - /Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py
{"type":"metadata","task":"open settings","platform":"android","initial_phase":"agent"}
{"type":"attempt_start","attempt":0,"max_retries":3,"task":"open system settings"}
{"type":"attempt_exception","attempt":0,"error_type":"BadRequestError","error_message":"..."}
{"type":"step","step_index":1,"action":{"action_type":"tap"},"model_output":"Tap...","screenshot_path":"..."}
{"type":"result","success":false,"total_steps":0,"duration_s":1.81,"error":"..."}
```

### Recommended Browser Filter
```python
# Source basis:
# - opengui/trajectory/recorder.py
# - opengui/agent.py

def summarize_step(raw: dict[str, Any]) -> str:
    action = raw.get("action")
    if isinstance(action, dict):
        return str(action.get("action_type", "step"))
    if isinstance(action, str):
        return action
    return raw.get("tool_result") or raw.get("model_output") or "step"
```

## Concrete Artifact Recommendations

### Safe to Read from Existing Run Artifacts
- Workspace sessions: `workspace/sessions/*.jsonl`
  - Safe fields: `key`, `created_at`, `updated_at`, metadata fields already written by the browser path such as `origin` and `channel`
  - Use for: session status counts, recent browser sessions, recent activity timestamps
- OpenGUI aggregate traces: `opengui_runs/**/trace_*.jsonl`
  - Safe fields to parse and expose: `type`, `task`, `platform`, `initial_phase`, `timestamp`, `step_index`, `success`, `total_steps`, `duration_s`, `error`, `attempt`, `max_retries`, `error_type`
  - Use for: run summary cards, recent failures, completion status, step counts, retry counts
- OpenGUI per-attempt traces: `opengui_runs/**/trace.jsonl`
  - Safe fields to parse and expose after filtering: `event`, `timestamp`, `step_index`, `action`, `tool_result`, `done`, `error_type`, `error_message`
  - Use for: compact activity log and per-run timeline

### Read but Filter Before Exposure
- `model_output`
  - Useful for operator summaries, but must be length-limited and treated as untrusted text
- `screenshot_path`
  - Useful internally for correlation, but should not be surfaced as a browser contract in v1.3
- `trace_path`
  - Safe as backend internal linkage; do not make it the UI’s public identifier

### Do Not Expose Directly in Phase 19
- Raw `prompt` or `model_response` snapshots from trajectory events
- Raw tool arguments beyond a concise scrubbed summary
- Arbitrary filesystem paths or directory traversal via path parameters
- Screenshot/image binaries, live viewer frames, or file download browsing

## Web-Triggerable Task Scope for Phase 19

### Recommended Supported Launches
- `nanobot_gui`
  - Backed by `GuiSubagentTool.execute()`
  - Parameters:
    - `task` required
    - `require_background_isolation` optional
    - `acknowledge_background_fallback` optional
    - `target_app_class` optional Windows-only hint
  - Why narrow enough: already host-facing, already returns structured JSON, already tested for remediation and filtering semantics
- `opengui_gui`
  - Only if implemented as a thin service adapter under `nanobot/tui`
  - Parameters:
    - `task` required
    - `backend` optional but restricted to `local` or `dry-run`
  - Why narrow enough: still a single GUI-task abstraction, not arbitrary CLI control

### Explicitly Out of Scope for Phase 19
- Arbitrary nanobot prompts that can invoke any tool
- CLI command execution or shell-backed operations
- Cron/job management
- Live browser viewer or screenshot streaming
- Artifact file downloads or raw screenshot browsing

## Recommended 3-Plan Split

### Plan 19-01: Runtime Status and Inspection Endpoints
Focus:
- expand runtime contracts and schemas beyond the current Phase 17 placeholder
- add an app-local operations registry for active web-launched runs
- aggregate session summaries, active runs, and recent failure summaries from persisted traces

Primary outputs:
- richer `nanobot/tui/schemas/runtime.py`
- runtime aggregation services under `nanobot/tui/services/`
- route tests covering OPS-01

### Plan 19-02: Typed Task Launch Flows
Focus:
- add typed launch request/response schemas
- implement narrow launch adapters for supported GUI task kinds
- register launched runs in the app-local registry and return stable `run_id`

Primary outputs:
- mutable `POST` launch routes under `nanobot/tui/routes/tasks.py`
- launch orchestration service under `nanobot/tui/services/tasks.py`
- tests covering validation, launch state transitions, and unsupported task kinds

### Plan 19-03: Filtered Trace and Log Exposure
Focus:
- parse existing `opengui_runs` JSONL artifacts
- expose filtered run detail, event timeline, and recent failure diagnostics
- keep browser contracts independent from raw filesystem layout

Primary outputs:
- `nanobot/tui/routes/traces.py` and matching schemas/services
- artifact reader/filter logic
- tests covering filtering, recent-failure discovery, and trace contract stability

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Contract-only `/tasks` route with `mutable=false` | Typed, explicit launch routes under `nanobot/tui` | Phase 19 | Browser can launch a small supported task set without opening the terminal |
| Manual terminal inspection of `opengui_runs` | Filtered browser-safe run summaries and trace events | Phase 19 | Operators can diagnose failed runs from the web UI |
| Raw artifact layout as implicit knowledge | Stable DTOs over existing JSONL artifacts | Phase 19 | Frontend stays decoupled from directory naming and trace-file quirks |

**Deprecated/outdated:**
- Using the current Phase 17 `/runtime` placeholder as a real runtime signal: too shallow for OPS-01.
- Treating `/tasks` as a capability stub only: Phase 19 should make it mutable, but only through typed launch models.

## Open Questions

1. **Should Phase 19 support both `nanobot_gui` and `opengui_gui`, or only the nanobot-hosted path first?**
   - What we know: `GuiSubagentTool.execute()` already exposes the cleanest host-facing JSON result contract.
   - What's unclear: whether a direct OpenGUI launch path is needed before Phase 20 frontend integration.
   - Recommendation: ship `nanobot_gui` first, and add `opengui_gui` only if it can reuse the same run registry and filtered artifact contracts without touching core OpenGUI flow control.

2. **Should active run updates be polling-only or reuse SSE?**
   - What we know: Phase 18 already established a working GET SSE pattern, but the current requirement only needs inspection, not a live viewer.
   - What's unclear: whether the frontend needs incremental event push before Phase 20.
   - Recommendation: make the primary contract polling-friendly (`GET /operations/runs`, `GET /operations/runs/{run_id}`); treat SSE as optional sugar if it reuses the same typed event DTOs.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest>=9.0.0,<10.0.0` |
| Config file | `pyproject.toml` |
| Quick run command | `.venv/bin/python -m pytest tests/test_tui_p19_runtime.py tests/test_tui_p19_launch.py tests/test_tui_p19_traces.py -q` |
| Full suite command | `.venv/bin/python -m pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_launch.py tests/test_tui_p19_traces.py tests/test_commands.py tests/test_opengui_p16_host_integration.py -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-01 | Runtime API reports sessions, active runs, and recent failures with stable schemas | unit/api | `.venv/bin/python -m pytest tests/test_tui_p19_runtime.py -q` | ❌ Wave 0 |
| OPS-02 | Launch API accepts only supported task kinds and validated parameters | unit/api | `.venv/bin/python -m pytest tests/test_tui_p19_launch.py -q` | ❌ Wave 0 |
| OPS-03 | Trace/log APIs expose filtered structured events for web-triggered runs | unit/api | `.venv/bin/python -m pytest tests/test_tui_p19_traces.py -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_tui_p19_runtime.py tests/test_tui_p19_launch.py tests/test_tui_p19_traces.py -q`
- **Per wave merge:** `.venv/bin/python -m pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_launch.py tests/test_tui_p19_traces.py tests/test_commands.py tests/test_opengui_p16_host_integration.py -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_tui_p19_runtime.py` — covers OPS-01 runtime aggregation and recent-failure listing
- [ ] `tests/test_tui_p19_launch.py` — covers OPS-02 request validation and launch-state transitions
- [ ] `tests/test_tui_p19_traces.py` — covers OPS-03 artifact parsing, filtering, and stable trace DTOs
- [ ] Shared fixture for synthetic `opengui_runs` artifact trees under `tmp_path`

## Sources

### Primary (HIGH confidence)
- [ROADMAP.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/ROADMAP.md) - Phase 19 scope, roadmap bullets, success criteria
- [REQUIREMENTS.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/REQUIREMENTS.md) - `OPS-01`, `OPS-02`, `OPS-03`
- [STATE.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/STATE.md) - locked decisions and current milestone state
- [17-RESEARCH.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/phases/17-web-runtime-boundary/17-RESEARCH.md) - web boundary constraints
- [18-RESEARCH.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/phases/18-chat-workspace/18-RESEARCH.md) - Phase 18 transport and persistence decisions
- [18-chat-workspace-01-SUMMARY.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/phases/18-chat-workspace/18-chat-workspace-01-SUMMARY.md) - chat service/runtime factory pattern
- [18-chat-workspace-02-SUMMARY.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/phases/18-chat-workspace/18-chat-workspace-02-SUMMARY.md) - transient broker and event ordering pattern
- [18-chat-workspace-03-SUMMARY.md](/Users/jinli/Documents/Personal/nanobot_fork/.planning/phases/18-chat-workspace/18-chat-workspace-03-SUMMARY.md) - recovery split and CLI isolation pattern
- [contracts.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/contracts.py) - current TUI contract surface
- [dependencies.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/dependencies.py) - current DI/runtime factory seams
- [runtime.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/routes/runtime.py) - current runtime route placeholder
- [tasks.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/routes/tasks.py) - current task route placeholder
- [runtime.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/services/runtime.py) - current runtime service
- [tasks.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/services/tasks.py) - current task service
- [manager.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/session/manager.py) - session persistence format and listing behavior
- [gui.py](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py) - host-facing GUI execution contract and filtering behavior
- [agent.py](/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py) - attempt logging and run artifact format
- [recorder.py](/Users/jinli/Documents/Personal/nanobot_fork/opengui/trajectory/recorder.py) - trajectory event schema
- [cli.py](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py) - CLI-only parameter surface and why not to import it into routes
- [test_opengui_p3_nanobot.py](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p3_nanobot.py) - GUI tool contract coverage
- [test_opengui_p16_host_integration.py](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p16_host_integration.py) - remediation/filtering parity expectations

### Secondary (MEDIUM confidence)
- [pyproject.toml](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml) - dependency ranges and pytest config
- Existing `opengui_runs/*` artifacts in the workspace - confirmed current JSONL layout for aggregate and per-attempt traces

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM-HIGH - repo pins and prior Phase 18 verification are strong, but this turn did not re-query package registries
- Architecture: HIGH - grounded directly in current `nanobot/tui`, `SessionManager`, `GuiSubagentTool`, and OpenGUI artifact formats
- Pitfalls: HIGH - derived from current placeholder routes, existing filtering logic, and concrete artifact shapes already present in the workspace

**Research date:** 2026-03-21
**Valid until:** 2026-04-20
