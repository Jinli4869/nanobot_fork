---
phase: quick-260325-ts0
plan: 01
subsystem: nanobot/agent/tools/gui
tags: [skill-execution, gui-agent, config, tdd]
dependency_graph:
  requires: []
  provides: [enable_skill_execution config field, SkillExecutor wiring in GuiSubagentTool]
  affects: [nanobot/agent/tools/gui.py, nanobot/config/schema.py]
tech_stack:
  added: []
  patterns: [lazy-import-to-module-level promotion, opt-in feature flag via config]
key_files:
  created: [tests/test_gui_skill_executor_wiring.py]
  modified: [nanobot/config/schema.py, nanobot/agent/tools/gui.py]
decisions:
  - "GuiAgent and TrajectoryRecorder promoted to module-level imports in gui.py so unittest.mock.patch can resolve them by dotted name"
  - "SkillExecutor instantiated inside _run_task (not __init__) to capture the active_backend which may vary per call via backend override"
  - "LLMStateValidator constructed with self._llm_adapter (NanobotLLMAdapter) mirroring opengui CLI reference pattern"
metrics:
  duration: 12 min
  completed: "2026-03-25"
---

# Quick Task 260325-ts0: Wire SkillExecutor into GuiSubagentTool Summary

**One-liner:** Opt-in skill execution via `enable_skill_execution: bool = False` in GuiConfig, wired as `SkillExecutor(backend, LLMStateValidator(llm))` in `_run_task()`.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| RED | Add failing tests for SkillExecutor wiring | 1907ae1 | tests/test_gui_skill_executor_wiring.py |
| GREEN | Implement enable_skill_execution config + wiring | 5f81c1b | nanobot/config/schema.py, nanobot/agent/tools/gui.py |

## What Was Built

- `GuiConfig.enable_skill_execution: bool = False` — simple boolean opt-in field with camelCase alias support (`enableSkillExecution`) via the existing `Base` model alias generator.
- In `GuiSubagentTool._run_task()`: when `enable_skill_execution=True`, builds `SkillExecutor(backend=active_backend, state_validator=LLMStateValidator(self._llm_adapter))` and passes it to `GuiAgent(...)` as `skill_executor=skill_executor`.
- When `enable_skill_execution=False` (default), `skill_executor=None` is passed, preserving the existing no-skill-execution behavior.
- 8 unit tests across 3 test classes verify the config field and the wiring paths.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Promoted GuiAgent and TrajectoryRecorder to module-level imports**

- **Found during:** GREEN phase — tests patched `nanobot.agent.tools.gui.GuiAgent.__init__` but `GuiAgent` was only imported inside `_run_task()` (local scope), making the dotted-name target unresolvable.
- **Issue:** `AttributeError: module 'nanobot.agent.tools.gui' has no attribute 'GuiAgent'` when tests attempted `patch("nanobot.agent.tools.gui.GuiAgent.__init__", ...)`.
- **Fix:** Moved `from opengui.agent import GuiAgent` and `from opengui.trajectory.recorder import TrajectoryRecorder` from inside `_run_task()` to module-level imports. Removed the now-redundant local import in `_scrub_payload` static method. No behavior change — `opengui.interfaces` was already imported at module level, confirming no circular-import risk.
- **Files modified:** `nanobot/agent/tools/gui.py`
- **Commit:** 5f81c1b (included in GREEN commit)

## Verification

```
python -m pytest tests/test_gui_skill_executor_wiring.py -x -v
# 8 passed

python -c "from nanobot.config.schema import GuiConfig; c = GuiConfig(enable_skill_execution=True); assert c.enable_skill_execution is True; c2 = GuiConfig(); assert c2.enable_skill_execution is False; print('OK')"
# OK

python -m pytest tests/ -x -q
# 364 passed (1 pre-existing unrelated failure in tests/cli/test_commands.py)
```

## Pre-existing Failures (Out of Scope)

`tests/cli/test_commands.py::test_agent_uses_default_config_when_no_workspace_or_config_flags` — fails because the test asserts `set(awaited.kwargs) == {"on_progress"}` but the call site now also passes `on_stream` and `on_stream_end`. This failure predates this task and is unrelated to the skill execution changes (confirmed by running the test against the pre-change commit).

## Self-Check: PASSED

- `nanobot/config/schema.py` — FOUND: `enable_skill_execution: bool = False`
- `nanobot/agent/tools/gui.py` — FOUND: `SkillExecutor` instantiation in `_run_task`
- `tests/test_gui_skill_executor_wiring.py` — FOUND: 8 tests, all passing
- Commit 1907ae1 — FOUND: RED phase tests
- Commit 5f81c1b — FOUND: GREEN phase implementation
