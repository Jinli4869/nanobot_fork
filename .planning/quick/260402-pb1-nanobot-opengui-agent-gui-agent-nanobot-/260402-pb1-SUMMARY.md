---
phase: quick
plan: 260402-pb1
subsystem: gui-runtime
tags: [gui, model-routing, provider-resolution, evaluation, nanobot, opengui]
dependency_graph:
  requires: []
  provides: [gui-model-decoupling, gui-evaluation-hook]
  affects: [nanobot/config/schema.py, nanobot/cli/commands.py, nanobot/agent/loop.py, nanobot/tui/dependencies.py, nanobot/agent/tools/gui.py, nanobot/utils/gui_evaluation.py, eval/eval.py]
tech_stack:
  added: [nanobot/utils/gui_evaluation.py]
  patterns: [runtime-provider-override, background-gui-postprocessing, shared-single-trace-eval]
key_files:
  modified: [nanobot/config/schema.py, nanobot/cli/commands.py, nanobot/agent/loop.py, nanobot/tui/dependencies.py, nanobot/agent/tools/gui.py, eval/eval.py]
  created: [nanobot/utils/gui_evaluation.py]
decisions:
  - "GUI model/provider overrides are optional and inherit from agents.defaults when omitted"
  - "CLI gateway and TUI task-launch paths share the same GUI runtime resolution helper"
  - "GUI evaluation runs on the existing background postprocessing path and writes evaluation.json beside the trace"
  - "eval/eval.py now reuses the same single-trajectory judge helper as the runtime integration"
metrics:
  duration: 1 session
  completed: 2026-04-02
---

# Quick Task 260402-pb1: Decouple GUI Runtime Model And Add Eval Hook

**One-liner:** Nanobot can now resolve a different model/provider pair for `gui_task` than for the main agent, and GUI runs can optionally trigger a background evaluation artifact through shared `eval` judge logic.

## What Changed

- `nanobot/config/schema.py`
  Added `gui.model`, `gui.provider`, and nested `gui.evaluation` settings so `~/.nanobot/config.json` can independently steer GUI runtime model selection and post-run evaluation.

- `nanobot/cli/commands.py`, `nanobot/agent/loop.py`, `nanobot/tui/dependencies.py`
  Added a shared GUI runtime resolution path so gateway, direct agent runs, and TUI launches can all pass a GUI-specific provider/model into `GuiSubagentTool` without affecting the main agent runtime.

- `nanobot/agent/tools/gui.py`
  Added fail-soft `_maybe_run_evaluation()` wiring on the existing background postprocessing path. When enabled and a successful trace exists, the tool writes `evaluation.json` beside the trace and keeps GUI task completion non-blocking.

- `nanobot/utils/gui_evaluation.py`, `eval/eval.py`
  Introduced a reusable single-trajectory evaluation helper and updated `eval/eval.py` to reuse it for batch processing, so runtime evaluation and offline evaluation stay aligned.

## Verification

- `uv run pytest tests/cli/test_commands.py::test_make_provider_honors_gui_model_and_provider_override tests/test_opengui_p3_nanobot.py::test_agent_loop_registers_gui_tool_with_gui_runtime_override tests/test_opengui_p6_wiring.py::test_gui_config_accepts_model_provider_and_evaluation_aliases tests/test_opengui_p8_trajectory.py::test_gui_evaluation_runs_from_background_postprocessing tests/test_opengui_p8_trajectory.py::test_gui_evaluation_failure_is_non_fatal -q`
- `uv run pytest tests/test_opengui_p8_trajectory.py -q`
- `uv run python -m py_compile nanobot/config/schema.py nanobot/cli/commands.py nanobot/agent/loop.py nanobot/tui/dependencies.py nanobot/agent/tools/gui.py nanobot/utils/gui_evaluation.py eval/eval.py`

## Notes

- A broader mixed test slice still contains unrelated baseline failures already present in this worktree, so verification was kept to the feature-specific regression slice above.
