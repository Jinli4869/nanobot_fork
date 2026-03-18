# Phase 3: Nanobot Subagent - Research

**Researched:** 2026-03-18
**Domain:** Python async adapter pattern, Pydantic config extension, asyncio background tasks, opengui-nanobot protocol bridging
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Tool Invocation Design**
- GuiSubagentTool runs in background (async), not blocking the main agent loop
- Tree router fires GUI ATOMs in background but awaits before dependent ATOMs — effectively sync for sequential dependencies, truly parallel for independent branches
- Tool returns a structured dict: `{success, summary, trace_path, steps_taken, error}` (maps from AgentResult fields)
- Tool takes only task string + optional backend override — all agent params (max_steps, skill_threshold, etc.) come from nanobot config defaults, no per-call overrides
- Router gets the result dict directly when awaited — no bus notification for GUI results

**LLM Adapter Bridge**
- NanobotLLMAdapter lives in `nanobot/agent/gui_adapter.py` — imports nanobot provider + opengui interfaces, keeps opengui zero-dependency on nanobot
- Adapter strips to opengui protocol: only passes content + tool_calls + raw. Nanobot's reasoning_content, thinking_blocks, finish_reason, usage are dropped
- Adapter delegates retry logic to nanobot's `chat_with_retry` internally — opengui's `chat()` gets a single reliable call, no duplicate retry logic
- NanobotEmbeddingAdapter as a separate small class alongside NanobotLLMAdapter — both created by the tool and passed to GuiAgent

**Backend Selection**
- New `gui` config section in nanobot config schema: `gui: {backend: "adb", adb: {serial: "..."}, artifacts_dir: "gui_runs/"}`
- Backend type is `"adb"`, `"local"`, or `"dry-run"` — read from `gui.backend` in config
- dry-run requires explicit config — no auto-detection for test environments; tests create their own backend instances directly
- If gui config section is absent: tool registration behavior is Claude's discretion

**Trajectory & Workspace**
- Trajectory files saved to `workspace/gui_runs/` — each run gets a timestamped subdirectory with trace.jsonl + screenshots (e.g., `workspace/gui_runs/2026-03-18_143022/`)
- Aligns with opengui's existing `artifacts_root` pattern

**Skill Extraction**
- Auto-extraction after every GUI run — GuiSubagentTool automatically calls SkillExtractor on the trajectory. No manual trigger needed from the main agent
- Extract from both successful and failed trajectories — SkillExtractor already supports failed trajectories for negative examples
- Immediate dedup on extraction — run SkillLibrary's existing dedup logic right after adding extracted skills
- Per-backend skill libraries — separate directories per platform (e.g., `workspace/gui_skills/android/`, `workspace/gui_skills/desktop/`). Skills aren't portable across platforms

**Fixed-Parameter Skill Step Extraction**
- LLM classifies each step as fixed or dynamic during extraction (existing design from Phase 2)
- Fixed text for known UI elements stored as `fixed_values: {text: "Settings"}` — only parameterize text that varies
- Canonical storage format is always [0,999] relative coords with model-specific normalization:
  - Qwen/Gemini (native [0,999] output): store as-is, rescale to resolution at execution time
  - Other models (absolute resolution output): rescale to [0,999] during extraction, execute directly without rescale

### Claude's Discretion
- Whether to skip tool registration or register-but-error when gui config is missing
- Memory store scoping (shared vs per-backend)
- Exact config schema field names and Pydantic model structure
- Adapter internal implementation details (error mapping, model name passthrough)
- Timestamp format for run directories
- Whether to expose a manual trajectory_summary skill alongside auto-extraction

### Deferred Ideas (OUT OF SCOPE)
- Bus notifications for GUI task progress (user seeing intermediate steps in chat)
- Manual trajectory_summary skill for re-processing old trajectories
- Per-call config overrides on GuiSubagentTool (max_steps, skill_threshold)
- Cross-platform skill transfer (learning from Android to inform desktop)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| NANO-01 | GuiSubagentTool registered in nanobot tool registry | Tool ABC + ToolRegistry patterns fully understood; SpawnTool is reference for async background execution; `_register_default_tools()` in AgentLoop is where registration is hooked |
| NANO-02 | NanobotLLMAdapter wrapping nanobot's provider to opengui LLMProvider protocol | Both protocols fully read; nanobot uses `chat_with_retry(messages, tools, model, ...)` returning `LLMResponse(content, tool_calls: list[ToolCallRequest], reasoning_content, thinking_blocks, finish_reason, usage)`; opengui protocol needs `chat(messages, tools, tool_choice) -> LLMResponse(content, tool_calls: list[ToolCall], raw)` |
| NANO-03 | Backend selection from nanobot config (adb/local/dry-run) | Config schema uses Pydantic `Base` model with camelCase alias; `Config` root model is the target; AdbBackend and DryRunBackend exist in opengui/backends/ |
| NANO-04 | Trajectory saved to nanobot workspace for later skill extraction | TrajectoryRecorder takes `output_dir: Path`; GuiAgent takes `artifacts_root: Path`; workspace/gui_runs/ is the target path |
| NANO-05 | Main agent trajectory_summary skill for post-run skill extraction | SkillExtractor.extract() takes a trajectory path + LLM; SkillLibrary.add_or_merge() handles dedup; auto-extracted after every run inside GuiSubagentTool.execute() |
</phase_requirements>

---

## Summary

Phase 3 wires opengui's GuiAgent into nanobot as a first-class tool. The core challenge is a clean protocol bridge: nanobot's `LLMProvider` ABC and opengui's `LLMProvider` Protocol have different method signatures and response types, requiring a one-way adapter. The existing codebase provides all the primitives: the Tool ABC + ToolRegistry pattern is well-established, SpawnTool demonstrates background asyncio.Task execution, and GuiAgent's constructor accepts all optional components (memory, skills, embedder).

The three major construction tasks are: (1) `NanobotLLMAdapter` + `NanobotEmbeddingAdapter` in `gui_adapter.py`, (2) `GuiSubagentTool` in `tools/gui.py` that builds and drives a GuiAgent, and (3) config schema extension with a `GuiConfig` Pydantic model. Skill extraction is handled automatically by calling `SkillExtractor` + `SkillLibrary.add_or_merge()` after every `GuiAgent.run()`, using the existing implementations from Phase 1/2. The TreeRouter's `_run_gui` dispatch already calls `context.gui_agent.run()` — once `GuiSubagentTool` is registered, the router can be wired to use it via `RouterContext.gui_agent`.

**Primary recommendation:** Build `gui_adapter.py` first (pure adapter, testable in isolation), then `tools/gui.py` (depends on adapters + config), then extend `schema.py` (no logic, just Pydantic models), then hook registration into `AgentLoop._register_default_tools()`. Each piece is independently testable.

---

## Standard Stack

### Core

All dependencies are already present in the project — Phase 3 introduces no new packages.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| opengui | local | GuiAgent, SkillExtractor, SkillLibrary, TrajectoryRecorder | Phase 1/2 built this |
| nanobot.providers.base | local | LLMProvider ABC, `chat_with_retry` with retry logic | Existing nanobot LLM infrastructure |
| pydantic | 2.x (existing) | GuiConfig Pydantic model extending Config | Used throughout nanobot config schema |
| asyncio | stdlib | Background task management for GuiSubagentTool | Already used in SpawnTool, AgentLoop |

### No New Dependencies Required

The adapter pattern is pure Python. No pip installs needed for Phase 3.

---

## Architecture Patterns

### Recommended Project Structure

New files:

```
nanobot/
├── agent/
│   ├── gui_adapter.py         # NEW: NanobotLLMAdapter + NanobotEmbeddingAdapter
│   └── tools/
│       └── gui.py             # NEW: GuiSubagentTool
└── config/
    └── schema.py              # MODIFIED: add AdbConfig + GuiConfig + gui field on Config
```

Runtime directories (created on first run, not committed):

```
workspace/
├── gui_runs/                  # Trajectory artifacts per run
│   └── 2026-03-18_143022/     # Timestamped subdirectory
│       ├── trace.jsonl
│       └── screenshots/
└── gui_skills/                # Per-platform skill libraries
    ├── android/
    └── macos/
```

### Pattern 1: LLM Adapter Bridge

**What:** One-directional wrapper — nanobot's `LLMProvider` ABC → opengui's `LLMProvider` Protocol.

**When to use:** Whenever nanobot's LLM infrastructure must be used inside opengui code, without introducing a reverse dependency.

The critical mapping:
- Nanobot `chat_with_retry(messages, tools, model, max_tokens, temperature, ...)` → opengui `chat(messages, tools, tool_choice)`
- Nanobot `LLMResponse.tool_calls: list[ToolCallRequest]` → opengui `LLMResponse.tool_calls: list[ToolCall]`
- `ToolCallRequest(id, name, arguments)` → `ToolCall(id, name, arguments)` — same fields, different frozen dataclass types
- Nanobot extras (reasoning_content, thinking_blocks, finish_reason, usage) are dropped
- The `tool_choice` parameter from opengui must be passed through; nanobot's `chat_with_retry` accepts it as a kwarg

**Example structure (reference, not final code):**
```python
# nanobot/agent/gui_adapter.py
from nanobot.providers.base import LLMProvider as NanobotLLMProvider
from opengui.interfaces import LLMResponse as OpenguiLLMResponse, ToolCall

class NanobotLLMAdapter:
    def __init__(self, provider: NanobotLLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> OpenguiLLMResponse:
        # Delegate to chat_with_retry for built-in retry on transient errors
        nano_resp = await self._provider.chat_with_retry(
            messages=messages,
            tools=tools,
            model=self._model,
            tool_choice=tool_choice,
        )
        # Map ToolCallRequest -> ToolCall (strip nanobot-specific fields)
        opengui_tool_calls = [
            ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
            for tc in (nano_resp.tool_calls or [])
        ] or None
        return OpenguiLLMResponse(
            content=nano_resp.content or "",
            tool_calls=opengui_tool_calls,
            raw=nano_resp,
        )
```

**Key pitfall:** `nanobot.LLMResponse.tool_calls` is `list[ToolCallRequest]` (empty list by default). `opengui.LLMResponse.tool_calls` is `list[ToolCall] | None`. The adapter must convert `[]` → `None`.

### Pattern 2: Embedding Adapter

**What:** Wraps a nanobot-configured embedding endpoint (e.g., DashScope qwen3-vl-embedding) as opengui's `EmbeddingProvider` protocol.

**When to use:** GuiAgent's `MemoryRetriever` and `SkillLibrary` both optionally accept an `EmbeddingProvider`. If no embedding endpoint is configured in nanobot, pass `None` (BM25-only retrieval still works).

**Example structure:**
```python
class NanobotEmbeddingAdapter:
    def __init__(self, embed_fn) -> None:
        # embed_fn: async callable (texts: list[str]) -> np.ndarray
        self._embed_fn = embed_fn

    async def embed(self, texts: list[str]) -> np.ndarray:
        return await self._embed_fn(texts)
```

The `embed_fn` must be sourced from the nanobot provider's embedding API. If the nanobot config has no embedding API key configured, `NanobotEmbeddingAdapter` should not be instantiated — GuiAgent works without it.

### Pattern 3: GuiSubagentTool Construction

**What:** Tool that constructs GuiAgent on first call (lazy init) or at registration time, using nanobot config to select backend and wire adapters.

**When to use:** Any time the main agent wants to delegate a GUI task.

**GuiAgent constructor signature (from opengui/agent.py):**
```python
GuiAgent(
    llm: LLMProvider,           # NanobotLLMAdapter
    backend: DeviceBackend,     # AdbBackend or DryRunBackend
    trajectory_recorder: TrajectoryRecorder,
    model: str = "",            # nanobot config model name
    artifacts_root: Path,       # workspace/gui_runs/
    max_steps: int = 15,
    memory_retriever: Any = None,
    skill_library: Any = None,
    skill_executor: Any = None,
    memory_top_k: int = 5,
    skill_threshold: float = 0.6,
)
```

**Tool parameters (JSON Schema):**
```python
{
    "type": "object",
    "properties": {
        "task": {"type": "string", "description": "The GUI task to perform"},
        "backend": {
            "type": "string",
            "enum": ["adb", "local", "dry-run"],
            "description": "Optional backend override (defaults to config)"
        }
    },
    "required": ["task"]
}
```

**execute() return:** JSON string serialization of `{success, summary, trace_path, steps_taken, error}` mapped from `AgentResult`.

### Pattern 4: Config Schema Extension

**What:** Add `GuiConfig` Pydantic model to `nanobot/config/schema.py` and mount it on `Config`.

**Existing pattern (from schema.py):** All config submodels extend `Base` which sets `alias_generator=to_camel, populate_by_name=True`. Field defaults use `Field(default_factory=...)`.

**Example structure:**
```python
class AdbConfig(Base):
    serial: str | None = None

class GuiConfig(Base):
    backend: Literal["adb", "local", "dry-run"] = "adb"
    adb: AdbConfig = Field(default_factory=AdbConfig)
    artifacts_dir: str = "gui_runs"
    max_steps: int = 15
    skill_threshold: float = 0.6

class Config(BaseSettings):
    # ... existing fields ...
    gui: GuiConfig | None = None   # None = gui capability not configured
```

Making `gui: GuiConfig | None = None` (optional) is the natural fit: absence means GUI not configured, tool registration can be skipped or deferred.

### Pattern 5: AgentLoop Registration Hook

**What:** Conditional registration of GuiSubagentTool in `_register_default_tools()`.

**How:** Check if `gui` config is present, construct the tool, register it. Since `AgentLoop.__init__` doesn't currently receive the full `Config` object (only individual config fields), it needs access to `GuiConfig`. Recommend passing `gui_config: GuiConfig | None = None` as a new parameter to `AgentLoop.__init__`.

**Example:**
```python
def _register_default_tools(self) -> None:
    # ... existing registrations ...
    if self._gui_config is not None:
        from nanobot.agent.tools.gui import GuiSubagentTool
        self.tools.register(GuiSubagentTool(
            gui_config=self._gui_config,
            provider=self.provider,
            model=self.model,
            workspace=self.workspace,
        ))
```

### Pattern 6: Post-Run Skill Extraction

**What:** After `GuiAgent.run()` returns, extract skills from the trajectory JSONL.

**How:** `SkillExtractor(llm=NanobotLLMAdapter)` — the extractor takes an opengui `LLMProvider`, so the same adapter used for the agent works. Then `SkillLibrary.add_or_merge(skill)` with immediate dedup. Per-platform: `workspace/gui_skills/{platform}/` from `backend.platform`.

**`SkillExtractor.extract()` signature** (from opengui/skills/extractor.py):
```python
async def extract(
    self,
    trajectory_path: Path,
    success: bool,
) -> Skill | None
```

Returns `None` if extraction fails (no error raised). Handle gracefully.

### Anti-Patterns to Avoid

- **Importing nanobot from opengui:** All adapter code lives in `nanobot/`. opengui must remain zero-dependency on nanobot.
- **Rebuilding GuiAgent on every tool call:** GuiAgent is stateless per-run (TrajectoryRecorder is scoped per-run); it's safe to construct once at tool registration. BUT TrajectoryRecorder must be created fresh per run — it holds per-run state.
- **Duplicate retry logic:** Do NOT implement retry in the adapter AND in the agent loop. Adapter delegates entirely to `chat_with_retry`.
- **Blocking asyncio:** `GuiAgent.run()` is fully async. Always `await` it, never `asyncio.run()` inside the tool.
- **Ignoring SkillExtractor None return:** If extraction returns `None`, log a warning but don't raise — failed extraction should not break the tool result.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM retry on transient errors | Custom retry loop in adapter | `nanobot.providers.base.LLMProvider.chat_with_retry` | Already handles 429, 500, 502/503/504, image-stripping fallback |
| Trajectory recording | Custom JSONL writer | `opengui.trajectory.recorder.TrajectoryRecorder` | Handles metadata, phase, step, result events with atomic writes |
| Skill extraction from trajectory | Custom LLM prompt | `opengui.skills.extractor.SkillExtractor` | Handles both success and failure modes, parameter extraction, valid_state |
| Skill deduplication | Custom similarity | `opengui.skills.library.SkillLibrary.add_or_merge` | Multi-factor similarity with LLM merge decision already implemented |
| Background task management | Custom asyncio task dict | `asyncio.create_task` + done callback (SpawnTool pattern) | SpawnTool already demonstrates the exact pattern needed |
| JSON Schema validation for tool params | Custom validator | `Tool.validate_params` (base class) | Already handles required fields, type coercion via cast_params |

**Key insight:** Every sub-problem in this phase has a working implementation in either nanobot or opengui. Phase 3 is pure assembly work with a thin adapter layer.

---

## Common Pitfalls

### Pitfall 1: ToolCall Type Mismatch

**What goes wrong:** Passing `nanobot.ToolCallRequest` objects to opengui code that expects `opengui.ToolCall` frozen dataclasses. The two types have the same `id/name/arguments` fields but are different classes.

**Why it happens:** Both packages define their own response types. The adapter must explicitly construct `opengui.ToolCall` from `nanobot.ToolCallRequest`.

**How to avoid:** In `NanobotLLMAdapter.chat()`, always create new `ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)` instances. Never pass `ToolCallRequest` objects through.

**Warning signs:** `AttributeError: 'ToolCallRequest' object has no attribute 'foo'` in opengui code, or isinstance checks failing in opengui.

### Pitfall 2: tool_calls None vs Empty List

**What goes wrong:** `opengui.LLMResponse.tool_calls` is `list[ToolCall] | None` — `None` means no tool call. `nanobot.LLMResponse.tool_calls` is `list[ToolCallRequest]` with default `field(default_factory=list)` — empty list means no tool call.

**Why it happens:** Different None-vs-empty conventions in the two codebases.

**How to avoid:** In the adapter: `tool_calls = [...] or None` — converts empty list to None.

**Warning signs:** `GuiAgent._run_step` raises `RuntimeError("LLM did not return a computer_use tool call after retries.")` when there actually was a tool call — caused by the agent seeing `tool_calls=[]` (truthy-empty treated as absent).

### Pitfall 3: TrajectoryRecorder Per-Run Scope

**What goes wrong:** Reusing a single `TrajectoryRecorder` across multiple `GuiAgent.run()` calls. The recorder has mutable state (`_step_count`, `_closed`, `_current_phase`) and will produce corrupted output if reused.

**Why it happens:** GuiAgent stores `self._trajectory_recorder` as instance state, making it easy to assume it's safe to reuse.

**How to avoid:** Create a fresh `TrajectoryRecorder(output_dir=run_dir, task=task, platform=backend.platform)` for each `execute()` call. Either construct GuiAgent fresh per call or pass the recorder in.

**Warning signs:** Trajectory JSONL files containing steps from multiple runs.

### Pitfall 4: GuiConfig Field Access Before Registration

**What goes wrong:** Calling `AgentLoop._register_default_tools()` before `GuiConfig` is available, or trying to access `gui_config.backend` when `gui` config is `None`.

**Why it happens:** `AgentLoop.__init__` currently takes individual config fields, not the full `Config` object. Adding gui_config requires a new parameter.

**How to avoid:** Add `gui_config: GuiConfig | None = None` to `AgentLoop.__init__`. Guard all gui tool construction with `if self._gui_config is not None`.

**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'backend'`

### Pitfall 5: Skill Library Path Construction

**What goes wrong:** Using the wrong directory path for per-platform skill libraries, causing skills from different platforms to be stored together or lost.

**Why it happens:** `SkillLibrary` takes a `storage_path: Path` at construction — using a shared path merges platforms.

**How to avoid:** Construct `SkillLibrary(storage_path=workspace / "gui_skills" / backend.platform, ...)` where `backend.platform` is the string from `DeviceBackend.platform` property (e.g., `"android"`, `"macos"`).

**Warning signs:** Skills for Android appearing in desktop sessions, or skill search returning irrelevant results.

### Pitfall 6: SkillExtractor Requires LLMProvider

**What goes wrong:** Instantiating `SkillExtractor` with a nanobot `LLMProvider` instead of an opengui `LLMProvider`. `SkillExtractor` calls `self._llm.chat(messages)` expecting the opengui protocol.

**How to avoid:** Pass the `NanobotLLMAdapter` instance (which satisfies opengui's `LLMProvider` protocol) to `SkillExtractor`.

---

## Code Examples

Verified patterns from source code:

### GuiAgent.run() Return Value Mapping

```python
# From opengui/agent.py — AgentResult fields
@dataclass(frozen=True)
class AgentResult:
    success: bool        # → result["success"]
    summary: str         # → result["summary"]
    trace_path: str | None = None  # → result["trace_path"]
    steps_taken: int = 0  # → result["steps_taken"]
    error: str | None = None  # → result["error"]

# Tool.execute() must return a JSON string:
import json
return json.dumps({
    "success": result.success,
    "summary": result.summary,
    "trace_path": result.trace_path,
    "steps_taken": result.steps_taken,
    "error": result.error,
})
```

### Tool Registration Pattern

```python
# From nanobot/agent/tools/registry.py + loop.py
# Registration in _register_default_tools():
self.tools.register(GuiSubagentTool(
    gui_config=self._gui_config,
    provider=self.provider,
    model=self.model,
    workspace=self.workspace,
))

# Tool execute() returns str — JSON for structured data:
async def execute(self, task: str, backend: str | None = None, **kwargs) -> str:
    ...
    return json.dumps({...})
```

### SpawnTool Background Task Pattern (reference)

```python
# From nanobot/agent/tools/spawn.py — pattern for background execution
bg_task = asyncio.create_task(self._run_gui_agent(task))
self._running_tasks[task_id] = bg_task
bg_task.add_done_callback(lambda t: self._running_tasks.pop(task_id, None))
# Return immediately (fire-and-forget) OR await (blocking)
```

### SkillExtractor Usage

```python
# From opengui/skills/extractor.py
extractor = SkillExtractor(llm=nanobot_llm_adapter)
skill = await extractor.extract(
    trajectory_path=trace_path,
    success=result.success,
)
if skill is not None:
    await skill_library.add_or_merge(skill)
    skill_library.dedup()  # immediate dedup after extraction
```

### Pydantic Config Extension Pattern

```python
# From nanobot/config/schema.py — existing pattern
class Base(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

# New models follow the same pattern:
class AdbConfig(Base):
    serial: str | None = None

class GuiConfig(Base):
    backend: Literal["adb", "local", "dry-run"] = "adb"
    adb: AdbConfig = Field(default_factory=AdbConfig)
    artifacts_dir: str = "gui_runs"
    max_steps: int = 15
    skill_threshold: float = 0.6

class Config(BaseSettings):
    # Add after existing fields:
    gui: GuiConfig | None = None
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual skill trigger after GUI run | Auto-extract in GuiSubagentTool.execute() | Phase 3 decision | NANO-05: no explicit skill command needed |
| Shared skill library across platforms | Per-backend directories `gui_skills/{platform}/` | Phase 3 decision | Prevents cross-platform skill contamination |
| Bus notification for subagent results | Direct structured dict return (no bus) | Phase 3 decision | Router gets result synchronously when awaited |

---

## Integration Points Summary

| File | Change Type | What |
|------|------------|------|
| `nanobot/agent/gui_adapter.py` | NEW | NanobotLLMAdapter + NanobotEmbeddingAdapter |
| `nanobot/agent/tools/gui.py` | NEW | GuiSubagentTool |
| `nanobot/config/schema.py` | MODIFY | Add AdbConfig, GuiConfig; add `gui: GuiConfig | None` to Config |
| `nanobot/agent/loop.py` | MODIFY | Add `gui_config` param; register GuiSubagentTool in `_register_default_tools()` |

---

## Open Questions

1. **NanobotEmbeddingAdapter: what embedding API to wrap?**
   - What we know: nanobot's LiteLLM provider supports DashScope (dashscope provider config); qwen3-vl-embedding is the target model from requirements. LiteLLM has `aembedding()` function for embedding calls.
   - What's unclear: Is there an existing embedding call path in nanobot's LiteLLM provider, or does the adapter need to call `litellm.aembedding()` directly?
   - Recommendation: If no embedding endpoint is configured, set embedding_provider=None in GuiAgent (BM25-only). For the adapter, call `litellm.aembedding(model=..., input=texts)` with the configured api_key — this is a simpler path than adding embedding to LLMProvider ABC.

2. **AgentLoop constructor: pass GuiConfig or construct GuiSubagentTool externally?**
   - What we know: AgentLoop currently receives individual config fields, not the full Config object.
   - What's unclear: Is the cleaner approach (a) add `gui_config: GuiConfig | None = None` to `AgentLoop.__init__`, or (b) construct GuiSubagentTool outside and inject via `loop.tools.register()`?
   - Recommendation: Option (a) — consistent with how other config fields are passed (web_search_config, exec_config). Option (b) creates an awkward external construction step.

3. **TreeRouter.RouterContext.gui_agent: is it GuiAgent or GuiSubagentTool?**
   - What we know: `RouterContext.gui_agent: Any = None` and `_run_gui()` calls `context.gui_agent.run(instruction)`. GuiSubagentTool wraps GuiAgent. GuiAgent.run() exists directly.
   - What's unclear: Should the router call `GuiSubagentTool.execute(task=...)` or `GuiAgent.run(task)` directly?
   - Recommendation: Wire `RouterContext.gui_agent` to the GuiAgent instance (not the tool wrapper). The tool wrapper is for main-agent tool calls; the router has direct access to the GuiAgent. This keeps the two execution paths (tool-call vs. router dispatch) independent.

---

## Validation Architecture

> `workflow.nyquist_validation` not set to `false` — validation architecture included.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pyproject.toml` or `pytest.ini` (check project root) |
| Quick run command | `pytest tests/test_opengui_p3*.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NANO-01 | GuiSubagentTool is registered and callable via ToolRegistry | unit | `pytest tests/test_opengui_p3_nanobot.py::test_gui_tool_registered -x` | Wave 0 |
| NANO-02 | NanobotLLMAdapter.chat() correctly maps ToolCallRequest→ToolCall and drops extras | unit | `pytest tests/test_opengui_p3_nanobot.py::test_llm_adapter_maps_response -x` | Wave 0 |
| NANO-02 | NanobotLLMAdapter.chat() converts empty tool_calls list to None | unit | `pytest tests/test_opengui_p3_nanobot.py::test_llm_adapter_empty_tool_calls -x` | Wave 0 |
| NANO-03 | GuiSubagentTool constructs AdbBackend / DryRunBackend from config | unit | `pytest tests/test_opengui_p3_nanobot.py::test_backend_selection -x` | Wave 0 |
| NANO-04 | Trajectory JSONL written to workspace/gui_runs/ after a run | integration | `pytest tests/test_opengui_p3_nanobot.py::test_trajectory_saved_to_workspace -x` | Wave 0 |
| NANO-05 | SkillExtractor called and skills added to per-platform library | integration | `pytest tests/test_opengui_p3_nanobot.py::test_auto_skill_extraction -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_opengui_p3_nanobot.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_opengui_p3_nanobot.py` — covers NANO-01 through NANO-05
- [ ] Uses `_FakeEmbedder` and `_ScriptedLLM` patterns from `test_opengui_p2_integration.py` and `test_opengui.py`
- [ ] DryRunBackend available in opengui — use for integration tests (no real device needed)

---

## Sources

### Primary (HIGH confidence)

All findings below are from direct source code inspection of the working codebase:

- `nanobot/agent/tools/base.py` — Tool ABC: name, description, parameters, execute(), validate_params(), cast_params()
- `nanobot/agent/tools/registry.py` — ToolRegistry: register(), execute(), get_definitions()
- `nanobot/agent/tools/spawn.py` — SpawnTool: background asyncio.Task pattern
- `nanobot/agent/subagent.py` — SubagentManager: asyncio.create_task + done_callback lifecycle
- `nanobot/agent/loop.py` — AgentLoop._register_default_tools(), _background_tasks pattern
- `nanobot/config/schema.py` — Config, Base, Pydantic field patterns, camelCase aliasing
- `nanobot/providers/base.py` — LLMProvider ABC, LLMResponse, ToolCallRequest, chat_with_retry
- `opengui/interfaces.py` — opengui LLMProvider Protocol, LLMResponse (content, tool_calls, raw), ToolCall, DeviceBackend, EmbeddingProvider
- `opengui/agent.py` — GuiAgent constructor, AgentResult dataclass fields
- `opengui/skills/extractor.py` — SkillExtractor.extract(trajectory_path, success) → Skill | None
- `opengui/skills/library.py` — SkillLibrary(storage_path), add_or_merge(), dedup()
- `opengui/trajectory/recorder.py` — TrajectoryRecorder(output_dir, task, platform), mutable per-run state
- `opengui/memory/retrieval.py` — EmbeddingProvider protocol: `async def embed(texts) -> np.ndarray`
- `nanobot/agent/router.py` — RouterContext.gui_agent, _run_gui() dispatch pattern
- `nanobot/agent/planner.py` — PlanNode, CapabilityType ("gui" | "tool" | "mcp" | "api")
- `tests/test_opengui_p2_integration.py` — _FakeEmbedder, _RecordingLLM test helper patterns
- `tests/test_opengui.py` — _ScriptedLLM pattern, DryRunBackend usage in tests

### Secondary (MEDIUM confidence)

- None required — all necessary information available in source code.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified directly in source; no new dependencies
- Architecture: HIGH — adapter pattern is textbook, both protocols fully read
- Pitfalls: HIGH — identified from direct comparison of the two LLMResponse types and TrajectoryRecorder state analysis
- Test patterns: HIGH — existing test infrastructure (DryRunBackend, _FakeEmbedder, _ScriptedLLM) directly reusable

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable domain, no external dependencies to track)
