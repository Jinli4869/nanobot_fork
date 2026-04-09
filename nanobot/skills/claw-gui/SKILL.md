---
name: claw-gui
description: "Android mobile device control: use ADB commands, deeplink probing, and GUI automation. Prefer programmatic approaches; use visual GUI only when necessary."
metadata: {"nanobot":{"emoji":"📱","os":["darwin","linux"],"requires":{"bins":["adb"]}}}
---

# Claw GUI — Android Device Control

Use this skill when a task involves controlling an Android device: toggling system settings, navigating apps, probing deep links, or performing visual GUI interactions.

## Strategy

Always prefer the lightest approach that can complete the task. Try each priority level before escalating:

1. **ADB shell commands** — instant, no UI needed. Toggle WiFi, adjust brightness, open settings panels, etc. See the [ADB command catalog](references/adb-commands.md) for the full list.
2. **Deeplink probing** — reach a specific app screen via intent URIs. Use when you need to navigate inside an app. See [deeplink method](references/deeplink-method.md) and the [probe script](#deeplink-probing).
3. **`gui_task` tool** — if the claw provides a native `gui_task` tool, use it for visual automation. Pass a natural-language task description.
4. **`opengui` CLI** — when no native GUI tool is available, invoke the CLI directly from shell. See [opengui CLI fallback](#opengui-cli-fallback).

## Decision flow

- Can the task be done with a single `adb shell` command (toggle, launch settings, input keyevent)?
  **Yes** → use ADB command (Priority 1).

- Does the task require navigating to a specific screen inside an app?
  **Yes** → try deeplink probing first (Priority 2). If the app has no viable deep links, escalate.

- Does the task require reading screen content, identifying visual elements, or multi-step UI interaction?
  **Yes** → use `gui_task` if available (Priority 3), otherwise `opengui` CLI (Priority 4).

- For compound tasks, decompose into sub-steps and apply the decision flow to each step independently. For example: "Turn off WiFi and open Chrome to example.com" → sub-step 1 (adb WiFi off) + sub-step 2 (deeplink or GUI for Chrome navigation).

## ADB quick commands

Most common operations — execute via `adb shell`:

| Action | Command |
|--------|---------|
| WiFi on/off | `svc wifi enable` / `svc wifi disable` |
| Bluetooth on/off | `svc bluetooth enable` / `svc bluetooth disable` |
| Airplane mode | `cmd connectivity airplane-mode enable` / `disable` |
| Mobile network | `svc data enable` / `svc data disable` |
| Dark mode | `cmd uimode night yes` / `cmd uimode night no` |
| Power-Saving mode | `cmd power set-mode 1` / `0` |
| Don't Disturb mode | `cmd notification set_dnd on` / `off` |
| Brightness (manual, Turn off the automatic brightness mode to take effect) | `settings put system screen_brightness <0-255>` |
| Auto-brightness | `settings put system screen_brightness_mode 1` / `0` |
| DND | `cmd notification set_dnd on` / `off` |
| Location on/off | `cmd location set-location-enabled true` / `false` |
| Open notifications | `cmd statusbar expand-notifications` |
| Open control center | `cmd statusbar expand-settings` |
| Collapse panels | `cmd statusbar collapse` |
| Check background apps | `input keyevent KEYCODE_APP_SWITCH` |
| App gallery(on homescreen) | `input keyevent 284` |
| Global search | `am start -a android.search.action.GLOBAL_SEARCH` |

For the full catalog including settings panels, night display, auto-rotate, battery saver, global search, and OEM notes, read [references/adb-commands.md](references/adb-commands.md).

## Deeplink probing

Use when you need to reach a specific page inside an Android app, especially for OEM or preinstalled apps where the route is unclear.

### When to use

- Task like "open search with keyword", "jump to note detail", "figure out which exported component is usable"
- You know (or can discover) the package name
- Blind `am start -n` guessing is too noisy

### Helper script

```bash
# Fast mode — compact candidate set, quick results
python3 nanobot/skills/claw-gui/scripts/probe_deeplinks.py \
  --package com.example.app \
  --task "open search with keyword" \
  --mode fast \
  --no-exec

# Execute against a device
python3 nanobot/skills/claw-gui/scripts/probe_deeplinks.py \
  --package com.example.app \
  --task "open search with keyword" \
  --serial emulator-5554 \
  --mode fast

# Investigate mode — broader expansion when fast mode stalls
python3 nanobot/skills/claw-gui/scripts/probe_deeplinks.py \
  --package com.example.app \
  --task "open note detail" \
  --mode investigate \
  --scheme appname \
  --host example.com
```

### Modes

- `fast`: compact candidate set + lightweight package profiling. Use by default.
- `investigate`: broader expansion + deeper profiling. Use when fast mode stalls.

### Output

JSON with `inputs`, `probes`, `system_checks`, and `summary`. Use `--format json` when piping to another tool. The summary reports: best candidates, partial matches, invalid candidates, and next commands to try.

### Guidance

- Start with `--no-exec` if unsure whether a device is connected.
- Summarize findings instead of pasting raw shell output.
- Treat `http/https` results separately from custom schemes — browser fallback usually means domain verification is missing.
- For OEM system apps, pivot to provider/service lanes if `dumpsys package` reveals authorities or non-UI entry paths.
- For deeper methodology, read [references/deeplink-method.md](references/deeplink-method.md).

## gui_task tool

If the claw provides a native `gui_task` tool (e.g., nanobot's built-in GUI subagent), prefer it over the CLI for visual automation. It handles screenshots, action grounding, skill matching, and multi-step execution internally.

Usage: pass a natural-language task description as the `task` parameter. Optional `backend` parameter overrides the configured backend (`adb`, `ios`, `hdc`, `local`, `dry-run`).

## opengui CLI fallback

When no native GUI tool is available, invoke the opengui CLI directly:

```bash
# Basic task on Android
python -m opengui.cli "tap the Settings icon" --backend adb --json

# With explicit task flag
python -m opengui.cli --task "scroll down and tap Wi-Fi" --backend adb

# iOS device
python -m opengui.cli "open Safari" --backend ios

# Dry run (no device needed)
python -m opengui.cli "tap the search bar" --dry-run --json
```

Key flags:
- `--backend adb|ios|hdc|local|dry-run` — target platform (default: `local`)
- `--json` — structured JSON output
- `--config <path>` — config file (default: `~/.opengui/config.yaml`)
- `--agent-profile <name>` — prompt/action profile override
- `--dry-run` — plan actions without executing

Requires `~/.opengui/config.yaml` with an LLM provider configured. See opengui documentation for setup.

## Agent hygiene

- Do not paste raw `dumpsys` or `logcat` output unless the user asks for it.
- When combining ADB commands with GUI steps, run ADB commands first to set up preconditions, then hand off to GUI for the visual part.
- For multi-device scenarios, always specify `--serial` or the device serial in adb commands.
- If a component is not exported or requires privileged permissions, report that boundary instead of retrying blindly.
