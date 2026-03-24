---
phase: quick
plan: 260324-ltk
type: execute
wave: 1
depends_on: []
files_modified:
  - opengui/skills/normalization.py
  - opengui/prompts/system.py
  - tests/test_opengui.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "OPPO/ColorOS system apps are mapped in _ANDROID_PACKAGE_DISPLAY_NAMES"
    - "annotate_android_apps only returns entries with a known display name (unmapped packages are dropped)"
    - "System prompt Android app list shows only display names without package names"
    - "resolve_android_package still resolves display names to package names at execution time"
  artifacts:
    - path: "opengui/skills/normalization.py"
      provides: "OPPO/ColorOS mappings and filtered annotate_android_apps"
      contains: "com.coloros"
    - path: "opengui/prompts/system.py"
      provides: "Display-name-only app list in system prompt"
    - path: "tests/test_opengui.py"
      provides: "Regression tests for filtered annotation and display-name-only prompt"
  key_links:
    - from: "opengui/prompts/system.py"
      to: "opengui/skills/normalization.py"
      via: "annotate_android_apps import"
      pattern: "annotate_android_apps"
    - from: "opengui/agent.py"
      to: "opengui/skills/normalization.py"
      via: "resolve_android_package at execution time"
      pattern: "resolve_android_package"
---

<objective>
Filter the Android app list in the system prompt to only show mapped apps (those with display names), show display names only (no package names) in the prompt, and add OPPO/ColorOS system app mappings.

Purpose: Reduce prompt noise by dropping unknown packages and removing redundant package identifiers from the app list. The package name lookup happens via resolve_android_package() at execution time as a safety net. OPPO/ColorOS devices contribute many system apps that need display name mappings.

Output: Updated normalization.py with OPPO mappings + filtered annotate_android_apps, updated system.py with display-name-only format, regression tests.
</objective>

<execution_context>
@/Users/jinli/.claude/get-shit-done/workflows/execute-plan.md
@/Users/jinli/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@opengui/skills/normalization.py
@opengui/prompts/system.py
@opengui/agent.py (lines 682-692 — resolve_android_package usage at execution time)
@tests/test_opengui.py (existing test_build_system_prompt_uses_mobile_agent_style_sections)

<interfaces>
<!-- Key functions the executor needs to understand -->

From opengui/skills/normalization.py:
```python
_ANDROID_PACKAGE_DISPLAY_NAMES: dict[str, str]  # package -> "中文/English"
def annotate_android_apps(packages: list[str]) -> list[str]  # currently returns ALL packages
def resolve_android_package(app_text: str) -> str  # display name -> package name (used at execution time)
```

From opengui/prompts/system.py:
```python
def build_system_prompt(
    *,
    platform: str = "unknown",
    coordinate_mode: str = "absolute",
    memory_context: str | None = None,
    skill_context: str | None = None,
    tool_definition: dict[str, Any] | None = None,
    installed_apps: list[str] | None = None,
) -> str
```

Current Android app list format in system prompt (lines 103-115):
```python
if platform == "android":
    from opengui.skills.normalization import annotate_android_apps
    annotated = annotate_android_apps(installed_apps)
    app_list = "\n".join(f"- {app}" for app in annotated)
    # Shows: "- 美团/Meituan: com.sankuai.meituan" and "- com.unknown.pkg"
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add OPPO/ColorOS mappings and filter annotate_android_apps</name>
  <files>opengui/skills/normalization.py</files>
  <action>
Two changes in normalization.py:

1. Add OPPO/ColorOS system app package-to-display-name mappings to `_ANDROID_PACKAGE_DISPLAY_NAMES`. Add these under a new "# OPPO/ColorOS System" comment block, placed after the existing "# System" block (after line 120). Include at minimum:
   - com.coloros.soundrecorder -> "录音/Sound Recorder"
   - com.coloros.filemanager -> "文件管理/File Manager"
   - com.coloros.weather2 -> "天气/Weather"
   - com.coloros.calendar -> "日历/Calendar"
   - com.coloros.calculator -> "计算器/Calculator"
   - com.coloros.compass2 -> "指南针/Compass"
   - com.coloros.alarmclock -> "闹钟/Alarm Clock"
   - com.coloros.note -> "备忘录/Notes"
   - com.coloros.translate -> "翻译/Translate"
   - com.coloros.backuprestore -> "备份与恢复/Backup"
   - com.coloros.gallery3d -> "相册/Gallery"
   - com.coloros.camera -> "相机/Camera"
   - com.coloros.phonemanager -> "手机管家/Phone Manager"
   - com.coloros.safecenter -> "安全中心/Security Center"
   - com.coloros.oshare -> "互传/OShare"
   - com.heytap.browser -> "浏览器/Browser"
   - com.heytap.music -> "音乐/Music"
   - com.heytap.themestore -> "主题商店/Theme Store"
   - com.nearme.gamecenter -> "游戏中心/Game Center"
   - com.oppo.market -> "应用商店/App Store"
   - com.oppo.quicksearchbox -> "搜索/Search"

2. Modify `annotate_android_apps()` to FILTER OUT packages that have no display name. Change the function so it only returns entries for packages found in `_ANDROID_PACKAGE_DISPLAY_NAMES`. Update the docstring to reflect the new filtering behavior. The return format stays `"display_name: package_name"` for now (Task 2 will change the prompt format).
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "
from opengui.skills.normalization import annotate_android_apps, _ANDROID_PACKAGE_DISPLAY_NAMES, resolve_android_package

# Verify OPPO mappings exist
assert 'com.coloros.soundrecorder' in _ANDROID_PACKAGE_DISPLAY_NAMES
assert 'com.coloros.filemanager' in _ANDROID_PACKAGE_DISPLAY_NAMES
assert 'com.heytap.browser' in _ANDROID_PACKAGE_DISPLAY_NAMES
assert 'com.oppo.market' in _ANDROID_PACKAGE_DISPLAY_NAMES

# Verify filtering: unmapped packages are dropped
result = annotate_android_apps(['com.sankuai.meituan', 'com.unknown.foo', 'com.coloros.soundrecorder'])
assert len(result) == 2, f'Expected 2 but got {len(result)}: {result}'
assert any('美团' in r for r in result)
assert any('录音' in r or 'Sound Recorder' in r for r in result)
assert not any('com.unknown.foo' in r for r in result)

# Verify resolve_android_package still works for OPPO apps
assert resolve_android_package('录音') == 'com.coloros.soundrecorder'
print('All checks passed')
"
    </automated>
  </verify>
  <done>OPPO/ColorOS system apps are mapped. annotate_android_apps drops unmapped packages and only returns entries with display names. resolve_android_package resolves OPPO display names to package names.</done>
</task>

<task type="auto">
  <name>Task 2: Change system prompt to display-name-only format and add tests</name>
  <files>opengui/prompts/system.py, tests/test_opengui.py</files>
  <action>
Two changes:

1. In `opengui/prompts/system.py`, modify the Android branch of the `installed_apps` section (lines 103-115). Change the app list format to show ONLY display names (e.g. "- 美团/Meituan") without the package name. Since `annotate_android_apps` returns `"display_name: package_name"` format, extract just the display name portion. Alternatively, create a new helper or modify the call to directly get display names from `_ANDROID_PACKAGE_DISPLAY_NAMES`. Update the header text from "use the package name (the `com.xxx.xxx` identifier)" to something like "The following apps are available on this device:" since the model will use the display name and `resolve_android_package()` handles the package name lookup at execution time.

2. In `tests/test_opengui.py`, add three tests after `test_build_system_prompt_uses_mobile_agent_style_sections`:

   a. `test_annotate_android_apps_filters_unmapped_packages` — import `annotate_android_apps` from normalization, pass a list containing one known package (e.g. "com.sankuai.meituan") and one unknown package (e.g. "com.unknown.xyz"), assert the result has length 1 and contains the known app's display name, and does NOT contain "com.unknown.xyz".

   b. `test_build_system_prompt_android_apps_shows_display_names_only` — call `build_system_prompt(platform="android", installed_apps=["com.sankuai.meituan", "com.unknown.dropped"])`, assert the prompt contains "美团/Meituan" (display name), does NOT contain "com.sankuai.meituan" in the app list section (package name should not appear as an app list item), and does NOT contain "com.unknown.dropped".

   c. `test_build_system_prompt_android_apps_excludes_unmapped` — call `build_system_prompt(platform="android", installed_apps=["com.totally.unknown"])`, assert the prompt does NOT contain "# Installed Apps" section at all (since no apps survived filtering, the section should be omitted or empty). OR if the section is still rendered with zero items, assert it has no app list entries. Use whichever approach matches the implementation.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -m pytest tests/test_opengui.py::test_build_system_prompt_uses_mobile_agent_style_sections tests/test_opengui.py::test_annotate_android_apps_filters_unmapped_packages tests/test_opengui.py::test_build_system_prompt_android_apps_shows_display_names_only tests/test_opengui.py::test_build_system_prompt_android_apps_excludes_unmapped -x -v</automated>
  </verify>
  <done>System prompt shows display names only (no package names) for Android apps. Unmapped apps are excluded from the prompt. Three new regression tests pass alongside the existing system prompt test.</done>
</task>

</tasks>

<verification>
1. Run all existing opengui tests to check for regressions: `python -m pytest tests/test_opengui.py -x -v`
2. Verify the system prompt output manually for a realistic package list: `python -c "from opengui.prompts.system import build_system_prompt; print(build_system_prompt(platform='android', installed_apps=['com.sankuai.meituan', 'com.tencent.mm', 'com.coloros.soundrecorder', 'com.unknown.pkg']))"`
3. Verify resolve_android_package still works at execution time for mapped display names: `python -c "from opengui.skills.normalization import resolve_android_package; print(resolve_android_package('美团'))"`
</verification>

<success_criteria>
- OPPO/ColorOS system apps (15+ apps) are mapped in _ANDROID_PACKAGE_DISPLAY_NAMES
- annotate_android_apps returns only mapped apps, drops unknown packages
- System prompt Android app list shows "- 美团/Meituan" format (no package names)
- resolve_android_package still resolves display names to packages at execution time (unchanged)
- All existing tests pass, 3 new tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260324-ltk-filter-system-prompt-to-mapped-only-apps/260324-ltk-SUMMARY.md`
</output>
