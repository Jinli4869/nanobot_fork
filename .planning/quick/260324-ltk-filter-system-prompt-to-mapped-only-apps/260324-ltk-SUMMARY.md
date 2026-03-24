---
phase: quick
plan: 260324-ltk
subsystem: opengui/skills, opengui/prompts
tags: [android, system-prompt, normalization, oppo, coloros, filtering]
dependency_graph:
  requires: []
  provides: [oppo-coloros-mappings, display-name-only-prompt, filtered-annotate]
  affects: [opengui/skills/normalization.py, opengui/prompts/system.py, tests/test_opengui.py]
tech_stack:
  added: []
  patterns: [filter-on-annotation, display-name-extraction, prompt-noise-reduction]
key_files:
  modified:
    - opengui/skills/normalization.py
    - opengui/prompts/system.py
    - tests/test_opengui.py
decisions:
  - "annotate_android_apps silently drops unmapped packages so callers never see unknown COM identifiers in the prompt"
  - "Display name extraction uses split(': ', 1)[0] — safe because annotated entries are always 'DisplayName: pkg' format from annotate_android_apps"
  - "# Installed Apps section is suppressed entirely when no apps survive filtering (not rendered as empty section)"
  - "resolve_android_package unchanged — package name resolution stays at execution time, decoupled from prompt rendering"
metrics:
  duration: "~2.5 min"
  completed: "2026-03-24"
  tasks: 2
  files: 3
  commits:
    - "8efbd64"
    - "b392c90"
---

# Quick Task 260324-ltk: Filter System Prompt to Mapped-Only Apps Summary

**One-liner:** OPPO/ColorOS mappings added (21 entries), annotate_android_apps now filters unmapped packages, and system prompt Android app list shows display names only ("美团/Meituan") without package identifiers.

## What Was Built

### Task 1: OPPO/ColorOS mappings and filtered annotate_android_apps

Added 21 OPPO/ColorOS system app entries to `_ANDROID_PACKAGE_DISPLAY_NAMES` under a new `# OPPO/ColorOS System` block placed after the existing `# System` block. Entries span recorders, file manager, weather, calendar, calculator, compass, alarm clock, notes, translate, backup, gallery, camera, phone manager, security center, OShare, HeyTap browser, HeyTap music, theme store, game center, App Store, and search.

Modified `annotate_android_apps()` to silently drop packages that have no entry in `_ANDROID_PACKAGE_DISPLAY_NAMES`. Previously unknown packages were passed through verbatim; now only mapped packages produce an entry. The return format remains `"display_name: package_name"` so Task 2 can parse it.

### Task 2: Display-name-only system prompt format and regression tests

Updated the Android branch in `build_system_prompt()` to extract just the display name portion from each annotated string (split at first `": "`), producing `"- 美团/Meituan"` lines instead of `"- 美团/Meituan: com.sankuai.meituan"`. Changed section header from "use the package name (`com.xxx.xxx` identifier)" to "The following apps are available on this device:" to reflect that the model uses display names while `resolve_android_package()` handles package resolution at action execution time.

Added a guard so the `# Installed Apps` section is omitted entirely when all input packages are unmapped (no noise heading with empty content).

Added three regression tests:
- `test_annotate_android_apps_filters_unmapped_packages` — confirms unknown packages are dropped
- `test_build_system_prompt_android_apps_shows_display_names_only` — confirms display names appear and package names do not appear as list items
- `test_build_system_prompt_android_apps_excludes_unmapped` — confirms section is omitted when all packages are unknown

## Verification Results

All 17 tests pass (14 pre-existing + 3 new):

```
17 passed in 0.10s
```

Manual prompt output for `['com.sankuai.meituan', 'com.tencent.mm', 'com.coloros.soundrecorder', 'com.unknown.pkg']`:
```
# Installed Apps

The following apps are available on this device:
- 美团/Meituan
- 微信/WeChat
- 录音/Sound Recorder
```

`resolve_android_package('美团')` returns `com.sankuai.meituan` — execution-time resolution unchanged.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- `opengui/skills/normalization.py` — exists and contains `com.coloros.soundrecorder`
- `opengui/prompts/system.py` — exists and shows display-name-only format
- `tests/test_opengui.py` — exists with all 3 new tests
- Commit 8efbd64 — OPPO mappings + filtered annotate_android_apps
- Commit b392c90 — display-name-only prompt + regression tests
