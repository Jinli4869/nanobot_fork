---
phase: 25-multi-layer-execution
plan: "01"
subsystem: skills
tags: [shortcut-execution, contract-verification, grounding-protocol, tdd, protocols]

# Dependency graph
requires:
  - phase: 24-schema-and-grounding
    provides: ShortcutSkill, StateDescriptor, ParameterSlot, GrounderProtocol, GroundingContext, GroundingResult

provides:
  - ConditionEvaluator protocol for evaluating StateDescriptor conditions against screenshots
  - ContractViolationReport dataclass for typed pre/post condition violation reporting
  - ShortcutStepResult per-step execution record with grounding metadata
  - ShortcutExecutionSuccess result dataclass with discriminator field
  - ShortcutExecutor dataclass executing ShortcutSkill with pluggable grounding and condition evaluation
  - opengui.skills __all__ extended with all Phase 25 shortcut executor types

affects:
  - 25-02 (Phase 25 Plan 02 - TaskSkillExecutor will inject ShortcutExecutor)
  - 27 (Phase 27 will wire ShortcutExecutor with real ConditionEvaluator and GrounderProtocol)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Discriminated union result via is_violation field (ContractViolationReport.is_violation=True vs ShortcutExecutionSuccess.is_violation=False)"
    - "Optional protocol injection with always-pass default for dry-run/test scenarios"
    - "Shared step execution normalizes all actions through parse_action() for centralized validation"
    - "TDD RED/GREEN cycle: failing test committed before implementation"

key-files:
  created:
    - opengui/skills/multi_layer_executor.py
    - tests/test_opengui_p25_multi_layer_execution.py
  modified:
    - opengui/skills/__init__.py
    - tests/test_opengui_p1_skills.py

key-decisions:
  - "ShortcutExecutor is a new module (multi_layer_executor.py), NOT an extension of legacy executor.py — incompatible fail-open and template fallback semantics"
  - "ConditionEvaluator defaults to always-pass (_AlwaysPassEvaluator) when not injected — enables dry-run and test scenarios with no LLM/device dependency"
  - "Fixed steps bypass grounder entirely; all actions normalize through parse_action() so validation stays centralized"
  - "Pre/post conditions are checked on EVERY step (not once per skill) — per locked Phase 25 design decision"
  - "Caller-supplied literal params win over grounder-returned resolved_params on key conflict"

patterns-established:
  - "Pattern: @runtime_checkable Protocol injection with optional default — same style as StateValidator, ActionGrounder in executor.py"
  - "Pattern: is_violation discriminator field enables clean pattern-matching without isinstance() in caller code"
  - "Pattern: _screenshot_path() helper builds deterministic screenshot filenames as {skill_id}-step-{step_index:03d}-{boundary}.png"

requirements-completed: [EXEC-01, EXEC-03]

# Metrics
duration: 4min
completed: 2026-04-02
---

# Phase 25 Plan 01: Multi-layer Execution Summary

**ShortcutExecutor with typed pre/post contract violation reports and pluggable GrounderProtocol grounding seam — EXEC-01 and EXEC-03 satisfied**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T08:09:15Z
- **Completed:** 2026-04-02T08:13:42Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- New `opengui/skills/multi_layer_executor.py` module with ConditionEvaluator protocol, ContractViolationReport/ShortcutExecutionSuccess discriminated union, and ShortcutExecutor
- ShortcutExecutor checks preconditions before each step and postconditions after each step; aborts immediately with typed ContractViolationReport on first failure
- Grounding seam: non-fixed steps route through GrounderProtocol.ground() and normalize through parse_action(); stub grounder swaps behavior without touching executor code
- Fixed steps bypass grounder entirely, still normalize through parse_action() for centralized action validation
- Phase 25 types added to opengui.skills.__all__ alongside all legacy exports

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing Phase 25 coverage (TDD RED)** - `94cfdd5` (test)
2. **Task 2: Implement ShortcutExecutor (TDD GREEN)** - `b057924` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD tasks have two commits — test (RED) then feat (GREEN)_

## Files Created/Modified

- `opengui/skills/multi_layer_executor.py` — ConditionEvaluator protocol, ContractViolationReport/ShortcutStepResult/ShortcutExecutionSuccess dataclasses, ShortcutExecutor with shared step runner
- `opengui/skills/__init__.py` — Phase 25 exports added to __all__ (ConditionEvaluator, ContractViolationReport, ShortcutExecutionSuccess, ShortcutExecutor, ShortcutStepResult)
- `tests/test_opengui_p25_multi_layer_execution.py` — 5 contract tests covering pre/post violations, grounder seam, fixed-value bypass, and package exports
- `tests/test_opengui_p1_skills.py` — Extended package export compatibility assertion to include Phase 25 types

## Decisions Made

- **New module, not extension:** `multi_layer_executor.py` is a separate file from `executor.py` because the legacy executor has fail-open validation and template-substitution semantics incompatible with Phase 25 strict contract requirements
- **Always-pass default:** `ConditionEvaluator` is optional; absence defaults to `_AlwaysPassEvaluator` so executors are usable in dry-run/test scenarios without a real evaluator
- **Centralized parse_action():** Both fixed and non-fixed steps normalize through `parse_action()` — this reuses the canonical action validation boundary and prevents drift
- **Per-step condition checks:** Preconditions evaluated before each step, postconditions after each step (not once-per-skill) per locked Phase 25 design

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 25 Plan 02 (TaskSkillExecutor) can inject ShortcutExecutor and share the same step runner pattern
- Phase 27 can wire real ConditionEvaluator and GrounderProtocol implementations into ShortcutExecutor at construction time
- Legacy SkillExecutor in executor.py remains unchanged — backward compatibility fully preserved

---
*Phase: 25-multi-layer-execution*
*Completed: 2026-04-02*
