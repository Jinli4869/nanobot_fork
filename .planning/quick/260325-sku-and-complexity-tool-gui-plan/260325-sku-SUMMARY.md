---
phase: quick
plan: 260325-sku
subsystem: nanobot/agent
tags: [router, loop, bug-fix, tdd, planning-gate, exit-code, and-sequential]
dependency_graph:
  requires: []
  provides: [exit-code-error-detection, and-sequential-execution, gui-only-planning-gate]
  affects: [nanobot/agent/router.py, nanobot/agent/loop.py]
tech_stack:
  added: []
  patterns: [_is_error_output helper, sequential-and-execution, gui-gated-complexity-assessment]
key_files:
  created: []
  modified:
    - nanobot/agent/router.py
    - nanobot/agent/loop.py
    - tests/test_opengui_p22_route_dispatch.py
decisions:
  - _is_error_output() uses re.search for Exit code: N detection — regex handles whitespace variation; non-"0" string check covers 1–255
  - AND sequential execution uses index-aware for loop; child sees merged context.completed from all previous siblings immediately
  - max_concurrency parameter removed from TreeRouter.__init__ — no longer needed with sequential execution
  - _needs_planning system prompt: GUI interaction is the sole gate; direct tools explicitly listed as sufficient for non-GUI tasks
metrics:
  duration: 12 min
  completed: "2026-03-25"
  tasks: 2
  files: 3
---

# Phase quick Plan 260325-sku: Router Bug Fixes and GUI-Only Planning Gate Summary

**One-liner:** Fixed ExecTool exit-code error detection, converted AND nodes to sequential execution, and gated _COMPLEXITY_TOOL planning trigger to GUI-only tasks.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Fix error detection and AND sequential execution in router.py | 604aeaf | router.py, test file |
| 2 | Make _COMPLEXITY_TOOL gate GUI-only in loop.py | 56e685b | loop.py |

## What Was Built

### Task 1: router.py — Exit Code Detection + AND Sequential Execution

**Bug 1: Silent failure on non-zero exit codes**

`ExecTool` outputs failures in the format `"STDERR:\n...\n\nExit code: 127"`. The existing checks in `_dispatch_with_fallback`, `_run_tool`, and `_run_mcp` only detected `output_str.startswith("Error")` — completely missing shell failures that report via exit code.

Fix: Added `_is_error_output(output_str: str) -> bool` helper at module level that checks both the `Error` prefix and a `re.search(r"Exit code:\s*(\d+)", output_str)` match where the captured number is not `"0"`. All three dispatch sites now call this helper.

**Bug 2: AND nodes ran children in parallel via asyncio.gather**

The planner contract specifies AND as sequential: step N depends on step N-1 completing. The parallel `asyncio.Semaphore` + `asyncio.gather` implementation violated this semantic and introduced shared-state mutation risks.

Fix: Replaced the semaphore + gather approach with a simple `for i, child in enumerate(node.children):` loop. Each child runs to completion before the next starts. On failure, replanning is attempted immediately and remaining children are not started until the failed child is resolved. The `max_concurrency` parameter was removed from `TreeRouter.__init__` as it no longer serves any purpose.

**Regression tests added (4 new):**
- `test_run_tool_detects_nonzero_exit_code`: Exit code 127 → `NodeResult(success=False)`
- `test_run_tool_allows_zero_exit_code`: Exit code 0 → `NodeResult(success=True)`
- `test_dispatch_with_fallback_detects_nonzero_exit_code`: Exit code 127 triggers fallback chain
- `test_execute_and_runs_sequentially`: Execution order verified as [0, 1, 2] with monotonic timestamps

### Task 2: loop.py — GUI-Only Planning Gate

`_COMPLEXITY_TOOL` and `_needs_planning` were returning `True` for multi-step pure-tool tasks (e.g. "search for X and save to file"), routing them through expensive planning unnecessarily.

Fix:
- Updated `_COMPLEXITY_TOOL` function description to focus on "GUI operations that need multi-step planning"
- Updated `needs_planning` property description to explicitly state "True ONLY if the task requires GUI operations" and "Pure tool/shell tasks NEVER need planning"
- Updated `_needs_planning` system prompt to make GUI interaction the sole trigger gate

The outer `if self._gui_config is not None` guard remains unchanged — it correctly ensures planning is never attempted when no GUI is configured.

## Verification

All existing 40 tests in `tests/test_opengui_p22_route_dispatch.py` continue to pass.
4 new regression tests added and passing.
`_COMPLEXITY_TOOL` description verified to contain "GUI" keyword.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing asyncio import in test file**

- **Found during:** Task 1 (GREEN phase — `asyncio.sleep` used in `test_execute_and_runs_sequentially`)
- **Issue:** `tests/test_opengui_p22_route_dispatch.py` had no `import asyncio` at module level; the sequential test's `dispatch_side_effect` called `asyncio.sleep()` which raised `NameError`
- **Fix:** Added `import asyncio` to the test file imports
- **Files modified:** `tests/test_opengui_p22_route_dispatch.py`
- **Commit:** 604aeaf

## Self-Check: PASSED

All files verified present. All commits verified in git history. 44/44 tests passing.
