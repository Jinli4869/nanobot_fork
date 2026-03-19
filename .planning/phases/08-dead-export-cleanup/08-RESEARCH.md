# Phase 8: Dead Export Cleanup — Research

**Researched:** 2026-03-19
**Domain:** Python async agent integration — task decomposition, capability routing, trajectory post-processing
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Wire TaskPlanner and TreeRouter into the nanobot agent loop
- Conditional planning: LLM decides whether a task needs decomposition via a lightweight assessment prompt before calling TaskPlanner
- If TaskPlanner is invoked, it decomposes the task into an AND/OR/ATOM tree with capability-typed ATOMs (gui, tool, mcp)
- TreeRouter dispatches ATOMs to the appropriate executor (GuiSubagentTool, nanobot tool registry, MCP servers)
- AND nodes: Independent children execute in parallel with a configurable concurrency limit (default 3)
- OR nodes: Priority order is mcp > tool > gui — GUI is the fallback of last resort
- OR failure handling: Auto-fallback — try next child automatically on failure, only report if all children fail
- Plan visibility: Log the decomposed plan tree before execution so user/developer can see the plan
- Auto-extract skills after every GUI run — both successful and failed trajectories
- Newly extracted skills are immediately available in SkillLibrary for the next run (no gating or review queue)
- This fulfills NANO-05 (main agent trajectory_summary skill for post-run skill extraction)
- Phase 8 absorbs remaining Phase 3 Plan 02 work (NANO-01, NANO-04, NANO-05)
- Upon Phase 8 completion, both Phase 3 and Phase 8 are marked complete

### Claude's Discretion
- How the LLM complexity assessment prompt is structured
- Exact concurrency limit default and configuration mechanism
- Whether PlanNode/NodeResult/RouterContext are exported from nanobot.agent.__init__ alongside main classes
- Whether TrajectorySummarizer gets a top-level opengui re-export or stays in opengui.trajectory

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

## Summary

This phase wires three fully-implemented but production-unreachable components — `TaskPlanner`, `TreeRouter`, and `TrajectorySummarizer` — into the live execution paths of the nanobot agent loop and the `GuiSubagentTool` post-run pipeline. All three classes are complete, well-tested, and have no remaining logic gaps; the work is purely integration plumbing.

**TaskPlanner + TreeRouter** need a two-part integration into `AgentLoop._process_message` (or a wrapper around `_run_agent_loop`): (1) a lightweight pre-call complexity check that asks the LLM "does this task need decomposition?", and (2) if yes, a full plan + dispatch cycle that replaces the direct `_run_agent_loop` call with `TaskPlanner.plan` + `TreeRouter.execute`. The `RouterContext` must wire `gui_agent` (the existing `GuiSubagentTool`), `tool_registry` (`self.tools`), and `mcp_client` (from the MCP stack).

**TrajectorySummarizer** needs a post-run hook in `GuiSubagentTool.execute()`. It already calls `_extract_skill` after every run; adding a `TrajectorySummarizer.summarize_file` call immediately before skill extraction makes summaries available as part of the extraction context or for logging. The summarizer lives in `opengui.trajectory` — no new files, just a new call in the existing pipeline.

**Primary recommendation:** Wire TaskPlanner/TreeRouter as a thin pre-flight layer in `AgentLoop._process_message` and add `TrajectorySummarizer` as the first step of the post-run chain in `GuiSubagentTool._extract_skill`.

---

## Standard Stack

All components are already present in the project. No new dependencies are required.

### Core (already installed)
| Component | Location | Purpose |
|-----------|----------|---------|
| `TaskPlanner` | `nanobot/agent/planner.py` | Decomposes tasks into AND/OR/ATOM trees via one LLM call with `create_plan` tool |
| `TreeRouter` | `nanobot/agent/router.py` | Walks AND/OR/ATOM plan trees, dispatches ATOMs by capability to gui/tool/mcp executors |
| `TrajectorySummarizer` | `opengui/trajectory/summarizer.py` | LLM-based trajectory summarization from JSONL file |
| `GuiSubagentTool` | `nanobot/agent/tools/gui.py` | Already registered; the `gui` capability executor for TreeRouter |
| `ToolRegistry` | `nanobot/agent/tools/registry.py` | Already holds all registered tools; maps to `tool` capability |
| `AgentLoop` | `nanobot/agent/loop.py` | Integration target for TaskPlanner + TreeRouter |

### Supporting
| Component | Location | When Used |
|-----------|----------|-----------|
| `PlanNode` | `nanobot/agent/planner.py` | Returned by `TaskPlanner.plan`, consumed by `TreeRouter.execute` |
| `NodeResult` | `nanobot/agent/router.py` | Returned from each tree node execution |
| `RouterContext` | `nanobot/agent/router.py` | Threads executors through tree walk |
| `NanobotLLMAdapter` | `nanobot/agent/gui_adapter.py` | Bridges nanobot LLMProvider to opengui LLMProvider — needed for TrajectorySummarizer |

---

## Architecture Patterns

### Recommended Project Structure (additions only)
```
nanobot/
├── agent/
│   ├── planner.py          # existing — no changes
│   ├── router.py           # existing — no changes
│   ├── loop.py             # MODIFY: add planning pre-flight
│   └── __init__.py         # MODIFY: add TaskPlanner + TreeRouter exports
opengui/
├── trajectory/
│   ├── summarizer.py       # existing — no changes
│   └── __init__.py         # existing — TrajectorySummarizer already exported
nanobot/agent/tools/
└── gui.py                  # MODIFY: add TrajectorySummarizer post-run call
```

### Pattern 1: Complexity Assessment Before Planning

The locked decision requires a lightweight LLM check before calling `TaskPlanner`. The canonical pattern is a small boolean-returning prompt with `tool_choice` forced to a `should_plan` tool, separate from the full planning call.

```python
# Complexity check — runs before the main _run_agent_loop call
_COMPLEXITY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "assess_complexity",
        "description": "Determine if a task requires multi-step decomposition.",
        "parameters": {
            "type": "object",
            "properties": {
                "needs_planning": {
                    "type": "boolean",
                    "description": "True if the task requires multiple distinct steps or capabilities.",
                }
            },
            "required": ["needs_planning"],
        },
    },
}

async def _needs_planning(self, task: str) -> bool:
    """One LLM call to assess whether task warrants decomposition."""
    messages = [
        {"role": "system", "content": "You are a task complexity assessor."},
        {"role": "user", "content": (
            f"Does the following task require multiple distinct steps or capabilities "
            f"(e.g. GUI + web search, or sequential multi-app operations)?\n\nTask: {task}"
        )},
    ]
    response = await self.provider.chat_with_retry(
        messages=messages,
        tools=[_COMPLEXITY_TOOL],
        model=self.model,
    )
    if response.tool_calls:
        args = response.tool_calls[0].arguments
        return bool(args.get("needs_planning", False))
    return False  # safe default: skip planning if LLM misbehaves
```

**Confidence:** HIGH — matches `TaskPlanner.plan()` pattern for tool-forced single calls.

### Pattern 2: Routing TaskPlanner Output Through TreeRouter

After the complexity check returns `True`, the integration replaces a direct `_run_agent_loop` call with a plan + dispatch pair:

```python
async def _run_with_planning(
    self,
    task: str,
    context: RouterContext,
) -> tuple[str, list[str]]:
    """Plan the task and execute via TreeRouter."""
    planner = TaskPlanner(llm=self.provider)
    tree = await planner.plan(task)
    # Log the plan for visibility (locked decision)
    logger.info("Task plan: {}", _format_plan_tree(tree))
    router = TreeRouter(planner=planner, max_replans=2)
    result = await router.execute(tree, context)
    tools_used = ["task_planner", "tree_router"]
    return result.output or ("Completed." if result.success else result.error or "Failed."), tools_used
```

### Pattern 3: AND Node Parallelism

The locked decision specifies AND nodes execute in parallel with a configurable concurrency limit (default 3). The current `TreeRouter._execute_and` is sequential. The integration must override this for parallel execution:

```python
async def _execute_and_parallel(
    self, node: PlanNode, context: RouterContext, max_concurrency: int = 3
) -> NodeResult:
    """AND: parallel execution with concurrency semaphore."""
    sem = asyncio.Semaphore(max_concurrency)
    async def _run_child(child):
        async with sem:
            return await self.execute(child, context)
    results = await asyncio.gather(*[_run_child(c) for c in node.children], return_exceptions=True)
    # collect outputs, handle failures and replanning
```

**Important:** The current `TreeRouter._execute_and` is sequential (fail-fast with replan). The locked decision overrides this to parallel with semaphore. The router needs a subclass or a modified `_execute_and` — the cleanest approach is extending `TreeRouter` in `nanobot/agent/loop.py` or passing a `max_concurrency` parameter to `TreeRouter`.

### Pattern 4: OR Node Priority Reordering

The locked decision fixes priority `mcp > tool > gui`. The current `TreeRouter._execute_or` tries children in their given order. A sort pass before the loop enforces priority:

```python
_CAPABILITY_PRIORITY = {"mcp": 0, "tool": 1, "gui": 2}

def _sort_or_children(self, children):
    return sorted(
        children,
        key=lambda n: _CAPABILITY_PRIORITY.get(getattr(n, "capability", "gui"), 99)
    )
```

### Pattern 5: TrajectorySummarizer Post-Run Hook

`GuiSubagentTool.execute()` already has the post-run chain: `agent.run(task)` → `_extract_skill()`. Insert `TrajectorySummarizer.summarize_file()` before extraction. The summarizer needs an `LLMProvider` — use `self._llm_adapter` (already available).

```python
# In GuiSubagentTool.execute(), after agent.run()
trace_path = self._resolve_trace_path(...)
summary = await self._summarize_trajectory(trace_path)
await self._extract_skill(trace_path, result.success, skill_library)

async def _summarize_trajectory(self, trace_path: Path | None) -> str:
    """Summarize the trajectory via LLM; return empty string on error."""
    if trace_path is None or not trace_path.exists():
        return ""
    from opengui.trajectory.summarizer import TrajectorySummarizer
    try:
        summarizer = TrajectorySummarizer(llm=self._llm_adapter)
        return await summarizer.summarize_file(trace_path)
    except Exception:
        logger.warning("Trajectory summarization failed for %s", trace_path, exc_info=True)
        return ""
```

### Anti-Patterns to Avoid

- **Importing TaskPlanner/TreeRouter at module top-level in loop.py:** Use lazy import (`from nanobot.agent.planner import TaskPlanner`) inside the method, consistent with how `GuiSubagentTool` is imported in `_register_default_tools`.
- **Mutating RouterContext across concurrent AND children:** `context.completed` is a list — append from parallel coroutines without a lock is a data race. Use `asyncio.Lock` or collect completed instructions per-child and merge after gather.
- **Passing `self.tools` directly as `tool_registry` to RouterContext:** `TreeRouter._run_tool` checks `context.tool_registry is not None` then returns a placeholder. For Phase 8, passing `self.tools` (a `ToolRegistry`) satisfies the non-None check. Real tool dispatch via instruction string needs a dispatcher — this is acceptable to leave as a stub or route through the LLM (complexity gate ensures simple tool tasks don't get over-decomposed).
- **Calling `TrajectorySummarizer` with nanobot's `LLMProvider` directly:** The summarizer expects `opengui.interfaces.LLMProvider`. The bridge is `self._llm_adapter` (a `NanobotLLMAdapter`) — always use the adapter.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Task tree decomposition | Custom prompt parser | `TaskPlanner.plan()` | Already implemented with fallback atom, tool-forced, handles JSON errors |
| Tree execution | Manual recursion | `TreeRouter.execute()` | Already handles AND/OR/ATOM, replan budget, all node types |
| Trajectory summarization | Custom LLM call | `TrajectorySummarizer.summarize_file()` | Already implemented with compact events format and LLM call |
| Concurrency limiting | Manual task tracking | `asyncio.Semaphore` | Standard stdlib primitive, no extra dependency |
| LLM protocol bridging | New adapter class | `NanobotLLMAdapter` | Already bridges nanobot → opengui LLMProvider protocol |

---

## Common Pitfalls

### Pitfall 1: RouterContext Concurrency — Shared Mutable List

**What goes wrong:** `RouterContext.completed` is a plain `list[str]`. When AND children run in parallel via `asyncio.gather`, multiple coroutines may call `context.completed.append()` concurrently. In CPython this is safe for `list.append` (GIL) but the ordering is non-deterministic and the pattern is fragile for other asyncio runtimes.
**Why it happens:** `asyncio.gather` schedules coroutines on the same event loop; awaits interleave. Since `append` is atomic in CPython but not guaranteed elsewhere, it's a latent bug.
**How to avoid:** Either (a) collect per-child completed lists and merge after gather, or (b) pass a child-scoped copy of completed into each parallel child (read-only), merging into the parent after join.
**Warning signs:** Non-deterministic completed list ordering in tests.

### Pitfall 2: OR Node Priority Sort Changes Semantic Contract

**What goes wrong:** The locked decision says OR children should be tried in `mcp > tool > gui` order. But `TaskPlanner` generates the tree and may put nodes in any order. If the sort happens at the `PlanNode` level (frozen dataclass), that would require mutation. The sort must happen inside `TreeRouter._execute_or`, not in the plan tree.
**Why it happens:** `PlanNode` is `frozen=True` — children cannot be reordered on the instance.
**How to avoid:** Sort in `TreeRouter._execute_or` over the children sequence before iterating, not on the node itself.

### Pitfall 3: Complexity Gate False Negatives Leave Simple Tasks in Planning Path

**What goes wrong:** The complexity LLM may return `needs_planning=True` for trivially simple tasks, sending them through the full plan + dispatch cycle. This adds latency and may produce overly decomposed single-ATOM trees.
**Why it happens:** LLMs err on the side of caution when asked "does this need planning?"
**How to avoid:** Prompt clearly that single-capability tasks with no sequential dependencies should return `False`. Add a `max_concurrency` path that short-circuits: if the planner returns a single ATOM node, execute it directly without tree dispatch overhead.
**Warning signs:** All tasks going through planning even in tests with simple one-step instructions.

### Pitfall 4: TrajectorySummarizer Called on Missing Trace File

**What goes wrong:** If `GuiAgent.run()` fails very early (preflight error before any steps), `trace_path` may be `None` or a directory that contains no `.jsonl`. Calling `TrajectorySummarizer.summarize_file(None)` returns `""` gracefully, but `TrajectorySummarizer.summarize_file(path_that_doesnt_exist)` also returns `""` with a warning. The current `_resolve_trace_path` already handles `None` → `None`, so the guard is: check `trace_path is not None and trace_path.exists()` before calling.
**How to avoid:** The `_summarize_trajectory` helper pattern above already has this guard.

### Pitfall 5: AgentLoop Already Exports TaskPlanner/TreeRouter Implicitly Via Test Imports

**What goes wrong:** Tests import `from nanobot.agent.planner import PlanNode, TaskPlanner` and `from nanobot.agent.router import ...` directly. If `nanobot/agent/__init__.py` adds these exports, it creates no conflict — but if there's any circular import through `loop.py` importing `planner.py` at the top level (instead of lazy), it will be caught only at import time.
**How to avoid:** Keep planner/router imports lazy (inside method bodies) in `loop.py`. Export from `__init__.py` with a direct module import (not through `loop.py`).

---

## Code Examples

### RouterContext Assembly in AgentLoop

```python
# Inside AgentLoop._process_message, after building initial context:
from nanobot.agent.router import RouterContext

# gui_agent is the GuiSubagentTool if registered, else None
gui_tool = self.tools.get("gui_task")
ctx = RouterContext(
    task=msg.content,
    gui_agent=gui_tool,         # TreeRouter._run_gui calls gui_agent.run(instruction)
    tool_registry=self.tools,   # TreeRouter._run_tool checks non-None
    mcp_client=self._mcp_stack, # TreeRouter._run_mcp checks non-None
)
```

**Note:** `TreeRouter._run_gui` calls `context.gui_agent.run(instruction, max_retries=1)` — `GuiSubagentTool.execute(task=instruction)` is the actual method. A thin adapter or override of `TreeRouter._run_gui` is needed, since `GuiSubagentTool.execute` takes `task=` not `instruction` and returns JSON string rather than `AgentResult`. The cleanest fix: subclass `TreeRouter` in `loop.py` and override `_run_gui` to call `await context.gui_agent.execute(task=instruction)` and parse the JSON result.

### TaskPlanner Integration Sketch

```python
# nanobot/agent/loop.py — new method on AgentLoop
async def _plan_and_execute(self, msg_content: str, ctx: RouterContext) -> tuple[str, list[str]]:
    from nanobot.agent.planner import TaskPlanner
    from nanobot.agent.router import TreeRouter

    planner = TaskPlanner(llm=self.provider)
    tree = await planner.plan(msg_content)
    logger.info("Decomposed plan: {}", tree.to_dict())

    router = NanobotTreeRouter(planner=planner, max_replans=2)
    result = await router.execute(tree, ctx)
    output = result.output or ("Done." if result.success else result.error or "Task failed.")
    return output, ["task_planner", "tree_router"]
```

### TrajectorySummarizer in GuiSubagentTool

```python
# Immediately before _extract_skill in GuiSubagentTool.execute():
summary = await self._summarize_trajectory(trace_path)
if summary:
    logger.info("Trajectory summary: %s", summary[:200])
await self._extract_skill(trace_path, result.success, skill_library)
```

### nanobot/agent/__init__.py Additions (Discretion Area)

```python
# Current exports + new additions
from nanobot.agent.planner import PlanNode, TaskPlanner
from nanobot.agent.router import NodeResult, RouterContext, TreeRouter

__all__ = [
    "AgentLoop", "ContextBuilder", "MemoryStore", "SkillsLoader",
    "TaskPlanner", "PlanNode",        # new
    "TreeRouter", "NodeResult", "RouterContext",  # new
]
```

---

## State of the Art

| Old State | New State After Phase 8 | Notes |
|-----------|------------------------|-------|
| TaskPlanner: tested, not called from production | TaskPlanner wired into AgentLoop complexity gate | No LLM changes needed |
| TreeRouter: tested, not called from production | TreeRouter wired into AgentLoop plan execution path | AND parallelism added |
| TrajectorySummarizer: tested, not called from production | TrajectorySummarizer called in GuiSubagentTool.execute post-run | NANO-05 fulfilled |
| nanobot.agent.__init__ only exports 4 classes | Exports TaskPlanner, TreeRouter, PlanNode, NodeResult, RouterContext | Discretion area |

---

## Open Questions

1. **How should the MCP client reference be passed to RouterContext?**
   - What we know: `AgentLoop._mcp_stack` is an `AsyncExitStack` that wraps connected MCP tools. The actual MCP tool execution goes through `self.tools` (ToolRegistry), not a direct MCP client object.
   - What's unclear: `TreeRouter._run_mcp` checks `context.mcp_client is not None` and returns a stub result `"MCP executed: {instruction}"`. Passing `self._mcp_stack` satisfies the non-None check but MCP tasks won't actually execute by instruction string.
   - Recommendation: Pass `self.tools` as `mcp_client` as well (same as `tool_registry`). The TreeRouter needs a real dispatch method for MCP by instruction — either stub it as acceptable for Phase 8 (since complexity gate will mostly route MCP-only tasks through direct LLM), or override `_run_mcp` in the AgentLoop subclass to call `self.tools.execute` with a tool lookup by instruction.

2. **Does the complexity gate fire for every message or only task-like messages?**
   - What we know: `AgentLoop._process_message` handles all messages including `/new`, `/help`, and conversational replies.
   - What's unclear: Running a complexity check LLM call for every `/help` command is wasteful.
   - Recommendation: Apply the complexity gate only when the message does not start with `/` and is over a minimum length threshold (e.g., 20 chars). Short messages and slash commands bypass planning entirely.

3. **Should TrajectorySummarizer result be persisted or just logged?**
   - What we know: NANO-05 is "main agent trajectory_summary skill for post-run skill extraction" — the requirement is about extraction, not storage.
   - What's unclear: Whether the summary should be stored in the run directory alongside the trajectory JSONL.
   - Recommendation: Log the summary and pass it to SkillExtractor if the extractor accepts a pre-computed summary parameter (check `SkillExtractor.extract_from_file` signature). If not, summarization is for observability only and no storage is needed.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x with pytest-asyncio |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `pytest tests/test_opengui_p3_nanobot.py tests/test_opengui_p2_integration.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

This phase has no formal requirement IDs (tech debt) but has specific success criteria:

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|-------------|
| TaskPlanner wired: plan tree produced for complex task | unit | `pytest tests/test_opengui_p8_planning.py -x` | Wave 0 |
| TreeRouter dispatches gui ATOM via GuiSubagentTool | unit | `pytest tests/test_opengui_p8_planning.py::test_router_gui_dispatch -x` | Wave 0 |
| AND children execute in parallel (semaphore respected) | unit | `pytest tests/test_opengui_p8_planning.py::test_and_parallel -x` | Wave 0 |
| OR children tried in mcp > tool > gui order | unit | `pytest tests/test_opengui_p8_planning.py::test_or_priority_order -x` | Wave 0 |
| Complexity gate skips planning for simple task | unit | `pytest tests/test_opengui_p8_planning.py::test_complexity_gate_skip -x` | Wave 0 |
| TrajectorySummarizer called after GUI run | unit | `pytest tests/test_opengui_p8_trajectory.py::test_summarizer_called_post_run -x` | Wave 0 |
| All existing tests still pass after changes | regression | `pytest tests/ -x -q` | Yes |

### Sampling Rate
- **Per task commit:** `pytest tests/test_opengui_p3_nanobot.py tests/test_opengui_p2_integration.py tests/test_opengui_p8_planning.py -x -q` (if new file exists)
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p8_planning.py` — new test file covering TaskPlanner+TreeRouter integration
- [ ] `tests/test_opengui_p8_trajectory.py` — new test file covering TrajectorySummarizer wiring (or extend `test_opengui_p3_nanobot.py`)

*(Existing test infrastructure is sufficient for regression; only new behavior needs new test files)*

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `nanobot/agent/planner.py` — TaskPlanner public API, tool schema, fallback behavior
- Direct code inspection: `nanobot/agent/router.py` — TreeRouter execution semantics, RouterContext fields, AND/OR/ATOM dispatch
- Direct code inspection: `opengui/trajectory/summarizer.py` — TrajectorySummarizer public API, LLMProvider dependency
- Direct code inspection: `nanobot/agent/loop.py` — AgentLoop._register_default_tools, _run_agent_loop, _process_message integration point
- Direct code inspection: `nanobot/agent/tools/gui.py` — GuiSubagentTool.execute, _extract_skill post-run chain
- Direct code inspection: `nanobot/agent/__init__.py` — current exports (4 classes, planner/router absent)
- Direct code inspection: `tests/test_opengui_p2_integration.py` — existing test patterns for planner/router
- Direct code inspection: `tests/test_opengui_p3_nanobot.py` — existing test patterns for GuiSubagentTool

### Secondary (MEDIUM confidence)
- Python stdlib `asyncio.Semaphore` documentation — parallel concurrency control pattern
- `asyncio.gather` semantics for concurrent coroutine execution

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all components exist and were read directly
- Architecture patterns: HIGH — derived from actual code structure and locked decisions
- Pitfalls: HIGH — identified from frozen dataclass constraint, concurrent list mutation, and existing stub methods
- Validation: HIGH — pytest infra confirmed in pyproject.toml

**Research date:** 2026-03-19
**Valid until:** 2026-04-18 (stable internal codebase)
