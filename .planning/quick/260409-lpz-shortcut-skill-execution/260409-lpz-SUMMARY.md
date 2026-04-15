# Quick Task 260409-lpz: Disable Shortcut System

**Date:** 2026-04-09
**Status:** Complete

## Changes

### nanobot/agent/tools/gui.py
- Removed `ShortcutExecutor`, `ShortcutApplicabilityRouter`, `LLMConditionEvaluator` imports and instantiation
- Removed `unified_skill_search` retrieval
- Removed `shortcut_executor`, `unified_skill_search`, `shortcut_applicability_router` from GuiAgent constructor args
- Preserved `SkillExecutor` creation and `skill_library` passing

### opengui/agent.py
- Removed `_retrieve_shortcut_candidates()` call from `run()` method
- Removed entire shortcut applicability evaluation + execution block (90+ lines)
- Removed `_shortcut_attempted` tracking variable and stale-context clearing logic
- Preserved original `SkillExecutor` execution path (`self._skill_executor.execute()`)

### opengui/postprocessing.py
- Replaced `_promote_shortcut()` with `_extract_skill()` in `PostRunProcessor`
- New method uses `SkillExtractor` + `SkillLibrary` (original system) instead of `ShortcutPromotionPipeline` + `ShortcutSkillStore`
- `_run_all()` now calls `_extract_skill()` instead of `_promote_shortcut()`

## What's Preserved
- `SkillExtractor` — extracts skills from trajectories (postprocessing)
- `SkillExecutor` — executes matched skills during agent run
- `SkillLibrary` — stores/retrieves extracted skills
- All trajectory recording, summarization, and evaluation unchanged
