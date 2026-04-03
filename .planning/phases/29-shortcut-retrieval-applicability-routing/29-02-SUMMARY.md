---
phase: 29-shortcut-retrieval-applicability-routing
plan: "02"
subsystem: opengui/agent
tags: [shortcut-router, applicability, trajectory, tdd, nanobot-wiring]
dependency_graph:
  requires:
    - phase: 29-01
      provides: ShortcutApplicabilityRouter, ApplicabilityDecision, filter_candidates_by_context, shortcut_candidates in run()
    - opengui/skills/executor.py (LLMStateValidator as ConditionEvaluator)
  provides:
    - opengui/agent.py (_evaluate_shortcut_applicability, applicability gate in run(), retry clearing)
    - nanobot/agent/tools/gui.py (ShortcutApplicabilityRouter wired with LLMStateValidator)
  affects:
    - Phase 30 (any future phases that extend shortcut execution or evaluation)
tech-stack:
  added: []
  patterns:
    - applicability gate evaluates candidates in score order, returns first passing decision
    - trajectory event emitted on every code path (no_candidates, no_router, run, all_failed)
    - _shortcut_attempted flag drives retry clearing for free-exploration fallback
    - lazy import of ShortcutApplicabilityRouter inside enable_skill_execution guard
key-files:
  created: []
  modified:
    - opengui/agent.py
    - nanobot/agent/tools/gui.py
    - tests/test_opengui_p29_retrieval_applicability.py
key-decisions:
  - "Applicability evaluation takes a pre-loop observation inside the retry loop at attempt==0 so the screenshot is as close to execution time as possible"
  - "All four code paths (no_candidates, no_router, run, all_candidates_failed) emit shortcut_applicability trajectory event for full traceability"
  - "_shortcut_attempted flag tracks whether first attempt used a shortcut; retries after failure clear matched_skill and skill_context unconditionally"
  - "ShortcutApplicabilityRouter wired only when enable_skill_execution=True because state_validator (LLMStateValidator) is only constructed in that branch"
  - "Legacy _search_skill path is preserved unchanged; applicability-selected shortcut takes priority when shortcut_candidates is non-empty and router returns run"

requirements-completed: [SUSE-02]

duration: 7min
completed: "2026-04-03"
---

# Phase 29 Plan 02: Applicability Evaluation Gate and Nanobot Wiring Summary

**Screen-aware shortcut applicability gate added to GuiAgent.run() with live screenshot precondition evaluation, structured outcome tracing, retry clearing, and real LLMStateValidator wired into the nanobot host path.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-03T04:32:01Z
- **Completed:** 2026-04-03T04:39:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added `_evaluate_shortcut_applicability()` to `GuiAgent` that iterates candidates in score order, evaluates preconditions using `ShortcutApplicabilityRouter`, and returns the first passing `ApplicabilityDecision`
- Integrated the applicability gate inside `run()` retry loop at attempt 0: captures a live screenshot before evaluating candidates; on "run" outcome, injects the approved shortcut for execution
- Clears `matched_skill` and `skill_context` on retries after a failed shortcut attempt via `_shortcut_attempted` flag so retries use free exploration
- All 4 code paths emit a `shortcut_applicability` trajectory event (no_candidates, no_applicability_router, run, all_candidates_failed) for complete traceability
- Wired `ShortcutApplicabilityRouter(condition_evaluator=state_validator)` into `nanobot/agent/tools/gui.py` `_run_task()` when `enable_skill_execution=True`
- Added 9 SUSE-02 test cases (8 in Task 1, 1 in Task 2); all Phase 27/28/29 tests green (47 total)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add applicability evaluation gate in GuiAgent.run() and SUSE-02 tests** - `5b68647` (feat)
2. **Task 2: Wire ShortcutApplicabilityRouter into nanobot host path and run regression** - `d5e7ce1` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py` — Added `_evaluate_shortcut_applicability()` method; modified `run()` to call it inside the retry loop at attempt==0 with live screenshot; added `_shortcut_attempted` flag and retry clearing logic
- `/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py` — Added `ShortcutApplicabilityRouter` construction in `_run_task()` when `enable_skill_execution=True`; passed as `shortcut_applicability_router` to `GuiAgent` constructor
- `/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p29_retrieval_applicability.py` — Added 9 new test cases: `test_applicability_run_when_conditions_pass`, `test_applicability_skip_when_condition_fails`, `test_applicability_exception_produces_fallback`, `test_fallback_when_no_candidates`, `test_applicability_emits_trajectory_event`, `test_applicability_selects_first_passing_candidate`, `test_failed_shortcut_clears_for_retry`, `test_normal_path_unchanged_when_no_shortcut`, `test_nanobot_wires_applicability_router`

## Decisions Made

1. **Observation inside retry loop**: Taking the pre_shortcut_check screenshot inside `attempt==0` of the retry loop (not before the loop) ensures the observation is as temporally close to execution as possible. A pre-loop screenshot could become stale if other setup work takes time.

2. **All-paths event emission**: Every possible outcome of `_evaluate_shortcut_applicability` emits a `shortcut_applicability` trajectory event. This is essential for debugging and audit — it means the trajectory always records whether a shortcut was considered, approved, or rejected.

3. **`_shortcut_attempted` flag**: Using an explicit flag rather than inspecting `matched_skill` on retry is cleaner and avoids ambiguity with the legacy `_search_skill` path. The flag is set only when shortcut candidates lead to an approved execution attempt.

4. **Router wired only with skill_execution**: `LLMStateValidator` is only constructed when `enable_skill_execution=True`, so wiring the router inside that branch is the natural and correct location with no code duplication.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — all tests passed on first run after implementation.

## Self-Check

- opengui/agent.py contains `async def _evaluate_shortcut_applicability`: FOUND (line 1711)
- opengui/agent.py contains `record_event.*shortcut_applicability`: FOUND (lines 1739, 1756, 1783, 1807)
- opengui/agent.py run() contains `applicability_decision`: FOUND (line 557)
- opengui/agent.py contains logic to clear matched_skill on retry: FOUND (line 612)
- nanobot/agent/tools/gui.py contains `ShortcutApplicabilityRouter`: FOUND (line 229, 255)
- tests: all 9 new test functions present and passing
- `uv run pytest tests/test_opengui_p29_retrieval_applicability.py -x -q`: 20 passed
- `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py -x -q`: 47 passed

## Self-Check: PASSED

## Next Phase Readiness

- Phase 29 complete: multi-candidate retrieval (Plan 01) + applicability gate (Plan 02) both shipped
- Full SUSE-02 requirement satisfied with structured decision, trajectory event, and retry clearing
- Nanobot production path wired with real LLM-backed applicability evaluation
- Phase 30 can build on the applicability gate for execution stability improvements

---
*Phase: 29-shortcut-retrieval-applicability-routing*
*Completed: 2026-04-03*
