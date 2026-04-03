---
phase: 31-shortcut-observability-and-regression-hardening
plan: "01"
subsystem: opengui-shortcut-telemetry
tags: [telemetry, shortcut, trajectory, tdd, observability]
dependency_graph:
  requires:
    - opengui/skills/multi_layer_executor.py (ShortcutExecutor)
    - opengui/agent.py (GuiAgent shortcut dispatch branch)
    - opengui/trajectory/recorder.py (TrajectoryRecorder.record_event)
  provides:
    - shortcut_grounding and shortcut_settle telemetry events from ShortcutExecutor
    - live recorder injection from GuiAgent into ShortcutExecutor before execute()
    - JSONL trace artifacts containing full shortcut telemetry boundary set
  affects:
    - tests/test_opengui_p30_stable_shortcut_execution.py (extended with wiring regression)
    - tests/test_opengui_p31_shortcut_observability.py (new Phase 31 telemetry tests)
tech_stack:
  added: []
  patterns:
    - Structural dependency injection: trajectory_recorder field on ShortcutExecutor
      avoids circular import while enabling testable telemetry emission
    - Guard-against-None pattern for optional recorder: if self.trajectory_recorder is not None
    - TDD (RED-GREEN): tests written first to confirm failure, then implementation
key_files:
  created:
    - tests/test_opengui_p31_shortcut_observability.py
  modified:
    - opengui/skills/multi_layer_executor.py
    - opengui/agent.py
    - tests/test_opengui_p30_stable_shortcut_execution.py
decisions:
  - "trajectory_recorder field typed as Any on ShortcutExecutor to avoid circular import with opengui.trajectory.recorder — structural injection is the correct pattern here"
  - "shortcut_grounding event emits after backend.execute() but before settle handling so both grounding and action execution are confirmed before the event fires"
  - "shortcut_settle event emits after asyncio.sleep() (inside the if settle > 0 block) so the settle_seconds payload matches what was actually waited"
  - "recorder injection in GuiAgent.run() placed immediately before execute() so it takes effect on each call without creating a second recorder"
metrics:
  duration: "3m 20s"
  completed: "2026-04-03"
  tasks_completed: 1
  files_modified: 4
---

# Phase 31 Plan 01: Shortcut Observability Telemetry Summary

Wired end-to-end shortcut grounding and settle telemetry: `ShortcutExecutor` now emits `shortcut_grounding` and `shortcut_settle` events via an injected `trajectory_recorder`, and `GuiAgent` injects its live recorder before each `execute()` call so all five shortcut boundary events land in a single JSONL trace artifact.

## What Was Built

### ShortcutExecutor telemetry (opengui/skills/multi_layer_executor.py)

Added `trajectory_recorder: Any = None` as the last dataclass field on `ShortcutExecutor`.  Callers that do not pass this field continue to work without error.

Two new event emissions inside `execute()`:

1. **shortcut_grounding** — emitted after `backend.execute(action)` when `grounding is not None` (i.e., the step was non-fixed and went through the grounder).  Payload: `skill_id`, `step_index`, `target`, `resolved_params`.

2. **shortcut_settle** — emitted inside the `if settle > 0:` block, after `asyncio.sleep(settle)`.  Only fires for non-exempt action types where an actual settle wait occurred.  Payload: `skill_id`, `step_index`, `action_type`, `settle_seconds`.

Neither event fires when `trajectory_recorder is None`, preserving backward compatibility.

### GuiAgent recorder injection (opengui/agent.py)

Inside the `if self._shortcut_executor is not None:` branch of `GuiAgent.run()`, one line was added immediately before `await self._shortcut_executor.execute(matched_skill)`:

```python
self._shortcut_executor.trajectory_recorder = self._trajectory_recorder
```

This ensures the executor's recorder is always the agent's live recorder for every shortcut dispatch.  No second recorder is created and the existing `shortcut_execution` event in `GuiAgent` is unchanged.

### Phase 30 wiring regression (tests/test_opengui_p30_stable_shortcut_execution.py)

Added `test_gui_agent_injects_live_trajectory_recorder_into_shortcut_executor`.  Uses a custom `_capturing_execute` coroutine that records `shortcut_executor.trajectory_recorder` at the moment `execute()` is called, then asserts it is the same object as the agent's live `TrajectoryRecorder`.

### Phase 31 telemetry tests (tests/test_opengui_p31_shortcut_observability.py)

New test file with seven tests:

| Test | Purpose |
|------|---------|
| `test_grounding_telemetry` | One shortcut_grounding event for a non-fixed step with correct payload |
| `test_no_grounding_event_for_fixed_step` | Zero shortcut_grounding events for a fixed step |
| `test_settle_telemetry` | One shortcut_settle event for a non-exempt tap with correct payload |
| `test_no_settle_event_for_exempt_action` | Zero shortcut_settle events for done/wait/request_intervention |
| `test_no_settle_event_when_settle_is_zero` | Zero shortcut_settle events when post_action_settle_seconds=0.0 |
| `test_no_recorder_no_error` | No error when trajectory_recorder not passed (backward compat) |
| `test_full_trace_event_coverage` | Real GuiAgent + real TrajectoryRecorder + real ShortcutExecutor trace contains all five required event types |

## Verification

```
uv run python -m pytest tests/test_opengui_p31_shortcut_observability.py tests/test_opengui_p30_stable_shortcut_execution.py -q --tb=short
25 passed in 3.17s
```

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `opengui/skills/multi_layer_executor.py` contains `trajectory_recorder: Any = None` on ShortcutExecutor
- `opengui/skills/multi_layer_executor.py` contains `"shortcut_grounding"` event emission inside `execute()`
- `opengui/skills/multi_layer_executor.py` contains `"shortcut_settle"` event emission inside `if settle > 0:` block
- `opengui/agent.py` contains `self._shortcut_executor.trajectory_recorder = self._trajectory_recorder`
- `tests/test_opengui_p30_stable_shortcut_execution.py` contains `test_gui_agent_injects_live_trajectory_recorder_into_shortcut_executor`
- `tests/test_opengui_p31_shortcut_observability.py` contains `test_full_trace_event_coverage`
- All 25 tests pass (15 Phase 30 + 10 Phase 31 including new wiring test)
- Commit: 98d2692
