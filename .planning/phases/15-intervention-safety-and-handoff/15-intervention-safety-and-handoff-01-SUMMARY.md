---
phase: 15-intervention-safety-and-handoff
plan: "01"
subsystem: testing
tags: [pytest, gui-agent, prompt-schema, action-parser, intervention-safety]
requires:
  - phase: 13-macos-background-execution
    provides: shared background execution contracts reused by Phase 15
  - phase: 14-windows-isolated-desktop-execution
    provides: isolated target-surface execution paths Phase 15 will hand off safely
provides:
  - Wave 0 regression tests for the explicit intervention action contract
  - Parser support for request_intervention with required reason text
  - Prompt and runtime tool schema parity for intervention requests
affects: [phase-15-plan-02, cli-handoff, nanobot-gui-tooling]
tech-stack:
  added: []
  patterns: [tdd-red-green, explicit-intervention-action-contract, prompt-parser-schema-parity]
key-files:
  created: [tests/test_opengui_p15_intervention.py]
  modified: [opengui/action.py, opengui/prompts/system.py, opengui/agent.py]
key-decisions:
  - "Intervention is a first-class action_type instead of overloading done or assistant free text."
  - "The parser, system prompt, and runtime tool schema must advertise the same request_intervention vocabulary."
patterns-established:
  - "Wave 0 contract tests land before pause/resume orchestration work."
  - "Sensitive or blocked states route through request_intervention with a required human-readable reason."
requirements-completed: [SAFE-01]
duration: 4min
completed: 2026-03-21
---

# Phase 15 Plan 01: Intervention Safety and Handoff Summary

**Wave 0 request_intervention contract across pytest coverage, the action parser, and both model-visible tool schemas**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-21T02:53:34Z
- **Completed:** 2026-03-21T02:57:33Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added focused Phase 15 tests that pin parser behavior and prompt/runtime schema parity for `request_intervention`
- Extended `parse_action()` and `describe_action()` to accept and describe intervention requests with non-empty reason text
- Updated both system prompt and runtime tool schema so the model is told to request intervention for sensitive, blocked, or unsafe states instead of using `done`

## Task Commits

1. **Task 1: Add Wave 0 tests for the explicit intervention action contract** - `5198050` (`test`)
2. **Task 2: Implement the explicit intervention action in parser and tool schemas** - `ead7a77`, `50b46ad` (`feat`, `fix`)

## Files Created/Modified
- `tests/test_opengui_p15_intervention.py` - Locks the explicit intervention contract with four focused pytest cases
- `opengui/action.py` - Accepts `request_intervention`, validates non-empty reason text, and describes the action for logs/debug output
- `opengui/prompts/system.py` - Exposes `request_intervention` in the tool enum and instructs the model to use it for sensitive, blocked, or unsafe states
- `opengui/agent.py` - Keeps the runtime `computer_use` schema aligned with the parser and prompt contract

## Decisions Made

- Added `request_intervention` as a first-class tool action now so later pause/resume work can branch on a deterministic contract.
- Required non-empty `text` for intervention requests to preserve a human-readable reason without starting broader lifecycle changes in this plan.

## Deviations from Plan

### Process deviations

- Task 2 landed as two commits instead of one because a transient `.git/index.lock` interrupted staging during the first implementation commit.
- Impact on plan: no behavior changed beyond the planned scope, and the final verification run passed against the completed working tree.

## Issues Encountered

- A transient git index lock caused two staging attempts to fail mid-task. I retried staging sequentially, confirmed the first implementation commit only touched `opengui/prompts/system.py`, and completed the remaining parser/runtime changes in a follow-up commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 15 now has a locked `SAFE-01` action/schema contract for the deeper pause/resume and trace-scrubbing work in Plans 02-04.
- No functional blockers remain for the next plan.

## Self-Check

PASSED

- Found summary file on disk
- Verified task commits `5198050`, `ead7a77`, and `50b46ad` in git history

---
*Phase: 15-intervention-safety-and-handoff*
*Completed: 2026-03-21*
