---
phase: quick-260330-khq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - opengui/backends/ios_wda.py
  - opengui/skills/normalization.py
  - opengui/cli.py
  - nanobot/agent/router.py
  - nanobot/agent/loop.py
  - nanobot/agent/capabilities.py
autonomous: true
requirements: [IOS-BACKEND]
must_haves:
  truths:
    - "CLI accepts --backend ios and connects to a WDA endpoint"
    - "iOS backend can take screenshots, query screen size, detect foreground app"
    - "iOS backend can execute all standard actions: tap, swipe, input_text, open_app, close_app, home, back, etc."
    - "iOS bundle IDs are normalized to display names in system prompts"
    - "Nanobot planner routes to gui.ios when ios backend is active"
  artifacts:
    - path: "opengui/backends/ios_wda.py"
      provides: "WdaBackend class implementing DeviceBackend protocol"
      min_lines: 200
    - path: "opengui/skills/normalization.py"
      provides: "iOS bundle ID display name mapping and normalization"
      contains: "_IOS_BUNDLE_DISPLAY_NAMES"
    - path: "opengui/cli.py"
      provides: "ios backend choice and WdaBackend construction"
      contains: "ios"
  key_links:
    - from: "opengui/cli.py"
      to: "opengui/backends/ios_wda.py"
      via: "build_backend dispatches name='ios' to WdaBackend"
      pattern: "WdaBackend"
    - from: "nanobot/agent/loop.py"
      to: "nanobot/agent/capabilities.py"
      via: "active_gui_route=gui.ios when gui_backend=ios"
      pattern: "gui\\.ios"
---

<objective>
Add an iOS/iPhone device control backend to OpenGUI using WebDriverAgent (WDA) via the `facebook-wda` Python client (`wda` package).

Purpose: Enable OpenGUI to automate iOS devices with the same action vocabulary as the existing ADB Android backend.
Output: Working WdaBackend class, CLI integration, iOS app normalization, and nanobot planner routing for gui.ios.
</objective>

<execution_context>
@/Users/jinli/.claude/get-shit-done/workflows/execute-plan.md
@/Users/jinli/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@opengui/backends/adb.py (reference implementation pattern)
@opengui/interfaces.py (DeviceBackend protocol)
@opengui/cli.py (build_backend, parse_args, AppCache.cache_key)
@opengui/skills/normalization.py (Android normalization pattern to mirror for iOS)
@opengui/action.py (Action dataclass, VALID_ACTION_TYPES, resolve_coordinate)
@opengui/observation.py (Observation dataclass)
@nanobot/agent/capabilities.py (CapabilityCatalogBuilder.build, PlanningContext)
@nanobot/agent/loop.py (active_gui_route derivation at line 596)
@nanobot/agent/router.py (_dispatch_with_fallback gui sentinel set at line 377)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create WdaBackend and iOS app normalization</name>
  <files>opengui/backends/ios_wda.py, opengui/skills/normalization.py</files>
  <action>
**1a. Create `opengui/backends/ios_wda.py`** (~250-350 lines)

Mirror the AdbBackend pattern exactly. Use `facebook-wda` (`wda` package) as the HTTP client to WebDriverAgent.

Constructor:
- `__init__(self, wda_url: str = "http://localhost:8100")` — default WDA port
- Store `self._client = wda.Client(wda_url)` (import wda at top)
- `self._screen_width = 375` / `self._screen_height = 812` (iPhone defaults)

Property:
- `platform` returns `"ios"`

`preflight()`:
- Call `self._client.status()` to verify WDA connectivity
- Raise a `WdaError` (custom exception, same pattern as `AdbError`) if unreachable
- Log device info from status response (model, OS version) at INFO level

`list_apps()`:
- Use `self._client.app_list()` if available, otherwise return empty list with a warning
- Return list of bundle ID strings

`observe(screenshot_path, timeout)`:
- `self._client.screenshot()` returns a PIL Image — save to `screenshot_path` as PNG
- Query screen size from `self._client.window_size()` — returns `width, height`
- Query foreground app: `self._client.app_current()` returns dict with `bundleId`
- Update `self._screen_width` / `self._screen_height`
- Return `Observation(screenshot_path=str(screenshot_path), screen_width=w, screen_height=h, foreground_app=bundle_id, platform="ios")`

`execute(action, timeout)`:
- Handle all action types matching AdbBackend's coverage:
  - `tap`: `session.tap(x, y)` — resolve coordinates via `resolve_coordinate()` from `opengui.action`
  - `long_press`: `session.tap_hold(x, y, duration)` — duration from `action.duration_ms or 800`, convert to seconds
  - `double_tap`: `session.double_tap(x, y)`
  - `drag`/`swipe`: `session.swipe(x1, y1, x2, y2, duration)` — duration from `action.duration_ms or 300`, convert to seconds
  - `scroll`: Compute swipe vector same as AdbBackend `_do_scroll`, then `session.swipe()`
  - `input_text`: `session.send_keys(action.text)`
  - `hotkey`: Map key names via `_IOS_KEYCODE_MAP` (home->home button, back->not available on iOS so no-op with warning, etc.)
  - `wait`: `await asyncio.sleep()`
  - `back`: No physical back on iOS. Use swipe from left edge: `session.swipe(0, h//2, w//3, h//2, 0.3)` as iOS back gesture
  - `home`: `session.home()`
  - `done`: no-op pass
  - `open_app`: `session.app_launch(action.text)` — text is bundle ID
  - `close_app`: `session.app_terminate(action.text)`
- Return `describe_action(action)` at end, same as AdbBackend

Note: `wda.Client` operations are synchronous. Wrap blocking calls with `asyncio.to_thread()` (or `loop.run_in_executor(None, ...)`) so the backend stays async-compatible. Create a helper `async def _wda_call(self, fn, *args)` that wraps `await asyncio.to_thread(fn, *args)`.

Define `_IOS_KEYCODE_MAP` for the limited iOS key set:
```python
_IOS_KEYCODE_MAP: dict[str, str] = {
    "home": "home",
    "volumeup": "volumeUp",
    "volume_up": "volumeUp",
    "volumedown": "volumeDown",
    "volume_down": "volumeDown",
}
```

Coordinate resolution helpers: same `_resolve_x`, `_resolve_y`, `_resolve_point`, `_resolve_second_point` as AdbBackend, using `resolve_coordinate` from `opengui.action`.

**1b. Add iOS bundle ID mappings to `opengui/skills/normalization.py`**

Add `_IOS_BUNDLE_DISPLAY_NAMES: dict[str, str]` mapping bundle IDs to display names. Include common iOS apps that mirror the Android list where applicable:

```python
_IOS_BUNDLE_DISPLAY_NAMES: dict[str, str] = {
    # Social & Communication
    "com.tencent.xin": "WeChat",
    "com.tencent.mqq": "QQ",
    "com.sina.weibo": "Weibo",
    "com.zhihu.ios": "Zhihu",
    "com.xingin.discover": "RedNote",
    "com.atebits.Tweetie2": "X/Twitter",
    "net.whatsapp.WhatsApp": "WhatsApp",
    "ph.telegra.Telegraph": "Telegram",
    "com.facebook.Facebook": "Facebook",
    "com.bilibili.bilibili": "Bilibili",
    # Shopping & Food
    "com.taobao.taobao4iphone": "Taobao",
    "com.jingdong.app.iphone": "JD",
    "com.xunmeng.pinduoduo": "Pinduoduo",
    "com.taobao.fleamarket": "Xianyu",
    "com.meituan.imeituan": "Meituan",
    "com.dianping.dpscope": "Dianping",
    # Transport
    "com.xiaojukeji.didi": "DiDi",
    "com.autonavi.amap": "Amap",
    # Travel
    "ctrip.com": "Ctrip",
    "com.12306": "12306",
    # Finance
    "com.alipay.iphoneclient": "Alipay",
    # Entertainment
    "com.ss.iphone.ugc.Aweme": "Douyin",
    "com.netease.cloudmusic": "NetEase Music",
    "com.google.ios.youtube": "YouTube",
    # Work & Productivity
    "com.ss.iphone.lark": "Lark",
    "com.tencent.wework": "WeCom",
    "com.tencent.tgmeeting": "VooV",
    # AI
    "com.openai.chat": "ChatGPT",
    "com.deepseek.chat": "DeepSeek",
    # Reading
    "com.tencent.weread": "WeRead",
    # Google
    "com.google.chrome.ios": "Chrome",
    "com.google.Gmail": "Gmail",
    "com.google.Maps": "Google Maps",
    # System
    "com.apple.Preferences": "Settings",
    "com.apple.mobilesafari": "Safari",
    "com.apple.mobilemail": "Mail",
    "com.apple.mobilenotes": "Notes",
    "com.apple.reminders": "Reminders",
    "com.apple.Maps": "Apple Maps",
    "com.apple.camera": "Camera",
    "com.apple.mobileslideshow": "Photos",
    "com.apple.calculator": "Calculator",
    "com.apple.mobiletimer": "Clock",
    "com.apple.weather": "Weather",
    "com.apple.AppStore": "App Store",
    "com.apple.iBooks": "Books",
    "com.apple.Health": "Health",
    "com.apple.Fitness": "Fitness",
    "com.apple.MobileStore": "Apple Store",
    "com.apple.Music": "Music",
    "com.apple.podcasts": "Podcasts",
    "com.apple.tv": "Apple TV",
    "com.apple.DocumentsApp": "Files",
    "com.apple.mobilephone": "Phone",
    "com.apple.MobileSMS": "Messages",
    "com.apple.facetime": "FaceTime",
}
```

Add `_IOS_APP_ALIASES_BASE` and `_build_ios_aliases()` mirroring the Android pattern — build reverse lookup from display names + manual aliases.

Add `annotate_ios_apps(bundle_ids: list[str]) -> list[str]` — same pattern as `annotate_android_apps()`.

Add `resolve_ios_bundle(app_text: str) -> str` — same pattern as `resolve_android_package()`.

Update `normalize_app_identifier()`: add `elif platform_key == "ios":` block that checks `_IOS_APP_ALIASES` then falls through to slug if no match. If the input contains a "com.apple." or "com." prefix with dots, return lowered directly (same dot-check pattern as Android).
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "from opengui.backends.ios_wda import WdaBackend; print('WdaBackend imported OK'); from opengui.skills.normalization import annotate_ios_apps, resolve_ios_bundle, normalize_app_identifier; print('iOS normalization imported OK'); assert normalize_app_identifier('ios', 'com.apple.mobilesafari') == 'com.apple.mobilesafari'; print('normalize OK'); assert resolve_ios_bundle('wechat') != 'wechat'; print('resolve OK')"</automated>
  </verify>
  <done>
    - WdaBackend class exists and implements all DeviceBackend protocol methods
    - All standard action types handled (tap, swipe, input_text, open_app, etc.)
    - iOS back gesture implemented as left-edge swipe
    - Blocking WDA calls wrapped in asyncio.to_thread for async compatibility
    - iOS bundle ID display names and alias resolution working
    - normalize_app_identifier handles "ios" platform correctly
  </done>
</task>

<task type="auto">
  <name>Task 2: Wire iOS backend into CLI and nanobot routing</name>
  <files>opengui/cli.py, nanobot/agent/router.py, nanobot/agent/loop.py, nanobot/agent/capabilities.py</files>
  <action>
**2a. Update `opengui/cli.py`**

1. Add `"ios"` to `--backend` choices: `choices=("adb", "ios", "local", "dry-run")`

2. In `build_backend()`, add iOS case:
   ```python
   if name == "ios":
       from opengui.backends.ios_wda import WdaBackend
       return WdaBackend(wda_url=config.ios.wda_url)
   ```

3. Add iOS config support. In `CliConfig` dataclass (or wherever ADB config is structured), add:
   ```python
   @dataclasses.dataclass
   class IosConfig:
       wda_url: str = "http://localhost:8100"
   ```
   Add `ios: IosConfig` field to `CliConfig` with default `IosConfig()`. Parse from config YAML under `ios.wda_url` key, same pattern as `adb` section parsing.

4. In `AppCache.cache_key()`, add iOS case:
   ```python
   if platform == "ios":
       return "ios_default"
   ```

5. In `parse_args()`, update the `--background` incompatibility check to include "ios":
   ```python
   if args.background and args.backend in ("adb", "ios", "dry-run"):
       parser.error("--background requires --backend local (or omit --backend)")
   ```

6. Where `annotate_android_apps` is called to build app list for system prompt, add iOS branch. Find where the app list annotation happens (likely in the run function) and add:
   ```python
   if backend.platform == "ios":
       from opengui.skills.normalization import annotate_ios_apps
       app_display = annotate_ios_apps(apps)
   ```

**2b. Update `nanobot/agent/router.py`**

In `_dispatch_with_fallback`, add `"gui.ios"` to the GUI sentinel set:
```python
if route_id in ("gui.desktop", "gui.adb", "gui.ios"):
```

**2c. Update `nanobot/agent/loop.py`**

Update `active_gui_route` derivation (line ~596) to include "ios":
```python
active_gui_route = f"gui.{gui_backend}" if gui_backend in ("adb", "ios", "desktop") else "gui.desktop"
```

This maps `gui_backend="ios"` to `active_gui_route="gui.ios"`.

**2d. Update `nanobot/agent/capabilities.py`**

In `CapabilityCatalogBuilder.build()`, add iOS backend override block after the ADB block:
```python
if tool_name == "gui_task" and gui_backend == "ios":
    route_id = "gui.ios"
    kind = "ios"
    summary = "Use the GUI subagent to operate apps on the connected iOS device"
```
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "
from opengui.cli import parse_args, build_backend
# Verify 'ios' is accepted as backend choice
args = parse_args(['--backend', 'ios', '--task', 'test'])
assert args.backend == 'ios'
print('CLI parse OK')

# Verify router sentinel set
import ast, inspect
from nanobot.agent import router
src = inspect.getsource(router)
assert 'gui.ios' in src
print('Router gui.ios OK')

# Verify loop active_gui_route
from nanobot.agent import loop
loop_src = inspect.getsource(loop)
assert 'ios' in loop_src
print('Loop ios OK')

# Verify capabilities
from nanobot.agent import capabilities
cap_src = inspect.getsource(capabilities)
assert 'gui.ios' in cap_src
print('Capabilities gui.ios OK')
print('All wiring checks passed')
"</automated>
  </verify>
  <done>
    - `--backend ios` accepted by CLI argument parser
    - `build_backend("ios", config)` returns a WdaBackend instance
    - AppCache.cache_key returns "ios_default" for iOS backend
    - --background rejects ios backend (same as adb)
    - iOS app list uses annotate_ios_apps for display names
    - Router dispatches gui.ios to GUI subagent
    - Planner sees gui.ios route when gui_backend="ios"
    - active_gui_route="gui.ios" when backend is ios
  </done>
</task>

</tasks>

<verification>
1. `python -c "from opengui.backends.ios_wda import WdaBackend"` imports without error
2. `python -m opengui.cli --backend ios --task "test" --dry-run` does not crash on argument parsing (will fail at WDA connection which is expected)
3. iOS normalization functions resolve known app names to bundle IDs
4. All existing tests still pass: `python -m pytest tests/ -x -q --timeout=30` (skip if test suite is large; at minimum verify no import errors)
</verification>

<success_criteria>
- WdaBackend implements the full DeviceBackend protocol with all action types
- iOS backend is selectable via --backend ios in CLI
- iOS bundle ID normalization mirrors Android pattern quality
- Nanobot planner and router correctly dispatch gui.ios route
- No regressions in existing Android/desktop backend paths
</success_criteria>

<output>
After completion, create `.planning/quick/260330-khq-opengui-iphone-os/260330-khq-SUMMARY.md`
</output>
