# Phase 4: Desktop Backend - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement `LocalDesktopBackend` conforming to the `DeviceBackend` protocol so that `GuiAgent` can automate macOS, Linux, or Windows desktops. The backend handles screenshot capture, action dispatch (tap/click, swipe/drag, scroll, text input, hotkeys, app launch/close), and preflight checks. This phase does NOT add new agent capabilities or modify the agent loop — it adds a new backend alongside the existing `AdbBackend` and `DryRunBackend`.

**Not in scope:** CLI entry point (Phase 5), new action types beyond what `Action` already supports, agent loop changes, multi-monitor support.

</domain>

<decisions>
## Implementation Decisions

### Screenshot Capture
- Use **mss** library (not pyautogui) for screenshots — faster, uses native APIs
- Capture **primary monitor only** (mss `monitors[1]`)
- **Downscale to logical resolution** on HiDPI/Retina displays — Observation reports logical width/height so coordinate mapping stays 1:1 with what the user sees (consistent with AdbBackend behavior)
- Save as PNG to the `screenshot_path` provided by the agent loop

### Foreground App Detection
- **Platform-specific detection** of the active foreground app name:
  - macOS: `osascript` (AppleScript) to get frontmost app name
  - Linux: `xdotool getactivewindow getwindowpid` + process name lookup
  - Windows: `win32gui.GetForegroundWindow()` + process name
- Returns human-readable app name (e.g., "Safari", "Firefox", "Code")

### Action Dispatch
- **Action type mapping to desktop equivalents:**
  - `tap` → `pyautogui.click(x, y)`
  - `double_tap` → `pyautogui.doubleClick(x, y)`
  - `long_press` → `pyautogui.rightClick(x, y)` (context menu on desktop)
  - `swipe` / `drag` → `pyautogui.click(x1, y1)` + `pyautogui.moveTo(x2, y2)` with button held (click-hold-move-release)
  - `scroll` → `pyautogui.scroll(clicks)` — convert `Action.pixels` to wheel clicks via `pixels // 120`
  - `wait` → `asyncio.sleep(duration_ms / 1000)`
  - `back` / `home` → map to OS-level shortcuts (e.g., Cmd+Left for back on macOS, Super for home on Linux)
  - `done` → no-op (terminal action)
- Coordinate resolution uses existing `resolve_coordinate()` with logical screen dimensions

### Hotkey Handling
- Use **pyautogui.hotkey()** with native pyautogui key names (not Android keycodes)
- **Platform-aware modifier normalization:**
  - macOS: `cmd` → `command`, `option` → `alt`
  - Linux: `cmd` → `win`, `super` → `win`
  - Windows: `cmd` → `win`, `option` → `alt`
- Modifier validation: modifiers ordered first, single non-modifier key last
- Support full modifier combos: `['cmd', 'shift', 'c']` → `pyautogui.hotkey('command', 'shift', 'c')` on macOS

### Text Input
- **Clipboard-paste only** via pyperclip: `pyperclip.copy(text)` + `pyautogui.hotkey('command', 'v')` (macOS) / `('ctrl', 'v')` (Linux/Windows)
- No per-character typing fallback — clipboard paste handles CJK/Unicode natively
- Matches the success criteria specification exactly

### App Management (open_app / close_app)
- **OS-native commands** for app lifecycle:
  - macOS: `open -a "AppName"` / `osascript -e 'quit app "AppName"'`
  - Linux: `xdg-open` or direct executable / `pkill -f "AppName"`
  - Windows: `os.startfile()` or `subprocess.Popen()` / `taskkill /IM app.exe`
- **Graceful close first**, force kill (`SIGKILL` / `taskkill /F`) as fallback on timeout
- App names (human-readable), not package IDs

### Platform Targeting
- **macOS-first for v1** — fully implemented and tested on macOS (development platform is Darwin 24.5.0)
- Linux and Windows dispatch stubs with correct subprocess calls but marked as untested in this phase
- Platform string from `platform` property: `'macos'` / `'linux'` / `'windows'` (detected at runtime via `platform.system()`)
- Skills stored per-platform under `workspace/gui_skills/{platform}/` — macOS skills stay separate from Android skills

### Preflight Checks
- **Check and raise clear error** for macOS Accessibility permissions
- `preflight()` tests a no-op pyautogui call; if permission error, raises with message: "Enable Accessibility for Terminal/iTerm in System Settings > Privacy > Accessibility"
- Linux/Windows preflight checks for required tools (xdotool/wmctrl on Linux, etc.)

### Claude's Discretion
- Exact mss screenshot-to-PIL conversion and HiDPI scale factor detection
- Scroll click conversion ratio (pixels // 120 is the default, adjust if needed)
- `back` / `home` key mappings per platform
- Error message formatting for unsupported actions per platform
- Test structure and mock patterns (follow existing test conventions)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### DeviceBackend Protocol
- `opengui/interfaces.py` — DeviceBackend protocol definition (observe, execute, preflight, platform)
- `opengui/action.py` — Action dataclass, VALID_ACTION_TYPES, resolve_coordinate(), ActionError
- `opengui/observation.py` — Observation dataclass (screenshot_path, screen_width/height, foreground_app, platform)

### Existing Backend Implementations (reference patterns)
- `opengui/backends/adb.py` — AdbBackend: full reference implementation with observe/execute/preflight (~366 lines)
- `opengui/backends/dry_run.py` — DryRunBackend: minimal no-op implementation (~48 lines)
- `opengui/backends/__init__.py` — Backend exports

### Nanobot Integration (backend wiring)
- `nanobot/agent/tools/gui.py` — GuiSubagentTool with `NotImplementedError` for `backend="local"` that this phase resolves
- `nanobot/config/schema.py` — GuiConfig with `backend: Literal["adb", "local", "dry-run"]`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `resolve_coordinate(value, dimension, relative)` in `opengui/action.py`: maps [0,999] relative coords to device pixels — reuse directly
- `describe_action(action)` in `opengui/action.py`: returns human-readable action description — return from execute()
- `Observation` dataclass: use as-is, populate with platform-specific values
- `Action` dataclass: frozen, immutable — read action_type, coordinates, text, key fields

### Established Patterns
- Backends are plain classes (not inheriting from a base) that satisfy the `DeviceBackend` protocol structurally
- All I/O is async (`async def observe`, `async def execute`, `async def preflight`)
- `execute()` returns `str` (action description via `describe_action()`)
- `observe()` creates parent directories, writes screenshot, returns `Observation`
- `preflight()` raises on failure, returns None on success

### Integration Points
- `opengui/backends/__init__.py` — add `LocalDesktopBackend` export
- `nanobot/agent/tools/gui.py` — replace `NotImplementedError` for `backend="local"` with `LocalDesktopBackend` construction
- Phase 3's GuiSubagentTool already handles backend selection from config

</code_context>

<specifics>
## Specific Ideas

- User provided detailed reference implementations for **DesktopHotkeyHandler** (platform-aware modifier normalization, key validation, pyautogui.hotkey() generation) and **DesktopAppManager** (OS-native open/close with graceful quit + force kill fallback). These should be used as **logic references** during implementation — adapt to the async DeviceBackend pattern, not copied verbatim.
- The hotkey handler reference includes a complete `PLATFORM_MODIFIER_MAP` for darwin/linux/win32 with alias normalization (`cmd` → `command` on macOS, `win` on Linux/Windows)
- The app manager reference includes both graceful close (osascript quit / SIGTERM / taskkill) and force kill paths per platform

</specifics>

<deferred>
## Deferred Ideas

- Multi-monitor support (configurable monitor index) — future enhancement
- Per-character typing fallback for headless Linux — future if needed
- Window-level close (close specific window, not whole app) — future
- `open_file` action (open file with default or specified app) — future capability
- Linux Wayland support (currently assuming X11 for xdotool) — future

</deferred>

---

*Phase: 04-desktop-backend*
*Context gathered: 2026-03-18*
