# Phase 3: Nanobot Subagent - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Expose GuiAgent as a nanobot tool so the main agent can spawn GUI tasks, receive structured results, and automatically extract new skills from recorded trajectories. This phase creates GuiSubagentTool, NanobotLLMAdapter, NanobotEmbeddingAdapter, backend selection from config, trajectory workspace persistence, and auto skill extraction.

**Not in scope:** Desktop backend implementation (Phase 4), CLI entry point (Phase 5), new GUI agent capabilities (already complete in Phase 2).

</domain>

<decisions>
## Implementation Decisions

### Tool Invocation Design
- GuiSubagentTool runs in **background** (async), not blocking the main agent loop
- Tree router fires GUI ATOMs in background but **awaits before dependent ATOMs** — effectively sync for sequential dependencies, truly parallel for independent branches
- Tool returns a **structured dict**: `{success, summary, trace_path, steps_taken, error}` (maps from AgentResult fields)
- Tool takes only **task string + optional backend override** — all agent params (max_steps, skill_threshold, etc.) come from nanobot config defaults, no per-call overrides
- Router gets the result dict directly when awaited — **no bus notification** for GUI results

### LLM Adapter Bridge
- **NanobotLLMAdapter** lives in `nanobot/agent/gui_adapter.py` — imports nanobot provider + opengui interfaces, keeps opengui zero-dependency on nanobot
- Adapter **strips to opengui protocol**: only passes content + tool_calls + raw. Nanobot's reasoning_content, thinking_blocks, finish_reason, usage are dropped
- Adapter **delegates retry logic** to nanobot's `chat_with_retry` internally — opengui's `chat()` gets a single reliable call, no duplicate retry logic
- **NanobotEmbeddingAdapter** as a separate small class alongside NanobotLLMAdapter — both created by the tool and passed to GuiAgent

### Backend Selection
- New **`gui` config section** in nanobot config schema: `gui: {backend: "adb", adb: {serial: "..."}, artifacts_dir: "gui_runs/"}`
- Backend type is `"adb"`, `"local"`, or `"dry-run"` — read from `gui.backend` in config
- **dry-run requires explicit config** — no auto-detection for test environments; tests create their own backend instances directly
- If gui config section is absent: tool registration behavior is **Claude's discretion** (skip registration or register-but-error)

### Trajectory & Workspace
- Trajectory files saved to **`workspace/gui_runs/`** — each run gets a timestamped subdirectory with trace.jsonl + screenshots (e.g., `workspace/gui_runs/2026-03-18_143022/`)
- This aligns with opengui's existing `artifacts_root` pattern

### Skill Extraction
- **Auto-extraction after every GUI run** — GuiSubagentTool automatically calls SkillExtractor on the trajectory. No manual trigger needed from the main agent
- Extract from **both successful and failed** trajectories — SkillExtractor already supports failed trajectories for negative examples
- **Immediate dedup** on extraction — run SkillLibrary's existing dedup logic right after adding extracted skills
- **Per-backend skill libraries** — separate directories per platform (e.g., `workspace/gui_skills/android/`, `workspace/gui_skills/desktop/`). Skills aren't portable across platforms

### Fixed-Parameter Skill Step Extraction
- **LLM classifies** each step as fixed or dynamic during extraction (existing design from Phase 2)
- Fixed text for known UI elements (e.g., tapping "Settings") stored as `fixed_values: {text: "Settings"}` — only parameterize text that varies (like search queries)
- **Canonical storage format is always [0,999] relative coords** with model-specific normalization:
  - Qwen/Gemini (native [0,999] output): store as-is, rescale to resolution at execution time
  - Other models (absolute resolution output): rescale to [0,999] during extraction, execute directly without rescale

### Memory
- Memory store scope is **Claude's discretion** — MemoryEntry already has a platform field, so shared store with platform filtering is the natural fit, but per-backend separation is acceptable if it simplifies the implementation

### Claude's Discretion
- Whether to skip tool registration or register-but-error when gui config is missing
- Memory store scoping (shared vs per-backend)
- Exact config schema field names and Pydantic model structure
- Adapter internal implementation details (error mapping, model name passthrough)
- Timestamp format for run directories
- Whether to expose a manual trajectory_summary skill alongside auto-extraction

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Tool & Registry Pattern
- `nanobot/agent/tools/base.py` — Tool ABC: name, description, parameters, execute()
- `nanobot/agent/tools/registry.py` — ToolRegistry: register(), execute(), get_definitions()
- `nanobot/agent/tools/spawn.py` — SpawnTool: existing background subagent pattern (reference for async execution)

### LLM Provider Protocols
- `opengui/interfaces.py` — opengui LLMProvider protocol (chat method, LLMResponse, ToolCall)
- `nanobot/providers/base.py` — nanobot LLMProvider (chat_with_retry, LLMResponse with reasoning_content/thinking_blocks, ToolCallRequest)

### GUI Agent
- `opengui/agent.py` — GuiAgent class, AgentResult dataclass, constructor params (llm, backend, trajectory_recorder, memory_retriever, skill_library, etc.)
- `opengui/backends/` — DryRunBackend, ADBBackend implementations
- `opengui/skills/extractor.py` — SkillExtractor for trajectory-to-skill extraction
- `opengui/skills/library.py` — SkillLibrary with add(), search(), dedup
- `opengui/trajectory/recorder.py` — TrajectoryRecorder with JSONL output

### Nanobot Agent Infrastructure
- `nanobot/agent/subagent.py` — SubagentManager (existing background task spawning)
- `nanobot/agent/loop.py` — AgentLoop (tool registration, main iteration)
- `nanobot/config/schema.py` — Config schema (add gui section here)
- `nanobot/agent/planner.py` — TaskPlanner (AND/OR/ATOM tree) created in Phase 2
- `nanobot/agent/router.py` — TreeRouter (ATOM dispatch) created in Phase 2

### Phase 2 Context (Prior Decisions)
- `.planning/phases/02-agent-loop-integration/02-CONTEXT.md` — Architecture decisions: two-level execution, skill execution, memory injection, SKILL.md registry

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Tool` ABC + `ToolRegistry`: Well-established pattern for tool registration. GuiSubagentTool follows same interface
- `SpawnTool`: Reference implementation for background subagent execution with asyncio.Task
- `SubagentManager`: Background task lifecycle management (spawn, cleanup callbacks)
- `GuiAgent`: Full constructor with all optional components (memory_retriever, skill_library, skill_executor)
- `SkillExtractor` + `SkillLibrary`: Extraction and dedup already implemented in opengui
- `TrajectoryRecorder`: JSONL recording with ExecutionPhase tracking
- `_FakeEmbedder` + `_ScriptedLLM`: Test patterns for mocking LLM and embedding in tests

### Established Patterns
- Protocol-based interfaces (LLMProvider, DeviceBackend, EmbeddingProvider) — adapter must conform
- Frozen dataclasses for data containers (AgentResult, ToolCall, LLMResponse)
- Async-first design (all backend/LLM calls are async)
- Pydantic models for config schema validation
- Tool parameters as JSON Schema for OpenAI function calling format

### Integration Points
- `nanobot/config/schema.py`: Add `GuiConfig` Pydantic model with backend, adb, artifacts_dir fields
- `nanobot/agent/loop.py`: Register GuiSubagentTool in `_register_default_tools()` (conditional on gui config)
- `nanobot/agent/gui_adapter.py`: New file — NanobotLLMAdapter + NanobotEmbeddingAdapter
- `nanobot/agent/tools/gui.py`: New file — GuiSubagentTool implementation
- `workspace/gui_runs/`: Runtime directory for trajectory artifacts
- `workspace/gui_skills/{platform}/`: Runtime directory for per-platform skill libraries

</code_context>

<specifics>
## Specific Ideas

- Background execution with dependency-aware awaiting: fire-and-forget for parallelism, but the router blocks when the next ATOM depends on the GUI result — best of both worlds
- Auto-extraction from both success and failure trajectories: learn "what works" and "what to avoid" — SkillExtractor already supports this dual mode
- Per-backend skill libraries: Android tap coordinates and app packages are meaningless on desktop — strict platform separation avoids cross-contamination
- Coord normalization is model-dependent: Qwen/Gemini output [0,999] natively (store as-is, rescale at execution), other models output absolute resolution (rescale to [0,999] at extraction, no rescale at execution). This is critical for fixed-parameter skill portability across resolutions

</specifics>

<deferred>
## Deferred Ideas

- Bus notifications for GUI task progress (user seeing intermediate steps in chat) — could add later as an optional feature
- Manual trajectory_summary skill for re-processing old trajectories — auto-extraction covers the common case
- Per-call config overrides on GuiSubagentTool (max_steps, skill_threshold) — add if needed later
- Cross-platform skill transfer (learning from Android to inform desktop) — fundamentally different UI paradigms

</deferred>

---

*Phase: 03-nanobot-subagent*
*Context gathered: 2026-03-18*
