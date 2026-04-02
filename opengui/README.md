# OpenGUI

OpenGUI is a vision-based GUI automation engine. It takes a screenshot of the current screen, asks an LLM what action to take next, and executes that action — repeating until the task is complete. It supports Android (via ADB), iOS (via WebDriverAgent), HarmonyOS (via HDC), desktop (macOS / Linux / Windows), and a dry-run mode for testing.

OpenGUI can be used in two ways:

- **Standalone CLI** — run `opengui` directly with a YAML config file
- **nanobot GUI subagent** — OpenGUI is embedded as a tool inside nanobot, callable through any nanobot channel (TUI, Gateway, MCP, etc.)

---

## Table of Contents

1. [Installation](#installation)
2. [Standalone CLI](#standalone-cli)
   - [Config file](#config-file-homeopengui-configyaml)
   - [CLI flags reference](#cli-flags-reference)
   - [Usage examples](#usage-examples)
   - [Platform notes](#platform-notes)
3. [nanobot Integration](#nanobot-integration)
   - [Starting nanobot](#starting-nanobot)
   - [nanobot config.json](#nanobot-configjson)
   - [GUI section reference](#gui-section-reference)
   - [Switching backends](#switching-backends)
   - [Platform-specific examples](#platform-specific-examples)
4. [Planner / Router Integration](#planner--router-integration)
5. [App List Initialization](#app-list-initialization)
6. [Memory Store](#memory-store)
7. [Backends](#backends)
8. [Skills System](#skills-system)

---

## Installation

```bash
# Stable release
pip install nanobot-ai

# Development (from source)
pip install -e .

# Recommended: via uv
uv tool install nanobot-ai
```

**Platform extras** are installed automatically. On macOS the `pyobjc` accessibility stack is required — it ships with the package and requires no manual steps.

For the **iOS backend**, install the optional `facebook-wda` dependency:

```bash
pip install facebook-wda
```

---

## Standalone CLI

The `opengui` command drives a single GUI task without any nanobot runtime.

### Config file (`~/.opengui/config.yaml`)

The CLI reads configuration from `~/.opengui/config.yaml` by default (override with `--config <path>`).

**Minimal config (Alibaba Cloud DashScope):**

```yaml
provider:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3.5-plus"
  api_key: "sk-..."          # DashScope API Key from console.aliyun.com
```

**Full config with all options:**

```yaml
# LLM provider (required)
# DashScope OpenAI-compatible endpoint
provider:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3.5-plus"
  api_key: "sk-..."

# Embedding provider for semantic skill retrieval (optional)
# When omitted, skill search falls back to BM25 keyword matching
embedding:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "text-embedding-v4"
  api_key: "sk-..."          # defaults to provider.api_key if omitted

# ADB settings (Android backend only)
adb:
  serial: null               # null = auto-detect first connected device
  adb_path: "adb"            # path to adb binary; set if not on $PATH

# iOS / WebDriverAgent settings (iOS backend only)
ios:
  wda_url: "http://localhost:8100"   # URL of the running WDA server

# HDC settings (HarmonyOS backend only)
hdc:
  serial: null               # null = auto-detect first connected device
  hdc_path: "hdc"            # path to hdc binary; set if not on $PATH

# Execution limits
max_steps: 15

# Persistent storage (defaults shown)
memory_dir: "~/.opengui/memory"
skills_dir: "~/.opengui/skills"

# Headless virtual display (Linux only; requires Xvfb)
background: false
background_config:
  display_num: 99
  width: 1280
  height: 720
```

> **Get your DashScope API Key:** Log in to [Alibaba Cloud Console](https://dashscope.console.aliyun.com/) → API Keys → Create API Key.

### CLI flags reference

```
opengui [TASK] [OPTIONS]

Positional:
  TASK                    Task description (or use --task)

Options:
  --task TEXT             Task description (alternative to positional)
  --backend {adb,ios,hdc,local,dry-run}
                          Execution backend (default: local)
  --dry-run               Shortcut for --backend dry-run
  --config PATH           Config file path (default: ~/.opengui/config.yaml)
  --refresh-apps          Force re-fetch and cache the installed app list
  --background            Run on virtual Xvfb display [Linux only]
  --require-isolation     Fail if isolated background execution is unavailable
  --target-app-class {classic-win32,uwp,directx,gpu-heavy,electron-gpu}
                          Windows app class hint for background isolation
  --display-num INT       Xvfb display number (default: 99)
  --width INT             Display width in pixels (default: 1280)
  --height INT            Display height in pixels (default: 720)
  --json                  Emit machine-readable JSON output
```

### Usage examples

```bash
# Control local desktop (default)
opengui "Open the browser and go to github.com"

# Control Android device via ADB
opengui --backend adb "Open Settings and enable Wi-Fi"

# Control iOS device via WebDriverAgent
opengui --backend ios "Open Settings and check the iOS version"

# Control HarmonyOS device via HDC
opengui --backend hdc "Open Settings and enable Bluetooth"

# Run headlessly on Linux CI
opengui --backend local --background "Take a screenshot of the desktop"

# Dry-run (no real actions taken, useful for testing config)
opengui --dry-run "Click the save button"

# Force refresh the installed app list, then run
opengui --backend adb --refresh-apps "Open WeChat"

# Use a custom config file
opengui --config ~/my-config.yaml "Open the calculator"
```

### Platform notes

| Platform | Backend | Notes |
|----------|---------|-------|
| macOS    | `local` | Accessibility permission required: **System Settings → Privacy & Security → Accessibility** → add your terminal |
| Linux    | `local` | Install `xdotool` and `xclip`; use `--background` for headless CI |
| Windows  | `local` | Use `--target-app-class` to hint the window type for background isolation |
| Android  | `adb`   | Install [ADBKeyboard](https://github.com/senzhk/ADBKeyboard): `adb shell ime set com.android.adbkeyboard/.AdbIME` |
| iOS      | `ios`   | Requires WebDriverAgent running on device; install `pip install facebook-wda` |
| HarmonyOS | `hdc`  | Requires HDC (Huawei Device Connector) on `$PATH`; UITest service must be running on device |

---

## nanobot Integration

When you use nanobot, OpenGUI runs as the `gui` subagent tool. The main agent can delegate tasks like _"open the browser and log in"_ to OpenGUI automatically.

### Starting nanobot

nanobot ships two entry points:

**Interactive TUI / Gateway:**

```bash
nanobot                          # start interactive TUI chat
nanobot gateway                  # start API gateway only (0.0.0.0:18790)
```

**Standalone web UI backend:**

```bash
nanobot-tui                      # serves web UI at http://127.0.0.1:18791
```

Both accept a `--config` flag:

```bash
nanobot --config ~/my-config.json
nanobot-tui --config ~/my-config.json
```

Default config path: `~/.nanobot/config.json`

### nanobot config.json

nanobot reads a single JSON file. All keys accept both `camelCase` and `snake_case`.

**Minimal config (DashScope):**

```json
{
  "providers": {
    "dashscope": {
      "apiKey": "sk-..."
    }
  },
  "agents": {
    "defaults": {
      "model": "qwen3.5-plus"
    }
  }
}
```

**Full config with GUI subagent (main agent on DashScope, GUI agent on OpenRouter):**

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "qwen3.5-plus",
      "provider": "auto",
      "maxTokens": 8192,
      "temperature": 0.1,
      "maxToolIterations": 40
    }
  },

  "providers": {
    "dashscope": {
      "apiKey": "sk-..."
    },
    "openrouter": {
      "apiKey": "sk-or-...",
      "apiBase": "https://openrouter.ai/api/v1"
    }
  },

  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  },

  "tui": {
    "host": "127.0.0.1",
    "port": 18791,
    "logLevel": "info"
  },

  "gui": {
    "backend": "adb",
    "model": "openrouter/qwen/qwen2.5-vl-72b-instruct",
    "provider": "openrouter",
    "adb": { "serial": null },
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "skillThreshold": 0.6,
    "enableSkillExecution": true,
    "evaluation": {
      "enabled": true,
      "judgeModel": "qwen3-vl-plus",
      "apiKey": "sk-judge-...",
      "apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    }
  }
}
```

> **Note on `embeddingModel`:** When set, nanobot uses the DashScope embedding endpoint for semantic skill search. If omitted, skill matching falls back to BM25 keyword search.
>
> **Note on `gui.model` / `gui.provider`:** These are optional overrides for GUI tasks only. If omitted, the GUI subagent inherits `agents.defaults.model` and `agents.defaults.provider`.
>
> **Note on `gui.evaluation.judgeModel`:** This judge model is only used for optional post-run evaluation. It does not change the model that actually performs the GUI task.

### Using a different provider/model for GUI tasks

The main nanobot agent and the GUI subagent now support separate runtime selection:

- `agents.defaults.model` / `agents.defaults.provider`
  Main agent model/provider for planning, tool orchestration, chat, and non-GUI work
- `gui.model` / `gui.provider`
  GUI-only override for `gui_task`
- `gui.evaluation.judgeModel`
  Judge model used only when post-run GUI evaluation is enabled

Typical pattern:

```json
{
  "agents": {
    "defaults": {
      "model": "qwen3.5-plus",
      "provider": "dashscope"
    }
  },
  "providers": {
    "dashscope": {
      "apiKey": "sk-main-..."
    },
    "openrouter": {
      "apiKey": "sk-or-...",
      "apiBase": "https://openrouter.ai/api/v1"
    }
  },
  "gui": {
    "backend": "local",
    "model": "openrouter/qwen/qwen2.5-vl-72b-instruct",
    "provider": "openrouter"
  }
}
```

In that setup:

- the main agent stays on `qwen3.5-plus`
- GUI execution uses `openrouter/qwen/qwen2.5-vl-72b-instruct`
- the provider named by `gui.provider` must exist under the top-level `providers` block

If you omit `gui.provider`, nanobot falls back to the same provider-resolution logic used by the main agent and tries to infer the provider from `gui.model`.

### Optional GUI evaluation

If you want nanobot to evaluate each successful GUI run after the task finishes, enable `gui.evaluation`:

```json
{
  "gui": {
    "backend": "adb",
    "evaluation": {
      "enabled": true,
      "judgeModel": "qwen3-vl-plus",
      "apiKey": "sk-judge-...",
      "apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    }
  }
}
```

Behavior:

- evaluation runs only after a successful GUI task with a saved `trace.jsonl`
- evaluation runs in the background postprocessing path and does not block the main GUI result
- the evaluation result is written as `evaluation.json` next to the GUI run trace
- if `apiKey` is omitted, nanobot falls back to `OPENAI_API_KEY`
- `judgeModel` can use a different provider/model pair than both the main agent and the GUI agent, as long as `apiBase` and `apiKey` point to a compatible endpoint

### GUI section reference

The `gui` section activates the GUI subagent tool. If omitted, nanobot has no GUI capability.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `backend` | `"adb"` \| `"ios"` \| `"hdc"` \| `"local"` \| `"dry-run"` | `"adb"` | Execution backend |
| `model` | `string \| null` | `null` | GUI-only model override; inherits `agents.defaults.model` when omitted |
| `provider` | `string \| null` | `null` | GUI-only provider override; inherits main-agent provider resolution when omitted |
| `adb.serial` | `string \| null` | `null` | ADB device serial; `null` = auto-detect |
| `ios.wdaUrl` | `string` | `"http://localhost:8100"` | WebDriverAgent server URL |
| `hdc.serial` | `string \| null` | `null` | HDC device serial; `null` = auto-detect |
| `artifactsDir` | `string` | `"gui_runs"` | Directory for screenshots and run logs (relative to workspace) |
| `maxSteps` | `int` | `15` | Maximum actions per task before giving up |
| `embeddingModel` | `string \| null` | `null` | Embedding model for semantic skill search (e.g. `"text-embedding-v4"`) |
| `skillThreshold` | `float` | `0.6` | Minimum similarity score to attempt skill reuse |
| `background` | `bool` | `false` | Use isolated virtual display (Linux only; requires `backend: "local"`) |
| `displayNum` | `int \| null` | `null` | Xvfb display number |
| `displayWidth` | `int` | `1280` | Virtual display width in pixels |
| `displayHeight` | `int` | `720` | Virtual display height in pixels |
| `enableSkillExecution` | `bool` | `false` | Enable learned skill replay (see [Skills System](#skills-system)) |
| `evaluation.enabled` | `bool` | `false` | Run post-task evaluation for successful GUI runs |
| `evaluation.judgeModel` | `string` | `"qwen3-vl-plus"` | Judge model used for evaluation only |
| `evaluation.apiKey` | `string` | `""` | API key for the judge endpoint; falls back to `OPENAI_API_KEY` when empty |
| `evaluation.apiBase` | `string \| null` | `"https://dashscope.aliyuncs.com/compatible-mode/v1"` | OpenAI-compatible base URL for the judge endpoint |

### Switching backends

Change the `backend` field in the `gui` section to switch between device and desktop control:

```json
"gui": { "backend": "adb"      }   // Android device via ADB
"gui": { "backend": "ios"      }   // iOS device via WebDriverAgent
"gui": { "backend": "hdc"      }   // HarmonyOS device via HDC
"gui": { "backend": "local"    }   // local desktop (macOS / Linux / Windows)
"gui": { "backend": "dry-run"  }   // no real actions, for testing
```

In the standalone CLI, use the `--backend` flag:

```bash
opengui --backend adb     "..."    # Android
opengui --backend ios     "..."    # iOS
opengui --backend hdc     "..."    # HarmonyOS
opengui --backend local   "..."    # desktop
opengui --backend dry-run "..."    # dry-run
```

### Platform-specific examples

#### macOS — local desktop

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "local",
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> **Accessibility permission required.**
> Go to **System Settings → Privacy & Security → Accessibility** and add your terminal app (Terminal, iTerm2, or whichever app runs nanobot).

#### Linux — local desktop (GUI or headless CI)

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "local",
    "background": true,
    "displayNum": 99,
    "displayWidth": 1920,
    "displayHeight": 1080
  }
}
```

> Install required system packages first:
> ```bash
> sudo apt install xvfb xdotool xclip
> ```
>
> Set `"background": false` if you have a real display and don't need Xvfb.

#### Windows — local desktop

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "local",
    "maxSteps": 15,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> For GPU-accelerated or DirectX applications, use the `opengui` CLI with `--target-app-class directx` (or `gpu-heavy`, `electron-gpu`, `uwp`). This is not yet configurable via nanobot config.json.

#### Android — ADB

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "adb",
    "adb": { "serial": null },
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> **Android setup steps:**
> 1. Enable USB Debugging: **Settings → Developer Options → USB Debugging**
> 2. Connect the device via USB and accept the pairing prompt
> 3. Install ADBKeyboard (for text input): `adb install ADBKeyboard.apk`
> 4. Activate it: `adb shell ime set com.android.adbkeyboard/.AdbIME`
> 5. Verify: `adb devices` — your device serial should appear

To target a specific device when multiple are connected:

```json
"adb": { "serial": "R3CN70BAYER" }
```

Run `adb devices` to list available serials.

#### iOS — WebDriverAgent

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "ios",
    "ios": { "wdaUrl": "http://localhost:8100" },
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> **iOS setup steps:**
> 1. Install the Python client: `pip install facebook-wda`
> 2. Build and deploy [WebDriverAgent](https://github.com/appium/WebDriverAgent) onto your device via Xcode
> 3. Start the WDA server (Xcode test runner or `xcodebuild test-without-building`) — it listens on port `8100` by default
> 4. Forward the port over USB: `iproxy 8100 8100` (from `libimobiledevice`)
> 5. Verify the server is reachable: `curl http://localhost:8100/status`
>
> If WDA listens on a different host/port, update `wdaUrl` accordingly.

#### HarmonyOS — HDC

```json
{
  "providers": {
    "dashscope": { "apiKey": "sk-..." }
  },
  "agents": {
    "defaults": { "model": "qwen3.5-plus" }
  },
  "gui": {
    "backend": "hdc",
    "hdc": { "serial": null },
    "maxSteps": 20,
    "embeddingModel": "text-embedding-v4",
    "enableSkillExecution": true
  }
}
```

> **HarmonyOS setup steps:**
> 1. Enable Developer Mode: **Settings → About Phone → tap Build Number 7 times**
> 2. Enable USB Debugging: **Settings → Developer Options → USB Debugging**
> 3. Connect the device via USB and accept the pairing prompt on-device
> 4. Install the HDC tool (ships with DevEco Studio SDK): ensure `hdc` is on your `$PATH`
> 5. Verify: `hdc list targets` — your device serial should appear
>
> The UITest framework (`uitest` service) must be running on the device. It starts automatically on HarmonyOS 3.1+ when USB debugging is enabled.

To target a specific device when multiple are connected:

```json
"hdc": { "serial": "FMR0223C13000649" }
```

Run `hdc list targets` to list available serials.

---

## Planner / Router Integration

When nanobot decomposes a multi-step task into a plan, it needs to know which GUI route to assign to each GUI subtask. OpenGUI exposes a **route sentinel** per backend that the planner uses to emit correctly-typed plan nodes.

### Route sentinels

| Backend | Route sentinel | When it is active |
|---------|---------------|-------------------|
| `local` or `dry-run` | `gui.desktop` | Default; local desktop control |
| `adb` | `gui.adb` | Android device via ADB |
| `ios` | `gui.ios` | iOS device via WebDriverAgent |
| `hdc` | `gui.hdc` | HarmonyOS device via HDC |

The active sentinel is derived from `gui.backend` in your config:

```
"backend": "adb"   →  planner emits  route_id = "gui.adb"
"backend": "ios"   →  planner emits  route_id = "gui.ios"
"backend": "hdc"   →  planner emits  route_id = "gui.hdc"
"backend": "local" →  planner emits  route_id = "gui.desktop"
```

The router dispatches any of `gui.desktop`, `gui.adb`, `gui.ios`, and `gui.hdc` to the same underlying GUI subagent tool — the sentinel exists only so the planner (and human readers of plan traces) can see which physical device a subtask targets.

### How the planner learns the active backend

At planning time, nanobot passes the current backend as `active_gui_route` inside `PlanningContext`. The planner directive instructs the LLM:

> *"The current GUI backend is 'gui.hdc'. Use route_id='gui.hdc' for ALL GUI subtasks — do not use 'gui.desktop' or other GUI route IDs."*

This ensures that when you switch between an Android phone, an iPhone, and a HarmonyOS device, the planner automatically generates the correct route IDs without any manual intervention.

### Capability catalog

The capability catalog shown to the planner also reflects the active backend:

| `gui.backend` | Catalog summary shown to planner |
|---------------|----------------------------------|
| `adb` | "Use the GUI subagent to operate apps on the connected Android device" |
| `ios` | "Use the GUI subagent to operate apps on the connected iOS device" |
| `hdc` | "Use the GUI subagent to operate apps on the connected HarmonyOS device" |
| `local` | "Use the GUI subagent to operate apps on the local desktop" |

---

## App List Initialization

OpenGUI caches the list of installed apps so the agent knows which apps are available on the target device or desktop. The cache lives under `~/.opengui/apps/` as plain JSON arrays.

**Cache file locations by platform:**

| Platform | Cache file |
|----------|-----------|
| Android (default device) | `~/.opengui/apps/android_default.json` |
| Android (specific serial) | `~/.opengui/apps/android_R3CN70BAYER.json` |
| iOS | `~/.opengui/apps/ios_default.json` |
| HarmonyOS (default device) | `~/.opengui/apps/harmonyos_default.json` |
| HarmonyOS (specific serial) | `~/.opengui/apps/harmonyos_FMR0223C13000649.json` |
| macOS | `~/.opengui/apps/macos.json` |
| Linux | `~/.opengui/apps/linux.json` |
| Windows | `~/.opengui/apps/windows.json` |

### Auto-population

The app list is fetched automatically on first run and cached. Subsequent runs read from cache (fast). To force a full refresh:

```bash
opengui --refresh-apps --backend adb "Open WeChat"
opengui --refresh-apps --backend ios "Open Settings"
opengui --refresh-apps --backend hdc "Open Settings"
```

### Manual initialization

You can seed or edit the cache by hand. The format is a JSON array of strings.

**Android** (`~/.opengui/apps/android_default.json`):

```json
[
  "com.tencent.mm",
  "com.eg.android.AlipayGphone",
  "com.taobao.taobao",
  "com.android.settings",
  "com.android.chrome",
  "tv.danmaku.bili",
  "com.ss.android.ugc.aweme"
]
```

> Android entries are **package names**. Find them with:
> ```bash
> adb shell pm list packages -3      # third-party apps only
> adb shell pm list packages          # all packages
> ```

**iOS** (`~/.opengui/apps/ios_default.json`):

```json
[
  "com.apple.Preferences",
  "com.apple.mobilesafari",
  "com.tencent.xin",
  "com.alipay.iphoneclient",
  "com.ss.iphone.ugc.Aweme"
]
```

> iOS entries are **bundle IDs**. List installed app bundle IDs with:
> ```bash
> ideviceinstaller -l          # requires libimobiledevice
> ```

**HarmonyOS** (`~/.opengui/apps/harmonyos_default.json`):

```json
[
  "com.huawei.settings",
  "com.huawei.browser",
  "com.tencent.mm",
  "com.eg.android.AlipayGphone",
  "com.ss.android.ugc.aweme"
]
```

> HarmonyOS entries are **bundle names**. List installed bundles with:
> ```bash
> hdc shell bm dump -a          # list all bundles
> ```

**macOS** (`~/.opengui/apps/macos.json`):

```json
[
  "Safari",
  "Google Chrome",
  "Firefox",
  "Finder",
  "Terminal",
  "Visual Studio Code",
  "Slack",
  "Notion"
]
```

> macOS entries are the `.app` bundle names **without** the `.app` suffix, as they appear in `/Applications` or `~/Applications`.

**Linux** (`~/.opengui/apps/linux.json`):

```json
[
  "firefox",
  "google-chrome",
  "code",
  "gnome-terminal",
  "nautilus",
  "gedit",
  "slack"
]
```

> Linux entries are `.desktop` file stems from `/usr/share/applications/`. List them with:
> ```bash
> ls /usr/share/applications/*.desktop | xargs -I{} basename {} .desktop
> ```

**Windows** (`~/.opengui/apps/windows.json`):

```json
[
  "Microsoft Edge",
  "Google Chrome",
  "File Explorer",
  "Notepad",
  "Visual Studio Code",
  "Slack"
]
```

> Windows entries are human-readable application names used by OpenGUI when locating windows.

---

## Memory Store

OpenGUI maintains a persistent knowledge base at `~/.opengui/memory/` (both CLI and nanobot use the same path). Memory entries teach the agent how to navigate your specific OS environment, applications, and icons, and encode policies that govern its behaviour.

### Memory types

| Type | File | Purpose |
|------|------|---------|
| `os` | `os_guide.md` | General OS navigation tips (e.g. how the taskbar works, keyboard shortcuts) |
| `app` | `app_guide.md` | App-specific interaction guides (e.g. how a particular app's menu is structured) |
| `icon` | `icon_guide.md` | Icon and visual element recognition hints (e.g. what a custom icon looks like) |
| `policy` | `policy.md` | Agent behaviour policies (e.g. always confirm before deleting files) |

### File format

Each file is a sequence of Markdown `##` sections — one section per memory entry:

```markdown
## {heading — first line of content, max 72 characters}
id: {uuid}
type: {os|app|icon|policy}
platform: {android|ios|harmonyos|macos|linux|windows|dry-run}
app: {package name or app name, leave blank if not app-specific}
tags: {comma-separated tags, or leave blank}
created_at: {unix timestamp as float}
access_count: {int}

{content — free-form text describing what the agent should know}
```

### Examples

#### OS guide — macOS system navigation (`os_guide.md`)

```markdown
## Mission Control can be opened with Ctrl+Up or a three-finger swipe up
id: 3a7f2c1e-0001-4b2d-a100-000000000001
type: os
platform: macos
app:
tags: navigation, shortcut
created_at: 1711468800.0
access_count: 0

Mission Control can be opened with Ctrl+Up or a three-finger swipe up on the
trackpad. Use it to see all open windows and spaces. To switch spaces, swipe
left or right with three fingers, or press Ctrl+Left/Right.
```

#### App guide — WeChat Android (`app_guide.md`)

```markdown
## WeChat chat list is on the first tab; tap the compose icon to start a new
id: 3a7f2c1e-0002-4b2d-a100-000000000002
type: app
platform: android
app: com.tencent.mm
tags: wechat, chat
created_at: 1711468800.0
access_count: 0

WeChat chat list is on the first tab (bottom nav). Tap the compose icon
(pencil, top-right) to start a new chat. The search bar at the top searches
contacts and messages. Long-press a conversation to pin, mute, or delete it.
```

#### App guide — HarmonyOS Settings (`app_guide.md`)

```markdown
## HarmonyOS Settings main menu uses a card-based layout; swipe down to search
id: 3a7f2c1e-0005-4b2d-a100-000000000005
type: app
platform: harmonyos
app: com.huawei.settings
tags: settings, navigation
created_at: 1711468800.0
access_count: 0

HarmonyOS Settings presents options as large cards. Pull down anywhere in the
list to reveal the search bar. Wi-Fi is under "WLAN", Bluetooth under
"Bluetooth", and app permissions under "Apps > Permission Manager".
```

#### Icon guide — custom app icon (`icon_guide.md`)

```markdown
## The Lark/Feishu icon is a blue stylised wing shape on a white background
id: 3a7f2c1e-0003-4b2d-a100-000000000003
type: icon
platform: android
app: com.ss.android.lark
tags: icon, lark
created_at: 1711468800.0
access_count: 0

The Lark (Feishu) icon is a blue stylised wing or bird shape on a white
background. It may appear as "Lark" or "飞书" depending on locale. Do not
confuse it with the Twitter/X bird icon which is similar in shape but darker.
```

#### Policy — safety rules (`policy.md`)

```markdown
## Always confirm before sending any message or making any purchase
id: 3a7f2c1e-0004-4b2d-a100-000000000004
type: policy
platform: android
app:
tags: safety, confirmation
created_at: 1711468800.0
access_count: 0

Before sending any message, submitting any form, or completing any purchase,
pause and ask the user to confirm the action. Never proceed with irreversible
actions autonomously.
```

### Editing memory

You can add, edit, or delete entries by directly editing the Markdown files in `~/.opengui/memory/`. Rules:

- Each entry must start with `## ` followed by a short heading (≤ 72 chars)
- The `id:`, `type:`, and `platform:` metadata lines are **required**; all others are optional but recommended
- `id` must be a UUID — generate one with `python -c "import uuid; print(uuid.uuid4())"`
- `type` must be one of: `os`, `app`, `icon`, `policy`
- `platform` must be one of: `android`, `ios`, `harmonyos`, `macos`, `linux`, `windows`, `dry-run`
- Separate the metadata block from the content body with a blank line
- Multiple entries in the same file are separated by `##` headings

To delete an entry, simply remove its entire `##` section from the file.

---

## Backends

| Backend | Supported Platforms | Description |
|---------|---------------------|-------------|
| `local` | macOS / Linux / Windows | Control the desktop of the machine running nanobot/opengui |
| `adb` | Android (USB or network ADB) | Control a connected Android device or emulator |
| `ios` | iOS (USB or Wi-Fi via WebDriverAgent) | Control a connected iPhone or iPad via the WDA HTTP server |
| `hdc` | HarmonyOS (USB or network HDC) | Control a connected HarmonyOS device via `hdc` CLI and UITest framework |
| `dry-run` | Any | Testing mode — no real actions executed; screenshots return a 1×1 transparent PNG |

---

## Skills System

OpenGUI learns from successful task runs. After each task it extracts a reusable **skill** — a named, parameterised sequence of steps — and stores it in the skill library. On subsequent tasks it searches the library first; if a match scores above `skillThreshold`, the skill is replayed directly instead of exploring from scratch.

**Skill storage locations:**

| Mode | Location |
|------|----------|
| CLI (opengui) | `~/.opengui/skills/<platform>/` |
| nanobot | `<workspace>/gui_skills/<platform>/` |

### Enabling skill execution

Skill learning (extraction) is always on. Skill *execution* (replay) is opt-in:

```json
"gui": {
  "enableSkillExecution": true,
  "skillThreshold": 0.6,
  "embeddingModel": "text-embedding-v4"
}
```

With `enableSkillExecution: false` (default), skills are extracted and stored for future use but never replayed. This lets you build up a library passively before enabling replay.

### Tuning `skillThreshold`

| Value | Behaviour |
|-------|-----------|
| `1.0` | Only exact matches trigger replay |
| `0.6` | Default — matches semantically similar tasks |
| `0.3` | Aggressive reuse; may trigger on loosely related tasks |

Skills that fail repeatedly are automatically pruned (confidence falls below 0.3 after 5+ attempts).
