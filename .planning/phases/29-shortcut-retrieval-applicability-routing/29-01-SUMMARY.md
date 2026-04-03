---
phase: 29-shortcut-retrieval-applicability-routing
plan: "01"
subsystem: opengui/skills
tags: [shortcut-router, retrieval, filtering, trajectory, tdd]
dependency_graph:
  requires:
    - opengui/skills/shortcut.py (ShortcutSkill, StateDescriptor)
    - opengui/skills/shortcut_store.py (SkillSearchResult, UnifiedSkillSearch)
    - opengui/skills/normalization.py (normalize_app_identifier)
    - opengui/skills/multi_layer_executor.py (ConditionEvaluator protocol)
    - opengui/trajectory/recorder.py (TrajectoryRecorder.record_event)
  provides:
    - opengui/skills/shortcut_router.py (ApplicabilityDecision, ShortcutApplicabilityRouter, filter_candidates_by_context)
    - opengui/agent.py (_retrieve_shortcut_candidates, shortcut_applicability_router param)
  affects:
    - opengui/agent.py (GuiAgent.run() now calls _retrieve_shortcut_candidates at step 3b)
tech_stack:
  added:
    - opengui/skills/shortcut_router.py (new module)
  patterns:
    - frozen dataclass for immutable decision record
    - pluggable evaluator with always-pass default for dry-run safety
    - pure function filter with platform-first + app-fallback strategy
    - trajectory event emission on every retrieval call
key_files:
  created:
    - opengui/skills/shortcut_router.py
    - tests/test_opengui_p29_retrieval_applicability.py
  modified:
    - opengui/agent.py
decisions:
  - "filter_candidates_by_context falls back to platform-only results when normalized app filter is empty, preserving retrieval recall over precision"
  - "shortcut_candidates stored but not yet used for execution gating — Plan 02 adds applicability evaluation gate"
  - "_AlwaysPassEvaluator default enables all test and dry-run scenarios without LLM or device dependency"
  - "top_k=5 for multi-candidate retrieval vs top_k=1 for legacy _search_skill — both paths coexist through Plan 02"
metrics:
  duration_minutes: 6
  completed_date: "2026-04-03"
  tasks_completed: 2
  files_created: 2
  files_modified: 1
---

# Phase 29 Plan 01: Multi-Candidate Shortcut Retrieval and Applicability Routing Summary

**One-liner:** Multi-candidate shortcut retrieval with platform/app filtering via new `shortcut_router.py` module, wired into `GuiAgent.run()` as a pre-loop step that emits a `shortcut_retrieval` trajectory event.

## What Was Built

### Task 1: shortcut_router.py and retrieval regression tests (TDD)

**RED phase** — wrote `tests/test_opengui_p29_retrieval_applicability.py` with 10 test cases that initially failed (module not found).

**GREEN phase** — created `opengui/skills/shortcut_router.py`:

- `ApplicabilityDecision` — frozen dataclass with `outcome: Literal["run","skip","fallback"]`, `shortcut_id`, `reason`, `score`, `failed_condition` fields
- `_AlwaysPassEvaluator` — private class returning `True` for all conditions; used as default when no real evaluator is injected
- `ShortcutApplicabilityRouter` — accepts any `ConditionEvaluator`-compatible object; iterates preconditions, returns `skip` on first failure with `failed_condition` set, `run` on all pass, `fallback` on exception
- `filter_candidates_by_context` — pure function: always filters by platform, optionally by normalized app (with fallback to platform-only if app filter yields empty list)

### Task 2: Wire multi-candidate retrieval into GuiAgent.run()

Modified `opengui/agent.py`:

1. Added top-level imports: `ShortcutApplicabilityRouter`, `filter_candidates_by_context`, `normalize_app_identifier`
2. Added `shortcut_applicability_router: ShortcutApplicabilityRouter | None = None` parameter to `GuiAgent.__init__`, stored as `self._shortcut_applicability_router`
3. Added `_retrieve_shortcut_candidates(task, *, platform, app_hint)` async method: calls `unified_skill_search.search(task, top_k=5)`, applies score threshold, calls `filter_candidates_by_context`, emits `shortcut_retrieval` trajectory event
4. Called `_retrieve_shortcut_candidates` in `run()` at step 3b (between skill search and skill execution) — stored as `shortcut_candidates` for Plan 02 usage
5. The existing `_search_skill` path is **unchanged** — Plan 02 will integrate the applicability gate

Implemented `test_retrieval_in_agent_run` — verifies platform filtering (2 android, 1 ios → 2 returned), trajectory event emission with correct `candidate_count`, `task`, and `platform` keys.

## Verification Results

```
uv run pytest tests/test_opengui_p29_retrieval_applicability.py -q
11 passed in 0.08s

uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py -q
27 passed in 10.52s

uv run python -c "from opengui.skills.shortcut_router import ApplicabilityDecision, ShortcutApplicabilityRouter, filter_candidates_by_context; print('OK')"
OK
```

## Decisions Made

1. **filter fallback strategy**: When normalized app filter produces empty results, fall back to platform-only list. This preserves retrieval recall — a shortcut in the right platform but wrong-app slot is better than no candidates at all.

2. **coexist with legacy path**: `_search_skill` (top_k=1, score-only gate) remains unchanged. `_retrieve_shortcut_candidates` runs alongside it. Plan 02 will integrate the applicability decision to replace the score-only gate for shortcut candidates.

3. **always-pass default evaluator**: `_AlwaysPassEvaluator` is the default to keep test and dry-run environments free of LLM/device dependencies, consistent with Phase 25's `ShortcutExecutor` design.

4. **top_k=5**: Five candidates gives the applicability gate in Plan 02 enough options while keeping retrieval cost bounded.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- opengui/skills/shortcut_router.py: FOUND
- tests/test_opengui_p29_retrieval_applicability.py: FOUND
- .planning/phases/29-shortcut-retrieval-applicability-routing/29-01-SUMMARY.md: FOUND
- Commits 3762004, beed732, 93a6f92: FOUND
