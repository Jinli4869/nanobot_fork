# Stack Research

**Domain:** Stack additions for macOS background execution, Windows isolated desktop execution, and intervention handoff
**Researched:** 2026-03-20
**Confidence:** MEDIUM

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `pyobjc-core` + `pyobjc-framework-Quartz` + `pyobjc-framework-ApplicationServices` | `12.1` | macOS bridge for CoreGraphics, Quartz, and Accessibility APIs | This is the cleanest Python path to Apple native APIs. It covers public C APIs directly and gives Objective-C runtime lookup (`objc.lookUpClass`) for the undocumented `CGVirtualDisplay*` classes without introducing a custom Swift or C extension first. |
| Win32 `user32` / `kernel32` / process APIs via `ctypes` plus `pywin32` | `pywin32==311` | Windows desktop creation, process launch onto a named desktop, desktop switching, and session input detection | `ctypes` keeps raw API access explicit and testable; `pywin32` removes boilerplate around handles, process creation, and constants. This is the smallest addition that can support `CreateDesktop`-class isolation from Python. |
| Existing `mss`, `pyautogui`, `pyperclip`, and `Pillow` desktop stack | Existing project versions (`mss>=10.0`, `pyautogui>=0.9.50`, `pyperclip>=1.8`, `Pillow>=10.0`) | Reuse screenshot and visible-desktop input paths | Reuse the shipped desktop backend for foreground mode and for macOS once the correct monitor is selected. Do not treat these libraries as sufficient for hidden Windows desktop automation. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `objc.lookUpClass` from PyObjC | bundled with `pyobjc-core 12.1` | Runtime lookup of `CGVirtualDisplay`, `CGVirtualDisplayDescriptor`, `CGVirtualDisplayMode`, and `CGVirtualDisplaySettings` | Use inside a new `CGVirtualDisplayManager` because the virtual-display classes are not present in public SDK headers on this machine's macOS 15.5 CLT SDK. |
| `ctypes.wintypes` | stdlib | Define `HDESK`, `STARTUPINFO`, `LASTINPUTINFO`, and Win32 function signatures | Use for `CreateDesktopW`, `OpenInputDesktop`, `SwitchDesktop`, `GetLastInputInfo`, and `GetUserObjectInformationW` if pywin32 does not expose the exact wrapper you need. |
| `win32process`, `win32event`, `win32gui`, `win32con`, `pywintypes` | from `pywin32 311` | Launch and manage a helper process attached to the isolated Windows desktop | Use for the Windows background worker process. This is preferable to trying to call `SetThreadDesktop` inside the long-lived main agent process. |
| `asyncio.subprocess` or `multiprocessing.connection` | stdlib | IPC between the main agent process and a Windows desktop worker process | Use because Windows desktop handles are process-local enough that "flip global state in-process" is the wrong abstraction. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Xcode Command Line Tools / macOS SDK | Validate header availability for public permission APIs and general build sanity | Local inspection on this machine confirms `AXIsProcessTrustedWithOptions`, `CGEventSourceSecondsSinceLastEventType`, `CGPreflightScreenCaptureAccess`, and `CGRequestScreenCaptureAccess`, but not public `CGVirtualDisplay` headers. |
| `pytest` + `pytest-asyncio` | Keep platform tests CI-safe | Mock the native boundary for lifecycle tests. Reserve real macOS and Windows validation for platform runners. |
| Platform-gated smoke tests on real OSes | Verify the undocumented and session-bound pieces | Required for `CGVirtualDisplay` creation on macOS and for desktop worker launch / switch behavior on Windows. |

## System Constraints

- macOS background display creation is the weakest-certainty path in this milestone. `CGVirtualDisplay` is not documented in the public SDK used here; current evidence comes from runtime/class usage in shipping software and Chromium's reverse-engineered interfaces. Treat this as a supported runtime capability only after validating on the target macOS versions.
- Production macOS support should target macOS 14+ even though Chromium labels the reverse-engineered classes as available earlier. The API is undocumented, behavior changed on newer releases, and current ecosystem code carries macOS 14-specific workarounds.
- macOS automation still requires Accessibility trust and Screen Recording permission. Those are public, stable requirements and should be checked before starting a background run.
- Windows desktop APIs are public and stable, but generic hidden-desktop input is constrained by foreground/input-desktop semantics. Microsoft documents that synthetic keyboard input is delivered to the foreground thread queue, which means a hidden alternate desktop cannot be treated like Linux Xvfb.
- The current `LocalDesktopBackend.observe()` hard-codes `mss.monitors[1]`. macOS virtual-display support therefore needs one code change outside dependency wiring: observation must honor `DisplayInfo.monitor_index` or explicit display bounds.

## Installation

```bash
# Existing desktop stack stays as-is
uv pip install -e ".[desktop,dev]"

# macOS additions
uv pip install "pyobjc-core==12.1" "pyobjc-framework-Quartz==12.1" "pyobjc-framework-ApplicationServices==12.1"

# Windows additions
uv pip install "pywin32==311"
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| PyObjC bridge into CoreGraphics and Accessibility APIs | A custom Swift helper binary | Use a Swift helper only if PyObjC runtime lookup of `CGVirtualDisplay*` proves too brittle in practice. Do not start there. |
| `ctypes` + `pywin32` with a Windows worker process launched onto a named desktop | In-process `SetThreadDesktop` switching | Use in-process switching only for tiny throwaway experiments. Microsoft documents that `SetThreadDesktop` fails once the thread owns windows or hooks, which makes it a poor fit for the main agent process. |
| Windows isolated desktop plus explicit foreground handoff | Separate VM / separate interactive user session | Use a VM or separate session if the product requirement becomes "fully unattended, truly hidden Windows input" across arbitrary apps. That is the more honest equivalent to Linux Xvfb. |
| Native OS idle/input APIs for intervention detection | Global hook libraries such as `pynput` | Use a hook library only if the public idle-time APIs are insufficient. Native OS APIs are smaller, clearer, and keep the permission surface lower. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| External runtime dependency on BetterDisplay, BetterDummy, dummy-plug workflows, or other GUI apps to create the macOS virtual display | That turns a library feature into a manual ops dependency and makes automation non-reproducible | Use direct PyObjC integration with `CGVirtualDisplay` first; keep external tools only for manual debugging. |
| `pywinauto` / raw UI Automation as the primary Windows background strategy | It changes the product from a vision-driven desktop agent into a control-tree automation stack and still does not solve arbitrary canvas apps | Keep the existing screen-driven backend semantics and use `CreateDesktop` / handoff or an isolated session. |
| Reusing `pyautogui` blindly for hidden Windows desktops | `pyautogui` is built on foreground input assumptions; Microsoft documents synthetic keyboard input as going to the foreground thread queue | Use a Windows worker plus explicit `SwitchDesktop` handoff when real input is required. |
| A new cross-platform notification dependency just for handoff | The hard problem is not notifications, it is pausing, state transfer, and backend rebind | Implement handoff in the backend/orchestration layer; add notifications later only if UX still needs them. |

## Stack Patterns by Variant

**If macOS background mode is enabled:**

- Add `CGVirtualDisplayManager` implementing the existing `VirtualDisplayManager` protocol.
- Build it with PyObjC runtime lookup for `CGVirtualDisplay*` classes, plus public `Quartz` / `ApplicationServices` calls for permission checks and idle-time detection.
- Return `DisplayInfo` with the virtual display identifier, pixel size, coordinate offsets, and the monitor index or bounds needed by `mss`.
- Keep `BackgroundDesktopBackend` as the wrapper for macOS. This path fits the current abstraction well once observation honors the selected monitor instead of always using monitor `1`.

**If Windows background mode is enabled:**

- Do not force Windows into the existing `VirtualDisplayManager` model. `CreateDesktop` creates a desktop/session boundary, not a display-server endpoint like Xvfb.
- Add a Windows-only backend adapter such as `WindowsIsolatedDesktopBackend` that still satisfies `DeviceBackend` but internally talks to a helper process created with `STARTUPINFO.lpDesktop` set to the named desktop.
- Let the helper own desktop-local observation and action execution. The main process should stay on the normal desktop and communicate over IPC.
- Use `CreateDesktopW`, `OpenInputDesktop`, `SwitchDesktop`, `GetLastInputInfo`, and desktop-name inspection as the core User32 primitives.

**If intervention detection and handoff are enabled:**

- Add a small cross-platform `InterventionMonitor` abstraction instead of embedding ad hoc checks inside each backend.
- On macOS, use `CGEventSourceSecondsSinceLastEventType` for idle-time detection. Keep `CGEventTapCreate` as an optional advanced mode only, because Apple explicitly requires user approval for monitoring keyboard events across apps.
- On Windows, use `GetLastInputInfo` for session-local user input timing and compare the input desktop from `OpenInputDesktop` with the worker desktop to detect when the user has taken focus elsewhere or when the agent needs a visible handoff.
- The handoff itself should be orchestrator-level: pause run, flush trace, stop background wrapper or worker, then reconstruct the existing foreground `LocalDesktopBackend` path rather than mutating the active backend in place.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `pyobjc-core==12.1` | Python `>=3.10`; project Python `3.11-3.12` | Current PyPI release is 12.1 (2025-11-14). |
| `pyobjc-framework-Quartz==12.1` | Python `>=3.10`; macOS `10.15+` wheels | Current PyPI release is 12.1 (2025-11-14). |
| `pyobjc-framework-ApplicationServices==12.1` | Python `>=3.10`; macOS `10.15+` wheels | Needed for Accessibility/HIServices bindings such as `AXIsProcessTrustedWithOptions`. |
| `pywin32==311` | Python `3.8-3.14`; Windows | Current PyPI release is 311 (2025-07-14). |
| Existing desktop extra | Existing `LocalDesktopBackend` | No dependency changes required for Linux/Xvfb. The only mandatory code change is monitor-selection support for macOS virtual displays. |

## Sources

- Local code inspection: `opengui/backends/virtual_display.py`, `opengui/backends/background.py`, `opengui/backends/desktop.py`, `opengui/cli.py`, `nanobot/agent/tools/gui.py`, `nanobot/config/schema.py` - integration seams and current abstraction constraints. Confidence: HIGH.
- PyPI: `pyobjc-core 12.1` - current version and Python compatibility. https://pypi.org/project/pyobjc-core/ Confidence: HIGH.
- PyPI: `pyobjc-framework-Quartz 12.1` - current Quartz wrapper version and packaging. https://pypi.org/project/pyobjc-framework-Quartz/ Confidence: HIGH.
- PyPI: `pyobjc-framework-ApplicationServices 12.1` - current ApplicationServices wrapper version. https://pypi.org/project/pyobjc-framework-ApplicationServices/ Confidence: HIGH.
- PyObjC docs: `objc.lookUpClass` and ApplicationServices API notes. https://pyobjc.readthedocs.io/en/latest/api/module-objc.html and https://pyobjc.readthedocs.io/en/latest/apinotes/ApplicationServices.html Confidence: HIGH.
- Local macOS 15.5 SDK headers: `AXUIElement.h`, `CGEventSource.h`, `CGWindow.h` - public availability of trust, idle-time, and screen-capture permission APIs. Confidence: HIGH.
- Chromium source: reverse-engineered `CGVirtualDisplay*` interfaces and creation flow. https://chromium.googlesource.com/chromium/src/+/cca923fbde2d338f3730885e0dbe734eee8465a2/ui/display/mac/test/virtual_display_mac_util.mm Confidence: MEDIUM.
- Microsoft Learn: `CreateDesktopW`, `SetThreadDesktop`, `Thread Connection to a Desktop`, `STARTUPINFOW`, `OpenInputDesktop`, `SwitchDesktop`, `GetLastInputInfo`, `KEYBDINPUT`. Confidence: HIGH.
- Apple WWDC 2019 "Advances in macOS Security" - global keyboard monitoring via `CGEventTapCreate` requires user approval. https://developer.apple.com/la/videos/play/wwdc2019/701/ Confidence: HIGH.

---
*Stack research for: macOS/Windows background execution additions*
*Researched: 2026-03-20*
