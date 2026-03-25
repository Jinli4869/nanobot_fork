---
phase: quick
plan: 260325-sku
type: execute
wave: 1
depends_on: []
files_modified:
  - nanobot/agent/router.py
  - nanobot/agent/loop.py
  - tests/test_opengui_p22_route_dispatch.py
autonomous: true
requirements: [SKU-01, SKU-02, SKU-03]

must_haves:
  truths:
    - "ExecTool outputs with non-zero exit codes are detected as failures by router dispatch"
    - "AND nodes execute children sequentially, not in parallel"
    - "_needs_planning only returns True when the task involves GUI operations (screen taps, app navigation)"
  artifacts:
    - path: "nanobot/agent/router.py"
      provides: "Fixed error detection and sequential AND execution"
      contains: "Exit code:"
    - path: "nanobot/agent/loop.py"
      provides: "GUI-gated complexity assessment"
      contains: "GUI"
    - path: "tests/test_opengui_p22_route_dispatch.py"
      provides: "Regression tests for exit code detection"
  key_links:
    - from: "nanobot/agent/router.py"
      to: "nanobot/agent/tools/shell.py"
      via: "ExecTool output format with Exit code: N"
      pattern: "Exit code:"
    - from: "nanobot/agent/loop.py"
      to: "nanobot/agent/loop.py"
      via: "_needs_planning prompt drives _COMPLEXITY_TOOL gate"
      pattern: "_needs_planning"
---

<objective>
Fix three bugs in the nanobot agent: (1) error detection misses non-zero exit codes from ExecTool, (2) AND nodes run in parallel instead of sequentially as the planner contract specifies, (3) _COMPLEXITY_TOOL planning gate fires for pure tool/shell tasks when it should only fire for GUI tasks.

Purpose: Correct agent reliability — failed shell commands silently pass, AND-node parallelism violates planner semantics, and non-GUI tasks are unnecessarily routed through expensive planning.
Output: Patched router.py and loop.py with regression tests.
</objective>

<execution_context>
@/Users/jinli/.claude/get-shit-done/workflows/execute-plan.md
@/Users/jinli/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@nanobot/agent/router.py
@nanobot/agent/loop.py
@nanobot/agent/tools/shell.py (ExecTool output format reference — line 132-134: "STDERR:\n...\nExit code: {N}")
@tests/test_opengui_p22_route_dispatch.py

<interfaces>
<!-- ExecTool output format (shell.py lines 129-136): -->
<!-- STDERR:\n{stderr_text}\n\nExit code: {returncode} -->
<!-- The output_str checked by router may look like: -->
<!--   "STDERR:\n/bin/sh: pip: command not found\n\nExit code: 127" -->
<!-- Current router check: output_str.startswith("Error") — misses these -->

From nanobot/agent/router.py:
```python
class NodeResult:
    success: bool
    output: str = ""
    error: str | None = None
    trace_paths: list[str] = field(default_factory=list)

class RouterContext:
    task: str
    completed: list[str] = field(default_factory=list)
    gui_agent: Any = None
    tool_registry: Any = None
    mcp_client: Any = None
```

From nanobot/agent/loop.py:
```python
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
                    "description": "True if the task requires multiple distinct steps..."
                }
            },
            "required": ["needs_planning"],
        },
    },
}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Fix error detection and AND sequential execution in router.py</name>
  <files>nanobot/agent/router.py, tests/test_opengui_p22_route_dispatch.py</files>
  <behavior>
    - Test: ExecTool output "STDERR:\n/bin/sh: pip: command not found\n\nExit code: 127" is detected as failure by _run_tool (direct route, no fallbacks)
    - Test: ExecTool output "STDERR:\n/bin/sh: pip: command not found\n\nExit code: 127" is detected as failure by _dispatch_with_fallback (falls through to next fallback)
    - Test: ExecTool output "some output\n\nExit code: 0" is NOT treated as failure (exit code 0 is success)
    - Test: _run_mcp also detects non-zero exit code outputs as failures
    - Test: AND node with 3 children executes them sequentially (child 2 starts only after child 1 completes)
  </behavior>
  <action>
1. **Add a helper function `_is_error_output(output_str: str) -> bool`** at module level (near the route resolution tables) that returns True when:
   - `output_str.startswith("Error")` (existing check), OR
   - A regex match finds `Exit code: (\d+)` in output_str where the captured number is not "0"
   - Use `re.search(r"Exit code:\s*(\d+)", output_str)` — import `re` at the top of router.py

2. **Replace all three `output_str.startswith("Error")` checks** in `_dispatch_with_fallback` (line 411), `_run_tool` (line 491), and `_run_mcp` (line 543) with calls to `_is_error_output(output_str)`.

3. **Change `_execute_and` from parallel `asyncio.gather` to sequential loop:**
   - Remove the `asyncio.Semaphore` and the inner `_run_child` async closure
   - Remove the `asyncio.gather` call
   - Instead, iterate `enumerate(node.children)` sequentially with `for i, child in enumerate(node.children):`
   - For each child, create a child-specific `RouterContext` (same snapshot pattern), `await self.execute(child, child_ctx)`, collect results into the same `all_outputs`/`all_traces`/`child_completed`/`child_results` lists
   - On failure of any child, attempt replan (same logic), and if replan fails, return failure immediately (do not continue to next children)
   - After all children succeed, merge completed lists in order (same as current post-gather merge)
   - Remove `max_concurrency` parameter from `__init__` and its docstring references (no longer needed)
   - Update the class docstring to say "AND nodes execute children sequentially" instead of "in parallel via asyncio.gather"

4. **Add regression tests** at the bottom of `tests/test_opengui_p22_route_dispatch.py`:
   - `test_run_tool_detects_nonzero_exit_code`: registry.execute returns "STDERR:\n/bin/sh: pip: command not found\n\nExit code: 127", assert NodeResult.success is False
   - `test_run_tool_allows_zero_exit_code`: registry.execute returns "some output\n\nExit code: 0", assert NodeResult.success is True
   - `test_dispatch_with_fallback_detects_nonzero_exit_code`: primary route returns exit code 127, fallback route exists, assert fallback is tried
   - `test_execute_and_runs_sequentially`: create 3 ATOM children that append to a shared list with timestamps/ordering markers, assert execution order is 0,1,2 (not interleaved)
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -m pytest tests/test_opengui_p22_route_dispatch.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>All existing route dispatch tests still pass. New tests confirm: non-zero exit codes detected as failures in _run_tool, _run_mcp, and _dispatch_with_fallback; exit code 0 passes; AND nodes execute sequentially.</done>
</task>

<task type="auto">
  <name>Task 2: Make _COMPLEXITY_TOOL gate GUI-only in loop.py</name>
  <files>nanobot/agent/loop.py</files>
  <action>
1. **Update `_COMPLEXITY_TOOL` description** (line 49-56) to focus on GUI requirement:
   ```python
   "description": (
       "Determine if a task requires GUI operations that need multi-step planning."
   ),
   ```
   Update the `needs_planning` property description:
   ```python
   "description": (
       "True ONLY if the task requires GUI operations — screen taps, "
       "app navigation, interacting with device UI elements, opening "
       "or switching between apps on a device screen. "
       "False for tasks that can be completed with shell commands, "
       "file operations, web searches, API calls, or any non-GUI tool. "
       "Pure tool/shell tasks NEVER need planning."
   ),
   ```

2. **Update `_needs_planning` system prompt** (lines 497-504) to make GUI the primary gate:
   ```python
   "content": (
       "You are a task complexity assessor for a device automation agent. "
       "Determine if the user's task requires GUI operations — interacting "
       "with a device screen (tapping, swiping, typing into app UI, navigating "
       "between apps, reading screen content). "
       "ONLY return True when GUI interaction is needed.\n\n"
       f"The agent has these direct tools (no planning needed): {direct_tools_summary}.\n"
       "If the task can be accomplished entirely with these tools (shell commands, "
       "file I/O, web search, web fetch), return False. "
       "Planning is ONLY for tasks that require controlling a device screen."
   ),
   ```

3. **No changes needed** to the outer gate condition (`if self._gui_config is not None and len(msg.content.strip()) >= 20:`) — this correctly guards that planning is only considered when GUI config exists. The inner `_needs_planning` change ensures the LLM only returns True for actual GUI tasks.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "from nanobot.agent.loop import _COMPLEXITY_TOOL; desc = _COMPLEXITY_TOOL['function']['parameters']['properties']['needs_planning']['description']; assert 'GUI' in desc, f'Missing GUI in description: {desc}'; print('OK: _COMPLEXITY_TOOL description mentions GUI')"</automated>
  </verify>
  <done>_COMPLEXITY_TOOL description and _needs_planning system prompt both gate on GUI requirement. Pure tool/shell tasks will not trigger planning. The outer gui_config check remains unchanged as a prerequisite guard.</done>
</task>

</tasks>

<verification>
1. All existing tests pass: `python -m pytest tests/test_opengui_p22_route_dispatch.py -x -q`
2. New exit-code detection tests pass
3. AND sequential execution test passes
4. `_COMPLEXITY_TOOL` description contains "GUI" as primary gate keyword
5. `_needs_planning` system prompt explicitly says "ONLY return True when GUI interaction is needed"
</verification>

<success_criteria>
- Non-zero exit code outputs (e.g. "Exit code: 127") are detected as failures by _run_tool, _run_mcp, and _dispatch_with_fallback
- Exit code 0 outputs are NOT treated as failures
- AND node children execute sequentially (no asyncio.gather)
- _needs_planning only returns True for GUI tasks, not for pure shell/tool tasks
- All existing tests in test_opengui_p22_route_dispatch.py remain green
</success_criteria>

<output>
After completion, create `.planning/quick/260325-sku-and-complexity-tool-gui-plan/260325-sku-SUMMARY.md`
</output>
