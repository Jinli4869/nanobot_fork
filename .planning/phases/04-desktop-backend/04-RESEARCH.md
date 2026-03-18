# Phase 4: Desktop Backend - Research

**Researched:** 2026-03-18
**Domain:** Desktop GUI automation — pyautogui, mss, pyperclip, platform-native APIs
**Confidence:** HIGH (all core libraries verified via PyPI + official docs; HiDPI behavior verified against mss GitHub issues)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Screenshot capture:** Use **mss** library (not pyautogui) for screenshots — faster, uses native APIs
- **Screenshot target:** Capture primary monitor only (`mss.monitors[1]`)
- **HiDPI handling:** Downscale to logical resolution on HiDPI/Retina — Observation reports logical width/height so coordinate mapping stays 1:1 with what the user sees
- **Screenshot format:** Save as PNG to the `screenshot_path` provided by the agent loop
- **Foreground app detection:** Platform-specific:
  - macOS: `osascript` (AppleScript) to get frontmost app name
  - Linux: `xdotool getactivewindow getwindowpid` + process name lookup
  - Windows: `win32gui.GetForegroundWindow()` + process name
- **Action mapping:**
  - `tap` → `pyautogui.click(x, y)`
  - `double_tap` → `pyautogui.doubleClick(x, y)`
  - `long_press` → `pyautogui.rightClick(x, y)`
  - `swipe` / `drag` → `pyautogui.mouseDown()` + `pyautogui.moveTo()` + `pyautogui.mouseUp()`
  - `scroll` → `pyautogui.scroll(clicks)`, pixels // 120 conversion
  - `wait` → `asyncio.sleep(duration_ms / 1000)`
  - `back` / `home` → OS-level shortcuts
  - `done` → no-op
- **Hotkey handling:** `pyautogui.hotkey()` with platform-aware modifier normalization (darwin/linux/win32 map)
- **Text input:** Clipboard-paste only via pyperclip — no per-character fallback
- **App management:** OS-native open/close with graceful-then-force-kill pattern
- **Platform targeting:** macOS-first for v1; Linux/Windows stubs with correct subprocess calls but marked untested
- **Platform string:** `'macos'` / `'linux'` / `'windows'` detected via `platform.system()`
- **Skills location:** `workspace/gui_skills/{platform}/`
- **Preflight:** Raise with message "Enable Accessibility for Terminal/iTerm in System Settings > Privacy > Accessibility" on macOS permission error

### Claude's Discretion

- Exact mss screenshot-to-PIL conversion and HiDPI scale factor detection
- Scroll click conversion ratio (pixels // 120 is default, adjust if needed)
- `back` / `home` key mappings per platform
- Error message formatting for unsupported actions per platform
- Test structure and mock patterns (follow existing test conventions)

### Deferred Ideas (OUT OF SCOPE)

- Multi-monitor support (configurable monitor index) — future enhancement
- Per-character typing fallback for headless Linux — future if needed
- Window-level close (close specific window, not whole app) — future
- `open_file` action (open file with default or specified app) — future capability
- Linux Wayland support (currently assuming X11 for xdotool) — future
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BACK-03 | LocalDesktop backend (pyautogui + pyperclip) for macOS/Linux/Windows | mss for screenshots, pyautogui for actions, pyperclip for text input, platform-native foreground app detection, async DeviceBackend protocol pattern from AdbBackend |
</phase_requirements>

---

## Summary

Phase 4 implements `LocalDesktopBackend`, a new backend alongside `AdbBackend` and `DryRunBackend` that lets `GuiAgent` automate a local macOS/Linux/Windows desktop. The backend must conform to the `DeviceBackend` protocol (observe/execute/preflight/platform) and is structurally typed — no base class needed.

The core library stack is mature and stable: **mss 10.1.0** for screenshots (faster than PIL.ImageGrab, native ctypes, no X-server requirement), **pyautogui 0.9.54** for mouse/keyboard dispatch, and **pyperclip 1.11.0** for clipboard-based text input. All three have known macOS behaviors to account for — most importantly, mss returns physical (2x) pixel dimensions on Retina displays while pyautogui.click() accepts logical coordinates, requiring explicit downscaling of the captured image before saving and reporting logical dimensions to the Observation.

The DeviceBackend contract is fully understood from studying AdbBackend and DryRunBackend. Async subprocess wrappers for foreground-app detection and app lifecycle (open/close) follow the same `asyncio.create_subprocess_exec` pattern as AdbBackend. The single integration seam to wire up is replacing the `NotImplementedError` stub at line 132 of `nanobot/agent/tools/gui.py`.

**Primary recommendation:** Model `LocalDesktopBackend` directly on `AdbBackend` structure — same async I/O patterns, same coordinate helpers, same observe/execute/preflight layout — but swap all ADB subprocess calls with pyautogui/mss/pyperclip equivalents.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| mss | 10.1.0 | Screenshot capture (primary monitor) | Ultra-fast native ctypes; no extra deps; 2x faster than PIL.ImageGrab; explicitly chosen over pyautogui screenshot in locked decisions |
| pyautogui | 0.9.54 | Mouse/keyboard action dispatch | De-facto cross-platform desktop automation; hotkey(), click(), doubleClick(), scroll(), mouseDown/moveTo/mouseUp() |
| pyperclip | 1.11.0 | Clipboard read/write for text_input | Handles Unicode/CJK natively via OS clipboard; no per-character encoding issues |
| Pillow | >=11.0 (already in pyproject.toml as transitive) | mss BGRA-to-RGB conversion + PNG save + downscale on HiDPI | Required for Image.frombytes + Image.resize |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| platform (stdlib) | — | Detect OS at runtime (`platform.system()` → Darwin/Linux/Windows) | Always — used for platform property and dispatch branching |
| asyncio (stdlib) | — | Non-blocking subprocess + sleep | Always — all I/O is async |
| subprocess / asyncio.create_subprocess_exec | — | osascript, xdotool, open -a, pkill, taskkill | Foreground app detection + app management |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| mss | pyautogui.screenshot() | pyautogui wraps PIL.ImageGrab which is slower and adds HiDPI complications on macOS — mss is explicitly chosen |
| pyperclip | pyautogui.typewrite() | typewrite() fails on Unicode/CJK; clipboard paste handles all encodings |
| asyncio.create_subprocess_exec | subprocess.run() | run() is synchronous and blocks the event loop — must stay async |

**Installation:**
```bash
pip install mss pyautogui pyperclip
```

**Version verification (confirmed against PyPI 2026-03-18):**
- mss: 10.1.0 (released 2025-08-16)
- pyautogui: 0.9.54 (released 2023-05-24)
- pyperclip: 1.11.0 (released 2025-09-26)
- Pillow: already present in repo (11.3.0 confirmed installed locally)

---

## Architecture Patterns

### Recommended Project Structure
```
opengui/
├── backends/
│   ├── __init__.py          # Add LocalDesktopBackend export
│   ├── adb.py               # Reference implementation (do not modify)
│   ├── dry_run.py           # Reference implementation (do not modify)
│   └── desktop.py           # NEW: LocalDesktopBackend
nanobot/
└── agent/tools/gui.py       # Replace NotImplementedError stub (1 line change)
tests/
└── test_opengui_p4_desktop.py  # NEW: phase 4 tests
```

### Pattern 1: DeviceBackend Structural Protocol

The backend is a plain class with no base class. Protocol conformance is structural (duck typing). All methods are async. The `platform` property is a synchronous property returning a plain string.

```python
# Source: opengui/interfaces.py + opengui/backends/adb.py
class LocalDesktopBackend:
    def __init__(self) -> None:
        self._screen_width: int = 0
        self._screen_height: int = 0

    @property
    def platform(self) -> str:
        import platform as _platform
        system = _platform.system()
        if system == "Darwin":
            return "macos"
        if system == "Linux":
            return "linux"
        return "windows"

    async def preflight(self) -> None: ...
    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation: ...
    async def execute(self, action: Action, timeout: float = 5.0) -> str: ...
```

### Pattern 2: HiDPI-Aware Screenshot Capture

**Critical:** mss on macOS Retina returns physical pixels (2x logical). pyautogui.click() operates in logical pixels. The Observation must report logical dimensions so `resolve_coordinate()` maps [0,999] coords to correct logical screen pixels.

Strategy: capture at physical resolution, detect scale factor, downscale image to logical resolution, report logical width/height.

```python
# Source: mss docs + GitHub issue #257 (BoboTiG/python-mss)
import mss
from PIL import Image

def _capture_primary_logical() -> tuple[Image.Image, int, int]:
    """Capture primary monitor; return (PIL_image, logical_w, logical_h)."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # primary monitor
        sct_img = sct.grab(monitor)
        # sct_img.size = (physical_w, physical_h) on Retina
        # monitor["width"] / monitor["height"] = logical dimensions on macOS
        logical_w = monitor["width"]
        logical_h = monitor["height"]
        physical_w, physical_h = sct_img.size
        img = Image.frombytes("RGB", (physical_w, physical_h), sct_img.bgra, "raw", "BGRX")
        if physical_w != logical_w or physical_h != logical_h:
            img = img.resize((logical_w, logical_h), Image.LANCZOS)
    return img, logical_w, logical_h
```

**Why `monitor["width"]` is logical:** mss stores the logical/CSS pixel dimensions in the monitor dict (`width`, `height` fields), but the raw grab returns physical pixel data. On a 2x Retina display, `sct_img.size = (2880, 1800)` while `monitor["width"] = 1440`. Resizing to logical before saving keeps coordinate math consistent with pyautogui.

### Pattern 3: Async Subprocess for Foreground App

```python
# Source: opengui/backends/adb.py _run() pattern
async def _run_cmd(self, *args: str, timeout: float = 5.0) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return ""
    return stdout_bytes.decode(errors="replace").strip()

# macOS foreground app
async def _query_foreground_app_macos(self) -> str:
    script = 'tell application "System Events" to get name of first process where it is frontmost'
    result = await self._run_cmd("osascript", "-e", script)
    return result or "unknown"
```

### Pattern 4: Drag/Swipe via mouseDown/moveTo/mouseUp

The `dragTo()` convenience method in pyautogui is synchronous and blocks. For async-safe drag that holds button during movement, use the lower-level primitives:

```python
# Source: pyautogui docs — mouse.html
import pyautogui
# drag: hold left button, move, release
pyautogui.mouseDown(x1, y1, button="left")
pyautogui.moveTo(x2, y2, duration=0.3)
pyautogui.mouseUp(x2, y2, button="left")
```

All pyautogui calls are synchronous but fast (sub-millisecond); wrap in `asyncio.get_event_loop().run_in_executor(None, ...)` only if latency becomes an issue. For v1, direct synchronous calls inside async methods are acceptable because they complete instantly.

### Pattern 5: Platform-Aware Modifier Normalization

```python
# Source: CONTEXT.md specifics / locked decision
_MODIFIER_MAP: dict[str, dict[str, str]] = {
    "darwin": {"cmd": "command", "option": "alt", "super": "command"},
    "linux":  {"cmd": "win", "super": "win", "option": "alt"},
    "win32":  {"cmd": "win", "option": "alt", "super": "win"},
}

def _normalize_keys(self, keys: list[str]) -> list[str]:
    sys_map = _MODIFIER_MAP.get(sys.platform, {})
    return [sys_map.get(k.lower(), k.lower()) for k in keys]
```

### Anti-Patterns to Avoid

- **Importing pyautogui at module top-level in `__init__.py`:** pyautogui may call `SetProcessDpiAware()` on import and affect mss behavior. Import pyautogui inside `desktop.py` only, and always import mss before pyautogui.
- **Using `pyautogui.screenshot()`:** Slower, adds Retina scaling confusion — use mss exclusively.
- **Synchronous subprocess for app management:** Use `asyncio.create_subprocess_exec`, not `subprocess.run()`.
- **Per-character `typewrite()` for text_input:** Fails on non-ASCII. Clipboard-paste-only is the locked decision.
- **Blocking event loop with `time.sleep()`:** Use `asyncio.sleep()` for wait actions.
- **Hardcoding scale factor to 2:** Always compute from `physical / logical`; some external monitors have different ratios.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Mouse/keyboard dispatch | Custom CGEvent wrapper | pyautogui | Handles cross-platform quirks, FailSafe, delays; well-tested |
| Screenshot capture | PIL.ImageGrab / Quartz CGWindowListCreateImage | mss | 2x faster; pure ctypes; handles multi-monitor correctly |
| Clipboard I/O | Custom pbcopy/xclip subprocess | pyperclip | Cross-platform; handles fallback clipboard mechanisms per OS |
| Unicode text encoding | Per-character escape logic | pyperclip + paste | Native OS clipboard handles CJK, emoji, all Unicode |

**Key insight:** The clipboard-paste pattern for text input sidesteps every character encoding, IME, and key repeat issue. It is the correct solution for desktop automation — do not introduce per-character fallback.

---

## Common Pitfalls

### Pitfall 1: mss Returns Physical Pixels, pyautogui Expects Logical
**What goes wrong:** screenshot dimensions are 2880x1800, Observation reports 2880x1800, coordinate resolution maps [0,999] to 2880 pixels, pyautogui.click receives coordinate in physical space — click lands at wrong location (off by 2x).
**Why it happens:** mss grabs raw framebuffer pixels; pyautogui's coordinate system on macOS Retina is logical (1440x900).
**How to avoid:** Always use `monitor["width"]` / `monitor["height"]` (logical) as the reported Observation dimensions. Downscale the captured image to logical resolution before saving. The screenshot and action coordinates will then agree.
**Warning signs:** Clicks land in wrong quadrant; items are off by a consistent factor of ~2.

### Pitfall 2: pyautogui Requires macOS Accessibility Permission
**What goes wrong:** pyautogui calls succeed silently or raise `PyAutoGUIException` without a clear explanation.
**Why it happens:** macOS sandboxes keyboard/mouse control behind the Accessibility privacy permission. The terminal, iTerm, or Python executable must be granted permission.
**How to avoid:** `preflight()` must attempt a safe no-op (e.g., `pyautogui.position()`) inside a try/except and raise with the exact message: `"Enable Accessibility for Terminal/iTerm in System Settings > Privacy > Accessibility"`.
**Warning signs:** All pyautogui calls no-op; mouse does not move on test run.

### Pitfall 3: Importing pyautogui Before mss Sets DPI Awareness Incorrectly
**What goes wrong:** On Windows (and occasionally macOS), pyautogui/pyscreeze calls `SetProcessDpiAware()` at import time, which changes how subsequent mss calls perceive screen size.
**How to avoid:** In `desktop.py`, import mss at the top; lazy-import pyautogui inside methods or after mss has been used at least once. (Or: import mss first in the module-level imports block.)

### Pitfall 4: osascript Foreground App Returns Bundle ID Not Display Name
**What goes wrong:** The AppleScript `get name of first process` returns the process name (e.g., "Google Chrome"), but may return bundle executable names for some apps.
**How to avoid:** Use `tell application "System Events" to get name of first process where it is frontmost` — returns human-readable name consistent with what the user sees in the dock. Return `"unknown"` on any error; don't crash observe().

### Pitfall 5: pyperclip Clipboard Paste Overwrites User Clipboard
**What goes wrong:** After text_input, the user's clipboard contents are replaced by the injected text.
**Why it matters:** Acceptable trade-off for v1 (locked decision), but tests should not assume clipboard state is preserved.
**Mitigation (optional, discretion area):** Save and restore clipboard contents around paste. Only worth doing if explicitly requested.

### Pitfall 6: scroll() click Conversion Produces Zero for Small pixel Values
**What goes wrong:** `action.pixels = 60` → `60 // 120 = 0` → `pyautogui.scroll(0)` → no scroll happens.
**How to avoid:** Use `max(1, pixels // 120)` for non-zero pixel values. Use `min(-1, -(pixels // 120))` for upward scrolls. Alternatively, clamp to ±1 minimum when pixels > 0.

---

## Code Examples

Verified patterns from official sources and codebase study:

### observe() — mss screenshot + Pillow conversion
```python
# Source: mss docs (python-mss.readthedocs.io/examples.html) + GitHub issue #257
import mss
from PIL import Image
from pathlib import Path

async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        logical_w: int = monitor["width"]
        logical_h: int = monitor["height"]
        sct_img = sct.grab(monitor)
        physical_w, physical_h = sct_img.size

        img = Image.frombytes("RGB", (physical_w, physical_h), sct_img.bgra, "raw", "BGRX")
        if physical_w != logical_w or physical_h != logical_h:
            img = img.resize((logical_w, logical_h), Image.LANCZOS)
        img.save(str(screenshot_path), "PNG")

    self._screen_width = logical_w
    self._screen_height = logical_h
    fg_app = await self._query_foreground_app()

    return Observation(
        screenshot_path=str(screenshot_path),
        screen_width=logical_w,
        screen_height=logical_h,
        foreground_app=fg_app,
        platform=self.platform,
    )
```

### execute() — tap / click dispatch
```python
# Source: pyautogui docs (mouse.html) + opengui/backends/adb.py pattern
import pyautogui

async def execute(self, action: Action, timeout: float = 5.0) -> str:
    t = action.action_type

    if t == "tap":
        x, y = self._resolve_point(action)
        pyautogui.click(x, y)

    elif t == "double_tap":
        x, y = self._resolve_point(action)
        pyautogui.doubleClick(x, y)

    elif t == "long_press":
        x, y = self._resolve_point(action)
        pyautogui.rightClick(x, y)

    elif t in ("drag", "swipe"):
        x1, y1 = self._resolve_point(action)
        x2, y2 = self._resolve_second_point(action)
        dur = (action.duration_ms or 300) / 1000.0
        pyautogui.mouseDown(x1, y1, button="left")
        pyautogui.moveTo(x2, y2, duration=dur)
        pyautogui.mouseUp(x2, y2, button="left")

    elif t == "scroll":
        x = self._screen_width // 2
        y = self._screen_height // 2
        if action.x is not None and action.y is not None:
            x, y = self._resolve_point(action)
        direction = (action.text or "down").lower()
        clicks = max(1, abs(action.pixels or 120) // 120)
        pyautogui.moveTo(x, y)
        pyautogui.scroll(-clicks if direction == "down" else clicks)

    elif t == "input_text":
        import pyperclip
        text = action.text or ""
        if text:
            pyperclip.copy(text)
            import sys
            paste_key = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(paste_key, "v")

    elif t == "hotkey":
        keys = self._normalize_keys(action.key or [])
        pyautogui.hotkey(*keys)

    elif t == "wait":
        await asyncio.sleep((action.duration_ms or 1000) / 1000.0)

    elif t == "done":
        pass

    # ... back, home, open_app, close_app
    else:
        raise ValueError(f"Unsupported action type for desktop backend: {t!r}")

    return describe_action(action)
```

### preflight() — accessibility check
```python
# Source: pyautogui docs + GitHub issues #247, #325
async def preflight(self) -> None:
    import pyautogui
    try:
        pyautogui.position()  # no-op; fails if accessibility not granted
    except Exception as exc:
        raise RuntimeError(
            "Enable Accessibility for Terminal/iTerm in "
            "System Settings > Privacy & Security > Accessibility"
        ) from exc
```

### Integration seam in gui.py (1-line change)
```python
# Source: nanobot/agent/tools/gui.py line 132
# BEFORE:
#   raise NotImplementedError("LocalDesktopBackend is planned for Phase 4 ...")
# AFTER:
if backend_name == "local":
    from opengui.backends.desktop import LocalDesktopBackend
    return LocalDesktopBackend()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pyautogui.screenshot()` for capture | `mss.grab()` | ~2020 (mss 5.x+) | 2x+ faster; no PIL.ImageGrab blocking |
| `pyautogui.typewrite()` for text | `pyperclip.copy()` + paste hotkey | ~2019 | Full Unicode/CJK support |
| Direct `subprocess.run()` for shell | `asyncio.create_subprocess_exec` | Python 3.7+ | Non-blocking, works in async contexts |

**Deprecated/outdated:**
- `pyautogui.typewrite(text)`: Broken for non-ASCII; do not use for text_input
- `PIL.ImageGrab.grab()`: Slower than mss; HiDPI scaling handled inconsistently

---

## Open Questions

1. **mss `monitor["width"]` logical vs physical on all macOS versions**
   - What we know: GitHub issue #257 confirmed `sct.grab().size` returns physical pixels on Retina; community workaround uses `kCGWindowImageNominalResolution` flag. Later mss versions (after PR #346 merge) allow `IMAGE_OPTIONS = 0` to toggle behavior.
   - What's unclear: Whether `monitor["width"]` reliably returns logical pixels across mss 10.1.0 on all macOS versions, or if it returns physical on some.
   - Recommendation: Add a smoke test during Wave 0 that asserts `monitor["width"] == pyautogui.size()[0]` on the macOS development machine. If they differ, use `pyautogui.size()` as the authoritative logical size source, and scale the captured image from physical to that logical size.

2. **pyautogui.scroll() direction convention**
   - What we know: pyautogui `scroll(positive)` = scroll up (content moves up), `scroll(negative)` = scroll down. macOS natural scroll may invert this.
   - Recommendation: Implement, then verify empirically on macOS. Adjust sign if content moves opposite to expected direction.

3. **Minimum `pyautogui.PAUSE` value**
   - What we know: pyautogui inserts a 0.1s pause after every call by default (PAUSE attribute). For batch execute calls, this adds up.
   - Recommendation: Set `pyautogui.PAUSE = 0.0` in the backend constructor; the agent loop already controls step cadence via observation cycles.

---

## Validation Architecture

> `workflow.nyquist_validation` is absent from `.planning/config.json` — treat as enabled.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| Quick run command | `pytest tests/test_opengui_p4_desktop.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BACK-03 | `observe()` captures screenshot and returns Observation with correct platform string | unit | `pytest tests/test_opengui_p4_desktop.py::test_observe_returns_observation -x` | ❌ Wave 0 |
| BACK-03 | `observe()` writes a valid PNG file to `screenshot_path` | unit | `pytest tests/test_opengui_p4_desktop.py::test_observe_writes_png -x` | ❌ Wave 0 |
| BACK-03 | `execute(tap)` dispatches `pyautogui.click(x, y)` with resolved [0,999] coordinates | unit | `pytest tests/test_opengui_p4_desktop.py::test_execute_tap -x` | ❌ Wave 0 |
| BACK-03 | `execute(scroll)` calls `pyautogui.scroll()` with pixels//120 conversion | unit | `pytest tests/test_opengui_p4_desktop.py::test_execute_scroll -x` | ❌ Wave 0 |
| BACK-03 | `execute(input_text)` uses pyperclip.copy + hotkey paste (not typewrite) | unit | `pytest tests/test_opengui_p4_desktop.py::test_execute_input_text_uses_clipboard -x` | ❌ Wave 0 |
| BACK-03 | `execute(swipe)` uses mouseDown/moveTo/mouseUp (not dragTo) | unit | `pytest tests/test_opengui_p4_desktop.py::test_execute_swipe -x` | ❌ Wave 0 |
| BACK-03 | `preflight()` raises RuntimeError with accessibility message when pyautogui fails | unit | `pytest tests/test_opengui_p4_desktop.py::test_preflight_raises_on_permission_error -x` | ❌ Wave 0 |
| BACK-03 | `_build_backend("local")` in GuiSubagentTool returns LocalDesktopBackend (not NotImplementedError) | integration | `pytest tests/test_opengui_p4_desktop.py::test_gui_tool_builds_local_backend -x` | ❌ Wave 0 |

### Key Mock Patterns (for unit tests without a real display)

All pyautogui, mss, and pyperclip calls must be mocked in unit tests — CI has no display. Follow the existing `unittest.mock.patch` pattern from test_opengui.py and test_opengui_p3_nanobot.py:

```python
# Source: test_opengui_p3_nanobot.py pattern
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_execute_tap(tmp_path):
    with patch("opengui.backends.desktop.pyautogui") as mock_pag:
        backend = LocalDesktopBackend()
        backend._screen_width = 1000
        backend._screen_height = 1000
        action = Action(action_type="tap", x=500, y=500, relative=False)
        result = await backend.execute(action)
        mock_pag.click.assert_called_once_with(500, 500)
        assert "tap" in result
```

For `observe()`, mock `mss.mss` as a context manager returning a fake screenshot object, and mock PIL.Image operations if needed.

### Sampling Rate
- **Per task commit:** `pytest tests/test_opengui_p4_desktop.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p4_desktop.py` — all BACK-03 unit + integration tests
- [ ] `opengui/backends/desktop.py` — LocalDesktopBackend implementation file (Wave 1)

*(No new framework config needed — pytest + pytest-asyncio already configured in pyproject.toml)*

---

## Sources

### Primary (HIGH confidence)
- `opengui/interfaces.py` — DeviceBackend protocol definition (direct code read)
- `opengui/backends/adb.py` — AdbBackend reference pattern (direct code read)
- `opengui/backends/dry_run.py` — DryRunBackend minimal pattern (direct code read)
- `opengui/action.py` — Action dataclass, resolve_coordinate, describe_action (direct code read)
- `nanobot/agent/tools/gui.py` — Integration seam at line 132 (direct code read)
- [mss PyPI](https://pypi.org/project/mss/) — version 10.1.0 confirmed
- [mss examples](https://python-mss.readthedocs.io/examples.html) — PIL.Image.frombytes("RGB", ..., sct_img.bgra, "raw", "BGRX") pattern
- [mss API](https://python-mss.readthedocs.io/api.html) — IMAGE_OPTIONS scaling flag, monitor dict structure
- [pyperclip PyPI](https://pypi.org/project/pyperclip/) — version 1.11.0 confirmed
- [PyAutoGUI PyPI](https://pypi.org/project/PyAutoGUI/) — version 0.9.54 confirmed

### Secondary (MEDIUM confidence)
- [mss GitHub issue #257](https://github.com/BoboTiG/python-mss/issues/257) — confirmed mss returns physical pixels on Retina; `monitor["width"]` is logical; PR #346 merged for scaling control
- [pyautogui mouse docs](https://pyautogui.readthedocs.io/en/latest/mouse.html) — mouseDown/moveTo/mouseUp drag pattern; dragTo() alternative
- [pyautogui GitHub issue #12](https://github.com/asweigart/pyautogui/issues/12) — pyautogui.size() returns logical dimensions on macOS Retina; click() accepts logical coords

### Tertiary (LOW confidence — flag for validation)
- Community reports that `pyautogui.PAUSE = 0.0` disables inter-call delays (not in official docs; empirically confirmed by multiple Stack Overflow answers)
- `monitor["width"]` == logical pixels assumption should be verified on macOS development machine via smoke test

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified against PyPI 2026-03-18
- Architecture: HIGH — DeviceBackend protocol read directly; mss/pyautogui patterns from official docs
- HiDPI handling: MEDIUM — behavior confirmed via mss GitHub issues, but `monitor["width"]`=logical assumption needs smoke-test validation on target machine
- Pitfalls: HIGH — macOS Accessibility requirement, scroll direction, import order all from official sources or verified issues
- Test patterns: HIGH — follows existing project test conventions directly observed in codebase

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable libraries; mss and pyautogui change infrequently)
