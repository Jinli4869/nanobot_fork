---
phase: quick-260330-l0g
plan: "01"
subsystem: opengui-backends
tags: [hdc, harmonyos, backend, opengui, nanobot, device-automation]
dependency_graph:
  requires:
    - opengui/backends/adb.py (pattern reference for async subprocess)
    - opengui/backends/ios_wda.py (pattern reference for iOS integration)
    - opengui/interfaces.py (DeviceBackend protocol)
    - opengui/action.py (Action, resolve_coordinate, describe_action)
    - opengui/observation.py (Observation dataclass)
  provides:
    - opengui/backends/hdc.py (HdcBackend, HdcError)
    - opengui/cli.py (HdcConfig, hdc backend choice and config loading)
    - nanobot/config/schema.py (HdcConfig, GuiConfig.backend includes hdc)
    - nanobot/agent/tools/gui.py (hdc case in _build_backend, ios case added)
    - nanobot/agent/router.py (gui.hdc sentinel in GUI dispatch set)
    - nanobot/agent/loop.py (hdc in active_gui_route derivation)
    - nanobot/agent/capabilities.py (gui.hdc route override block)
  affects:
    - Any nanobot session with gui.backend = "hdc"
    - opengui CLI --backend hdc invocations
tech_stack:
  added:
    - Pillow (PIL) for JPEG-to-PNG screenshot conversion (lazy import, install hint on failure)
    - hdc CLI tool (HarmonyOS Device Connector, Huawei SDK)
  patterns:
    - asyncio.create_subprocess_exec for non-blocking hdc subprocess I/O (same as AdbBackend)
    - Lazy imports with helpful error messages (same as WdaBackend)
    - asyncio.gather for parallel screen-size + foreground-app queries in observe()
    - asyncio.to_thread for PIL blocking image conversion
    - Static bundle list fallback for list_apps() (no hdc package enumeration command)
key_files:
  created:
    - opengui/backends/hdc.py
  modified:
    - opengui/cli.py
    - nanobot/config/schema.py
    - nanobot/agent/tools/gui.py
    - nanobot/agent/router.py
    - nanobot/agent/loop.py
    - nanobot/agent/capabilities.py
decisions:
  - "HdcBackend returns platform='harmonyos' so AppCache cache_key() can distinguish harmonyos_<serial> from android and ios entries"
  - "_compute_swipe_speed() converts duration_ms to px/s: speed = distance / (duration_ms/1000), default 2000 px/s when no duration specified"
  - "list_apps() returns static common bundle list — HDC provides no equivalent to 'pm list packages'; static list is sufficient for LLM app resolution"
  - "observe() converts JPEG screenshot to PNG via asyncio.to_thread(PIL.Image.open.save) for protocol consistency with ADB and WDA backends"
  - "open_app uses '/' separator convention (bundle/ability) — if no slash, 'MainAbility' is the standard HarmonyOS default ability name"
  - "gui.py _build_backend also adds ios case (WdaBackend) for completeness since it was missing despite ios being wired in router/loop/capabilities"
  - "Pre-existing test failure test_agent_uses_default_config_when_no_workspace_or_config_flags is unrelated to these changes (on_stream/on_stream_end kwargs); confirmed pre-existing via git stash verification"
metrics:
  duration_min: 6
  completed_date: "2026-03-30"
  tasks_completed: 2
  files_created: 1
  files_modified: 6
---

# Phase quick-260330-l0g Plan 01: HarmonyOS HDC Backend Summary

**One-liner:** HdcBackend for HarmonyOS automation via hdc CLI with JPEG screenshot conversion, uitest uiInput actions, aa dump foreground detection, and full cli/nanobot gui.hdc routing.

## What Was Built

### Task 1: HdcBackend (opengui/backends/hdc.py)

Full `DeviceBackend` protocol implementation for HarmonyOS devices connected via the `hdc` CLI tool.

**Core design:**
- Async subprocess pattern identical to `AdbBackend` — `asyncio.create_subprocess_exec` + `asyncio.wait_for`
- `HdcError(message, returncode, stderr)` exception following the same shape as `AdbError`
- `_build_cmd()` adds `-t <serial>` when a serial is provided, otherwise targets the default device

**observe():** Three-phase capture:
1. Screenshot on device via `hdc shell screenshot` with `snapshot_display -f` as fallback for older HarmonyOS builds
2. Pull JPEG via `hdc file recv`; convert JPEG → PNG via PIL in `asyncio.to_thread` (Pillow required, lazy-imported with install hint)
3. Screen size (`hidumper -s RenderService` → regex) and foreground app (`aa dump -l` → FOREGROUND block → bundle_name) queried in parallel via `asyncio.gather`

**execute():** Full action coverage using `hdc shell uitest uiInput`:
- `tap` → `click X Y`
- `double_tap` → `doubleClick X Y`
- `long_press` → `longClick X Y`
- `swipe`/`drag` → `swipe X1 Y1 X2 Y2 speed` where speed = distance / (duration_s)
- `input_text` → `inputText X Y text` using screen centre as default coordinate target
- `hotkey` → `keyEvent Back|Home|2054|2055` via `_HDC_KEYCODE_MAP`
- `scroll` → computed swipe with directional offsets
- `open_app` → `aa start -b bundle -a ability` (slash convention for explicit ability; else `MainAbility`)
- `close_app` → `aa force-stop bundle`
- `wait`, `back`, `home`, `done` all handled

**preflight():** `hdc list targets` with presence check for specified serial or any-device fallback.

**list_apps():** Returns 10 common `com.huawei.hmos.*` bundle IDs as a static fallback (no hdc package enumeration command exists).

### Task 2: CLI and Nanobot Wiring (6 files)

**opengui/cli.py:**
- `HdcConfig` dataclass (`serial`, `hdc_path`)
- `HdcConfig` field on `CliConfig`
- `hdc` section parsing in `load_config()`
- `hdc` case in `build_backend()` (lazy import)
- `harmonyos` case in `AppCache.cache_key()` → `harmonyos_{serial}` key
- `"hdc"` added to `--backend` choices
- `"hdc"` added to `--background` incompatibility list

**nanobot/config/schema.py:**
- `HdcConfig(Base)` model with `serial: str | None = None`
- `GuiConfig.backend` Literal updated to `Literal["adb", "hdc", "local", "dry-run"]`
- `hdc: HdcConfig` field added to `GuiConfig`

**nanobot/agent/tools/gui.py:**
- `hdc` case in `_build_backend()` — instantiates `HdcBackend(serial=self._gui_config.hdc.serial)`
- `ios` case added to `_build_backend()` (was missing despite iOS being routed)
- Backend enum updated to `["adb", "ios", "hdc", "local", "dry-run"]`

**nanobot/agent/router.py:**
- `"gui.hdc"` added to the GUI sentinel set in `_dispatch_with_fallback`

**nanobot/agent/loop.py:**
- `"hdc"` added to the set in `active_gui_route` derivation → produces `"gui.hdc"` route for planner

**nanobot/agent/capabilities.py:**
- Override block for `gui_backend == "hdc"` → sets `route_id="gui.hdc"`, `kind="hdc"`, descriptive summary

## Verification Results

All plan verification checks passed:
- `HdcBackend().platform` → `"harmonyos"` ✓
- `parse_args(['--backend', 'hdc', 'test'])` succeeds ✓
- `GuiConfig(backend='hdc')` succeeds, `hdc.serial is None` ✓
- `"gui.hdc"` present in router `_dispatch_with_fallback` source ✓
- `"hdc"` present in loop `active_gui_route` derivation ✓
- `"gui.hdc"` present in capabilities `build()` source ✓
- 364 existing tests pass; 1 pre-existing failure unrelated to these changes ✓

## Deviations from Plan

### Auto-added: ios case in `_build_backend()`

- **Found during:** Task 2
- **Issue:** `nanobot/agent/tools/gui.py._build_backend()` was missing the `ios` case despite iOS being fully wired in router/loop/capabilities via the previous quick task (260330-khq)
- **Fix:** Added `ios` case that instantiates `WdaBackend()` using default WDA URL — mirrors the CLI pattern
- **Files modified:** `nanobot/agent/tools/gui.py`
- **Commit:** 767e290

## Self-Check

Files exist:
- `opengui/backends/hdc.py`: FOUND
- `.planning/quick/260330-l0g-opengui-hdc-harmony-os/260330-l0g-SUMMARY.md`: FOUND

Commits exist:
- 922627e (Task 1: HdcBackend): FOUND
- 767e290 (Task 2: wiring): FOUND

## Self-Check: PASSED
