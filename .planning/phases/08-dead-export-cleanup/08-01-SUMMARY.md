---
phase: 08-dead-export-cleanup
plan: "01"
subsystem: nanobot.agent / opengui trajectory
tags: [trajectory, summarizer, planner, router, public-api, tdd]
dependency_graph:
  requires: []
  provides:
    - TrajectorySummarizer post-run hook in GuiSubagentTool
    - nanobot.agent public API: TaskPlanner, PlanNode, TreeRouter, NodeResult, RouterContext
  affects:
    - nanobot/agent/tools/gui.py
    - nanobot/agent/__init__.py
tech_stack:
  added: []
  patterns:
    - lazy import inside method body for optional opengui dependency
    - TDD (RED/GREEN) with unittest.mock.patch for async method mocking
key_files:
  created:
    - tests/test_opengui_p8_trajectory.py
  modified:
    - nanobot/agent/tools/gui.py
    - nanobot/agent/__init__.py
decisions:
  - "_summarize_trajectory uses lazy import so gui.py does not gain a hard module-level opengui.trajectory.summarizer import"
  - "Summarizer failures are caught at WARNING level — non-fatal, does not affect tool result or _extract_skill"
  - "TrajectorySummarizer is called between trace_path resolution and _extract_skill to maintain logical ordering"
  - "nanobot.agent.__all__ uses alphabetical ordering for all 9 exported names"
metrics:
  duration: "4 minutes"
  completed_date: "2026-03-19"
  tasks_completed: 2
  files_changed: 3
---

# Phase 8 Plan 01: Dead Export Cleanup — TrajectorySummarizer Wiring and Public API Exports Summary

**One-liner:** Wire TrajectorySummarizer as non-fatal post-run hook in GuiSubagentTool and expose TaskPlanner/TreeRouter via nanobot.agent public API.

## Objective

Complete NANO-05 (trajectory summarization for skill extraction) by calling `TrajectorySummarizer.summarize_file()` after every GUI run, and eliminate orphaned planner/router exports by making `TaskPlanner`, `PlanNode`, `TreeRouter`, `NodeResult`, and `RouterContext` importable from `nanobot.agent`.

## Tasks Completed

| # | Name | Commit | Key Files |
|---|------|--------|-----------|
| RED | TDD failing tests | 08c3013 | tests/test_opengui_p8_trajectory.py |
| 1 | Wire TrajectorySummarizer into GuiSubagentTool | be8c401 | nanobot/agent/tools/gui.py |
| 2 | Export planner/router types from nanobot.agent | 4ec843b | nanobot/agent/__init__.py |

## Implementation Details

### Task 1: TrajectorySummarizer Wiring

Added `_summarize_trajectory(trace_path: Path | None) -> str` method to `GuiSubagentTool`:

- Lazy-imports `TrajectorySummarizer` from `opengui.trajectory.summarizer` to avoid module-level coupling
- Returns empty string immediately if `trace_path` is `None` or file does not exist (no summarization attempted)
- Creates `TrajectorySummarizer(llm=self._llm_adapter)` — reuses the existing LLM adapter
- Catches any `Exception`, logs at `WARNING` with `exc_info=True`, and returns `""` (non-fatal)
- Called in `execute()` between `_resolve_trace_path()` and `_extract_skill()`, with INFO log of first 200 chars when summary is non-empty

### Task 2: Public API Exports

Updated `nanobot/agent/__init__.py`:

- Added `from nanobot.agent.planner import PlanNode, TaskPlanner`
- Added `from nanobot.agent.router import NodeResult, RouterContext, TreeRouter`
- Expanded `__all__` to 9 names in alphabetical order

## Test Results

All 4 new tests pass in `tests/test_opengui_p8_trajectory.py`:

- `test_summarizer_called_post_run` — `summarize_file` awaited once with a `Path` argument
- `test_summarizer_failure_non_fatal` — `RuntimeError` in summarizer: `execute()` still returns valid JSON, `_extract_skill` still called
- `test_summarizer_skipped_when_no_trace` — `trace_path=None`: `summarize_file` never called
- `test_planner_router_exported_from_agent_package` — all 5 types are importable from `nanobot.agent` as classes

Full suite: 572 passed (baseline 568 + 4 new), 7 warnings. Pre-existing failures (`test_tool_validation.py::test_exec_head_tail_truncation`, `test_opengui_p8_planning.py::test_or_priority_order`) are out of scope.

## Deviations from Plan

None — plan executed exactly as written.

One note: `test_summarizer_failure_non_fatal` and `test_summarizer_skipped_when_no_trace` were already passing in RED phase because they don't assert the summarizer *was* called — they assert it was *not* called or that failure is non-fatal. Only `test_summarizer_called_post_run` and `test_planner_router_exported_from_agent_package` were the true RED tests requiring implementation to go GREEN.

## Self-Check: PASSED

All key files exist, all commits verified.
