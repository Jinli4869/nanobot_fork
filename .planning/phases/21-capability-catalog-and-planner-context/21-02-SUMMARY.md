---
phase: 21-capability-catalog-and-planner-context
plan: "02"
subsystem: planner
tags: [planner, routing, memory, prompt-budget, testing]
requires:
  - phase: 21-capability-catalog-and-planner-context
    provides: live planner capability catalog and planning-context seam from 21-01
provides:
  - planner-only routing-memory hint DTOs and read-only extraction from MemoryStore
  - bounded planner prompt rendering for routing memory hints with omission marker
  - loop-time injection of routing hints into PlanningContext before planner.plan()
affects: [22-route-aware-tool-and-mcp-dispatch, 23-routing-memory-feedback-and-verification]
tech-stack:
  added: []
  patterns: [read-only planner memory extraction, bounded prompt serialization, TDD task commits]
key-files:
  created:
    - nanobot/agent/planning_memory.py
  modified:
    - nanobot/agent/capabilities.py
    - nanobot/agent/planner.py
    - nanobot/agent/loop.py
    - tests/test_opengui_p21_planner_context.py
    - tests/test_opengui_p8_planning.py
key-decisions:
  - "Routing memory stays planner-only and read-only by extracting compact DTOs from MemoryStore instead of reusing ContextBuilder or get_memory_context()."
  - "Planner prompts render routing memory in a separate capped section with explicit omission text once hint count or budget limits are hit."
  - "AgentLoop builds routing hints immediately before planning so the live catalog and memory evidence stay aligned without changing router dispatch behavior."
patterns-established:
  - "Keep planner memory bounded by serializing at most five hints, 160 characters per line, and 900 total characters."
  - "Use prompt-level omission markers instead of forwarding extra hint text when planner context exceeds budget."
requirements-completed: [CAP-02]
duration: 7min
completed: 2026-03-22
---

# Phase 21 Plan 02: Planning Memory Hints And Prompt Guardrails Summary

**Planner-only routing-memory hints extracted from MemoryStore, injected into planning context, and rendered under explicit prompt-size guardrails**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-22T07:57:00Z
- **Completed:** 2026-03-22T08:03:34Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Added `PlanningMemoryHint`, `PlanningMemoryHintExtractor`, and bounded serialization helpers in `nanobot/agent/planning_memory.py`.
- Wired `AgentLoop._plan_and_execute()` to extract routing hints before planning and pass them through `PlanningContext(memory_hints=...)`.
- Updated `TaskPlanner` to render a dedicated `Routing memory hints:` block only when hints exist, with explicit truncation behavior and regression coverage proving unrelated memory stays out.

## Task Commits

Each task was committed atomically:

1. **Task 1: Define routing-memory hint contracts and failing exclusion/guardrail coverage** - `98b83f1` (test), `877958a` (feat)
2. **Task 2: Wire bounded memory hints into the planner context and preserve prompt-size safety** - `4aad951` (test), `d954583` (feat)

## Files Created/Modified
- `nanobot/agent/planning_memory.py` - planner-only hint DTOs, read-only extraction, and bounded serialization
- `nanobot/agent/capabilities.py` - `PlanningContext` typing updated to carry hint DTOs
- `nanobot/agent/planner.py` - bounded `Routing memory hints:` prompt section with omission marker
- `nanobot/agent/loop.py` - routing-hint extraction before `planner.plan(...)`
- `tests/test_opengui_p21_planner_context.py` - red/green coverage for hint extraction, exclusion, and prompt guardrails
- `tests/test_opengui_p8_planning.py` - `_plan_and_execute()` regression coverage for injected memory hints

## Decisions Made
- `PlanningMemoryHintExtractor` reads `MEMORY.md` plus a bounded tail of `HISTORY.md`, but only keeps snippets containing route evidence and outcome language.
- Hint serialization is shared between extraction tests and planner prompt rendering so the count and size caps are enforced in one place.
- The planner prompt keeps capability catalog lines first and appends routing hints only when non-empty, preserving the planner-only boundary from 21-01.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected `PlanningContext` hint typing to match the Phase 21 contract**
- **Found during:** Task 2
- **Issue:** `PlanningContext.memory_hints` still used `tuple[str, ...]`, which no longer matched the plan's planner-only hint DTO contract.
- **Fix:** Updated `nanobot/agent/capabilities.py` to carry `PlanningMemoryHint` instances through the existing planning-context seam.
- **Files modified:** `nanobot/agent/capabilities.py`
- **Verification:** `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_mcp_tool.py tests/test_opengui_p21_planner_context.py`
- **Committed in:** `d954583`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The fix was contract-alignment work required to complete the planned hint plumbing cleanly. No scope creep.

## Issues Encountered
- None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- CAP-02 is now satisfied with bounded planner-only routing hints and prompt guardrails proven by regression tests.
- Phase 22 can consume `route_id` plus memory-biased planning output without revisiting planner prompt shape again.

## Self-Check: PASSED
- Found summary file on disk.
- Verified task commits `98b83f1`, `877958a`, `4aad951`, and `d954583` in git history.
