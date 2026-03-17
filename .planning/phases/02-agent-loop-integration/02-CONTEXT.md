# Phase 2: Agent Loop Integration - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning
**Revised:** 2026-03-17 (architectural redesign — planner moved to main agent level)

<domain>
## Phase Boundary

Wire memory retrieval, skill search + execute, and trajectory recording into GuiAgent.run(). Additionally, build a main-agent-level TaskPlanner that decomposes tasks into AND/OR/ATOM trees and routes each ATOM to the appropriate executor (GUI subagent, tool/MCP, or API). The GUI agent becomes simpler — it receives a single focused instruction per invocation and does skill matching + execution or free exploration. This phase also migrates MemoryStore from JSON to markdown format and adds skill confidence tracking with lifecycle management.

**Key architectural change (revised from original):** The AND/OR/ATOM planner lives at the main agent level (nanobot), NOT inside opengui. This allows the planner to route subtasks to any capability (GUI, tools, MCP) rather than being limited to GUI-only execution. opengui does NOT have its own planner or tree executor — it receives a single ATOM instruction and executes it.

</domain>

<decisions>
## Implementation Decisions

### Architecture: Two-Level Execution (REVISED)
- **Main agent (nanobot)** owns task decomposition: AND/OR/ATOM tree planner + router
- **GUI subagent (opengui)** receives a single ATOM instruction, does skill match → execute or free explore
- AND/OR/ATOM tree is built ONCE at the main agent level — NOT duplicated inside opengui
- GuiAgent.run() takes a single instruction string (an ATOM-level subgoal), not a full complex task
- The existing `_run_once()` step loop remains the execution engine for each ATOM

### Main-Agent TaskPlanner (AND/OR/ATOM Tree)
- LLM planner decomposes every task into an AND/OR/ATOM tree before execution
- **AND node**: all children execute sequentially; replan if any child fails
- **OR node**: try children until one succeeds; replan if all fail
- **ATOM node**: smallest meaningful subgoal; leaf of planning. Tagged with a capability type (`gui`, `tool`, `mcp`, `api`)
- Tree is built upfront in a single planning LLM call; replan from current state on AND-child failure or all-OR-children failure
- Planner reads SKILL.md files to understand available capabilities when decomposing
- Output format: structured tool call (`create_plan`) returning JSON tree with capability type per ATOM
- Replanner receives: current state + remaining subgoals + summaries of last few completed/failed nodes

### Capability Registry via SKILL.md
- Main agent reads SKILL.md files from `nanobot/skills/` to understand available capabilities
- Each SKILL.md declares: name, description, type (gui/tool/mcp/api), and trigger patterns
- The planner uses this registry to decide how to decompose and which ATOM type to assign
- GUI capabilities come from opengui's SkillLibrary (searched at execution time, not planning time)
- Non-GUI capabilities come from nanobot's existing tool registry and MCP servers
- Portability: other claws (openclaw, nanoclaw, zeroclaw) ship their own SKILL.md files

### Main-Agent Router
- After planning, walks the AND/OR/ATOM tree
- For each ATOM, dispatches based on capability type:
  - `gui` → spawn GuiAgent.run(instruction) via existing SubagentManager
  - `tool` → invoke nanobot tool from ToolRegistry
  - `mcp` → call MCP server tool
  - `api` → direct API call
- Collects results, handles AND/OR semantics (sequential/alternative)
- On failure: triggers replanning with current state

### GuiAgent Simplified Role (REVISED)
- GuiAgent.run() receives a SINGLE focused instruction (one ATOM from the tree)
- On entry: search skill library for matching skill
- If match above threshold → attempt skill execution (with recovery)
- If no match or below threshold → free exploration via `_run_once()` step loop
- Returns AgentResult for the single instruction
- NO internal planner, NO tree executor — these are removed from opengui

### Skill-vs-Explore Strategy (unchanged, but per single ATOM)
- Always search skill library first for the received instruction
- Fixed score threshold (configurable, e.g., 0.6) — above threshold = attempt skill; below = free explore
- Match score = search_relevance * confidence (skill confidence multiplied into relevance)
- Single best match per instruction (no ranked fallback)
- Parameter pre-filling at match time: LLM extracts parameter values from instruction and pre-fills placeholders before execution begins

### Skill Execution (Fast-Path)
- **Fixed-parameter steps** (`fixed=true`): bypass LLM entirely, execute directly on backend. Only use LLM for valid_state verification before each step
- **Pre-filled text params**: text placeholders (e.g., `{{text}}`) pre-filled from instruction at match time; execute without LLM grounding
- **Dynamic coord params** (`{{coord}}`): LLM grounds at execution time by seeing current screenshot + step description
- **Partial skill execution**: sequential scan of valid_states via LLM — send all skill steps, LLM determines which step's valid_state is the last "true" one; start execution from the next step
- Placeholder format: Claude's discretion (`{{param}}` recommended per KnowAct convention)

### Skill Failure & Recovery
- When valid_state check fails: spawn recovery ReAct agent with NO history, instruction = the unmatched valid_state description, max 3 steps (separate budget from main run)
- If recovery agent calls `done`: skip re-checking valid_state, directly ground/execute the current skill step, continue remaining skill steps
- If recovery exhausts 3 steps: fall back to ReAct agent with the full instruction
- After skill completes all steps: fall back to ReAct mode with history; agent uses `done` action to signal completion, or continues if skill only covered part of the work
- Post-skill ReAct mode uses the received instruction (not full task)

### Free Exploration
- When no skill matches (below threshold): free exploration bounded by the received instruction
- Agent calls `done` action to signal completion
- Free exploration uses the existing `_run_once()` step loop with configurable max_steps

### Skill Confidence & Lifecycle
- Add `success_count`, `failure_count`, `success_streak`, `failure_streak` fields to Skill dataclass
- Confidence = success_count / (success_count + failure_count); default 1.0 for new skills
- Confidence multiplied into match score: `final_score = search_relevance * confidence`
- Decay formula for in-flight updates (success/failure tracked during run)
- Confidence persisted to skill library at end of run (not during)
- **Discard rule**: after min 5 total attempts, if confidence < 0.3, remove skill from library
- **Merge on update**: when confidence updates, check if skill should be merged with a similar higher-confidence skill
- Post-run maintenance pass: (1) update confidence, (2) discard low-confidence skills, (3) check merge opportunities

### Skill Data Model Changes
- Add `fixed: bool` and `fixed_values: dict[str, Any]` fields to SkillStep (KnowAct pattern)
- Fixed steps store concrete values (e.g., `point_fixed: "423,600"`)
- Dynamic steps use placeholders for runtime grounding
- During extraction, LLM classifies each step as fixed or dynamic
- Extracted coordinates stored as [0,999] relative (portable across resolutions)

### Memory Prompt Injection
- Memory entries injected as a `<memory>` section in the system prompt (via `build_system_prompt()`)
- Retrieval: all 4 types (OS_GUIDE, APP_GUIDE, ICON_GUIDE, POLICY) ranked by relevance, top-K overall
- **Exception**: POLICY entries always included regardless of relevance score (safety/behavioral rules)
- K is configurable (default 5), passed as parameter to GuiAgent
- Retrieval happens once at start of GuiAgent.run() using the received instruction
- Memory is read-only during runs; new memories created post-run only

### Memory Format Migration (JSON to Markdown)
- Replace MemoryStore internals to read/write .md files instead of JSON
- One .md file per memory type: `os_guide.md`, `app_guide.md`, `icon_guide.md`, `policy.md`
- Each H2 section = one retrievable MemoryEntry
- Structured H2 format: heading = topic, metadata lines (platform, app), then content body
- Same public API (add, get, list); H2 chunking layer converts markdown sections to MemoryEntry objects
- Existing Phase 1 tests updated to use .md format
- Keep simple relevance ranking (BM25 + FAISS hybrid); no multi-dimensional scoring for now

### Step Budget
- GuiAgent has a configurable max_steps (default 15) for the received instruction
- Recovery steps have separate budget (3 steps, not counted against main pool)
- When pool exhausts: fail with partial result (AgentResult showing progress)
- The main-agent router manages overall task budget across all ATOMs

### Optional Components
- **Trajectory recorder**: REQUIRED parameter on GuiAgent
- **Memory retriever**: optional (skip memory injection if None)
- **Skill library**: optional (always free explore if None)
- **EmbeddingProvider**: shared instance created by caller, passed to both MemoryRetriever and SkillLibrary externally (GuiAgent doesn't manage it)
- All new components passed as individual constructor params (not config object)

### Module Organization (REVISED)
- **NO** new `opengui/planner.py` — planner lives at main agent level
- **NO** new `opengui/tree_executor.py` — tree walking lives at main agent level
- `opengui/agent.py`: GuiAgent.run() simplified — receives instruction, does skill match + execute/explore, returns result
- `_run_once()` remains as the execution engine (not replaced)
- New `nanobot/agent/planner.py`: TaskPlanner with AND/OR/ATOM tree + capability-type routing
- New `nanobot/agent/router.py`: TreeRouter that walks the plan tree and dispatches ATOMs to executors

### Portability
- opengui maintains strict protocol boundary: LLMProvider + DeviceBackend + EmbeddingProvider only
- opengui is SIMPLER than before — no planner, no tree executor, just the GUI execution engine
- The planner/router pattern is portable via SKILL.md convention: any claw can implement its own planner that reads SKILL.md files
- Each claw ships its own SKILL.md capability registry
- Explicit constructor (no factory/builder); each claw creates GuiAgent with its own protocol implementations

### Integration Test (TEST-05)
- Full flow scenario at main-agent level: TaskPlanner decomposes task → Router dispatches ATOMs → GuiAgent handles GUI ATOMs
- Pre-seeded memory (app_guide for Settings) + pre-seeded skill (toggle Wi-Fi) + task "Turn on Wi-Fi"
- Mock LLM returns AND tree with 2 ATOMs: one gui (skill-matched), one tool (non-GUI)
- Assertions: trajectory records GUI execution, memory appears in system prompt, skill confidence updated, non-GUI ATOM handled by tool
- Second test covering recovery path: skill step valid_state fails → recovery agent → resume skill

### Claude's Discretion
- Parameter pre-fill: combined with planning call or separate extraction call
- Placeholder format for dynamic params (recommend `{{param}}`)
- Exact prompt wording for system prompt memory section
- Internal tree serialization format for trajectory events
- Exact confidence decay formula details
- Recovery agent prompt design
- Router implementation details (sync vs async dispatch, error propagation)

</decisions>

<specifics>
## Specific Ideas

- "We pursue low latency while high success-rate" — fixed-parameter skills execute without LLM calls; only valid_state verification and coord grounding need LLM
- KnowAct's `fixed_values` dict pattern for SkillStep — dual-mode parameter handling (fixed vs dynamic)
- KnowAct's `success_streak` / `failure_streak` tracking — adopted for momentum-aware confidence
- Parameter pre-filling from instruction at match time — "search for basketball" + skill "search_goods" → pre-fill `{{text}}` = "basketball" → zero LLM calls during execution
- Partial skill execution via sequential valid_state scan — find deepest valid starting point, skip already-completed steps
- Recovery agent as a nested mini-agent with its own budget — clean separation from main execution
- SKILL.md as universal capability registry — same format works for GUI skills, CLI tools, MCP servers, API integrations
- Planner at main-agent level enables mixed-modality task decomposition: "Turn on Wi-Fi AND check weather" → GUI ATOM + tool ATOM

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `GuiAgent._run_once()` step loop: remains the execution engine for each ATOM instruction
- `GuiAgent._build_messages()` / `_build_instruction_prompt()`: memory injection point (system prompt)
- `SkillExecutor`: already has per-step valid_state verification via `LLMStateValidator`
- `SkillLibrary`: already has hybrid search (BM25 + FAISS) and dedup logic
- `TrajectoryRecorder`: already has `ExecutionPhase` enum (AGENT, SKILL, RETRY, RECOVERY)
- `MemoryRetriever`: BM25 + FAISS hybrid search, needs markdown chunking layer
- `build_system_prompt()` in `opengui/prompts/system.py`: add `<memory>` section here
- `_FakeEmbedder` and `_ScriptedLLM` test patterns from Phase 1
- `nanobot/agent/tools/`: existing ToolRegistry for dispatching non-GUI ATOMs
- `nanobot/agent/subagent.py`: SubagentManager for spawning GUI subagent
- `nanobot/skills/`: existing SKILL.md files as capability declarations

### Established Patterns
- Frozen dataclasses for data containers (StepResult, HistoryTurn, AgentResult)
- Protocol-based interfaces (LLMProvider, DeviceBackend, EmbeddingProvider)
- Async-first design (all backend/LLM calls are async)
- [0,999] relative coordinates throughout
- SKILL.md with YAML frontmatter + markdown instructions (nanobot convention)

### Integration Points
- `GuiAgent.__init__()`: add trajectory_recorder (required), memory_retriever (optional), skill_library (optional), memory_top_k (configurable)
- `GuiAgent.run()`: simplified to receive single instruction, do skill match, execute/explore
- `build_system_prompt()`: receives memory entries, formats as `<memory>` section
- `SkillStep`: add `fixed`, `fixed_values` fields
- `Skill`: add `success_count`, `failure_count`, `success_streak`, `failure_streak` fields
- `MemoryStore`: internal rewrite from JSON to markdown with H2 chunking
- `nanobot/agent/planner.py`: new TaskPlanner module at main-agent level
- `nanobot/agent/router.py`: new TreeRouter module at main-agent level

</code_context>

<deferred>
## Deferred Ideas

- Multi-dimensional memory scoring (relevance + freshness + utility + confidence a la KnowAct) — defer to v2 memory improvements
- Multi-bucket skill library (primary, inter-task, candidate, micro) — keep single bucket for now
- Per-subgoal memory retrieval (retrieve memories specific to each subgoal instruction) — defer, using instruction-level retrieval for now
- CapabilityProvider protocol (typed interface for capability registration) — defer, using SKILL.md convention for now
- Planner as a shared library (extracting from nanobot for other claws) — defer, keep in nanobot for now; other claws implement their own

</deferred>

---

*Phase: 02-agent-loop-integration*
*Context gathered: 2026-03-17*
*Context revised: 2026-03-17 (planner → main agent level, SKILL.md capability registry)*
