# Phase 2: Agent Loop Integration - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire memory retrieval, skill search + execute, and trajectory recording into GuiAgent.run(). The agent loop becomes a fully integrated system: plan task into subgoal tree, match skills per subgoal, execute with fixed-parameter fast-path, record trajectory, and fall back to free exploration when needed. This phase also migrates MemoryStore from JSON to markdown format and adds skill confidence tracking with lifecycle management.

</domain>

<decisions>
## Implementation Decisions

### Subgoal Decomposition (AND/OR/ATOM Tree)
- LLM planner decomposes every task into an AND/OR/ATOM tree before execution
- **AND node**: all children execute sequentially; replan if any child fails
- **OR node**: try children until one succeeds; replan if all fail
- **ATOM node**: smallest meaningful subgoal (may take multiple GUI steps); leaf of planning
- Tree is built upfront in a single planning LLM call; replan from current screen state on AND-child failure or all-OR-children failure
- Each node's instruction is adapted by the LLM using the original task instruction + retrieved memory context
- Replanner receives: current screenshot + remaining subgoals + summaries of last few completed/failed nodes

### Planner Design
- Planner uses the same LLMProvider instance as the executor (no separate model)
- Planner sees: initial screenshot + task description + memory context
- Output format: structured tool call (`create_plan`) returning JSON tree matching the dataclass hierarchy
- Parameter pre-filling combined with planning call (Claude's discretion on whether one or two calls)

### Skill-vs-Explore Strategy
- Always search skill library first for every AtomNode
- Fixed score threshold (configurable, e.g., 0.6) — above threshold = attempt skill; below = free explore
- Match score = search_relevance * confidence (skill confidence multiplied into relevance)
- Single best match per subgoal (no ranked fallback)
- Parameter pre-filling at match time: LLM extracts parameter values from subgoal instruction and pre-fills placeholders before execution begins

### Skill Execution (Fast-Path)
- **Fixed-parameter steps** (`fixed=true`): bypass LLM entirely, execute directly on backend. Only use LLM for valid_state verification before each step
- **Pre-filled text params**: text placeholders (e.g., `{{text}}`) pre-filled from subgoal instruction at match time; execute without LLM grounding
- **Dynamic coord params** (`{{coord}}`): LLM grounds at execution time by seeing current screenshot + step description
- **Partial skill execution**: sequential scan of valid_states via LLM — send all skill steps, LLM determines which step's valid_state is the last "true" one; start execution from the next step
- Placeholder format: Claude's discretion (`{{param}}` recommended per KnowAct convention)

### Skill Failure & Recovery
- When valid_state check fails: spawn recovery ReAct agent with NO history, instruction = the unmatched valid_state description, max 3 steps (separate budget from main run)
- If recovery agent calls `done`: skip re-checking valid_state, directly ground/execute the current skill step, continue remaining skill steps
- If recovery exhausts 3 steps: fall back to ReAct agent with the full subgoal instruction
- After skill completes all steps: fall back to ReAct mode with history; agent uses `done` action to signal subgoal completion, or continues if skill only covered part of the work
- Post-skill ReAct mode uses subgoal instruction (not full task instruction)

### Free Exploration
- When no skill matches (below threshold): free exploration bounded by the subgoal instruction
- Agent calls `done` action to signal subgoal completion
- Free exploration draws from the shared step pool

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
- Retrieval happens once at start of run using the full task string (not per-subgoal)
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
- Shared step pool across all subgoals (configurable max_steps, default 15)
- Recovery steps have separate budget (3 steps, not counted against main pool)
- When pool exhausts mid-tree: fail with partial result (AgentResult showing which subgoals completed)
- No replanning on pool exhaustion — run is over

### Optional Components
- **Trajectory recorder**: REQUIRED parameter on GuiAgent
- **Memory retriever**: optional (skip memory injection if None)
- **Skill library**: optional (always free explore if None)
- **EmbeddingProvider**: shared instance created by caller, passed to both MemoryRetriever and SkillLibrary externally (GuiAgent doesn't manage it)
- All new components passed as individual constructor params (not config object)

### Module Organization
- New `opengui/planner.py`: SubgoalNode, AndNode, OrNode, AtomNode dataclasses + TaskPlanner
- New `opengui/tree_executor.py`: TreeExecutor (walks nodes, dispatches to skill/free-explore)
- `opengui/agent.py`: GuiAgent.run() uses TaskPlanner + TreeExecutor; `_run_once()` replaced by tree-based execution
- Tree executor replaces flat step loop; old step loop becomes the free-explore path for a single AtomNode

### Portability
- Strict protocol boundary maintained: host agents provide LLMProvider + DeviceBackend + EmbeddingProvider only
- All new components (planner, tree executor, memory, skills) stay inside opengui
- FAISS remains a required dependency
- Explicit constructor (no factory/builder); each claw creates GuiAgent with its own protocol implementations

### Integration Test (TEST-05)
- Full flow scenario: pre-seeded memory (app_guide for Settings) + pre-seeded skill (toggle Wi-Fi) + task "Turn on Wi-Fi"
- Mock LLM returns AND tree with 2 subgoals: one free-explore, one skill-matched
- Assertions: trajectory records both phases, memory appears in system prompt, skill confidence updated
- Second test covering recovery path: skill step valid_state fails -> recovery agent -> resume skill

### Claude's Discretion
- Parameter pre-fill: combined with planning call or separate extraction call
- Placeholder format for dynamic params (recommend `{{param}}`)
- Exact prompt wording for system prompt memory section
- Internal tree serialization format for trajectory events
- Exact confidence decay formula details
- Recovery agent prompt design

</decisions>

<specifics>
## Specific Ideas

- "We pursue low latency while high success-rate" — fixed-parameter skills execute without LLM calls; only valid_state verification and coord grounding need LLM
- KnowAct's `fixed_values` dict pattern for SkillStep — dual-mode parameter handling (fixed vs dynamic)
- KnowAct's `success_streak` / `failure_streak` tracking — adopted for momentum-aware confidence
- Parameter pre-filling from subgoal instruction at match time — "search for basketball" + skill "search_goods" → pre-fill `{{text}}` = "basketball" → zero LLM calls during execution
- Partial skill execution via sequential valid_state scan — find deepest valid starting point, skip already-completed steps
- Recovery agent as a nested mini-agent with its own budget — clean separation from main execution

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `GuiAgent._run_once()` step loop: becomes the free-explore path for AtomNode execution
- `GuiAgent._build_messages()` / `_build_instruction_prompt()`: memory injection point (system prompt)
- `SkillExecutor`: already has per-step valid_state verification via `LLMStateValidator`
- `SkillLibrary`: already has hybrid search (BM25 + FAISS) and dedup logic
- `TrajectoryRecorder`: already has `ExecutionPhase` enum (AGENT, SKILL, RETRY, RECOVERY)
- `MemoryRetriever`: BM25 + FAISS hybrid search, needs markdown chunking layer
- `build_system_prompt()` in `opengui/prompts/system.py`: add `<memory>` section here
- `_FakeEmbedder` and `_ScriptedLLM` test patterns from Phase 1

### Established Patterns
- Frozen dataclasses for data containers (StepResult, HistoryTurn, AgentResult)
- Protocol-based interfaces (LLMProvider, DeviceBackend, EmbeddingProvider)
- Async-first design (all backend/LLM calls are async)
- [0,999] relative coordinates throughout

### Integration Points
- `GuiAgent.__init__()`: add trajectory_recorder (required), memory_retriever (optional), skill_library (optional), memory_top_k (configurable)
- `GuiAgent._run_once()`: replaced by `_plan_task()` → `_execute_tree()` flow
- `build_system_prompt()`: receives memory entries, formats as `<memory>` section
- `SkillStep`: add `fixed`, `fixed_values` fields
- `Skill`: add `success_count`, `failure_count`, `success_streak`, `failure_streak` fields
- `MemoryStore`: internal rewrite from JSON to markdown with H2 chunking

</code_context>

<deferred>
## Deferred Ideas

- Multi-dimensional memory scoring (relevance + freshness + utility + confidence a la KnowAct) — defer to v2 memory improvements
- Multi-bucket skill library (primary, inter-task, candidate, micro) — keep single bucket for now
- Per-subgoal memory retrieval (retrieve memories specific to each subgoal instruction) — defer, using task-level retrieval for now
- TaskPlanner as a protocol (allowing host agents to provide custom planning strategies) — defer, keep internal

</deferred>

---

*Phase: 02-agent-loop-integration*
*Context gathered: 2026-03-17*
