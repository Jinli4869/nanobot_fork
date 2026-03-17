# Phase 2: Agent Loop Integration - Research

**Researched:** 2026-03-17
**Domain:** Python async agent loops, AND/OR/ATOM task planning, skill-matched execution, memory injection, trajectory recording
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Architecture: Two-Level Execution (REVISED)**
- Main agent (nanobot) owns task decomposition: AND/OR/ATOM tree planner + router
- GUI subagent (opengui) receives a single ATOM instruction, does skill match -> execute or free explore
- AND/OR/ATOM tree is built ONCE at the main agent level — NOT duplicated inside opengui
- GuiAgent.run() takes a single instruction string (an ATOM-level subgoal), not a full complex task
- The existing `_run_once()` step loop remains the execution engine for each ATOM

**Main-Agent TaskPlanner**
- LLM planner decomposes every task into AND/OR/ATOM tree before execution
- AND node: all children execute sequentially; replan if any child fails
- OR node: try children until one succeeds; replan if all fail
- ATOM node: smallest meaningful subgoal; leaf of planning. Tagged with capability type (`gui`, `tool`, `mcp`, `api`)
- Tree built upfront in single planning LLM call; replan from current state on failure
- Planner reads SKILL.md files to understand available capabilities when decomposing
- Output format: structured tool call (`create_plan`) returning JSON tree with capability type per ATOM
- Replanner receives: current state + remaining subgoals + summaries of last few completed/failed nodes

**Capability Registry via SKILL.md**
- Main agent reads SKILL.md files from `nanobot/skills/` to understand available capabilities
- Each SKILL.md declares: name, description, type (gui/tool/mcp/api), and trigger patterns
- GUI capabilities come from opengui's SkillLibrary (searched at execution time)
- Non-GUI capabilities come from nanobot's existing tool registry and MCP servers

**Main-Agent Router**
- Walks AND/OR/ATOM tree; dispatches each ATOM by capability type:
  - `gui` -> spawn GuiAgent.run(instruction) via existing SubagentManager
  - `tool` -> invoke nanobot tool from ToolRegistry
  - `mcp` -> call MCP server tool
  - `api` -> direct API call
- Handles AND/OR semantics (sequential/alternative)
- On failure: triggers replanning with current state

**GuiAgent Simplified Role**
- GuiAgent.run() receives a SINGLE focused instruction (one ATOM)
- On entry: search skill library for matching skill
- If match above threshold -> attempt skill execution (with recovery)
- If no match or below threshold -> free exploration via `_run_once()` step loop
- Returns AgentResult for the single instruction
- NO internal planner, NO tree executor

**Skill-vs-Explore Strategy**
- Fixed score threshold (configurable, default 0.6)
- Match score = search_relevance * confidence
- Single best match per instruction (no ranked fallback)
- Parameter pre-filling at match time from instruction

**Skill Execution (Fast-Path)**
- Fixed-parameter steps (`fixed=true`): bypass LLM entirely, execute directly
- Pre-filled text params execute without LLM grounding
- Dynamic coord params (`{{coord}}`): LLM grounds at execution time
- Partial skill execution: sequential valid_state scan to find resume point

**Skill Failure & Recovery**
- valid_state check fails: spawn recovery ReAct agent, max 3 steps (separate budget)
- If recovery calls `done`: skip re-checking, continue skill
- If recovery exhausts: fall back to ReAct with full instruction
- After skill completes all steps: fall back to ReAct mode with history

**Skill Confidence & Lifecycle**
- Add `success_streak`, `failure_streak` fields to Skill dataclass
- Confidence = success_count / (success_count + failure_count); default 1.0 for new
- Confidence multiplied into match score: `final_score = search_relevance * confidence`
- Discard rule: after min 5 total attempts, if confidence < 0.3, remove from library
- Post-run maintenance pass: update confidence, discard low-confidence, check merge

**Skill Data Model Changes**
- Add `fixed: bool` and `fixed_values: dict[str, Any]` to SkillStep
- Fixed steps store concrete values; dynamic steps use placeholders

**Memory Prompt Injection**
- Memory entries injected as `<memory>` section in system prompt (via `build_system_prompt()`)
- All 4 types ranked by relevance, top-K overall (default K=5, configurable)
- Exception: POLICY entries always included regardless of relevance score
- Retrieval once at start of GuiAgent.run()
- Memory is read-only during runs

**Memory Format Migration (JSON to Markdown)**
- Replace MemoryStore internals: read/write .md files instead of JSON
- One .md file per memory type: `os_guide.md`, `app_guide.md`, `icon_guide.md`, `policy.md`
- Each H2 section = one retrievable MemoryEntry
- Same public API (add, get, list); H2 chunking layer converts markdown sections to MemoryEntry objects
- Existing Phase 1 tests updated to use .md format

**Step Budget**
- GuiAgent: configurable max_steps (default 15) for received instruction
- Recovery steps: separate budget (3 steps, not counted against main pool)
- When pool exhausts: fail with partial result

**Optional Components**
- TrajectoryRecorder: REQUIRED parameter on GuiAgent
- Memory retriever: optional
- Skill library: optional
- EmbeddingProvider: shared instance, passed externally
- All new components passed as individual constructor params

**Module Organization**
- NO new `opengui/planner.py` or `opengui/tree_executor.py`
- New `nanobot/agent/planner.py`: TaskPlanner
- New `nanobot/agent/router.py`: TreeRouter

**Integration Test (TEST-05)**
- Full flow at main-agent level: TaskPlanner decomposes -> Router dispatches -> GuiAgent handles GUI ATOMs
- Pre-seeded memory (app_guide for Settings) + pre-seeded skill (toggle Wi-Fi)
- Mock LLM returns AND tree with 2 ATOMs: one gui (skill-matched), one tool (non-GUI)
- Second test covers recovery path

### Claude's Discretion
- Parameter pre-fill: combined with planning call or separate extraction call
- Placeholder format for dynamic params (recommend `{{param}}`)
- Exact prompt wording for system prompt memory section
- Internal tree serialization format for trajectory events
- Exact confidence decay formula details
- Recovery agent prompt design
- Router implementation details (sync vs async dispatch, error propagation)

### Deferred Ideas (OUT OF SCOPE)
- Multi-dimensional memory scoring (relevance + freshness + utility + confidence)
- Multi-bucket skill library (primary, inter-task, candidate, micro)
- Per-subgoal memory retrieval
- CapabilityProvider protocol (typed interface for capability registration)
- Planner as a shared library (extracting from nanobot for other claws)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AGENT-04 | GuiAgent.run() integrates memory retrieval into system prompt | `build_system_prompt()` already accepts `memory_context` param; memory injection is a call to `MemoryRetriever.search()` at run start + format into the existing `memory_context` slot |
| AGENT-05 | GuiAgent.run() integrates skill search -> execute matched skill or free explore | `SkillLibrary.search()` + `SkillExecutor.execute()` both exist; integration requires wiring the search-then-execute-or-explore branching in `run()` with confidence threshold gating |
| AGENT-06 | GuiAgent.run() records trajectory via TrajectoryRecorder | `TrajectoryRecorder` is fully implemented with `start()`, `record_step()`, `set_phase()`, `finish()`; integration wires these calls into `_run_once()` at the correct points |
| MEM-05 | Memory context formatted and injected into system prompt | `build_system_prompt()` already has `memory_context: str | None` parameter; requires updating `_build_messages()` to pass retrieved memory text + migrating MemoryStore to markdown format |
| SKILL-08 | Skill execution integrated into agent loop (search -> match -> execute) | SkillExecutor exists but is not called from GuiAgent; requires adding search->threshold->execute->fallback branching at start of `_run_once()`, plus adding `fixed`/`fixed_values` fields to SkillStep |
| TRAJ-03 | Trajectory recording integrated into agent loop | TrajectoryRecorder exists but is not called from GuiAgent; requires adding `recorder.start()` before the step loop and `recorder.record_step()` inside each step iteration |
| TEST-05 | Integration test: full agent loop with DryRunBackend + mock LLM + memory + skills | The test orchestrates TaskPlanner (nanobot) -> Router -> GuiAgent (opengui) end-to-end using the established `_FakeEmbedder` + `_ScriptedLLM` patterns from Phase 1 |
</phase_requirements>

---

## Summary

Phase 2 wires together three independently-tested subsystems (memory retrieval, skill execution, trajectory recording) into `GuiAgent.run()`, and adds a new `TaskPlanner` + `TreeRouter` at the nanobot main-agent level. The core challenge is architectural integration, not building new algorithms — all the pieces exist and are tested individually.

The opengui side is straightforward: `GuiAgent.run()` gains three responsibilities at entry: retrieve memory context, search skill library, choose execution mode (skill or free explore). The `build_system_prompt()` function already has a `memory_context` slot; it just needs to be filled. `TrajectoryRecorder` has the full API (`start/record_step/set_phase/finish`) and only needs to be instantiated and called at the right points. `SkillExecutor` needs two new fields (`fixed`, `fixed_values`) on `SkillStep`, and skill confidence tracking (`success_streak`, `failure_streak`) on `Skill`.

The nanobot side is the larger new surface: `nanobot/agent/planner.py` implements a single-call LLM decomposition into a typed AND/OR/ATOM JSON tree, reading SKILL.md files for context. `nanobot/agent/router.py` walks the tree and dispatches each ATOM to the right executor (existing `ToolRegistry`, MCP wrapper, or a new `GuiSubagentExecutor` thin wrapper). The existing `SubagentManager` spawns background tasks — the router needs a synchronous (awaitable) variant for inline dispatch that returns the result before moving to the next ATOM.

The most subtle piece is the memory store migration from JSON to markdown with H2 chunking. The existing `MemoryStore` public API (add/get/list_all) must remain unchanged so that Phase 1 tests continue to pass after the format migration.

**Primary recommendation:** Structure the work in three waves: (1) data model changes + MemoryStore markdown migration; (2) GuiAgent wiring (memory injection, skill execution, trajectory recording); (3) nanobot planner + router + integration test.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest / pytest-asyncio | 9.0.2 / 1.3.0 (installed) | Test runner; async test support | Already in dev deps; `asyncio_mode = "auto"` in pyproject.toml |
| faiss-cpu + numpy | installed | FAISS hybrid search | Already in production deps (added in Phase 1) |
| Python dataclasses (frozen) | stdlib | Data containers | Project pattern: all data objects are frozen dataclasses |
| Python typing.Protocol | stdlib | Interface definitions | Project pattern: LLMProvider, DeviceBackend, EmbeddingProvider |
| json (stdlib) | stdlib | Planner output serialization (JSON tree) | Consistent with existing JSONL trajectory format |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| re (stdlib) | stdlib | Markdown H2 section parsing in MemoryStore | Markdown-to-entry chunking layer |
| asyncio (stdlib) | stdlib | Async task coordination in Router | TreeRouter await chains |
| loguru | installed | Logging in nanobot modules | Already used in SubagentManager |
| logging (stdlib) | stdlib | Logging in opengui modules | Already used in executor.py, library.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON tree for planner output | Pydantic models | JSON is simpler, avoids new dependency, consistent with existing JSONL patterns |
| Inline recovery agent in GuiAgent | Separate RecoveryAgent class | Inline keeps opengui surface small; recovery is a bounded mini-loop, not a new abstraction |
| Markdown H2 chunking for memory | SQLite per-entry | SQLite deferred to v2 per REQUIREMENTS.md; markdown is human-readable and debuggable |

---

## Architecture Patterns

### Recommended Module Structure
```
opengui/
├── agent.py           # GuiAgent — add trajectory_recorder, memory_retriever, skill_library params
├── memory/
│   ├── store.py       # REWRITE internals: JSON -> markdown H2 files; same public API
│   └── ...
└── skills/
    └── data.py        # ADD fixed, fixed_values to SkillStep; ADD success_streak, failure_streak to Skill

nanobot/
└── agent/
    ├── planner.py     # NEW: TaskPlanner (AND/OR/ATOM tree via LLM tool call)
    └── router.py      # NEW: TreeRouter (walk tree, dispatch ATOMs by capability type)
```

### Pattern 1: Memory Injection into System Prompt

`build_system_prompt()` already accepts `memory_context: str | None`. The injection point is `_build_messages()` in `agent.py`. At the start of `run()`, call `MemoryRetriever.search(instruction)`, always include POLICY entries, format the result, and pass to `build_system_prompt()`.

**Critical detail:** POLICY entries bypass the relevance threshold — they must always be included. Implement this as a pre-filter: collect all POLICY entries first, then fill remaining K slots with top-ranked non-POLICY results.

```python
# In GuiAgent.run(), before the step loop:
if self._memory_retriever is not None:
    ranked = await self._memory_retriever.search(instruction, top_k=self._memory_top_k)
    # Always include POLICY entries regardless of score
    from opengui.memory.types import MemoryType
    policies = [
        (e, s) for e, s in ranked if e.memory_type == MemoryType.POLICY
    ]
    others = [
        (e, s) for e, s in ranked if e.memory_type != MemoryType.POLICY
    ][:self._memory_top_k]
    memory_entries = policies + others
    memory_context = self._memory_retriever.format_context(memory_entries)
else:
    memory_context = None
# Pass to _build_messages() which feeds build_system_prompt(memory_context=...)
```

### Pattern 2: MemoryStore Markdown Migration

Replace the single `memory.json` file with per-type `.md` files. Each H2 section is one MemoryEntry. The H2 heading is the topic; metadata appears as key: value lines immediately after the heading; content follows.

```markdown
## Settings app navigation guide
platform: android
app: com.android.settings
tags: navigation, settings

Tap the gear icon in the app drawer to open Settings. Use the search bar
at the top to find specific options quickly.
```

The chunking layer parses each `## ` heading as an entry boundary, extracts metadata lines (lines matching `key: value` before any blank line), and treats the remainder as `content`. The `entry_id` is derived from a deterministic hash of the heading + type.

**Key concern for backward compatibility:** Phase 1 tests create MemoryEntry objects and call `store.add()` / `store.get()` / `store.list_all()`. These tests must remain green after the migration. The public API must not change — only the internals (file format and `load()` / `save()` methods).

**Migration approach:** Keep `MemoryStore.__init__()` signature identical. Change `_path` from `memory.json` to four `.md` files. The `save()` method rewrites the relevant `.md` file when an entry changes. `load()` parses all four `.md` files on startup.

### Pattern 3: SkillStep and Skill Data Model Extension

`SkillStep` and `Skill` are frozen dataclasses. Adding new fields requires `field(default=...)` to preserve backward compatibility with existing `from_dict()` data.

```python
# SkillStep additions:
fixed: bool = False
fixed_values: dict[str, Any] = field(default_factory=dict)

# Skill additions (success_count already exists):
success_streak: int = 0
failure_streak: int = 0
```

`SkillStep` is currently `frozen=True` — however `fixed_values` is a mutable dict, which violates frozen semantics. Two options: (a) make it `tuple[tuple[str, Any], ...]` and convert on access, or (b) switch `SkillStep` from `frozen=True` to a regular dataclass with `eq=True`. Given project convention favors frozen, use `tuple` storage internally and expose a property:

```python
_fixed_values_tuple: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

@property
def fixed_values(self) -> dict[str, Any]:
    return dict(self._fixed_values_tuple)
```

Alternatively (simpler), store as `fixed_values: dict[str, Any]` but use `field(default_factory=dict, hash=False, compare=False)` to avoid hash issues with mutable defaults in frozen dataclasses. Python frozen dataclasses will raise `TypeError: unhashable type: 'dict'` if `fixed_values` is included in the hash. The clean fix is to exclude it from hash/compare:

```python
# Note: using dataclasses.field with hash=False on frozen dataclass works
# because frozen=True only adds __setattr__/__delattr__, not __hash__ control
# for fields with hash=False
fixed_values: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
```

### Pattern 4: Skill-Gated Execution in GuiAgent._run_once()

The skill search and execution path wraps the existing `_run_once()` loop. The outer `run()` method becomes the skill-decision layer; `_run_once()` is called for free exploration OR for post-skill ReAct fallback.

```python
async def run(self, instruction: str, ...) -> AgentResult:
    # 1. Start trajectory recorder
    self._recorder.start()

    # 2. Retrieve memory context (once)
    memory_context = await self._retrieve_memory(instruction)

    # 3. Search skill library
    skill_match = None
    if self._skill_library is not None:
        results = await self._skill_library.search(instruction, top_k=1)
        if results:
            skill, relevance = results[0]
            confidence = _compute_confidence(skill)
            final_score = relevance * confidence
            if final_score >= self._skill_threshold:
                skill_match = (skill, final_score)

    # 4. Execute: skill path or free explore
    if skill_match is not None:
        result = await self._run_skill_path(instruction, skill_match[0], memory_context)
    else:
        result = await self._run_once(instruction, memory_context=memory_context, ...)

    # 5. Post-run: update skill confidence, run maintenance
    await self._post_run_maintenance(skill_match, result)

    self._recorder.finish(success=result.success)
    return result
```

### Pattern 5: TaskPlanner (nanobot/agent/planner.py)

The TaskPlanner makes a single LLM call with a `create_plan` tool that returns a JSON tree. It reads available SKILL.md summaries to inform the LLM about available capabilities.

```python
_CREATE_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": "Decompose a task into an AND/OR/ATOM execution tree.",
        "parameters": {
            "type": "object",
            "properties": {
                "tree": {
                    "type": "object",
                    "description": "Root node of the plan tree. Each node has 'type' (and/or/atom), 'children' (for and/or), 'instruction' (for atom), 'capability' (for atom: gui/tool/mcp/api)."
                }
            },
            "required": ["tree"]
        }
    }
}
```

Example output for "Turn on Wi-Fi AND check weather":
```json
{
  "type": "and",
  "children": [
    {"type": "atom", "instruction": "Turn on Wi-Fi in Settings", "capability": "gui"},
    {"type": "atom", "instruction": "Check current weather", "capability": "tool"}
  ]
}
```

The planner system prompt includes a summarized SKILL.md registry (using the existing `SkillsLoader.build_skills_summary()` XML format) so the LLM knows what capabilities are available.

### Pattern 6: TreeRouter (nanobot/agent/router.py)

The TreeRouter is a recursive tree walker. AND nodes iterate children sequentially (fail-fast on any child failure unless replanning succeeds). OR nodes iterate children until one succeeds.

```python
class TreeRouter:
    async def execute(self, node: dict, context: RouterContext) -> NodeResult:
        node_type = node["type"]
        if node_type == "atom":
            return await self._dispatch_atom(node, context)
        elif node_type == "and":
            return await self._execute_and(node, context)
        elif node_type == "or":
            return await self._execute_or(node, context)
        raise ValueError(f"Unknown node type: {node_type}")

    async def _dispatch_atom(self, node: dict, context: RouterContext) -> NodeResult:
        capability = node.get("capability", "tool")
        instruction = node["instruction"]
        if capability == "gui":
            return await self._run_gui_atom(instruction, context)
        elif capability == "tool":
            return await self._run_tool_atom(instruction, context)
        elif capability == "mcp":
            return await self._run_mcp_atom(instruction, context)
        # api: direct call (future)
        raise ValueError(f"Unknown capability: {capability}")
```

**Critical design point for `gui` dispatch:** The existing `SubagentManager.spawn()` is fire-and-forget (returns a task ID, result arrives via message bus). The Router needs a synchronous-await variant. Two options:
1. Create `SubagentManager.run_inline()` that awaits the agent result directly
2. Create a thin `GuiAgentRunner` that the Router instantiates and calls directly

Option 2 is cleaner for the integration test and avoids coupling the Router to the message bus. The Router can create a `GuiAgent` instance and call `await gui_agent.run(instruction)` directly. The `GuiAgent` is constructed by the caller (AgentLoop) with the right backend and LLM, then passed to the Router.

### Pattern 7: Partial Skill Execution (Resume Point Detection)

The resume-point algorithm scans skill steps from the last to the first, asking the state validator "is valid_state[i] true right now?" The first step whose valid_state is true is the last-completed step; execution starts from step i+1.

```python
async def _find_resume_step(self, skill: Skill, screenshot: Path) -> int:
    """Return the index of the first step NOT yet completed (0 = start from beginning)."""
    # Scan backwards: find deepest valid state
    for i in range(len(skill.steps) - 1, -1, -1):
        step = skill.steps[i]
        if step.valid_state and await self._validator.validate(step.valid_state, screenshot):
            return i + 1  # Start from the next step
    return 0  # No state matched, start from beginning
```

This is only called when the user explicitly enables partial execution. The default path always starts from step 0.

### Anti-Patterns to Avoid

- **Passing EmbeddingProvider through GuiAgent:** EmbeddingProvider is shared between MemoryRetriever and SkillLibrary. The caller creates it and passes both retriever and library as constructed objects. GuiAgent should NOT manage or construct EmbeddingProvider.
- **Duplicating the planner in opengui:** The CONTEXT.md explicitly prohibits this. opengui is a dumb executor of ATOM instructions.
- **Using SubagentManager.spawn() in TreeRouter:** spawn() is async fire-and-forget via the message bus. TreeRouter needs awaitable inline execution. Use `GuiAgent.run()` directly.
- **Storing mutable dicts in frozen dataclasses without `hash=False`:** Will cause `TypeError` at runtime when the dataclass tries to hash itself. Use `field(hash=False, compare=False)` on mutable fields.
- **Including POLICY entries in the K-cap:** POLICY entries are always included, outside the top-K limit. They add to the context, they don't displace non-POLICY entries.
- **Post-run maintenance inside `_run_once()`:** Confidence updates must happen post-run, not during. The post-run pass (update, discard, check merge) runs on the SkillLibrary after AgentResult is returned.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| BM25 search for skill matching | Custom BM25 | `opengui.memory.retrieval._BM25Index` (already used in SkillLibrary) | Already implemented, tested, CJK-aware |
| FAISS vector search | Custom cosine sim | `opengui.memory.retrieval._FaissIndex` (already used in SkillLibrary) | Project decision: no pure-Python fallback |
| LLM state validation | Custom screen parser | `LLMStateValidator` in `opengui/skills/executor.py` | Already implemented with fail-open semantics |
| Tool call response parsing | Custom JSON extractor | Existing tool call parsing in nanobot's AgentLoop | Already handles malformed responses |
| Markdown YAML frontmatter parsing | Custom YAML | `nanobot/agent/skills.py:SkillsLoader._strip_frontmatter()` pattern | Already implemented, simple regex approach |
| Skill deduplication | Custom similarity check | `SkillLibrary.add_or_merge()` | Already implemented with multi-factor scoring |

---

## Common Pitfalls

### Pitfall 1: Frozen Dataclass + Mutable Default
**What goes wrong:** Adding `fixed_values: dict[str, Any] = field(default_factory=dict)` to a `frozen=True` dataclass causes `TypeError: unhashable type: 'dict'` when the dataclass is used as a dict key or in a set.
**Why it happens:** Python frozen dataclasses generate `__hash__` from all fields by default. Mutable dicts are unhashable.
**How to avoid:** Use `field(default_factory=dict, hash=False, compare=False)` on mutable fields in frozen dataclasses.
**Warning signs:** `TypeError: unhashable type: 'dict'` during test collection or when SkillStep objects are stored in sets/dict keys.

### Pitfall 2: POLICY Memory Entries Displaced by K-Cap
**What goes wrong:** Retriever returns top-5 entries, none of which are POLICY because they scored below other entries. Safety rules are silently omitted.
**Why it happens:** The retriever applies a uniform K-cap across all entry types.
**How to avoid:** Retrieve POLICY entries separately (filter by type), always include them, then fill remaining K slots with top-ranked non-POLICY entries. The integration test should assert that POLICY entries appear in the system prompt regardless of relevance score.
**Warning signs:** Tests pass but POLICY entries are missing from system prompts in edge cases.

### Pitfall 3: Markdown H2 Chunking Breaks Existing Tests
**What goes wrong:** Phase 1 memory tests create MemoryEntry objects and call `store.add()`. After migration, if the markdown parser or writer has a bug, `store.get(entry_id)` returns None.
**Why it happens:** The H2 chunking relies on deterministic entry_id derivation from heading text. If the writer produces slightly different heading format than the parser expects, roundtrip fails.
**How to avoid:** Use the MemoryEntry's `entry_id` field as an explicit metadata line in the markdown file (e.g., `id: {entry_id}`). Don't derive IDs from heading text — store them explicitly. Update Phase 1 tests to verify roundtrip with markdown format.
**Warning signs:** `test_store_get_after_reload` fails after format migration.

### Pitfall 4: GuiAgent Gets TrajectoryRecorder but Recorder Not Started
**What goes wrong:** `recorder.record_step()` is called before `recorder.start()`. This raises `RuntimeError: Recorder not started; call start() first`.
**Why it happens:** `start()` must be called to create the JSONL file. If `run()` is called without starting the recorder, all step recordings fail.
**How to avoid:** Call `recorder.start()` as the very first action in `GuiAgent.run()` before any step logic. Document this as a precondition. In the integration test, assert that the trajectory file exists after run.
**Warning signs:** `RuntimeError: Recorder not started` in any test that calls `GuiAgent.run()`.

### Pitfall 5: TreeRouter GUI Dispatch Creates a New GuiAgent Every Call
**What goes wrong:** Router creates a new `GuiAgent` per ATOM, each with its own `artifacts_root`. This is correct but means each ATOM gets a separate trace directory. The integration test must assert the correct trace path.
**Why it happens:** GuiAgent uses `_make_run_dir()` with a timestamp-based name. Multiple ATOMs in the same plan produce multiple trace dirs.
**How to avoid:** This is intentional — each ATOM is an independent GUI session. The Router collects trace paths from each AgentResult and includes them in the overall plan result. Tests should not assume a single trace dir.
**Warning signs:** Integration test looking for a single trace file when multiple exist.

### Pitfall 6: Confidence Score for New Skills Is 0 (Not 1.0)
**What goes wrong:** `confidence = success_count / (success_count + failure_count)` evaluates to `0 / 0 = ZeroDivisionError` for a new skill with zero attempts.
**Why it happens:** Default values for `success_count` and `failure_count` are both 0.
**How to avoid:** Add a guard: `confidence = success_count / (success_count + failure_count) if (success_count + failure_count) > 0 else 1.0`. New skills default to full confidence (1.0) so they are always tried at least once.
**Warning signs:** `ZeroDivisionError` during skill score computation, or new skills never being matched.

### Pitfall 7: Recovery Agent Uses Same Budget as Main Run
**What goes wrong:** If the recovery agent's 3 steps are counted against the main `max_steps` pool, the main run exhausts early.
**Why it happens:** Sharing the step counter between main loop and recovery mini-loop.
**How to avoid:** The recovery agent has its own `max_steps=3` counter, completely separate from the main agent's pool. The recovery agent is a separate `_run_once()` invocation (or mini-loop) with its own step counter.
**Warning signs:** Integration tests showing the main agent exhausting steps too early when recovery is triggered.

---

## Code Examples

### SkillStep with Fixed/Dynamic Fields
```python
# Source: opengui/skills/data.py (to be modified)
@dataclass(frozen=True)
class SkillStep:
    action_type: str
    target: str
    parameters: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
    expected_state: str | None = None
    valid_state: str | None = None
    # Phase 2 additions:
    fixed: bool = False
    fixed_values: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
```

### Skill with Confidence Fields
```python
# Source: opengui/skills/data.py (to be modified)
@dataclass(frozen=True)
class Skill:
    # ... existing fields ...
    success_count: int = 0
    failure_count: int = 0
    # Phase 2 additions:
    success_streak: int = 0
    failure_streak: int = 0

def compute_confidence(skill: Skill) -> float:
    total = skill.success_count + skill.failure_count
    return skill.success_count / total if total > 0 else 1.0
```

### MemoryStore Markdown Format (one entry)
```markdown
## Settings app navigation guide
id: e1a2b3c4-d5e6-f7a8-b9c0-d1e2f3a4b5c6
type: app
platform: android
app: com.android.settings
tags: navigation,settings

Tap the gear icon in the app drawer to open Settings. Use the search bar
at the top to find specific options quickly.
```

### TaskPlanner Tool Definition
```python
# Source: nanobot/agent/planner.py (new file)
_CREATE_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": (
            "Decompose a user task into an AND/OR/ATOM execution tree. "
            "AND nodes execute all children sequentially. "
            "OR nodes try children until one succeeds. "
            "ATOM nodes are leaf tasks with a capability type."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tree": {"type": "object"}
            },
            "required": ["tree"],
        },
    },
}
```

### GuiAgent Constructor Extension
```python
# Source: opengui/agent.py (to be modified)
def __init__(
    self,
    llm: LLMProvider,
    backend: DeviceBackend,
    trajectory_recorder: TrajectoryRecorder,           # REQUIRED (Phase 2)
    memory_retriever: MemoryRetriever | None = None,   # optional
    skill_library: SkillLibrary | None = None,         # optional
    memory_top_k: int = 5,                             # configurable
    skill_threshold: float = 0.6,                      # configurable
    model: str = "",
    # ... existing params ...
) -> None:
```

### Integration Test Skeleton
```python
# Source: tests/test_opengui_p2_integration.py (new file)
import pytest
from opengui.backends.dry_run import DryRunBackend
from opengui.trajectory.recorder import TrajectoryRecorder
from opengui.memory.store import MemoryStore
from opengui.memory.retrieval import MemoryRetriever
from opengui.skills.library import SkillLibrary

@pytest.mark.asyncio
async def test_full_agent_loop_with_skill_match(tmp_path):
    # Pre-seed: memory entry for Settings
    store = MemoryStore(tmp_path / "memory")
    # ... add app_guide entry ...

    # Pre-seed: skill for Wi-Fi toggle
    lib = SkillLibrary(tmp_path / "skills")
    # ... add wifi skill ...

    # Mock LLM: scripted responses for skill steps
    llm = _ScriptedLLM(...)
    embedder = _FakeEmbedder()
    recorder = TrajectoryRecorder(output_dir=tmp_path / "traj", task="Turn on Wi-Fi")
    retriever = MemoryRetriever(embedding_provider=embedder)
    await retriever.index(store.list_all())

    agent = GuiAgent(
        llm=llm,
        backend=DryRunBackend(),
        trajectory_recorder=recorder,
        memory_retriever=retriever,
        skill_library=lib,
    )
    result = await agent.run("Turn on Wi-Fi")

    assert result.success
    # Memory appears in LLM calls
    assert any("<memory>" in str(call) for call in llm.calls)
    # Trajectory file exists with steps
    assert recorder.path.exists()
    lines = [json.loads(l) for l in recorder.path.read_text().splitlines()]
    assert lines[0]["type"] == "metadata"
    assert any(l["type"] == "step" for l in lines)
    assert lines[-1]["type"] == "result"
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| JSON-based MemoryStore (per REQUIREMENTS.md MEM-02) | Markdown H2 file per type | Phase 2 (this phase) | Human-readable, git-diffable memory files |
| No planner (direct task execution) | AND/OR/ATOM tree planner at main-agent level | Phase 2 (this phase) | Mixed-modality task decomposition |
| GuiAgent handles complex tasks end-to-end | GuiAgent handles single ATOM instruction | Phase 2 (this phase) | Simpler opengui, more composable nanobot |
| No confidence tracking on skills | success/failure counts + streaks | Phase 2 (this phase) | Skills below 0.3 confidence are auto-discarded |

**Note:** The Phase 1 memory tests (`test_opengui_p1_memory.py`) test against the JSON-based `MemoryStore`. These tests MUST be updated as part of the markdown migration. The Phase 1 test suite is the primary regression check for the migration's backward compatibility.

---

## Open Questions

1. **How does the TaskPlanner handle tasks that cannot be decomposed?**
   - What we know: Simple tasks (single intent, single capability) should return a single-ATOM tree with no AND/OR wrapping.
   - What's unclear: Should the planner always wrap in an AND node for uniformity, or can it return a bare ATOM node?
   - Recommendation: Allow bare ATOM at root level. The Router handles ATOM as a valid root. This avoids unnecessary nesting for simple tasks.

2. **Should `GuiAgent.run()` still accept `max_retries`?**
   - What we know: The current `run()` has `max_retries: int = 3` for automatic retry on failure. Phase 2 simplifies GuiAgent to handle a single ATOM.
   - What's unclear: With the Router managing retries at the plan level (replanning on failure), internal GuiAgent retries may be redundant.
   - Recommendation: Keep `max_retries` but default to 1 for ATOM-level invocation. The Router does outer-level replanning; GuiAgent does inner-level step retries. Both serve different failure modes.

3. **Trajectory tree events: should ATOM boundaries be recorded?**
   - What we know: TrajectoryRecorder already has `phase_change` events. The Router executes multiple ATOMs sequentially.
   - What's unclear: Should the trajectory file record ATOM start/end events alongside step events for the multi-ATOM integration test?
   - Recommendation: Add `atom_start` and `atom_end` event types to the recorder for TRAJ-03. This makes the full plan visible in a single trajectory. Each GuiAgent instance records its own trace, and the Router records ATOM boundaries in a top-level plan trace.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `uv run pytest tests/test_opengui_p2_integration.py -x -q` |
| Full suite command | `uv run pytest tests/ -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AGENT-04 | Memory entries appear in system prompt when GuiAgent.run() is called | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_memory_injected_into_system_prompt -x` | No — Wave 0 |
| AGENT-05 | Matching skill is executed before free exploration; no-match falls through to explore | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_skill_path_chosen_above_threshold -x` | No — Wave 0 |
| AGENT-06 | Every agent run produces a JSONL trajectory file with metadata/step/result events | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_trajectory_recorded_on_run -x` | No — Wave 0 |
| MEM-05 | Memory context formatted and injected; POLICY entries always present | unit | `uv run pytest tests/test_opengui_p2_memory.py::test_policy_always_included -x` | No — Wave 0 |
| SKILL-08 | Skill execution integrated: search->match->execute with confidence score gating | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_skill_execution_fast_path -x` | No — Wave 0 |
| TRAJ-03 | Trajectory JSONL has one step entry per vision-action step | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_trajectory_step_count -x` | No — Wave 0 |
| TEST-05 | Full flow with DryRunBackend + mock LLM + pre-seeded memory + skill runs to completion | integration | `uv run pytest tests/test_opengui_p2_integration.py -x` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui.py tests/test_opengui_p1_memory.py tests/test_opengui_p1_skills.py tests/test_opengui_p1_trajectory.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p2_integration.py` — covers AGENT-04, AGENT-05, AGENT-06, SKILL-08, TRAJ-03, TEST-05
- [ ] `tests/test_opengui_p2_memory.py` — covers MEM-05 (markdown migration + POLICY always-include)
- [ ] `tests/test_opengui_p1_memory.py` — UPDATE existing tests to pass with markdown MemoryStore

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — `opengui/agent.py`, `opengui/skills/data.py`, `opengui/skills/executor.py`, `opengui/skills/library.py`, `opengui/memory/store.py`, `opengui/memory/retrieval.py`, `opengui/trajectory/recorder.py`, `opengui/prompts/system.py`
- Direct codebase inspection — `nanobot/agent/subagent.py`, `nanobot/agent/tools/registry.py`, `nanobot/agent/tools/base.py`, `nanobot/agent/skills.py`, `nanobot/agent/tools/mcp.py`
- Direct codebase inspection — `tests/test_opengui.py`, `tests/test_opengui_p1_memory.py`, `tests/test_opengui_p1_skills.py`, `tests/test_opengui_p1_trajectory.py`
- Direct codebase inspection — `pyproject.toml` (dependencies, pytest config)
- `.planning/phases/02-agent-loop-integration/02-CONTEXT.md` — locked decisions

### Secondary (MEDIUM confidence)
- Phase 1 RESEARCH.md — established test patterns (`_FakeEmbedder`, `_ScriptedLLM`)
- KnowAct paper patterns (referenced in CONTEXT.md `<specifics>`) — `fixed_values` dict pattern, `success_streak`/`failure_streak` confidence tracking

### Tertiary (LOW confidence)
- None — all findings based on direct code inspection

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries directly inspected in installed codebase
- Architecture: HIGH — integration points verified against actual function signatures and class definitions
- Pitfalls: HIGH — derived from concrete code observations (frozen dataclass mutable fields, TrajectoryRecorder lifecycle contract, retriever K-cap behavior)

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable codebase; re-verify if major refactors occur)
