---
phase: quick
plan: 260325-kgy
type: execute
wave: 1
depends_on: []
files_modified:
  - nanobot/agent/tools/gui.py
  - nanobot/agent/loop.py
  - nanobot/agent/planner.py
  - nanobot/agent/capabilities.py
  - opengui/agent.py
  - tests/test_gui_memory_split.py
autonomous: true
requirements: [gui-memory-split]

must_haves:
  truths:
    - "Planner receives os_guide, app_guide, and icon_guide memory content for task-aware planning"
    - "GUI agent system prompt receives full policy memory without search, injected as-is"
    - "GUI agent no longer receives os/app/icon guide entries via memory_context"
  artifacts:
    - path: "nanobot/agent/capabilities.py"
      provides: "PlanningContext extended with gui_memory_context field"
    - path: "nanobot/agent/planner.py"
      provides: "Planner system prompt injects gui memory context for task rewriting"
    - path: "nanobot/agent/loop.py"
      provides: "Agent loop loads opengui memory and passes guide entries to planner"
    - path: "nanobot/agent/tools/gui.py"
      provides: "GuiSubagentTool loads policy entries directly and passes to GuiAgent"
    - path: "opengui/agent.py"
      provides: "GuiAgent accepts policy_context parameter and injects into system prompt"
  key_links:
    - from: "nanobot/agent/loop.py"
      to: "nanobot/agent/planner.py"
      via: "PlanningContext.gui_memory_context"
      pattern: "gui_memory_context"
    - from: "nanobot/agent/tools/gui.py"
      to: "opengui/agent.py"
      via: "policy_context parameter on GuiAgent"
      pattern: "policy_context"
---

<objective>
Split GUI memory usage by type: feed os/app/icon guide entries into the planner's system prompt so it can rewrite and refine GUI task instructions with domain knowledge, while injecting all policy entries directly (full, non-search-based) into the GUI agent's system prompt.

Purpose: The planner needs device/app navigation knowledge to decompose and refine GUI tasks intelligently. The GUI agent needs policy rules (safety, forbidden actions) always present regardless of search relevance. Currently all memory types go through the same search-based retrieval path into the GUI agent, which means the planner is blind to guide knowledge and policy entries may be dropped if search scores are low.

Output: Modified planner, agent loop, gui tool, and gui agent with split memory paths.
</objective>

<execution_context>
@/Users/jinli/.claude/get-shit-done/workflows/execute-plan.md
@/Users/jinli/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@nanobot/agent/tools/gui.py
@nanobot/agent/loop.py
@nanobot/agent/planner.py
@nanobot/agent/capabilities.py
@opengui/agent.py
@opengui/prompts/system.py
@opengui/memory/store.py
@opengui/memory/types.py
@opengui/memory/retrieval.py
@nanobot/agent/planning_memory.py

<interfaces>
<!-- Key types and contracts the executor needs -->

From opengui/memory/types.py:
```python
class MemoryType(Enum):
    OS_GUIDE = "os"
    APP_GUIDE = "app"
    ICON_GUIDE = "icon"
    POLICY = "policy"

@dataclass(frozen=True)
class MemoryEntry:
    entry_id: str
    memory_type: MemoryType
    platform: str
    content: str
    app: str | None = None
    tags: tuple[str, ...] = ()
    created_at: float
    access_count: int = 0
```

From opengui/memory/store.py:
```python
class MemoryStore:
    def __init__(self, store_dir: Path | str) -> None: ...
    def list_all(self, *, memory_type: MemoryType | None = None, platform: str | None = None, app: str | None = None) -> list[MemoryEntry]: ...
```

From nanobot/agent/capabilities.py:
```python
@dataclass(frozen=True)
class PlanningContext:
    catalog: CapabilityCatalog
    memory_hints: tuple["PlanningMemoryHint", ...] = ()
```

From opengui/prompts/system.py:
```python
def build_system_prompt(
    *, platform: str = "unknown", coordinate_mode: str = "absolute",
    memory_context: str | None = None, skill_context: str | None = None,
    tool_definition: dict[str, Any] | None = None,
    installed_apps: list[str] | None = None,
) -> str: ...
```

From nanobot/agent/tools/gui.py:
```python
DEFAULT_OPENGUI_MEMORY_DIR = Path.home() / ".opengui" / "memory"

class GuiSubagentTool(Tool):
    async def _build_memory_retriever(self) -> Any | None: ...
    async def _run_task(self, active_backend, task, **kwargs) -> str: ...
```

From nanobot/agent/planner.py:
```python
class TaskPlanner:
    async def plan(self, task: str, *, context: str = "", planning_context: PlanningContext | None = None) -> PlanNode: ...
    def _build_system_prompt(self, *, planning_context: PlanningContext | None = None) -> str: ...
```

From opengui/agent.py (GuiAgent constructor, lines 140-171):
```python
class GuiAgent:
    def __init__(self, *, llm, backend, trajectory_recorder, model, artifacts_root,
                 max_steps=15, step_timeout=30.0, history_image_window=4,
                 include_date_context=True, progress_callback=None,
                 memory_retriever=None, skill_library=None, skill_executor=None,
                 memory_top_k=5, skill_threshold=0.6, installed_apps=None,
                 intervention_handler=None): ...
```

From nanobot/agent/loop.py (planning dispatch, lines 455-470):
```python
planner = TaskPlanner(llm=self.provider)
catalog = CapabilityCatalogBuilder().build(...)
memory_hints = PlanningMemoryHintExtractor(self.workspace).build(task=task, catalog=catalog)
planning_context = PlanningContext(catalog=catalog, memory_hints=memory_hints)
tree = await planner.plan(task, planning_context=planning_context)
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Extend PlanningContext and planner to accept GUI memory, change GUI tool to split memory by type</name>
  <files>
    nanobot/agent/capabilities.py
    nanobot/agent/planner.py
    nanobot/agent/loop.py
    nanobot/agent/tools/gui.py
    opengui/agent.py
    opengui/prompts/system.py
  </files>
  <action>
This task implements the full memory split in one coherent pass across all 6 files. The changes are tightly coupled (planner needs the context, loop builds it, gui tool changes what it passes to the agent), so they must land together.

**1. nanobot/agent/capabilities.py — Add gui_memory_context to PlanningContext:**

Add an optional `gui_memory_context: str = ""` field to the `PlanningContext` dataclass. This carries formatted os_guide + app_guide + icon_guide text for the planner.

```python
@dataclass(frozen=True)
class PlanningContext:
    catalog: CapabilityCatalog
    memory_hints: tuple["PlanningMemoryHint", ...] = ()
    gui_memory_context: str = ""   # <-- NEW: os/app/icon guide content for planner
```

**2. nanobot/agent/planner.py — Inject gui_memory_context into planner system prompt:**

In `_build_system_prompt()`, after the existing routing memory hints block (around line 300-310), add a new block that injects `gui_memory_context` when present:

```python
if planning_context is not None and planning_context.gui_memory_context:
    lines.extend([
        "",
        "Device and app knowledge (use this to refine GUI task instructions):",
        planning_context.gui_memory_context,
    ])
```

This goes BEFORE the "Call the create_plan tool" closing lines. The planner will see os/app/icon guide knowledge and can use it to write more specific ATOM instructions for gui tasks (e.g., knowing exact swipe gestures for a specific OS, or knowing how to navigate a specific Chinese app).

**3. nanobot/agent/loop.py — Build gui_memory_context from opengui MemoryStore:**

In the planning dispatch block (around line 455-470), after building `catalog` and `memory_hints`, add logic to load opengui guide memory:

```python
from opengui.memory.store import MemoryStore as GuiMemoryStore
from opengui.memory.types import MemoryType
from nanobot.agent.tools.gui import DEFAULT_OPENGUI_MEMORY_DIR

gui_memory_context = ""
try:
    gui_store = GuiMemoryStore(DEFAULT_OPENGUI_MEMORY_DIR)
    guide_entries = []
    for mt in (MemoryType.OS_GUIDE, MemoryType.APP_GUIDE, MemoryType.ICON_GUIDE):
        guide_entries.extend(gui_store.list_all(memory_type=mt))
    if guide_entries:
        lines = []
        for entry in guide_entries:
            tag = entry.memory_type.value.upper()
            prefix = f"[{tag}]"
            if entry.app:
                prefix += f" ({entry.app})"
            lines.append(f"- {prefix} {entry.content}")
        gui_memory_context = "\n".join(lines)
except Exception:
    logger.warning("Failed to load GUI memory for planner", exc_info=True)
```

Then pass it when creating PlanningContext:

```python
planning_context = PlanningContext(
    catalog=catalog,
    memory_hints=memory_hints,
    gui_memory_context=gui_memory_context,
)
```

IMPORTANT: Guard the import and store construction in try/except so that systems without opengui memory configured still work. Also guard with a check that DEFAULT_OPENGUI_MEMORY_DIR exists before constructing the store.

**4. nanobot/agent/tools/gui.py — Split memory: load policy separately, remove guide entries from retriever:**

Modify `_build_memory_retriever()` to ONLY index POLICY entries (not os/app/icon guide entries). The guide entries now go to the planner, not the GUI agent.

Replace the current `_build_memory_retriever` body:
```python
async def _build_memory_retriever(self) -> Any | None:
    """Build memory retriever indexed with policy entries only.

    Guide entries (os_guide, app_guide, icon_guide) are now consumed by
    the planner via PlanningContext.gui_memory_context instead.
    """
    if self._embedding_adapter is None:
        return None
    from opengui.memory.retrieval import MemoryRetriever
    from opengui.memory.store import MemoryStore
    from opengui.memory.types import MemoryType

    try:
        memory_store = MemoryStore(DEFAULT_OPENGUI_MEMORY_DIR)
        policy_entries = memory_store.list_all(memory_type=MemoryType.POLICY)
        if not policy_entries:
            return None
        memory_retriever = MemoryRetriever(embedding_provider=self._embedding_adapter, top_k=5)
        await memory_retriever.index(policy_entries)
        return memory_retriever
    except Exception:
        logger.warning(
            "GUI memory retriever initialization failed for %s",
            DEFAULT_OPENGUI_MEMORY_DIR,
            exc_info=True,
        )
        return None
```

Additionally, add a new method `_load_policy_context()` that loads ALL policy entries as raw text (no embedding search needed — policies are always fully included):

```python
def _load_policy_context(self) -> str | None:
    """Load all policy entries as raw text for direct system prompt injection."""
    from opengui.memory.store import MemoryStore
    from opengui.memory.types import MemoryType

    try:
        memory_store = MemoryStore(DEFAULT_OPENGUI_MEMORY_DIR)
        policy_entries = memory_store.list_all(memory_type=MemoryType.POLICY)
        if not policy_entries:
            return None
        lines = []
        for entry in policy_entries:
            lines.append(f"- {entry.content}")
        return "\n".join(lines)
    except Exception:
        logger.warning("Failed to load policy memory", exc_info=True)
        return None
```

In `_run_task()`, change how memory is passed to GuiAgent. Instead of passing `memory_retriever` (which would do search-based retrieval), pass the raw `policy_context` for direct injection:

```python
async def _run_task(self, active_backend: Any, task: str, **kwargs: Any) -> str:
    from opengui.agent import GuiAgent
    from opengui.trajectory.recorder import TrajectoryRecorder

    policy_context = self._load_policy_context()
    skill_library = self._get_skill_library(active_backend.platform)
    run_dir = self._make_run_dir()
    recorder = TrajectoryRecorder(
        output_dir=run_dir,
        task=task,
        platform=active_backend.platform,
    )
    agent = GuiAgent(
        llm=self._llm_adapter,
        backend=active_backend,
        trajectory_recorder=recorder,
        model=self._model,
        artifacts_root=run_dir,
        max_steps=self._gui_config.max_steps,
        policy_context=policy_context,        # NEW: direct policy injection
        skill_library=skill_library,
        skill_threshold=self._gui_config.skill_threshold,
        intervention_handler=self._build_intervention_handler(active_backend, task),
    )
    # ... rest unchanged
```

Remove `memory_retriever=memory_retriever` from GuiAgent constructor call. The `_build_memory_retriever()` method can be kept but is no longer called from `_run_task()`. If you want to be clean, remove the call entirely.

**5. opengui/agent.py — Accept policy_context and inject into system prompt:**

Add `policy_context: str | None = None` parameter to `GuiAgent.__init__()`. Store as `self._policy_context`.

In `_retrieve_memory()`, change behavior: if `self._policy_context` is not None, return it directly as the memory context without any search. If `self._memory_retriever` is still provided (backward compat), fall through to the existing search logic. But the primary path from nanobot now skips the retriever entirely:

```python
async def _retrieve_memory(self, task: str) -> str | None:
    """Return policy context (direct injection) or fall back to retriever search."""
    if self._policy_context is not None:
        self._log_policy_injection(self._policy_context)
        return self._policy_context
    # Existing retriever-based logic for backward compatibility (e.g., opengui CLI)
    if self._memory_retriever is None:
        return None
    # ... existing search code unchanged ...
```

Add a simple logging helper:
```python
def _log_policy_injection(self, context: str) -> None:
    line_count = context.count("\n") + 1
    logger.info("Policy context injected directly: %d line(s)", line_count)
    self._trajectory_recorder.record_event(
        "memory_retrieval",
        task="(policy_direct_injection)",
        hit_count=line_count,
        hits=[],
        context=context[:200],
    )
```

**6. opengui/prompts/system.py — No changes needed.** The `memory_context` parameter already handles the injection. Policy text flows through the existing `memory_context` pathway into `# Relevant Knowledge`.

**Key design decisions:**
- The opengui CLI (`opengui/cli.py`) path is NOT changed. It still uses `memory_retriever` with full search. This change only affects the nanobot pathway.
- `_build_memory_retriever()` is no longer called in `_run_task()`. The method is kept for potential future use or can be removed.
- Policy entries are loaded synchronously (no embedding needed), so no async overhead.
- Guide entry formatting for the planner uses the same `[TAG] (app) content` format as `MemoryRetriever.format_context()` for consistency.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "
from nanobot.agent.capabilities import PlanningContext, CapabilityCatalog
# Verify gui_memory_context field exists
pc = PlanningContext(catalog=CapabilityCatalog(), gui_memory_context='test')
assert pc.gui_memory_context == 'test'
print('PlanningContext: OK')
"</automated>
  </verify>
  <done>
    - PlanningContext has gui_memory_context field
    - Planner system prompt includes guide memory when gui_memory_context is non-empty
    - Agent loop loads os/app/icon guide entries from opengui MemoryStore and passes to PlanningContext
    - GuiSubagentTool loads policy entries directly (not search-based) and passes to GuiAgent via policy_context
    - GuiAgent injects policy_context into system prompt without embedding search
    - opengui CLI backward compatibility preserved (memory_retriever path unchanged)
  </done>
</task>

<task type="auto">
  <name>Task 2: Add regression tests for the memory split</name>
  <files>tests/test_gui_memory_split.py</files>
  <action>
Create `tests/test_gui_memory_split.py` with focused tests verifying the memory split behavior. Use the existing test patterns from `tests/test_opengui_p2_memory.py` and `tests/test_opengui_p21_planner_context.py`.

**Tests to write:**

1. `test_planning_context_gui_memory_context_field()` — Verify `PlanningContext` accepts and stores `gui_memory_context`.

2. `test_planner_system_prompt_includes_gui_memory()` — Instantiate `TaskPlanner` with a mock LLM, call `_build_system_prompt()` with a `PlanningContext` that has non-empty `gui_memory_context`. Assert the system prompt contains "Device and app knowledge" header and the guide content.

3. `test_planner_system_prompt_omits_gui_memory_when_empty()` — Same as above but with empty `gui_memory_context`. Assert "Device and app knowledge" is NOT in the prompt.

4. `test_gui_tool_load_policy_context()` — Test `_load_policy_context()` method on `GuiSubagentTool`. This requires creating a tmp dir with a policy.md file containing known entries, then monkeypatching `DEFAULT_OPENGUI_MEMORY_DIR` to point there. Verify the method returns formatted policy text.

5. `test_gui_agent_uses_policy_context_directly()` — Construct a `GuiAgent` with `policy_context="test policy"` and `memory_retriever=None`. Call `_retrieve_memory("any task")` and verify it returns `"test policy"` without any embedding call.

6. `test_gui_agent_falls_back_to_retriever_when_no_policy_context()` — Construct a `GuiAgent` with `policy_context=None` and a mock `memory_retriever`. Verify `_retrieve_memory()` calls the retriever's search method (backward compat for opengui CLI).

Use `pytest` with `tmp_path` fixture for file-based tests. Use `unittest.mock.AsyncMock` for async mocks. Keep tests focused and fast (no real embedding calls).
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -m pytest tests/test_gui_memory_split.py -x -v 2>&1 | tail -30</automated>
  </verify>
  <done>
    - All 6 tests pass
    - Tests cover: PlanningContext field, planner prompt injection, policy direct loading, GuiAgent policy path, backward compat fallback
    - No real embedding or LLM calls in tests
  </done>
</task>

</tasks>

<verification>
1. `python -c "from nanobot.agent.capabilities import PlanningContext; pc = PlanningContext(catalog=__import__('nanobot.agent.capabilities', fromlist=['CapabilityCatalog']).CapabilityCatalog(), gui_memory_context='x'); assert pc.gui_memory_context == 'x'"` passes
2. `python -m pytest tests/test_gui_memory_split.py -x -v` all pass
3. `python -m pytest tests/test_opengui_p21_planner_context.py -x -v` existing tests still pass (backward compat)
4. `python -m pytest tests/test_opengui_p2_memory.py -x -v` existing memory tests still pass
</verification>

<success_criteria>
- Planner receives os_guide, app_guide, icon_guide content and can use it to refine GUI task instructions
- GUI agent receives ALL policy entries directly in system prompt (no search-based filtering)
- GUI agent no longer receives os/app/icon guide entries (those go to planner only)
- opengui CLI path (direct GuiAgent usage without nanobot) continues to work via existing memory_retriever fallback
- All new and existing tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260325-kgy-gui-memory-os-app-icon-guide-planner-pla/260325-kgy-SUMMARY.md`
</output>
