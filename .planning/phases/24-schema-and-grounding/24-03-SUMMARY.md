---
phase: 24-schema-and-grounding
plan: "03"
subsystem: grounding
tags: [opengui, grounding, protocol, llm, import-safety]
requires:
  - phase: 24-schema-and-grounding
    provides: parameter slot and state descriptor schema primitives from 24-01
provides:
  - runtime-checkable grounding protocol and structured context/result DTOs
  - LLMGrounder implementation that returns parameter-resolution metadata
  - compile/import safety coverage for new grounding modules
affects: [25-multi-layer-execution, 26-quality-gated-extraction]
tech-stack:
  added: []
  patterns: [protocol-based grounding, structured DTO returns, compile-gate verification]
key-files:
  created:
    - opengui/grounding/__init__.py
    - opengui/grounding/protocol.py
    - opengui/grounding/llm.py
  modified:
    - tests/test_opengui_p24_schema_grounding.py
key-decisions:
  - "GrounderProtocol resolves semantic targets into `GroundingResult` metadata instead of constructing executable actions directly."
  - "GroundingContext carries `Observation`, screenshot path, parameter slots, and optional task hint so later executors receive grounding inputs without importing agent runtime code."
  - "LLMGrounder accepts the existing `LLMProvider` contract and parses either JSON content or tool-call argument payloads into `resolved_params`."
patterns-established:
  - "Keep grounding import-safe by isolating public contracts in `opengui/grounding/protocol.py` and re-exporting them through `opengui/grounding/__init__.py`."
  - "Use compile-gate verification alongside unit tests whenever a phase's success criteria include import and type-safety seams."
requirements-completed: [GRND-01, GRND-02, GRND-03]
duration: 1min
completed: 2026-04-02
---

# Phase 24 Plan 03: Grounding Protocol Package Summary

**OpenGUI now exposes a reusable grounding package with protocol/result DTOs and an LLM-backed grounder that returns structured parameter-resolution metadata**

## Performance

- **Duration:** 1 min
- **Started:** 2026-04-02T03:58:34Z
- **Completed:** 2026-04-02T03:59:19Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added `GrounderProtocol`, `GroundingContext`, and `GroundingResult` in a dedicated `opengui/grounding/protocol.py` module.
- Implemented `LLMGrounder` as a thin `LLMProvider`-backed adapter that returns `GroundingResult` instead of action objects.
- Added grounding regression tests plus a compile/import gate covering the new `opengui/grounding` package and its schema dependencies.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing tests for grounding protocol, result DTOs, and import safety** - `d606758` (test)
2. **Task 2: Implement the grounding package and compile/import sanity gate** - `8dce304` (feat)

## Files Created/Modified
- `opengui/grounding/protocol.py` - grounding protocol plus context/result dataclasses with explicit serializers
- `opengui/grounding/llm.py` - `LLMGrounder` adapter that parses LLM output into structured parameter metadata
- `opengui/grounding/__init__.py` - public package exports for the grounding contract surface
- `tests/test_opengui_p24_schema_grounding.py` - grounding DTO, protocol conformance, and import-safety coverage

## Decisions Made
- Kept grounding contracts executor-agnostic by returning `resolved_params` instead of `Action` instances.
- Serialized `Observation` inside `GroundingContext` manually so the grounding package stays decoupled from executor helpers while remaining JSON-friendly.
- Supported both JSON response bodies and tool-call argument dicts in `LLMGrounder` so future providers can supply structured grounding payloads either way.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 25 can now route all parameter grounding through `GrounderProtocol` without coupling executor logic to the current private agent grounding path.
- Phase 26 can consume `GroundingContext`, `GroundingResult`, and `ParameterSlot` without reopening the import boundary design.

## Self-Check: PASSED
- Found summary file on disk.
- Verified task commits `d606758` and `8dce304` in git history.
- Verified `uv run pytest -q tests/test_opengui_p1_skills.py tests/test_opengui_p1_memory.py tests/test_opengui_p24_schema_grounding.py` exits 0.
- Verified `uv run python -m py_compile opengui/skills/data.py opengui/skills/shortcut.py opengui/skills/task_skill.py opengui/grounding/__init__.py opengui/grounding/protocol.py opengui/grounding/llm.py` exits 0.

---
*Phase: 24-schema-and-grounding*
*Completed: 2026-04-02*
