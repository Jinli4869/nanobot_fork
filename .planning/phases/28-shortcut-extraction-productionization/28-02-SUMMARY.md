---
phase: 28-shortcut-extraction-productionization
plan: "02"
subsystem: testing
tags: [shortcut-store, provenance, promotion, deduplication, pytest]
requires:
  - phase: 28-01
    provides: shortcut promotion cutover from GUI postprocessing into the new promotion pipeline
provides:
  - persisted shortcut provenance and lineage metadata
  - explicit low-value promotion gates before store writes
  - shortcut-layer merge/version lifecycle in ShortcutSkillStore
affects: [phase-29-routing, phase-30-shortcut-execution, shortcut-search]
tech-stack:
  added: []
  patterns: [red-green task commits, additive schema evolution, store-owned deduplication]
key-files:
  created: [.planning/phases/28-shortcut-extraction-productionization/28-02-SUMMARY.md]
  modified: [opengui/skills/shortcut.py, opengui/skills/shortcut_store.py, opengui/skills/shortcut_promotion.py, tests/test_opengui_p27_storage_search_agent.py, tests/test_opengui_p28_shortcut_productionization.py]
key-decisions:
  - "Shortcut provenance lives directly on ShortcutSkill with safe defaults so existing Phase 27 stores still deserialize."
  - "ShortcutSkillStore now owns duplicate handling through add_or_merge() instead of letting promotion append blindly."
  - "Promotion rejects unknown-app, unsupported-action, empty-output, and too-short candidates before any store write."
patterns-established:
  - "Promotion seam enriches extracted shortcuts with trace provenance immediately before persistence."
  - "Canonical shortcut IDs stay stable across merges while shortcut_version and merged_from_ids capture lineage."
requirements-completed: [SXTR-02, SXTR-03, SXTR-04]
duration: 5 min
completed: 2026-04-03
---

# Phase 28 Plan 02: Shortcut Productionization Summary

**Shortcut provenance metadata, low-value promotion gates, and deterministic merge/version handling in the shortcut-layer store**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-03T00:52:40+08:00
- **Completed:** 2026-04-03T00:57:22+08:00
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Added backward-compatible provenance and lineage fields to `ShortcutSkill` and locked their round-trip behavior.
- Moved duplicate handling into `ShortcutSkillStore` with `list_all()`, `update()`, and `add_or_merge()` for canonical merge/version lifecycle.
- Added pre-write promotion gates for unsupported actions, empty evidence, unknown apps, and too-few promotable steps.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing provenance, gate, and merge/version contract tests** - `2d1dc92` (test)
2. **Task 2: Implement backward-compatible provenance fields, production gates, and shortcut-layer merge/version support** - `567d7cd` (feat)

## Files Created/Modified
- `opengui/skills/shortcut.py` - Adds persisted provenance/version fields with safe deserialization defaults.
- `opengui/skills/shortcut_store.py` - Adds shortcut listing, updating, conflict detection, and merge/version persistence behavior.
- `opengui/skills/shortcut_promotion.py` - Enforces production gates and persists enriched shortcuts through `add_or_merge()`.
- `tests/test_opengui_p27_storage_search_agent.py` - Extends Phase 27 round-trip coverage to include new optional metadata.
- `tests/test_opengui_p28_shortcut_productionization.py` - Locks provenance, reload, low-value rejection, and merge/version contracts.

## Decisions Made
- Stored provenance on `ShortcutSkill` directly so later routing and debugging phases can consume it without sidecar lookups.
- Used exact trace-path plus step-index equality as the highest-confidence same-origin conflict signal.
- Preserved the old canonical shortcut ID on merge and expressed lineage through `shortcut_version` plus `merged_from_ids`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Parallel `git add` calls briefly raced on `.git/index.lock`; retrying the affected add serially resolved it without changing the task scope or output.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 29 can now rely on persisted app/platform/provenance metadata and a deduplicated shortcut store for retrieval/applicability work.
- No blockers remain in this plan slice.

## Self-Check

PASSED

---
*Phase: 28-shortcut-extraction-productionization*
*Completed: 2026-04-03*
