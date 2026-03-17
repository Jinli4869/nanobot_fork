---
phase: 02-agent-loop-integration
plan: 04
status: complete
started: 2026-03-17
completed: 2026-03-17
---

## What was built

Replaced Wave 0 xfail test stubs with comprehensive integration tests covering all Phase 2 requirements.

### Task 1: Phase 2 integration and memory test suites

**tests/test_opengui_p2_integration.py** (8 tests):
- `test_memory_injected_into_system_prompt` — AGENT-04/MEM-05: memory context appears in LLM system prompt
- `test_skill_path_chosen_above_threshold` — AGENT-05/SKILL-08: skill execution triggered above threshold, SKILL phase in trajectory
- `test_free_explore_when_no_skill_match` — AGENT-05: free exploration when no skill match, no SKILL phase
- `test_trajectory_recorded_on_run` — AGENT-06/TRAJ-03: JSONL file with metadata/step/result events
- `test_planner_decomposes_task` — AGENT-04: TaskPlanner returns AND tree with typed ATOM children
- `test_router_dispatches_gui_and_tool_atoms` — capability-type dispatch to correct executors
- `test_router_replans_on_and_child_failure` — AND-child failure triggers replanning
- `test_full_flow_with_mock_llm` — TEST-05: end-to-end with DryRunBackend + memory + skill + trajectory

**tests/test_opengui_p2_memory.py** (2 tests):
- `test_policy_always_included` — MEM-05: POLICY entries in system prompt even with low top_k
- `test_memory_context_formatted_in_system_prompt` — MEM-05: formatted "Relevant Knowledge" section

### Task 2: Full regression check

All 57 tests pass: 8 P0 + 39 P1 + 10 P2.

### Bug fix discovered during testing

Fixed `_retrieve_memory` to fetch POLICY entries via a separate search call, not just filter from query results. Without this, POLICY entries with low query relevance could be missed.

## Key files

### key-files.modified
- `tests/test_opengui_p2_integration.py` — 8 integration tests replacing xfail stubs
- `tests/test_opengui_p2_memory.py` — 2 memory tests replacing xfail stubs
- `opengui/agent.py` — POLICY always-include bug fix

## Commits
- `1245a6f` fix(02-02): ensure POLICY memory entries always included via separate fetch
- `76bf055` test(02-04): replace Wave 0 xfail stubs with real integration and memory tests

## Deviations
- Fixed a bug in `_retrieve_memory`: POLICY entries need a separate search call to guarantee inclusion regardless of query relevance.

## Self-Check: PASSED
- [x] Integration test with DryRunBackend + mock LLM + memory + skill runs to completion
- [x] Memory entries appear in system prompt
- [x] Skill above threshold triggers SkillExecutor path
- [x] Trajectory JSONL has metadata/step/result events
- [x] TaskPlanner decomposes into AND/OR/ATOM tree
- [x] TreeRouter dispatches by capability type
- [x] Router replans on AND-child failure
- [x] POLICY always included regardless of relevance
- [x] 57 total tests pass, zero regressions
