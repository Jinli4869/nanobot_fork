---
phase: 26-quality-gated-extraction
plan: "02"
subsystem: opengui/skills
tags: [extraction, pipeline, exports, tdd, regression]
dependency_graph:
  requires: [26-01, phase-24, phase-25]
  provides: [ExtractionPipeline, package exports]
  affects: [opengui/skills/__init__.py, phase-26-verification]
tech_stack:
  added: []
  patterns:
    - Short-circuit pipeline orchestration across step critic, trajectory critic, and producer
    - Always-pass default critic seam for low-friction callers and isolated tests
    - Package-level re-exports that preserve legacy skills surface while adding Phase 26 types
key_files:
  created: []
  modified:
    - opengui/skills/shortcut_extractor.py
    - opengui/skills/__init__.py
    - tests/test_opengui_p26_quality_gated_extraction.py
decisions:
  - "ExtractionPipeline rejects trajectories with fewer than two steps before invoking any critic, keeping invalid traces cheap to discard."
  - "Step critic failures short-circuit before trajectory review, and trajectory failures short-circuit before skill production."
  - "Phase 26 symbols are exported from opengui.skills so callers can adopt the new pipeline without deep module imports."
metrics:
  completed_date: "2026-04-02"
  tasks: 2
  files: 3
requirements_completed: [EXTR-03]
---

# Phase 26 Plan 02: Quality-Gated Extraction Pipeline Summary

**One-liner:** Added `ExtractionPipeline` to orchestrate step and trajectory critics in order, then exported the full Phase 26 surface from `opengui.skills`.

## What Was Built

- Added `_AlwaysPassStepCritic`, `_AlwaysPassTrajectoryCritic`, and `ExtractionPipeline` to `opengui/skills/shortcut_extractor.py`.
- Wired the pipeline to reject short trajectories early, stop on the first failing step verdict, stop on failed trajectory verdicts, and only call `ShortcutSkillProducer` after both critics pass.
- Exported `ExtractionPipeline`, verdict/result types, critic protocols, and `ShortcutSkillProducer` from `opengui.skills`.
- Extended Phase 26 tests with pipeline sequencing coverage, default-critic behavior, and package-export assertions.

## Verification Results

```bash
uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q
20 passed in 0.12s

uv run pytest tests/test_opengui_p24_schema_grounding.py tests/test_opengui_p25_multi_layer_execution.py tests/test_opengui_p26_quality_gated_extraction.py -q
43 passed in 0.19s
```

## Task Commits

1. **Task 1 + Task 2: Add pipeline orchestration and package exports** - `858289f` (`feat(26-02): add quality-gated extraction pipeline`)

## Self-Check: PASSED

- `opengui/skills/shortcut_extractor.py` contains `_AlwaysPassStepCritic`, `_AlwaysPassTrajectoryCritic`, and `ExtractionPipeline`
- `ExtractionPipeline.run()` returns `too_few_steps`, `step_critic`, and `trajectory_critic` rejections on the expected branches
- `opengui/skills/__init__.py` re-exports all eight Phase 26 public types
- Phase 24, 25, and 26 regression tests pass together
