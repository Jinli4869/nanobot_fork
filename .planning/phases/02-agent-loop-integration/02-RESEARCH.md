# Phase 2: Agent Loop Integration - Research

**Researched:** 2026-03-17
**Domain:** Python async agent architecture — subgoal planning, skill dispatch, memory injection, trajectory recording
**Confidence:** HIGH

## Summary

Phase 2 wires together all the subsystems built in Phase 0/1 into a cohesive agent loop. GuiAgent.run() currently runs a flat step loop in `_run_once()`. This phase replaces that with a planning + tree-execution architecture: `TaskPlanner` decomposes the task into an AND/OR/ATOM subgoal tree, then `TreeExecutor` walks the tree dispatching each AtomNode to either SkillExecutor (fast-path) or the existing step loop (free-explore). Memory context is injected at run start, trajectory is recorded end-to-end, and skill confidence is updated post-run.

The implementation is predominantly a refactor/extension of existing code. All the heavy lifting — BM25+FAISS retrieval, skill execution with valid_state checking, trajectory recording, and prompt building — already exists and is tested. The new code is primarily the orchestration layer: planner dataclasses, tree executor dispatch logic, and the confidence update pass. Two new files (`opengui/planner.py`, `opengui/tree_executor.py`) plus targeted edits to `agent.py`, `skills/data.py`, `memory/store.py`, and `prompts/system.py`.

The integration test (TEST-05) is the most complex deliverable: it requires a mock LLM that returns different responses depending on call context (planning vs execution), pre-seeded memory + skill library, and assertion on trajectory events plus side-effect verification (confidence updates).

**Primary recommendation:** Build in wave order — (1) data model additions + MemoryStore migration, (2) planner dataclasses + TaskPlanner, (3) TreeExecutor + GuiAgent.run() wiring, (4) post-run maintenance pass, (5) integration tests.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Subgoal Decomposition (AND/OR/ATOM Tree)**
- LLM planner decomposes every task into an AND/OR/ATOM tree before execution
- AND node: all children execute sequentially; replan if any child fails
- OR node: try children until one succeeds; replan if all fail
- ATOM node: smallest meaningful subgoal; leaf of planning
- Tree built upfront in a single planning LLM call; replan from current screen state on AND-child failure or all-OR-children failure
- Each node's instruction adapted by LLM using original task + retrieved memory context
- Replanner receives: current screenshot + remaining subgoals + summaries of last few completed/failed nodes

**Planner Design**
- Same LLMProvider instance as executor (no separate model)
- Planner sees: initial screenshot + task description + memory context
- Output format: structured tool call (`create_plan`) returning JSON tree matching the dataclass hierarchy
- Parameter pre-filling combined with planning call (Claude's discretion on whether one or two calls)

**Skill-vs-Explore Strategy**
- Always search skill library first for every AtomNode
- Fixed score threshold (configurable, e.g., 0.6) — above threshold = attempt skill; below = free explore
- Match score = search_relevance * confidence
- Single best match per subgoal (no ranked fallback)
- Parameter pre-filling at match time: LLM extracts parameter values from subgoal instruction

**Skill Execution (Fast-Path)**
- Fixed-parameter steps (`fixed=true`): bypass LLM entirely; only LLM for valid_state verification before each step
- Pre-filled text params (`{{text}}`): execute without LLM grounding
- Dynamic coord params (`{{coord}}`): LLM grounds at execution time
- Partial skill execution: sequential scan of valid_states via LLM to find last "true" one; start execution from next step
- Placeholder format: `{{param}}`

**Skill Failure & Recovery**
- valid_state check fails → spawn recovery ReAct agent with NO history, instruction = unmatched valid_state description, max 3 steps
- If recovery calls `done`: skip re-checking, execute current skill step, continue remaining steps
- If recovery exhausts 3 steps: fall back to ReAct agent with full subgoal instruction
- After skill completes: fall back to ReAct mode with history; agent uses `done` to signal subgoal completion

**Free Exploration**
- No skill match (below threshold): free exploration bounded by subgoal instruction
- Agent calls `done` to signal subgoal completion
- Uses shared step pool

**Skill Confidence & Lifecycle**
- Add `success_streak`, `failure_streak` fields to Skill dataclass (plus existing `success_count`, `failure_count`)
- Confidence = success_count / (success_count + failure_count); default 1.0 for new skills
- Match score = search_relevance * confidence
- Confidence persisted to skill library at end of run
- Discard rule: after min 5 total attempts, if confidence < 0.3, remove skill from library
- Merge on update: check merge opportunities during post-run maintenance
- Post-run maintenance: (1) update confidence, (2) discard low-confidence skills, (3) check merge

**Skill Data Model Changes**
- Add `fixed: bool` and `fixed_values: dict[str, Any]` fields to SkillStep
- Fixed steps store concrete values (e.g., `point_fixed: "423,600"`)
- Dynamic steps use placeholders
- Coordinates stored as [0,999] relative

**Memory Prompt Injection**
- Memory entries injected as `<memory>` section in system prompt via `build_system_prompt()`
- All 4 types ranked by relevance; top-K overall
- POLICY entries always included regardless of relevance score
- K is configurable (default 5), passed as parameter to GuiAgent
- Retrieval once at run start using full task string
- Memory read-only during runs

**Memory Format Migration (JSON to Markdown)**
- Replace MemoryStore internals to read/write .md files
- One .md file per memory type: `os_guide.md`, `app_guide.md`, `icon_guide.md`, `policy.md`
- Each H2 section = one retrievable MemoryEntry
- Same public API (add, get, list); H2 chunking layer converts markdown sections to MemoryEntry objects
- Existing Phase 1 tests updated to use .md format
- Keep simple relevance ranking (BM25 + FAISS hybrid)

**Step Budget**
- Shared step pool across all subgoals (configurable max_steps, default 15)
- Recovery steps have separate budget (3 steps, not counted against main pool)
- Pool exhaustion mid-tree: fail with partial result (AgentResult showing completed subgoals)
- No replanning on pool exhaustion

**Optional Components**
- TrajectoryRecorder: REQUIRED parameter on GuiAgent
- MemoryRetriever: optional (skip memory injection if None)
- SkillLibrary: optional (always free explore if None)
- EmbeddingProvider: shared instance created by caller, passed externally

**Module Organization**
- New `opengui/planner.py`: SubgoalNode, AndNode, OrNode, AtomNode dataclasses + TaskPlanner
- New `opengui/tree_executor.py`: TreeExecutor (walks nodes, dispatches to skill/free-explore)
- `opengui/agent.py`: GuiAgent.run() uses TaskPlanner + TreeExecutor; `_run_once()` replaced by tree-based execution
- Tree executor replaces flat step loop; old step loop becomes the free-explore path for a single AtomNode

**Integration Test (TEST-05)**
- Full flow scenario: pre-seeded memory (app_guide for Settings) + pre-seeded skill (toggle Wi-Fi) + task "Turn on Wi-Fi"
- Mock LLM returns AND tree with 2 subgoals: one free-explore, one skill-matched
- Assertions: trajectory records both phases, memory appears in system prompt, skill confidence updated
- Second test covering recovery path: skill step valid_state fails → recovery agent → resume skill

### Claude's Discretion
- Parameter pre-fill: combined with planning call or separate extraction call
- Placeholder format for dynamic params (recommend `{{param}}`)
- Exact prompt wording for system prompt memory section
- Internal tree serialization format for trajectory events
- Exact confidence decay formula details
- Recovery agent prompt design

### Deferred Ideas (OUT OF SCOPE)
- Multi-dimensional memory scoring (relevance + freshness + utility + confidence) — defer to v2
- Multi-bucket skill library (primary, inter-task, candidate, micro) — keep single bucket
- Per-subgoal memory retrieval — defer, using task-level retrieval
- TaskPlanner as a protocol — defer, keep internal
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AGENT-04 | GuiAgent.run() integrates memory retrieval into system prompt | `build_system_prompt()` already accepts `memory_context` param; need to wire `MemoryRetriever.search()` + `format_context()` into `_build_messages()` before step loop |
| AGENT-05 | GuiAgent.run() integrates skill search → execute matched skill or free explore | New `TreeExecutor` dispatches per-AtomNode; `SkillLibrary.search()` already works; need score-threshold dispatch + SkillExecutor wiring |
| AGENT-06 | GuiAgent.run() records trajectory via TrajectoryRecorder | `TrajectoryRecorder` fully implemented; need `recorder.start()` at run start, `record_step()` per step, `recorder.finish()` at end |
| MEM-05 | Memory context formatted and injected into system prompt | `MemoryRetriever.format_context()` already exists; `build_system_prompt(memory_context=...)` already accepts the string; need to pass retrieved context into `_build_messages()` |
| SKILL-08 | Skill execution integrated into agent loop (search → match → execute) | `SkillExecutor.execute()` ready; new threshold-based dispatch in `TreeExecutor._execute_atom()` |
| TRAJ-03 | Trajectory recording integrated into agent loop | `TrajectoryRecorder` fully implemented with `ExecutionPhase` enum; need to inject recorder into agent and call from every step path |
| TEST-05 | Integration test: full agent loop with DryRunBackend + mock LLM + memory + skills | Established patterns: `_FakeEmbedder`, `_ScriptedLLM`; mock LLM needs context-sensitive responses for plan call vs execution steps |
</phase_requirements>

---

## Standard Stack

### Core (already in project, no new installs)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `dataclasses` | 3.12 | SubgoalNode tree, AtomNode, AndNode, OrNode | Existing pattern — all data containers are frozen dataclasses |
| `asyncio` | stdlib | Async execution flow in TreeExecutor | Entire codebase is async-first |
| `faiss-cpu` | 1.9.x | FAISS vector search (already in deps) | Required, no pure-Python fallback |
| `numpy` | 2.x | Embedding arrays (already in deps) | Required for FAISS |
| `pytest` + `pytest-asyncio` | 9.x / latest | Test framework (existing) | `asyncio_mode = "auto"` already configured |

### New Files to Create
| File | Purpose |
|---------|---------|
| `opengui/planner.py` | `SubgoalNode`, `AndNode`, `OrNode`, `AtomNode` dataclasses + `TaskPlanner` class |
| `opengui/tree_executor.py` | `TreeExecutor`: walks subgoal tree, dispatches ATOM → skill or free-explore |
| `tests/test_opengui_p2_integration.py` | TEST-05 integration test |

### Files to Modify
| File | Changes |
|---------|---------|
| `opengui/skills/data.py` | Add `fixed: bool`, `fixed_values: dict[str, Any]`, `success_streak: int`, `failure_streak: int` to `SkillStep` / `Skill` |
| `opengui/memory/store.py` | Internal rewrite: JSON → markdown .md files with H2 chunking; same public API |
| `opengui/agent.py` | Add `trajectory_recorder`, `memory_retriever`, `skill_library`, `memory_top_k` constructor params; replace `_run_once()` with tree-based `_plan_and_execute()` |
| `opengui/prompts/system.py` | `build_system_prompt()` already has `memory_context` param; verify `<memory>` XML tag is used (currently uses `# Relevant Knowledge` heading — may need to rename) |
| `tests/test_opengui_p1_memory.py` | Update to use .md format after MemoryStore migration |

**No new pip installs required.** All dependencies already present.

---

## Architecture Patterns

### Subgoal Tree Dataclasses

```python
# opengui/planner.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Union

SubgoalNode = Union["AndNode", "OrNode", "AtomNode"]

@dataclass(frozen=True)
class AtomNode:
    """Leaf node — smallest meaningful subgoal (one skill or free-explore)."""
    instruction: str
    node_id: str = ""

@dataclass(frozen=True)
class AndNode:
    """All children must succeed in sequence."""
    children: tuple[SubgoalNode, ...]
    node_id: str = ""

@dataclass(frozen=True)
class OrNode:
    """Try children in order until one succeeds."""
    children: tuple[SubgoalNode, ...]
    node_id: str = ""
```

The tree is returned from the LLM as a JSON tool call result and deserialized into these dataclasses. Planning uses the existing `create_plan` tool name pattern.

### TaskPlanner

```python
# opengui/planner.py
class TaskPlanner:
    """Calls LLM once to decompose task into SubgoalNode tree.

    Also pre-fills parameter values for matched skills at planning time
    (either in the same call or a second targeted call — Claude's discretion).
    """

    def __init__(self, llm: LLMProvider) -> None: ...

    async def plan(
        self,
        task: str,
        initial_screenshot: Path,
        memory_context: str,
    ) -> SubgoalNode: ...
```

The planner tool schema defines a `create_plan` function with a `tree` JSON parameter. The LLM must return exactly this tool call. The planner validates and deserializes the response.

### TreeExecutor

```python
# opengui/tree_executor.py
@dataclass
class TreeExecutor:
    """Walks a SubgoalNode tree, dispatching leaves to skill or free-explore."""

    llm: LLMProvider
    backend: DeviceBackend
    recorder: TrajectoryRecorder
    skill_library: SkillLibrary | None = None
    skill_threshold: float = 0.6
    max_recovery_steps: int = 3

    # Shared step pool (mutable counter)
    _steps_remaining: int = field(default=15, init=False)

    async def execute(self, node: SubgoalNode, ...) -> NodeResult: ...
    async def _execute_and(self, node: AndNode, ...) -> NodeResult: ...
    async def _execute_or(self, node: OrNode, ...) -> NodeResult: ...
    async def _execute_atom(self, node: AtomNode, ...) -> NodeResult: ...
    async def _free_explore(self, instruction: str, ...) -> NodeResult: ...
    async def _execute_with_skill(self, skill: Skill, params: dict, ...) -> NodeResult: ...
    async def _recovery_agent(self, valid_state_desc: str, ...) -> bool: ...
```

`_execute_atom()` calls `skill_library.search(node.instruction)`, multiplies top result score by `skill.confidence`, and dispatches based on threshold. The existing `_run_once()` step loop refactors into `_free_explore()`.

### GuiAgent Constructor Additions

```python
# opengui/agent.py — __init__ signature change
def __init__(
    self,
    llm: LLMProvider,
    backend: DeviceBackend,
    trajectory_recorder: TrajectoryRecorder,         # REQUIRED (new)
    memory_retriever: MemoryRetriever | None = None,  # optional
    skill_library: SkillLibrary | None = None,        # optional
    memory_top_k: int = 5,                            # optional
    skill_threshold: float = 0.6,                    # optional
    model: str = "",
    artifacts_root: Path | str = ".opengui/runs",
    max_steps: int = 15,
    step_timeout: float = 30.0,
    history_image_window: int = 4,
    include_date_context: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> None: ...
```

`GuiAgent.run()` becomes the thin outer wrapper: retrieve memory context once, call `TaskPlanner.plan()`, call `TreeExecutor.execute()`, run post-run maintenance pass, return `AgentResult`.

### Memory Format — H2 Markdown Chunking

```
# os_guide.md
## Navigate to Settings on Android
platform: android
app: com.android.settings

Tap the Settings icon on the home screen or pull down the notification shade and tap the gear icon.
```

The H2 chunking layer parses this into individual `MemoryEntry` objects. Each H2 heading becomes the entry topic, metadata lines are parsed as key=value, remaining lines are the content body. The `MemoryStore` public API (add, get, list_all) stays identical — only the persistence layer changes.

**Key parsing invariant:** An H2 section heading is the `entry_id` source (slugified). If `entry_id:` metadata line exists, use that; otherwise derive from the H2 heading text.

### Memory System Prompt Integration

`build_system_prompt()` already supports `memory_context` parameter — currently renders as `# Relevant Knowledge` section. The CONTEXT.md specifies a `<memory>` section tag. Decision: use `<memory>...</memory>` XML wrapper inside the `# Relevant Knowledge` section to match the locked decision while keeping the existing section structure.

The `_build_messages()` method in `GuiAgent` currently calls `build_system_prompt()` without `memory_context`. Add retrieved context as parameter here.

### Post-Run Maintenance Pass

After `TreeExecutor.execute()` returns, GuiAgent runs maintenance on each skill that was attempted during the run:

```python
# In GuiAgent._post_run_maintenance()
for skill_id, outcome in run_skill_outcomes.items():
    skill = self.skill_library.get(skill_id)
    updated = _update_confidence(skill, outcome.success)
    # Discard rule: min 5 attempts, confidence < 0.3
    total = updated.success_count + updated.failure_count
    if total >= 5 and _confidence(updated) < 0.3:
        self.skill_library.remove(skill_id)
    else:
        self.skill_library._upsert(updated)
# Persist changes
self.skill_library._save_platform_app(...)
```

Confidence formula: `success_count / (success_count + failure_count)`. Streaks are tracked but the exact decay formula is at Claude's discretion. Recommended: streaks used only for momentum display, not for confidence calculation itself (keep confidence pure ratio for simplicity).

### Integration Test Structure (TEST-05)

```python
# tests/test_opengui_p2_integration.py

class _ContextAwareLLM:
    """Mock LLM that returns different responses based on call context.

    - First call (no tool calls in history, system prompt contains 'create_plan'):
      return the plan tree tool call
    - Subsequent calls: return scripted computer_use tool calls
    """
    ...

@pytest.mark.asyncio
async def test_full_agent_loop_with_memory_and_skill(tmp_path: Path) -> None:
    # Pre-seed memory
    store = MemoryStore(tmp_path / "memory")
    store.add(MemoryEntry(..., memory_type=MemoryType.APP_GUIDE, ...))

    # Pre-seed skill library
    lib = SkillLibrary(store_dir=tmp_path / "skills")
    lib.add(Skill(name="toggle wifi", ...))

    # Wire agent
    recorder = TrajectoryRecorder(output_dir=tmp_path / "traj", task="Turn on Wi-Fi")
    agent = GuiAgent(
        llm=_ContextAwareLLM(...),
        backend=DryRunBackend(),
        trajectory_recorder=recorder,
        memory_retriever=MemoryRetriever(embedding_provider=_FakeEmbedder()),
        skill_library=lib,
    )

    result = await agent.run("Turn on Wi-Fi")

    # Assert trajectory has both AGENT and SKILL phases
    # Assert memory appears in system prompt
    # Assert skill confidence updated
    assert result.success
```

The key challenge: the mock LLM must distinguish planning calls from execution calls. Use system prompt content inspection (planning call has `create_plan` tool in tools list).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Hybrid search for skill matching | Custom similarity | `SkillLibrary.search()` (already exists) | BM25+FAISS already implemented and tested |
| Memory retrieval | Custom text matching | `MemoryRetriever.search()` + `format_context()` (already exists) | Hybrid search + POLICY pinning needed |
| Step execution on device | Custom action dispatch | `DeviceBackend.execute()` + `SkillExecutor.execute()` (already exist) | Both fully tested |
| Trajectory file writing | Custom JSONL writer | `TrajectoryRecorder` (already exists) | Phase/step/metadata/result events all handled |
| LLM state validation | Custom screenshot comparison | `LLMStateValidator` (already exists in executor.py) | Already handles multimodal + JSON parsing |
| Markdown H2 parsing | Custom regex | Python `re` with `^## ` pattern + `str.split()` | No external library needed; keep it simple |

**Key insight:** 90% of the building blocks are done. Phase 2 is an orchestration layer, not a new capability layer.

---

## Common Pitfalls

### Pitfall 1: Frozen Dataclass Mutation for Confidence Updates
**What goes wrong:** `Skill` is a frozen dataclass. Calling `skill.success_count += 1` raises `FrozenInstanceError`.
**Why it happens:** The `frozen=True` design is used throughout for immutability safety.
**How to avoid:** Use `dataclasses.replace(skill, success_count=skill.success_count + 1)` to create updated copies. Collect all updates during the run and apply in the post-run maintenance pass.
**Warning signs:** Any code that tries to mutate skill fields inline.

### Pitfall 2: MemoryStore Migration Breaks Existing Tests
**What goes wrong:** `test_opengui_p1_memory.py` tests JSON persistence; after migration to .md files, the tests fail because they check for `memory.json`.
**Why it happens:** Existing tests assert file paths and JSON format.
**How to avoid:** Update P1 memory tests together with the MemoryStore migration in the same wave. Do not migrate store without updating tests simultaneously.
**Warning signs:** Tests pass in isolation but fail after MemoryStore changes.

### Pitfall 3: Planning LLM Call Mixed with Step Loop
**What goes wrong:** Using the same `_ScriptedLLM` response queue for both the planning call and execution step calls causes the wrong responses to be consumed.
**Why it happens:** `_ScriptedLLM` pops responses in order; planning tool call has different schema than `computer_use` tool calls.
**How to avoid:** Integration test mock LLM must inspect `tools` parameter to distinguish plan calls (tools contains `create_plan`) from step calls (tools contains `computer_use`). Use `_ContextAwareLLM` pattern with separate response queues.
**Warning signs:** Integration test fails with "no tool calls" or wrong tool name.

### Pitfall 4: Step Pool Shared State in Async Code
**What goes wrong:** `TreeExecutor._steps_remaining` counter is mutated across multiple async calls. If any future implementation uses `asyncio.gather()` for concurrent subgoal execution, this races.
**Why it happens:** Phase 2 uses sequential execution (AND nodes run sequentially), so this won't race. But the counter must be passed correctly through recursive `_execute_*` methods.
**How to avoid:** Keep the counter as a mutable instance variable on `TreeExecutor`. Do NOT use class-level or module-level state. Confirm AND/OR nodes are strictly sequential.
**Warning signs:** Step count is wrong (too high or too low) after multi-subgoal runs.

### Pitfall 5: Partial Skill Execution Starting Point
**What goes wrong:** The partial skill execution scan (find last valid_state = True to determine starting step) makes N LLM calls for an N-step skill, even when starting from step 0.
**Why it happens:** Scanning all valid_states sequentially before any execution starts.
**How to avoid:** The scan is only needed when the agent suspects it's mid-way through a skill (e.g., after recovery). For first execution, start from step 0. Only scan if the initial valid_state check fails.
**Warning signs:** Excessive LLM calls visible in mock LLM call count assertions.

### Pitfall 6: Recovery Agent History Contamination
**What goes wrong:** Recovery agent incorrectly receives history from the main run, causing it to attempt to continue incomplete actions.
**Why it happens:** Passing `history` list by reference into the recovery agent.
**How to avoid:** Recovery agent gets NO history (empty list), only the `valid_state` description as its instruction. Create a fresh `GuiAgent`-like step runner (or use `TreeExecutor._free_explore` with empty history and the valid_state description as instruction).
**Warning signs:** Recovery agent calls reference previous steps in its actions.

### Pitfall 7: `build_system_prompt()` Memory Section Tag
**What goes wrong:** CONTEXT.md specifies `<memory>` XML tag injection, but `build_system_prompt()` currently uses `# Relevant Knowledge` as the section heading without XML tags.
**Why it happens:** The existing stub already renders memory context but without the `<memory>` wrapper.
**How to avoid:** Wrap the formatted memory entries in `<memory>...</memory>` tags within the existing `# Relevant Knowledge` section. Or rename the section to `# Memory Context` and add the XML wrapper. Test that `"<memory>"` appears in the system prompt in the integration test.
**Warning signs:** Integration test assertion `assert "<memory>" in system_prompt` fails.

---

## Code Examples

### Confidence Calculation (Verified from CONTEXT.md)

```python
def _confidence(skill: Skill) -> float:
    """Return skill confidence in [0, 1]. Default 1.0 for new skills."""
    total = skill.success_count + skill.failure_count
    if total == 0:
        return 1.0
    return skill.success_count / total

def _should_discard(skill: Skill) -> bool:
    """Discard if >= 5 attempts and confidence < 0.3."""
    total = skill.success_count + skill.failure_count
    return total >= 5 and _confidence(skill) < 0.3
```

### Match Score with Confidence

```python
# In TreeExecutor._execute_atom()
async def _find_skill_match(
    self, instruction: str
) -> tuple[Skill, float] | None:
    if self.skill_library is None:
        return None
    results = await self.skill_library.search(instruction, top_k=1)
    if not results:
        return None
    skill, search_score = results[0]
    confidence = _confidence(skill)
    final_score = search_score * confidence
    if final_score >= self.skill_threshold:
        return skill, final_score
    return None
```

### MemoryStore H2 Chunking (Markdown Parser)

```python
# In opengui/memory/store.py (new internals)
import re

_H2_PATTERN = re.compile(r"^## (.+)$", re.MULTILINE)

def _parse_md_file(text: str, memory_type: MemoryType) -> list[MemoryEntry]:
    """Parse one .md file into MemoryEntry objects, one per H2 section."""
    sections = _H2_PATTERN.split(text)
    # sections[0] = text before first H2 (skip)
    # sections[1::2] = headings, sections[2::2] = bodies
    entries = []
    for heading, body in zip(sections[1::2], sections[2::2]):
        entry_id, platform, app, content = _parse_section(heading, body)
        entries.append(MemoryEntry(
            entry_id=entry_id,
            memory_type=memory_type,
            platform=platform,
            content=content.strip(),
            app=app,
        ))
    return entries
```

### TrajectoryRecorder Integration in Agent

```python
# In GuiAgent.run() (simplified)
async def run(self, task: str, ...) -> AgentResult:
    self.trajectory_recorder.start()
    try:
        # Retrieve memory once
        memory_entries = []
        if self.memory_retriever:
            await self.memory_retriever.index(self.memory_store.list_all())
            results = await self.memory_retriever.search(task, top_k=self.memory_top_k)
            memory_entries = results

        # Plan
        memory_context = self.memory_retriever.format_context(memory_entries) if memory_entries else ""
        initial_obs = await self.backend.observe(...)
        tree = await self._planner.plan(task, initial_obs.screenshot_path, memory_context)

        # Execute tree
        node_result = await self._tree_executor.execute(tree)

        # Post-run maintenance
        await self._post_run_maintenance()

        success = node_result.success
        self.trajectory_recorder.finish(success=success)
        return AgentResult(success=success, ...)
    except Exception as exc:
        self.trajectory_recorder.finish(success=False, error=str(exc))
        raise
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat max-step loop in `_run_once()` | AND/OR/ATOM tree with per-subgoal dispatch | Phase 2 | Structured task decomposition, partial completion possible |
| No memory injection | `<memory>` section in system prompt | Phase 2 | Agent uses retrieved knowledge context |
| Free-explore only | Skill-first with threshold fallback | Phase 2 | Fast-path execution reduces LLM calls for known tasks |
| JSON memory store | Markdown H2 chunked store | Phase 2 | Human-readable knowledge base, easier manual editing |
| No trajectory recorder integration | `TrajectoryRecorder` wired in | Phase 2 | End-to-end JSONL trajectory for every run |

**Existing patterns that don't change:**
- Protocol-based interfaces (LLMProvider, DeviceBackend, EmbeddingProvider) — unchanged
- Frozen dataclasses for data containers — unchanged
- Async-first design — unchanged
- [0,999] relative coordinates — unchanged
- `_FakeEmbedder` + `_ScriptedLLM` test helpers — reused in TEST-05

---

## Open Questions

1. **Combined vs separate planning + parameter-fill call**
   - What we know: CONTEXT.md says "Claude's discretion on whether one or two calls"
   - What's unclear: Combining saves one LLM call; separating is cleaner but adds latency
   - Recommendation: Combine into one planning call. The `create_plan` tool response can include a `param_bindings` field alongside the tree. Simpler and faster.

2. **Exact confidence streak formula**
   - What we know: `success_streak` and `failure_streak` fields are added; decay formula is "Claude's discretion"
   - What's unclear: Whether streaks affect confidence score or are just metadata
   - Recommendation: Keep streaks as metadata only (for future v2 use). Confidence remains `success_count / (success_count + failure_count)`. Do not complicate the formula in phase 2.

3. **Recovery agent implementation**
   - What we know: Separate budget (3 steps), no history, instruction = valid_state description
   - What's unclear: Whether to create a new `GuiAgent` instance or reuse `TreeExecutor._free_explore`
   - Recommendation: Reuse `TreeExecutor._free_explore()` with `max_steps=3` and no history. Avoid instantiating a new GuiAgent (circular complexity). Pass a recovery-specific trajectory phase (`ExecutionPhase.RECOVERY`).

4. **MemoryStore backward compatibility during migration**
   - What we know: P1 tests use JSON; migration rewrites persistence
   - What's unclear: Whether to keep JSON as a fallback for old stores
   - Recommendation: No backward compat. Clean cut to .md format. Update P1 tests in the same wave. The store_dir is new in tests (tmp_path), so no migration of real data needed.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| Quick run command | `uv run pytest tests/test_opengui_p2_integration.py -q` |
| Full suite command | `uv run pytest tests/test_opengui*.py -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AGENT-04 | Memory entries appear in system prompt when `memory_retriever` is set | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_full_agent_loop_with_memory_and_skill -x` | Wave 0 |
| AGENT-05 | SkillExecutor used when skill score >= threshold; free explore below threshold | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_skill_matched_subgoal -x` | Wave 0 |
| AGENT-06 | Every run produces JSONL with one entry per step | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_trajectory_recorded_per_step -x` | Wave 0 |
| MEM-05 | `<memory>` section in system prompt with POLICY always included | unit | `uv run pytest tests/test_opengui_p2_integration.py::test_memory_prompt_injection -x` | Wave 0 |
| SKILL-08 | Skill confidence updates post-run; discard rule applied | unit | `uv run pytest tests/test_opengui_p2_integration.py::test_skill_confidence_updated -x` | Wave 0 |
| TRAJ-03 | Phase transitions (AGENT→SKILL→RECOVERY) appear in trajectory | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_recovery_path -x` | Wave 0 |
| TEST-05 | Full integration: DryRunBackend + mock LLM + pre-seeded memory + skill | integration | `uv run pytest tests/test_opengui_p2_integration.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p2_integration.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui*.py -q`
- **Phase gate:** Full suite green (`uv run pytest tests/test_opengui*.py -q`) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p2_integration.py` — covers all Phase 2 requirements
- [ ] `tests/test_opengui_p2_planner.py` (optional separate file) — unit tests for `TaskPlanner` plan parsing

*(Framework and shared fixtures exist — no additional setup required)*

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection of `opengui/` module files — authoritative for all existing APIs
- `opengui/agent.py` — GuiAgent current structure, `_run_once()`, `_build_messages()`
- `opengui/skills/data.py` — Skill/SkillStep dataclass fields; existing `success_count`/`failure_count` already present, `success_streak`/`failure_streak` absent
- `opengui/skills/executor.py` — SkillExecutor.execute() API, LLMStateValidator, _ground_step
- `opengui/skills/library.py` — SkillLibrary.search() returns `list[tuple[Skill, float]]`
- `opengui/memory/retrieval.py` — MemoryRetriever.search() + format_context() API
- `opengui/memory/store.py` — Current JSON implementation to be replaced
- `opengui/prompts/system.py` — build_system_prompt() already accepts memory_context + skill_context params
- `opengui/trajectory/recorder.py` — TrajectoryRecorder API + ExecutionPhase enum
- `tests/test_opengui_p1_*.py` — Established _FakeEmbedder, _ScriptedLLM patterns
- `.planning/phases/02-agent-loop-integration/02-CONTEXT.md` — Locked design decisions

### Secondary (MEDIUM confidence)
- KnowAct paper patterns (referenced in CONTEXT.md specifics): `fixed_values` dict, `success_streak`/`failure_streak` tracking, parameter pre-filling from subgoal instruction

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies already installed and tested
- Architecture patterns: HIGH — derived from existing codebase and locked CONTEXT.md decisions
- Pitfalls: HIGH — derived from code inspection and async architecture analysis
- Integration test design: HIGH — established _FakeEmbedder/_ScriptedLLM patterns; only mock LLM context-sensitivity is MEDIUM (design choice)

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable codebase, no fast-moving external deps)
