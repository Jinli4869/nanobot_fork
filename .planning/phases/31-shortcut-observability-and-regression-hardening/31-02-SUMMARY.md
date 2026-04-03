---
phase: 31-shortcut-observability-and-regression-hardening
plan: "02"
subsystem: testing
tags: [shortcut-executor, grounding, tdd, regression-seam, extraction-pipeline]

requires:
  - phase: 31-01
    provides: ShortcutExecutor trajectory_recorder injection and telemetry events
  - phase: 26
    provides: ShortcutExtractor/_to_skill_step() writing step.parameters from trace action fields
  - phase: 28
    provides: ShortcutPromotionPipeline.promote_from_trace() and ShortcutSkillStore

provides:
  - "ShortcutExecutor._execute_step() non-fixed branch now seeds merged payload with step.parameters before grounding overlay"
  - "test_extracted_step_parameters_feed_non_fixed_execution: unit seam for parameter merge logic"
  - "test_android_extraction_execution_seam: end-to-end Android JSONL trace -> promote -> execute pipeline"
  - "test_macos_extraction_execution_seam: end-to-end macOS JSONL trace -> promote -> execute pipeline"
  - "_FakeDesktopBackend, _FixtureGrounder, _write_jsonl helpers for future regression tests"

affects:
  - "Any future phase that executes promoted shortcuts through ShortcutExecutor"
  - "Phase 29/30 tests remain stable after the merge order fix"

tech-stack:
  added: []
  patterns:
    - "Three-layer non-fixed step merge: step.parameters < grounding.resolved_params < caller params"
    - "_FixtureGrounder pattern: deterministic dict-keyed grounder for seam tests"
    - "JSONL trace fixture constant + _write_jsonl helper for promotion integration tests"

key-files:
  created:
    - tests/test_opengui_p31_shortcut_observability.py (expanded with 3 new tests + 4 helpers)
  modified:
    - opengui/skills/multi_layer_executor.py

key-decisions:
  - "Three-layer merge order in non-fixed steps: step.parameters (lowest) -> grounding.resolved_params -> caller params (highest). Grounding values override stale recorded trace coords while step.parameters still provide static fields like 'text' and 'key'."
  - "Do not mark promoted steps fixed=True as a workaround — the seam must remain a non-fixed shortcut path so live re-grounding of coordinates works correctly."
  - "_FixtureGrounder raises AssertionError for unregistered targets to prevent silent test passes from unexpected grounder calls."

patterns-established:
  - "Promoted shortcut test pattern: JSONL fixture constant -> _write_jsonl -> ShortcutPromotionPipeline -> ShortcutSkillStore -> ShortcutExecutor with _FixtureGrounder"

requirements-completed: [SSTA-04]

duration: 8min
completed: 2026-04-03
---

# Phase 31 Plan 02: Promotion-to-Execution Seam Hardening Summary

**Three-layer step.parameters merge closes the extraction-to-execution seam: promoted shortcuts now carry static trace fields through ShortcutExecutor with Android and macOS regression tests proving pipeline stability.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-03T10:38:30Z
- **Completed:** 2026-04-03T10:44:18Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Fixed `ShortcutExecutor._execute_step()` to seed the non-fixed action payload with `step.parameters` before overlaying live grounding values, enabling promoted `input_text` and other typed-field steps to execute correctly
- Added Android end-to-end seam test: JSONL trace fixture promotes into `ShortcutSkillStore` and executes with a deterministic `_FixtureGrounder` verifying both grounder-provided coordinates (tap) and trace-preserved text (input_text)
- Added macOS end-to-end seam test: JSONL trace fixture with two tap steps promotes into `ShortcutSkillStore` as a macOS shortcut and executes through `_FakeDesktopBackend`
- All 56 Phase 28/29/30/31 tests remain green after the merge order change

## Task Commits

1. **Task 1 (RED): Add failing regression seam tests** - `39998c9` (test)
2. **Task 1 (GREEN): Implement step.parameters merge fix** - `cf2adfa` (feat)

**Plan metadata:** (docs commit to follow)

_Note: TDD task — RED commit first with failing tests, GREEN commit with minimal production fix._

## Files Created/Modified

- `opengui/skills/multi_layer_executor.py` - Non-fixed step merge now seeds from `step.parameters` before `grounding.resolved_params`, with explicit 3-layer comment
- `tests/test_opengui_p31_shortcut_observability.py` - Added `_FakeDesktopBackend`, `_FixtureGrounder`, `_write_jsonl`, JSONL fixture constants, and 3 new seam tests

## Decisions Made

- **Three-layer merge order**: `step.parameters` (static trace fields, lowest priority) then `grounding.resolved_params` (live re-ground, overrides stale coords) then caller `params` (unconditional override). This ensures promoted shortcuts carry their type-specific fields while remaining live-groundable.
- **Do not use fixed=True workaround**: Promoted steps must stay non-fixed so grounder can rebind coordinates dynamically. The seam closes at the merge layer, not the routing layer.
- **_FixtureGrounder raises on unregistered targets**: Prevents silent test success from unexpected grounder calls. Tests must declare all expected targets explicitly.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SSTA-04 is now fully satisfied: promoted shortcuts execute through the real non-fixed ShortcutExecutor path
- Phase 31 is complete: both P01 telemetry and P02 regression seam work are done
- The promotion-to-execution pipeline is proven stable on representative Android and macOS seams
- Prior phases 28/29/30 remain fully green

---
*Phase: 31-shortcut-observability-and-regression-hardening*
*Completed: 2026-04-03*
