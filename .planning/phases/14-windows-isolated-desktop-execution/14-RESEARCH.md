# Phase 14: Windows Isolated Desktop Execution - Research

**Researched:** 2026-03-20
**Domain:** Windows alternate-desktop automation inside the interactive user session, with explicit support gating and leak-safe cleanup
**Confidence:** MEDIUM

<user_constraints>
## User Constraints

No `14-CONTEXT.md` exists for this phase. This research therefore treats the following as authoritative constraints:
- `.planning/ROADMAP.md` Phase 14 goal and success criteria
- `.planning/REQUIREMENTS.md` requirements `WIN-01`, `WIN-02`, and `WIN-03`
- `.planning/STATE.md` and `.planning/PROJECT.md` decisions already locked by Phases 9-13
- project-level research already captured in `.planning/research/SUMMARY.md`, `.planning/research/STACK.md`, and `.planning/research/PITFALLS.md`

### Locked Decisions Inherited From Prior Phases
- Keep the shared `opengui/backends/background_runtime.py` probe/result/resolution contract introduced in Phase 12; Phase 14 extends it rather than bypassing it.
- Keep CLI and nanobot on the same capability vocabulary and resolved-mode logging contract.
- Do not silently downgrade from requested background isolation; unsupported Windows paths must warn or block explicitly.
- Keep Linux and macOS behavior unchanged.
- Treat Windows isolated execution as an alternate desktop inside the interactive user session, not as Session 0 or service UI automation.

### Claude's Discretion
- Exact module names for the Windows isolated backend and worker process.
- Exact Windows reason-code taxonomy, as long as it stays stable and user-facing remediation remains actionable.
- Whether the Windows implementation is one backend module or a small backend + helper module split, provided the main process does not rely on late `SetThreadDesktop()` switching.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| WIN-01 | User can run desktop automation on Windows inside an alternate isolated desktop within the interactive user session | Add a Windows-specific worker-backed backend that creates a named desktop with `CreateDesktopW`, launches the worker with `STARTUPINFO.lpDesktop`, and keeps capture/input inside that worker instead of reusing the main process desktop stack |
| WIN-02 | User receives a clear warning or block when the Windows launch context or target app class cannot support isolated desktop execution | Extend the shared runtime probe with Windows launch-context checks (`ProcessIdToSessionId`, `WTSGetActiveConsoleSessionId`, `OpenInputDesktop`, window-station checks) and add a post-launch support gate for app surfaces that fail capture/input readiness |
| WIN-03 | Windows isolated-desktop resources are cleaned up on success, failure, and cancellation without leaving orphaned desktops or leaked handles | Centralize ownership of the desktop handle, worker process/thread handles, IPC channel, and launched-app process handles in one backend object with idempotent `shutdown()` and strict close order |
</phase_requirements>

## Summary

Phase 14 should not copy the Linux/macOS `VirtualDisplayManager` pattern onto Windows. The current `BackgroundDesktopBackend` works when isolation can be expressed as process-global display routing (`DISPLAY` on Linux, target-monitor metadata on macOS). Windows alternate desktops are different: Microsoft documents `SetThreadDesktop()` as thread-scoped and fragile once the calling thread owns windows or hooks, and child processes must be created onto the target desktop through `STARTUPINFO.lpDesktop`. That makes a worker-backed Windows backend the correct planning target.

The recommended implementation is: keep Phase 12's probe and mode-resolution contract, add Windows-specific host preflight in `background_runtime.py`, then introduce a `WindowsIsolatedDesktopBackend` that owns desktop creation, worker launch, IPC, post-launch app support checks, and cleanup. CLI and nanobot should continue to ask the shared runtime what isolated backend to use, but for Windows they should build a direct backend adapter instead of a `BackgroundDesktopBackend` + manager pair.

The biggest planning risk is pretending Windows offers universal hidden-desktop parity. The Win32 APIs are stable, but Microsoft explicitly documents session boundaries, desktop-handle rules, and `SendInput` UIPI limits. Capture is also not universal: `PrintWindow` is synchronous and depends on the target app rendering its own image, while `BitBlt` has device/DC limits. Phase 14 should therefore ship with a narrow support envelope for launched classic desktop apps, explicit unsupported-path messaging, and aggressive cleanup guarantees.

**Primary recommendation:** Keep the shared runtime contract, but implement Windows as a worker-backed `DeviceBackend` that launches onto a named desktop with `lpDesktop`, probes interactive-session support before startup, and owns all desktop/process handle cleanup in one place.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`ctypes`, `ctypes.wintypes`, `asyncio`, `json`, `pathlib`, `subprocess`/process handles) | Project target `>=3.11` | Raw Win32 bindings, worker lifecycle, IPC framing, cleanup | The Win32 APIs needed here are stable and low-level; `ctypes` keeps signatures explicit and easy to patch in tests |
| `pywin32` | `311` | Reduce boilerplate around process creation, handles, wait/termination helpers on Windows | Current PyPI latest verified on 2026-03-20; pragmatic helper layer around Win32 process APIs without hiding the desktop semantics |
| Existing desktop stack (`mss`, `Pillow`, `pyautogui`, `pyperclip`) | Existing project versions from `pyproject.toml` | Reuse only where still valid | Keep these for foreground desktop mode and any worker-local reuse, but do not treat them as sufficient for main-process hidden-desktop automation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.x | Unit and integration coverage for probe, worker lifecycle, and cleanup | Default test framework already in use |
| `pytest-asyncio` | 1.3.x | Async tests for cancellation, shutdown, and CLI/nanobot flows | Required for the background-run lifecycle tests |
| `unittest.mock.AsyncMock` | stdlib | Mock worker boundaries and Win32 calls without a real Windows host in CI | Keep the validation slice fast and deterministic |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Worker-backed Windows backend | Reuse `BackgroundDesktopBackend` + `VirtualDisplayManager` | Simpler on paper, but wrong abstraction because the main process would still capture/input against the wrong desktop |
| `CreateDesktopW` + `STARTUPINFO.lpDesktop` child launch | Late `SetThreadDesktop()` in the main process | Microsoft documents that `SetThreadDesktop()` fails once the thread has windows or hooks, which is a bad fit for a long-lived agent process |
| Narrow support envelope for launched desktop apps | Promise universal hidden-desktop support for all Windows apps | Misleading; capture and input behavior varies by app class, integrity level, and rendering path |

**Installation:**
```bash
uv pip install -e ".[desktop,dev]"
uv pip install "pywin32==311; sys_platform == 'win32'"
```

**Version verification:**
- `pywin32==311` verified on PyPI on 2026-03-20; release date `2025-07-14`: https://pypi.org/project/pywin32/
- Existing desktop/test dependency ranges verified from `pyproject.toml`.

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
├── backends/
│   ├── background_runtime.py          # extend Windows host probe + remediation
│   ├── windows_isolated_desktop.py    # new: worker-backed DeviceBackend for Windows
│   ├── windows_worker.py              # new: child process entry point bound to lpDesktop
│   ├── background.py                  # likely unchanged for Windows; remains Linux/macOS wrapper
│   └── desktop.py                     # foreground backend remains shared, but not the hidden-desktop owner
opengui/
├── cli.py                             # build isolated backend from runtime backend_name
nanobot/
└── agent/tools/gui.py                 # same shared contract, Windows backend dispatch
tests/
├── test_opengui_p14_windows_desktop.py
├── test_opengui_p12_runtime_contracts.py
├── test_opengui_p5_cli.py
└── test_opengui_p11_integration.py
```

### Pattern 1: Keep the Shared Runtime Contract, Add Windows Host Preflight
**What:** Extend `probe_isolated_background_support()` with Windows launch-context checks, but keep the probe narrow: host capability before automation starts.
**When to use:** Every `--background` or nanobot background request on Windows.
**Concrete recommendation:**
- Return `backend_name="windows_isolated_desktop"` when the host is eligible.
- Add Windows reason codes such as:
  - `windows_alternate_desktop_available`
  - `windows_not_interactive_session`
  - `windows_input_desktop_unavailable`
  - `windows_window_station_unavailable`
  - `windows_dependencies_missing`
- Preflight should check:
  - current process session ID via `ProcessIdToSessionId`
  - active console session via `WTSGetActiveConsoleSessionId`
  - access to the current input desktop via `OpenInputDesktop`
  - current window-station/desktop metadata via `GetUserObjectInformation(..., UOI_NAME/UOI_IO)` when needed

**Why:** Phase 12 deliberately separated host capability from policy. Windows app-class support belongs later, after launch, but launch-context eligibility must still be known before the run starts.

### Pattern 2: Use a Worker Process Created on the Named Desktop
**What:** Build a Windows-only backend that creates a named desktop, launches a helper process onto that desktop, and sends it `observe` / `execute` / `shutdown` commands over IPC.
**When to use:** Every isolated Windows run that resolves to `mode="isolated"`.
**Concrete recommendation:**
- Parent backend creates the desktop with `CreateDesktopW`.
- Parent launches the worker with `STARTUPINFO.lpDesktop = "WinSta0\\OpenGUI-<run-id>"`.
- Worker opens/owns its desktop-local capture/input path before importing GUI-heavy modules.
- Parent never calls `SetThreadDesktop()` on the long-lived main event-loop thread.

**Why:** Microsoft documents that thread-to-desktop assignment is fragile once windows/hooks exist, while `lpDesktop` is the documented creation-time routing mechanism for child processes.

### Pattern 3: Do Not Force Windows Through `VirtualDisplayManager`
**What:** Treat Windows isolated execution as a separate backend path, not as another `DisplayInfo` producer.
**When to use:** During planning and module design.
**Concrete recommendation:**
- Leave `BackgroundDesktopBackend` as the Linux/macOS wrapper.
- Factor CLI/nanobot from `_build_isolated_display_manager(...)` toward `_build_isolated_backend(...)` or equivalent.
- For Linux/macOS, keep returning wrapped backends.
- For Windows, return a direct `WindowsIsolatedDesktopBackend` instance.

**Why:** The current display abstraction is about selecting a surface inside the same process. Windows hidden desktops are a different execution context, so pushing them through `DisplayInfo` would make the API look unified while still targeting the wrong desktop.

### Pattern 4: Support Only Launched, Verifiable App Surfaces
**What:** Decide app support by what the worker can actually launch, enumerate, capture, and inject into, not by a broad marketing promise.
**When to use:** Immediately after worker launch and target-app startup.
**Concrete recommendation:**
- **Supported baseline (HIGH confidence):**
  - classic Win32 desktop apps
  - launched by the worker onto the named desktop
  - same integrity level as the worker
  - top-level HWND discoverable on the target desktop
  - capture probe succeeds and is non-blank
- **Warn/block baseline (MEDIUM confidence; part inference from official capture/input limits):**
  - service / Session 0 / disconnected launches
  - already-running apps on a different desktop
  - elevated targets when the worker is not equally elevated (`SendInput` is subject to UIPI)
  - app surfaces where `PrintWindow`/`BitBlt` returns blank, stale, or unsupported results
  - packaged/UWP or compositor-heavy surfaces that fail the runtime capture probe

**Why:** Microsoft documents the session/input/integrity constraints directly, and the capture APIs themselves are explicitly conditional. Phase 14 should convert those into deterministic warnings and blocks.

### Pattern 5: Cleanup Order Must Be Strict and Idempotent
**What:** One owner object must release resources in the same order on success, failure, and cancellation.
**When to use:** Every isolated Windows run, especially around exceptions and cancelled tasks.
**Concrete recommendation:**
1. Stop accepting new commands.
2. Ask the worker to shut down gracefully.
3. Wait with a short timeout; terminate/kill the worker if it does not exit.
4. Close worker process/thread handles and IPC handles.
5. Close any auxiliary desktop handles opened for probing.
6. Call `CloseDesktop` on the created desktop handle.
7. Emit final lifecycle metadata to logs/trace.

**Why:** `CreateDesktopW` allocates limited desktop heap, and Windows requires handles to be closed explicitly. The worker must be gone before the desktop is torn down, or leaks and inconsistent close failures become likely.

### Anti-Patterns to Avoid
- **Windows via `BackgroundDesktopBackend`:** Wrong abstraction for hidden desktops.
- **Late `SetThreadDesktop()` on the main process:** Documented failure mode once windows/hooks exist.
- **Inheritable desktop handles by accident:** Thread-connection docs warn that inheriting multiple desktop handles makes desktop selection undefined.
- **Assuming `PrintWindow` is a universal screenshot API:** It is synchronous and depends on the app rendering into the provided DC.
- **Silent fallback after app-support failure:** Violates the phase requirement; the user must see a clear warning or block.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Host-session detection | Heuristics based on env vars or `sys.platform` alone | `ProcessIdToSessionId`, `WTSGetActiveConsoleSessionId`, `OpenInputDesktop`, `GetUserObjectInformation` | The Win32 APIs expose the real launch context and input-desktop state |
| Windows hidden-desktop routing | Main-process global state hacks | Creation-time worker launch with `STARTUPINFO.lpDesktop` | Matches the documented desktop-assignment rules |
| Screenshot capture | `pyautogui.screenshot()` or main-process `mss` against the normal desktop | Worker-local Win32 capture abstraction around desktop DC / `BitBlt` plus `PrintWindow` fallback or verification | The main process is on the wrong desktop; capture must happen inside the worker context |
| Cleanup | Scattered `try/except` closes across CLI, worker, and backend | One backend-owned shutdown path with a strict close order | `WIN-03` depends on centralized ownership |
| App support policy | Hardcoded “Windows supports everything” messaging | Post-launch readiness probe + stable reason codes | Hidden-desktop compatibility is surface-dependent |

**Key insight:** The dangerous custom work is not “calling Win32.” The dangerous custom work is trying to fake Windows into the existing virtual-display shape instead of acknowledging that it needs its own backend and lifecycle owner.

## Common Pitfalls

### Pitfall 1: Using `SetThreadDesktop()` After the Main Process Is Already Warm
**What goes wrong:** Desktop switching works in toy tests, then fails once the process has windows, hooks, or imported GUI tooling.
**Why it happens:** Microsoft documents that `SetThreadDesktop()` fails if the calling thread already has windows or hooks.
**How to avoid:** Use a fresh worker process launched onto the target desktop; do not repurpose the main event-loop thread.
**Warning signs:** Failures appear only after imports or after the first screenshot/input call.

### Pitfall 2: Treating Session 0 or Disconnected Sessions as Interactive
**What goes wrong:** The process starts, but no useful UI interaction is possible.
**Why it happens:** Windows services run in Session 0, and `OpenInputDesktop()` behaves differently in disconnected sessions.
**How to avoid:** Preflight the session/window-station state and block or warn before agent startup.
**Warning signs:** The worker is running, but there is no usable input desktop or the session is not the interactive one.

### Pitfall 3: Letting Child Processes Inherit Desktop Handles Accidentally
**What goes wrong:** Child desktop attachment becomes nondeterministic, and cleanup gets harder.
**Why it happens:** Microsoft documents that inherited desktop handles affect which desktop a process connects to, and multiple inherited desktop handles make the result undefined.
**How to avoid:** Prefer `lpDesktop` naming over inheriting the parent handle; keep the created desktop handle non-inheritable unless there is a specific reason not to.
**Warning signs:** Some launches connect to the right desktop and others do not, with no code-path difference.

### Pitfall 4: Assuming Capture APIs Mean “Any App Will Render”
**What goes wrong:** Screenshots are blank, stale, or missing key UI even though the window exists.
**Why it happens:** `PrintWindow` asks the target app to render itself; `BitBlt` has DC/device capability limits.
**How to avoid:** Build an explicit capture readiness probe and convert failure into a support warning/block instead of continuing blindly.
**Warning signs:** The backend finds the window handle but observation images are empty or never change.

### Pitfall 5: Ignoring UIPI and Keyboard-State Rules During Input Injection
**What goes wrong:** Clicks/keys silently fail, or modifiers remain “stuck” after a cancellation.
**Why it happens:** Microsoft documents that `SendInput` is subject to UIPI and does not reset the current keyboard state.
**How to avoid:** Keep Windows input in one worker, reject unsupported elevated targets, and include key/button release in shutdown.
**Warning signs:** Input failures correlate with elevated apps or only happen after cancelled drags/hotkeys.

### Pitfall 6: Closing the Desktop Before the Worker Is Gone
**What goes wrong:** Orphaned resources or intermittent close failures accumulate across runs.
**Why it happens:** The desktop still has active threads/processes attached when teardown starts.
**How to avoid:** Worker exit first, handles next, desktop last. Make `shutdown()` idempotent and always run it under `finally`.
**Warning signs:** First run works, later runs fail until reboot or logoff.

## Code Examples

Verified patterns from official sources:

### Example 1: Creation-Time Desktop Assignment
```python
# Source: Microsoft Learn CreateDesktopW + STARTUPINFOW + Thread Connection to a Desktop
desktop_name = f"OpenGUI-{run_id}"
desktop = CreateDesktopW(desktop_name, None, None, 0, DESKTOP_ACCESS_MASK, None)

startup = STARTUPINFOW()
startup.cb = ctypes.sizeof(STARTUPINFOW)
startup.lpDesktop = f"WinSta0\\{desktop_name}"

process_info = create_worker_process(
    python_exe=python_exe,
    module="opengui.backends.windows_worker",
    startupinfo=startup,
)
```

### Example 2: Narrow Host Probe Before Startup
```python
# Source: Microsoft Learn ProcessIdToSessionId + WTSGetActiveConsoleSessionId + OpenInputDesktop
probe = probe_isolated_background_support(sys_platform="win32")
decision = resolve_run_mode(
    probe,
    require_isolation=require_isolation,
    require_acknowledgement_for_fallback=is_nanobot,
)
log_mode_resolution(logger, decision, owner="cli", task=task)
```

### Example 3: Idempotent Cleanup Order
```python
# Source: Microsoft Learn CreateDesktopW/OpenInputDesktop/CloseDesktop lifecycle requirements
try:
    await backend.preflight()
    return await backend.run_task(task)
finally:
    await backend.request_worker_shutdown()
    await backend.wait_or_terminate_worker(timeout=2.0)
    backend.close_ipc_handles()
    backend.close_process_handles()
    backend.close_probe_desktop_handles()
    backend.close_created_desktop()
```

## Open Questions

1. **Primary capture path: desktop `BitBlt` or per-window `PrintWindow`?**
   - What we know: Microsoft documents real limits for both. `PrintWindow` is app-rendered and blocking; `BitBlt` is DC/device-dependent.
   - What's unclear: which path is more reliable on the target app set for this project.
   - Recommendation: Plan a Wave 1 capture abstraction with a real-host spike. Start with desktop-DC capture in the worker, but keep per-window fallback/verification available.

2. **Should Phase 14 support attaching to already-running Windows apps?**
   - What we know: the clean documented path is launching a process onto the named desktop at creation time with `lpDesktop`.
   - What's unclear: how much value there is in trying to claim attachment support for pre-existing windows.
   - Recommendation: Keep v1.2 narrow. Support only apps launched by the worker onto the isolated desktop. Treat “attach to an existing app” as out of scope unless a later milestone demands it.

3. **Should RDP sessions count as supported interactive contexts in v1.2?**
   - What we know: the session APIs distinguish current process session, active console session, and remote-session metadata, but the product requirement only says “interactive session.”
   - What's unclear: whether the milestone should promise parity across console and RDP.
   - Recommendation: Treat same-user console launches as the supported baseline. Mark RDP as manual-smoke / lower-confidence until verified on a real host.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio 1.3.x |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `uv run pytest tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p12_runtime_contracts.py -q` |
| Full suite command | `uv run pytest tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WIN-01 | Windows probe reports `supported=True` with `backend_name="windows_isolated_desktop"` when session/input-desktop checks pass | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_probe_reports_windows_alternate_desktop_available -q` | ❌ Wave 0 |
| WIN-01 | Windows isolated backend creates a named desktop, launches the worker with `lpDesktop`, and exposes a backend-local observe/execute contract | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_windows_isolated_backend_launches_worker_on_named_desktop -q` | ❌ Wave 0 |
| WIN-02 | Non-interactive launch contexts resolve to fallback/blocked before agent startup | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_probe_blocks_noninteractive_windows_session -q` | ❌ Wave 0 |
| WIN-02 | Unsupported app surfaces return a stable warning/block reason instead of continuing blindly | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_windows_backend_rejects_unsupported_app_surface -q` | ❌ Wave 0 |
| WIN-03 | Success path closes worker/process/desktop resources in the correct order | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_windows_backend_closes_resources_on_success -q` | ❌ Wave 0 |
| WIN-03 | Failure during preflight still closes created desktop/process handles | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_windows_backend_closes_resources_on_preflight_failure -q` | ❌ Wave 0 |
| WIN-03 | Cancellation triggers the same cleanup path without leaking handles | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_windows_backend_closes_resources_on_cancellation -q` | ❌ Wave 0 |
| WIN-01, WIN-02 | CLI chooses the Windows isolated backend from the shared runtime probe and logs the resolved mode before agent start | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_uses_windows_isolated_backend_for_win32_mode -q` | ❌ Wave 0 |
| WIN-01, WIN-02 | Nanobot chooses the same Windows isolated backend and preserves fallback/block messaging semantics | integration | `uv run pytest tests/test_opengui_p11_integration.py::test_gui_tool_uses_windows_isolated_backend_for_win32_mode -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p12_runtime_contracts.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p14_windows_desktop.py` — Windows probe, worker launch, app-support gate, cleanup ordering
- [ ] `tests/test_opengui_p12_runtime_contracts.py` additions — Windows reason-code and backend-name coverage
- [ ] `tests/test_opengui_p5_cli.py` additions — CLI Windows backend dispatch and remediation ordering
- [ ] `tests/test_opengui_p11_integration.py` additions — nanobot Windows backend dispatch and remediation ordering

### Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real Windows host can create a named desktop, launch a classic Win32 app there, and observe/act without taking over the user’s current desktop | WIN-01 | Hidden-desktop behavior cannot be honestly proven in generic CI | Use a real Windows 10/11 interactive session, launch Notepad or another simple Win32 app, and verify the run resolves to `isolated` and tears down cleanly |
| Unsupported contexts block or warn before automation starts | WIN-02 | Session 0 / disconnected / unsupported-surface conditions are host-dependent | Test at least one unsupported context or mocked equivalent on a real Windows host and confirm the logged reason code matches the preflight outcome |
| Cancelled and failed runs do not leave orphaned desktops or leaked handles | WIN-03 | Desktop-handle leaks show up only on repeated real-host runs | Run repeated start/cancel loops on Windows and verify later runs still create and close desktops successfully |

## Sources

### Primary (HIGH confidence)
- Microsoft Learn: `CreateDesktopW` — desktop creation, required access rights, `CloseDesktop`, desktop heap limit: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createdesktopw
- Microsoft Learn: `Thread Connection to a Desktop` — desktop assignment rules and inherited-handle warning: https://learn.microsoft.com/en-us/windows/win32/winstation/thread-connection-to-a-desktop
- Microsoft Learn: `SetThreadDesktop` — thread-scoped restriction and failure when windows/hooks already exist: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddesktop
- Microsoft Learn: `STARTUPINFOW` — `lpDesktop` creation-time desktop selection: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-startupinfow
- Microsoft Learn: `Interactive Services` — Session 0 limitation: https://learn.microsoft.com/en-us/windows/win32/services/interactive-services
- Microsoft Learn: `OpenInputDesktop` — current input desktop semantics and disconnected-session note: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-openinputdesktop
- Microsoft Learn: `SwitchDesktop` — same-session/invisible-window-station constraints: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-switchdesktop
- Microsoft Learn: `GetLastInputInfo` — session-specific idle/input signal and non-monotonic tick note: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo
- Microsoft Learn: `SendInput` — UIPI limit and keyboard-state caveat: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
- Microsoft Learn: `PrintWindow` — app-rendered capture and synchronous behavior: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow
- Microsoft Learn: `BitBlt` — device/DC capability limits: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-bitblt
- Microsoft Learn: `ProcessIdToSessionId` and `WTSGetActiveConsoleSessionId` — session detection: https://learn.microsoft.com/nb-no/windows/win32/api/processthreadsapi/nf-processthreadsapi-processidtosessionid and https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-wtsgetactiveconsolesessionid
- Microsoft Learn: `GetUserObjectInformation` — desktop/window-station name and input flags: https://learn.microsoft.com/tr-tr/windows/win32/api/winuser/nf-winuser-getuserobjectinformationw

### Secondary (MEDIUM confidence)
- `.planning/research/STACK.md` — prior Windows background-execution recommendations and dependency posture
- `.planning/research/PITFALLS.md` — prior Windows hidden-desktop failure modes and mitigation themes
- Existing code seams in `opengui/backends/background_runtime.py`, `opengui/backends/background.py`, `opengui/cli.py`, and `nanobot/agent/tools/gui.py`

### Tertiary (LOW confidence)
- App-class support boundaries beyond the documented Win32/session/UIPI/capture limits are partly inference. Packaged/UWP/Electron/DirectX-heavy surfaces should be treated as “runtime capability check required,” not as a permanently closed set, until real-host smoke data exists.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - The Win32 APIs are stable, but the exact amount of `pywin32` vs raw `ctypes` usage is still an implementation choice.
- Architecture: HIGH - The existing repo seams and Microsoft docs strongly support a worker-backed backend instead of a `VirtualDisplayManager` extension.
- Pitfalls: HIGH - Session 0, `SetThreadDesktop`, `CloseDesktop`, `SendInput`, and capture limits are explicitly documented.

**Research date:** 2026-03-20  
**Valid until:** 2026-04-19
