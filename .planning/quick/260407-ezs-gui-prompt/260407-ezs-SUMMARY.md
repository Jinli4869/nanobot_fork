# Quick Task 260407-ezs Summary

## Outcome

Updated GUI shortcut postprocessing so failed trajectories are no longer skipped outright. Successful runs still use the production `ShortcutPromotionPipeline`; failed runs now use the legacy `SkillExtractor` failure prompt path and convert the extracted result into a `ShortcutSkill` for the current shortcut store.

## What Changed

- Updated [`nanobot/agent/tools/gui.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py) so `_promote_shortcut()`:
  - keeps the existing success-path promotion pipeline
  - routes failed trajectories through `SkillExtractor.extract_from_file(..., is_success=False)`
  - persists extraction token usage to `extraction_usage.json`
  - converts legacy `Skill` objects into `ShortcutSkill` records with parameter slots, state descriptors, provenance, and step indices
- Added regression coverage in [`tests/test_opengui_p28_shortcut_productionization.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p28_shortcut_productionization.py) proving failed traces now trigger extraction and are written into `gui_skills`.

## Verification

- `uv run pytest tests/test_opengui_p28_shortcut_productionization.py -q`
- `uv run pytest tests/test_opengui_p8_trajectory.py -q`
- `uv run pytest tests/test_opengui_p3_nanobot.py -q`

## Notes

`tests/test_opengui_p3_nanobot.py` still has pre-existing stale expectations for the older `SkillExtractor`/`SkillLibrary` success path and an outdated GUI backend enum assertion. Those failures were observed during verification but were not expanded in this quick task because they are outside the requested behavior change.
