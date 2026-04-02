---
phase: 28-shortcut-extraction-productionization
plan: "03"
subsystem: testing
tags: [pytest, shortcut-promotion, gui-postprocessing, regression]
requires:
  - phase: 28-01
    provides: GUI postprocessing cutover to shortcut promotion
  - phase: 28-02
    provides: provenance, gating, and merge/version behavior for promoted shortcuts
provides:
  - Phase-local regression coverage for summary/result noise, retry noise, and duplicate promotions
  - Canonical-search compatibility coverage after shortcut merge/version updates
  - Background postprocessing seam coverage on the live `_promote_shortcut` path
affects: [phase-29-shortcut-retrieval-and-applicability-routing, phase-8-trajectory-tests, phase-11-integration-tests]
tech-stack:
  added: []
  patterns:
    - Patch `_promote_shortcut` and adjacent postprocessing helpers instead of legacy extractor seams
    - Verify shortcut merge behavior through both store count/version assertions and search canonical-id assertions
key-files:
  created:
    - .planning/phases/28-shortcut-extraction-productionization/28-03-SUMMARY.md
  modified:
    - tests/test_opengui_p28_shortcut_productionization.py
    - tests/test_opengui_p27_storage_search_agent.py
    - tests/test_opengui_p8_trajectory.py
    - tests/test_opengui_p11_integration.py
key-decisions:
  - "Phase 28 regression coverage now binds GUI postprocessing tests to `_promote_shortcut` rather than the removed legacy extractor seam."
  - "Duplicate-promotion compatibility is locked at both merge and search layers so canonical shortcut ids survive version bumps."
patterns-established:
  - "Background postprocessing seam tests should block `_promote_shortcut` directly when proving execute() returns before postprocessing finishes."
  - "Promotion lifecycle regressions should assert both no-write behavior and canonical store/search outcomes."
requirements-completed: [SXTR-01, SXTR-02, SXTR-03, SXTR-04]
duration: 8min
completed: 2026-04-02
---

# Phase 28 Plan 03: Regression Hardening Summary

**Regression matrix for shortcut promotion noise rejection, duplicate merge/versioning, and non-blocking GUI postprocessing on the production seam**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-02T17:00:29Z
- **Completed:** 2026-04-02T17:08:37Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added Phase 28 regression tests for summary/result noise, retry noise, duplicate promotions, and canonical search ids after merges.
- Moved adjacent seam coverage off the removed legacy extractor path and onto `_promote_shortcut`.
- Re-ran both required validation slices so the full Phase 28 extraction/store/postprocessing path closes green.

## Task Commits

Each task was committed atomically:

1. **Task 1: Build the phase-local regression matrix for noise rejection, gating, and duplicate handling** - `009c6cf` (test)
2. **Task 2: Extend adjacent seam coverage and run the full Phase 28 validation slice** - `762a94f` (test)

**Plan metadata:** recorded in the final docs commit created after summary/state updates

## Files Created/Modified

- `.planning/phases/28-shortcut-extraction-productionization/28-03-SUMMARY.md` - Phase 28 Plan 03 execution record
- `tests/test_opengui_p28_shortcut_productionization.py` - production promotion regression matrix for noise rejection and duplicate handling
- `tests/test_opengui_p27_storage_search_agent.py` - canonical shortcut-id compatibility coverage after merge/version updates
- `tests/test_opengui_p8_trajectory.py` - trajectory/postprocessing tests patched onto `_promote_shortcut`
- `tests/test_opengui_p11_integration.py` - integration coverage for pending/failing background promotion and intervention postprocessing

## Decisions Made

- Bound postprocessing seam tests to `_promote_shortcut` so they track the production lifecycle instead of the removed `SkillExtractor.extract_from_file` path.
- Kept duplicate-promotion coverage at two layers: the Phase 28 promotion matrix proves stable store count/version behavior, and the Phase 27 search test proves callers still see the canonical original `skill_id`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated stale Phase 11 intervention tests that still patched `_extract_skill`**
- **Found during:** Task 2 (Extend adjacent seam coverage and run the full Phase 28 validation slice)
- **Issue:** The full validation slice failed because two intervention tests referenced `_extract_skill`, which no longer exists after the promotion cutover.
- **Fix:** Switched those tests to patch `_promote_shortcut` so the intervention flow stays aligned with the production seam.
- **Files modified:** `tests/test_opengui_p11_integration.py`
- **Verification:** `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p8_trajectory.py tests/test_opengui_p11_integration.py tests/test_opengui_p28_shortcut_productionization.py`
- **Committed in:** `762a94f` (part of task commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The fix was necessary to keep the full regression slice aligned with the production promotion seam. No scope creep.

## Issues Encountered

- `git add` hit a transient `.git/index.lock` twice during staging; the lock disappeared on retry and no manual cleanup was needed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 28 now closes with green focused and full validation evidence for shortcut promotion noise rejection, provenance-preserving merge behavior, and non-blocking GUI postprocessing.
- Phase 29 can build retrieval/applicability routing on top of a locked promotion/store contract instead of a partially covered extraction seam.

## Self-Check: PASSED

- Found `.planning/phases/28-shortcut-extraction-productionization/28-03-SUMMARY.md`
- Verified task commits `009c6cf` and `762a94f` exist in git history
