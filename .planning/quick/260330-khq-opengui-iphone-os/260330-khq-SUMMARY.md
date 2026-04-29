---
phase: quick-260330-khq
plan: 01
subsystem: opengui-ios-backend
tags: [ios, wda, opengui, backend, normalization, routing]
dependency_graph:
  requires: [opengui/backends/adb.py, opengui/interfaces.py, opengui/skills/normalization.py]
  provides: [opengui/backends/ios_wda.py, iOS-normalization, gui.ios-routing]
  affects: [opengui/cli.py, nanobot/agent/router.py, nanobot/agent/loop.py, nanobot/agent/capabilities.py]
tech_stack:
  added: [facebook-wda (runtime dependency, lazy import)]
  patterns: [asyncio.to_thread for blocking WDA calls, lazy import guard, DeviceBackend protocol impl]
key_files:
  created: [opengui/backends/ios_wda.py]
  modified:
    - opengui/skills/normalization.py
    - opengui/cli.py
    - opengui/prompts/system.py
    - nanobot/agent/router.py
    - nanobot/agent/loop.py
    - nanobot/agent/capabilities.py
decisions:
  - "WdaBackend uses lazy import for wda package via _import_wda() helper to avoid ImportError on non-iOS hosts"
  - "iOS back gesture implemented as left-edge swipe (0, h//2 -> w//3, h//2, 0.3s) since iOS has no hardware back"
  - "WDA session obtained per execute() call via asyncio.to_thread(self._client.session) — no persistent session state"
  - "iOS app annotation via annotate_ios_apps() handled in opengui/prompts/system.py alongside android branch, not in cli.py"
  - "AppCache.cache_key returns ios_default (vs android_{serial}) since WDA device identity is URL-based"
metrics:
  duration: 7 min
  completed: "2026-03-30"
  tasks_completed: 2
  files_changed: 7
---

# Phase quick-260330-khq Plan 01: iOS WDA Backend for OpenGUI Summary

**One-liner:** Full iOS device automation backend using WebDriverAgent (facebook-wda) with bundle ID normalization, CLI integration, and nanobot gui.ios routing.

## What Was Built

Added complete iOS/iPhone device control to OpenGUI, mirroring the existing ADB Android backend pattern.

### Task 1: WdaBackend and iOS App Normalization

**`opengui/backends/ios_wda.py`** (~260 lines, new file):
- `WdaError` custom exception (same pattern as `AdbError`)
- `_IOS_KEYCODE_MAP` for iOS hardware keys (home, volumeUp/Down)
- `WdaBackend` implementing the full `DeviceBackend` protocol:
  - Lazy `wda` package import via `_import_wda()` helper — prevents `ImportError` on non-iOS hosts
  - `preflight()`: calls `self._client.status()` via `asyncio.to_thread`, logs device model + OS
  - `list_apps()`: calls `self._client.app_list()` via thread, handles various response shapes, warns on failure
  - `observe()`: parallel gather of screenshot (PIL Image → PNG), window_size, and foreground app (bundleId)
  - `execute()`: all standard action types — tap, long_press, double_tap, drag/swipe, scroll (directional swipe), input_text, hotkey, wait, back (left-edge swipe gesture), home, done (no-op), open_app, close_app
  - `_wda_call()` async helper wrapping `asyncio.to_thread`
  - Same coordinate helpers as AdbBackend (`_resolve_x`, `_resolve_y`, `_resolve_point`, `_resolve_second_point`)
  - `_do_scroll()` computing swipe vector from scroll direction

**`opengui/skills/normalization.py`** additions:
- `_IOS_BUNDLE_DISPLAY_NAMES`: 60+ bundle ID → display name mappings (social, shopping, transport, finance, entertainment, productivity, AI, system apps)
- `_IOS_APP_ALIASES_BASE`: manual aliases (wechat, alipay, safari, chrome, etc.)
- `_build_ios_aliases()` / `_IOS_APP_ALIASES`: reverse lookup dict
- `annotate_ios_apps(bundle_ids)`: filter + annotate bundle IDs for system prompt
- `resolve_ios_bundle(app_text)`: human name → bundle ID resolution
- `normalize_app_identifier()`: `elif platform_key == "ios"` branch using `_IOS_APP_ALIASES` + dot-check passthrough

### Task 2: CLI and Nanobot Routing Wiring

**`opengui/cli.py`**:
- `IosConfig` dataclass with `wda_url: str = "http://localhost:8100"`
- `CliConfig.ios: IosConfig` field
- `ios.wda_url` parsed from config YAML
- `--backend ios` added to choices `("adb", "ios", "local", "dry-run")`
- `build_backend("ios", config)` → `WdaBackend(wda_url=config.ios.wda_url)` (lazy import)
- `AppCache.cache_key`: platform `"ios"` → `"ios_default"`
- `--background` incompatibility check includes `"ios"`

**`opengui/prompts/system.py`**:
- `elif platform == "ios"` branch using `annotate_ios_apps()` for display names in system prompt

**`nanobot/agent/router.py`**:
- `gui.ios` added to GUI sentinel set: `if route_id in ("gui.desktop", "gui.adb", "gui.ios")`

**`nanobot/agent/loop.py`**:
- `active_gui_route` derivation: `gui_backend in ("adb", "ios", "desktop")` → `f"gui.{gui_backend}"`

**`nanobot/agent/capabilities.py`**:
- iOS backend override block: `gui_backend == "ios"` → `route_id="gui.ios"`, `kind="ios"`, iOS-specific summary

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Lazy wda import**
- **Found during:** Task 1 verification
- **Issue:** `import wda` at module level caused `ImportError` since `facebook-wda` is not installed in the dev environment; this would break all OpenGUI imports on non-iOS hosts
- **Fix:** Added `_import_wda()` helper with lazy import + helpful error message; called only in `WdaBackend.__init__`
- **Files modified:** `opengui/backends/ios_wda.py`
- **Commit:** 1f22c8f

**2. [Rule 2 - Missing Critical Functionality] iOS app display in system prompt**
- **Found during:** Task 2 — reviewing how Android apps are displayed in system prompt
- **Issue:** The plan said to add iOS app annotation in `cli.py`, but the actual annotation logic is in `opengui/prompts/system.py` which already has an android branch. Adding it to cli.py would have duplicated logic and missed the system prompt path used by both CLI and nanobot GUI agent
- **Fix:** Added `elif platform == "ios"` branch in `opengui/prompts/system.py` alongside the android branch — consistent with existing architecture
- **Files modified:** `opengui/prompts/system.py`
- **Commit:** 34adab0

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 1f22c8f | feat(quick-260330-khq-01): create WdaBackend and iOS app normalization |
| Task 2 | 34adab0 | feat(quick-260330-khq-01): wire iOS backend into CLI and nanobot routing |

## Self-Check: PASSED

- `opengui/backends/ios_wda.py` exists (260+ lines, WdaBackend class, all action types)
- `opengui/skills/normalization.py` updated with `_IOS_BUNDLE_DISPLAY_NAMES`, `annotate_ios_apps`, `resolve_ios_bundle`
- `opengui/cli.py` has `IosConfig`, `ios` choice, `WdaBackend` construction, `ios_default` cache key
- `nanobot/agent/router.py` sentinel set includes `gui.ios`
- `nanobot/agent/loop.py` active_gui_route includes `ios`
- `nanobot/agent/capabilities.py` has `gui.ios` route override block
- Commits 1f22c8f and 34adab0 both exist in git log
