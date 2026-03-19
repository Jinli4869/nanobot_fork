---
phase: 08-dead-export-cleanup
plan: "03"
subsystem: nanobot/agent
tags: [complexity-gate, plan-and-execute, agent-loop, task-planner, tree-router, tdd]
dependency_graph:
  requires: ["08-02"]
  provides: ["AgentLoop complexity gate", "_needs_planning", "_plan_and_execute", "_GuiDispatchAdapter"]
  affects: ["nanobot/agent/loop.py", "nanobot/agent/planner.py", "nanobot/agent/router.py"]
tech_stack:
  added: []
  patterns: ["complexity gate with safe fallback", "adapter pattern (_GuiDispatchAdapter)", "lazy module imports inside methods"]
key_files:
  created: []
  modified:
    - nanobot/agent/loop.py
    - tests/test_opengui_p8_planning.py
decisions:
  - "Lazy import of TaskPlanner and TreeRouter inside _plan_and_execute keeps loop.py import overhead minimal"
  - "_GuiDispatchAdapter bridges GuiSubagentTool.execute() (returns JSON string) to TreeRouter._run_gui interface (needs .run() returning object with .success/.summary/.error/.trace_path)"
  - "Complexity gate guards on two conditions: gui_config is not None AND message length >= 20 chars"
  - "Exception in _needs_planning falls back silently to _run_agent_loop — never blocks message processing"
  - "Tests patch nanobot.agent.tools.gui.GuiSubagentTool (not loop module) because it is imported conditionally inside _register_default_tools"
  - "test_plan_and_execute_logs_tree patches nanobot.agent.planner.TaskPlanner and nanobot.agent.router.TreeRouter at their definition sites because _plan_and_execute uses from-import inside the method"
metrics:
  duration: "5 minutes"
  completed_date: "2026-03-19"
  tasks_completed: 1
  files_modified: 2
---

# Phase 08 Plan 03: Complexity Gate + Plan-and-Execute Integration Summary

**One-liner:** Complexity gate using assess_complexity LLM tool routes long non-slash messages through TaskPlanner+TreeRouter when gui_config is set, with _GuiDispatchAdapter bridging GuiSubagentTool.execute() to TreeRouter's run() interface.

## What Was Built

`AgentLoop._process_message` now has a complexity gate that fires for non-slash, 20+ character messages when `_gui_config is not None`. The gate calls `_needs_planning()` (one LLM call with the `assess_complexity` structured tool) to decide whether to decompose the task. When planning is warranted, `_plan_and_execute()` decomposes the task via `TaskPlanner`, logs the tree, then dispatches via `TreeRouter`. A `_GuiDispatchAdapter` inner class bridges the interface gap between `GuiSubagentTool.execute()` (JSON string) and `TreeRouter._run_gui` (expects `.run()` returning an object with `.success`/`.summary`/`.error`/`.trace_path`).

### Key Components Added to loop.py

- **`_COMPLEXITY_TOOL`** — Module-level constant: the `assess_complexity` function tool definition used by `_needs_planning` to elicit a structured Boolean from the LLM.
- **`AgentLoop._needs_planning(task)`** — Single `chat_with_retry` call to assess task complexity. Returns `False` on any parsing failure (safe default).
- **`AgentLoop._plan_and_execute(task)`** — Lazy-imports `TaskPlanner`/`TreeRouter`/`RouterContext`, builds the plan tree, logs it, wires `RouterContext`, runs via `TreeRouter`. Returns `(output, tools_used, [])` matching the `_run_agent_loop` return signature.
- **`_GuiDispatchAdapter`** — Local class inside `_plan_and_execute` that wraps `GuiSubagentTool` to present the `.run(instruction)` interface `TreeRouter._run_gui` expects.
- **Complexity gate in `_process_message`** — Inserted between `initial_messages` construction and `_run_agent_loop` call; exceptions caught silently and fall back to direct agent loop.

### Tests Added (tests/test_opengui_p8_planning.py)

6 new tests (Plan 03) + existing 8 (Plan 02) = 14 total, all green:

| Test | What it verifies |
|------|-----------------|
| `test_complexity_gate_skip_slash_command` | `/help` returns early before `_needs_planning` is called |
| `test_complexity_gate_skip_short_message` | < 20 char messages never call `_needs_planning` |
| `test_complexity_gate_false_uses_agent_loop` | `_needs_planning` → False → `_run_agent_loop` called |
| `test_complexity_gate_true_uses_planning` | `_needs_planning` → True → `_plan_and_execute` called, not `_run_agent_loop` |
| `test_complexity_gate_exception_falls_back` | `_needs_planning` raises → `_run_agent_loop` called as safe fallback |
| `test_plan_and_execute_logs_tree` | `logger.info` called with "Decomposed plan" during execution |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test helper patched wrong import path for GuiSubagentTool**
- **Found during:** TDD RED phase
- **Issue:** `_make_agent_loop` tried to patch `nanobot.agent.loop.GuiSubagentTool` but the import is conditional inside `_register_default_tools`, so the name doesn't exist at module level.
- **Fix:** Patched `nanobot.agent.tools.gui.GuiSubagentTool` at its definition site instead.
- **Files modified:** tests/test_opengui_p8_planning.py
- **Commit:** 90ead93

**2. [Rule 1 - Bug] test_plan_and_execute_logs_tree patch paths were wrong**
- **Found during:** TDD GREEN phase (1 failing after 5 passing)
- **Issue:** Test tried to patch `nanobot.agent.loop.TaskPlanner` and `nanobot.agent.loop.TreeRouter` but both are lazy-imported inside `_plan_and_execute`, so they don't exist as module-level names in `loop`.
- **Fix:** Patched `nanobot.agent.planner.TaskPlanner` and `nanobot.agent.router.TreeRouter` at their definition sites.
- **Files modified:** tests/test_opengui_p8_planning.py
- **Commit:** 90ead93

### Pre-existing Failures (Out of Scope)

- `test_tool_validation.py::test_exec_head_tail_truncation` fails because `python` command is not on PATH in this environment (only `.venv/bin/python`). Pre-existing, unrelated to this plan's changes. Logged in `deferred-items.md`.

## Self-Check: PASSED

Files exist:
- `nanobot/agent/loop.py` contains `_COMPLEXITY_TOOL`, `_needs_planning`, `_plan_and_execute`, `_GuiDispatchAdapter`, `Decomposed plan:`
- `tests/test_opengui_p8_planning.py` contains all 6 new test functions

Commits exist:
- `90ead93` — feat(08-03): add complexity gate and plan-and-execute path to AgentLoop

Test results: `pytest tests/test_opengui_p8_planning.py` — 14 passed, 0 failed
