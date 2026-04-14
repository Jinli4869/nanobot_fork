# GUICLaw Checkpoint Log

## Entry Template
- Checkpoint ID:
- Date:
- Commit:
- Scope:
- Validation:
- Rollback:

---

## Recorded Entries

- Checkpoint ID: CP-BASE-20260414-A
- Date: 2026-04-14
- Commit: `dbfec9a`
- Scope: Added TUI trace playback API and operations step-by-step viewer.
- Validation: `npm test -- --run src/features/workspace-routes.test.tsx`
- Rollback: `git revert dbfec9a`

- Checkpoint ID: CP-BASE-20260414-B
- Date: 2026-04-14
- Commit: `73a20dc`
- Scope: Added stagnation-aware reasoning and rich step snapshots in GUI agent trace.
- Validation: `PYTHONPATH=. pytest -q tests/test_opengui.py::test_agent_trace_records_prompt_and_model_details tests/test_opengui_p1_trajectory.py`
- Rollback: `git revert 73a20dc`

- Checkpoint ID: CP-BASE-20260414-C
- Date: 2026-04-14
- Commit: `4053f27`
- Scope: Increased post-action settle delay from 0.25s to 0.50s for UI stability.
- Validation: `PYTHONPATH=. pytest -q tests/test_opengui.py::test_agent_trace_records_prompt_and_model_details`
- Rollback: `git revert 4053f27`

- Checkpoint ID: CP-S1-20260414-D
- Date: 2026-04-14
- Commit: `<pending>`
- Scope: Added normalized failure labels (`failure_label`) to attempt-level trace events and regression tests.
- Validation: `PYTHONPATH=. pytest -q tests/test_opengui.py::test_agent_classifies_failure_labels tests/test_opengui.py::test_agent_attempt_result_trace_includes_failure_label tests/test_opengui.py::test_agent_trace_records_prompt_and_model_details tests/test_opengui_p1_trajectory.py`
- Rollback: `git revert <pending_commit>`
