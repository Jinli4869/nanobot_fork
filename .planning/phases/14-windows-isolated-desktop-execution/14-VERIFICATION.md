---
phase: 14-windows-isolated-desktop-execution
verified: 2026-03-20T18:32:39Z
status: human_needed
score: 4/4 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 1/4
  gaps_closed:
    - "Supported Windows runs launch automation inside an isolated desktop/session target."
    - "Unsupported launch contexts or incompatible app classes are blocked or warned explicitly."
    - "Cleanup closes isolated-desktop resources on success, failure, and cancellation."
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Real Windows alternate-desktop execution against a classic Win32 app"
    expected: "The worker launches on WinSta0\\{desktop_name}, automation runs on the alternate desktop, and the user foreground desktop does not switch."
    why_human: "Real alternate-desktop rendering and input behavior depends on a live interactive Windows session and actual GUI surfaces; this verifier only checked code paths and tests."
  - test: "Unsupported context and app-class smoke run on a Windows host"
    expected: "Session 0 or service contexts block with windows_non_interactive_session, and UWP/DirectX/GPU-heavy targets warn or block before the first agent step."
    why_human: "Launch-context and app-surface behavior cannot be validated honestly from a non-Windows verifier host."
  - test: "Cleanup leak check on success, startup failure, and cancellation"
    expected: "Logs include cleanup_reason=normal/startup_failed/cancelled and no stale OpenGUI desktops or child processes remain."
    why_human: "Desktop-handle leaks and orphaned process cleanup require end-to-end inspection on a real Windows session."
---

# Phase 14: Windows Isolated Desktop Execution Verification Report

**Phase Goal:** Windows background runs use an alternate isolated desktop inside the interactive session, advertise when the launch context or app class is unsupported, and always clean up desktop resources safely.
**Verified:** 2026-03-20T18:32:39Z
**Status:** human_needed
**Re-verification:** Yes - after gap closure

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Supported Windows runs launch automation inside an isolated desktop/session target. | ✓ VERIFIED | `Win32DesktopManager.start()` now creates a real desktop handle via `_win32_create_desktop()` and `stop()` closes it via `_win32_close_desktop()` in `opengui/backends/displays/win32desktop.py:97` and `opengui/backends/displays/win32desktop.py:117`. `launch_windows_worker()` sets `STARTUPINFO.lpDesktop` in `opengui/backends/windows_worker.py:62`, and the worker services `observe` / `execute` / `list_apps` / `shutdown` in `opengui/backends/windows_worker.py:88` through `opengui/backends/windows_worker.py:126`. `WindowsIsolatedBackend` routes `observe()`, `execute()`, and `list_apps()` through worker RPC instead of the parent backend in `opengui/backends/windows_isolated.py:108`, `opengui/backends/windows_isolated.py:129`, and `opengui/backends/windows_isolated.py:146`. Regression coverage exists in `tests/test_opengui_p14_windows_desktop.py:148`, `tests/test_opengui_p14_windows_desktop.py:192`, `tests/test_opengui_p14_windows_desktop.py:305`, and the full slice passed: `50 passed in 4.16s`. |
| 2 | Unsupported launch contexts or incompatible app classes are blocked or warned explicitly. | ✓ VERIFIED | `probe_windows_isolated_desktop_support()` rejects unsupported app classes and non-interactive/input-desktop/create-desktop failures in `opengui/backends/displays/win32desktop.py:33` through `opengui/backends/displays/win32desktop.py:66` and `opengui/backends/displays/win32desktop.py:135` through `opengui/backends/displays/win32desktop.py:206`. CLI forwarding is wired through `--target-app-class`, `resolve_target_app_class()`, and `probe_isolated_background_support(..., target_app_class=...)` in `opengui/cli.py:225`, `opengui/cli.py:280`, and `opengui/cli.py:458`. Nanobot exposes the same signal in `nanobot/agent/tools/gui.py:91`, forwards it in `nanobot/agent/tools/gui.py:132` through `nanobot/agent/tools/gui.py:140`, and defaults omitted Windows background-local runs to `classic-win32` in `nanobot/agent/tools/gui.py:326` through `nanobot/agent/tools/gui.py:339`. Host-entry regressions exist in `tests/test_opengui_p5_cli.py:1196`, `tests/test_opengui_p5_cli.py:1261`, `tests/test_opengui_p11_integration.py:471`, and `tests/test_opengui_p11_integration.py:533`. |
| 3 | Cleanup closes isolated-desktop resources on success, failure, and cancellation. | ✓ VERIFIED | `WindowsIsolatedBackend.shutdown()` now sends worker `shutdown`, waits/stops the worker, closes pipes, unlinks the control path, then stops the desktop manager and releases the runtime lease in `opengui/backends/windows_isolated.py:154` through `opengui/backends/windows_isolated.py:225` and `opengui/backends/windows_isolated.py:242` through `opengui/backends/windows_isolated.py:343`. `Win32DesktopManager.stop()` owns real-handle teardown in `opengui/backends/displays/win32desktop.py:110` through `opengui/backends/displays/win32desktop.py:123`. Cleanup ordering is covered in `tests/test_opengui_p14_windows_desktop.py:398` and nanobot failure propagation is covered in `tests/test_opengui_p11_integration.py:564`. |
| 4 | Background-run traces expose enough metadata to diagnose target-surface ownership issues. | ✓ VERIFIED | Ready, worker-launch, and cleanup logs include `backend_name`, `display_id`, `desktop_name`, `lpDesktop`, and `cleanup_reason` in `opengui/backends/windows_isolated.py:80` through `opengui/backends/windows_isolated.py:87`, `opengui/backends/windows_isolated.py:205` through `opengui/backends/windows_isolated.py:213`, and `opengui/backends/windows_isolated.py:163` through `opengui/backends/windows_isolated.py:177`. Host-facing assertions exist in `tests/test_opengui_p5_cli.py:1366` and `tests/test_opengui_p11_integration.py:564`. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `opengui/backends/displays/win32desktop.py` | Real Win32 desktop lifecycle manager and support probe | ✓ VERIFIED | Owns Win32 wrappers, session/input/create-desktop checks, stable desktop naming, and real handle teardown. |
| `opengui/backends/windows_worker.py` | Worker process bound to `lpDesktop` with live command loop | ✓ VERIFIED | Launches with `lpDesktop`, keeps stdio pipes open, and services `observe`, `execute`, `list_apps`, and `shutdown`. |
| `opengui/backends/windows_isolated.py` | Windows isolated execution seam routing desktop IO through worker RPC | ✓ VERIFIED | Preflight owns lease plus desktop start, IO stays off the parent backend, and shutdown is worker-first then desktop-stop. |
| `opengui/backends/background_runtime.py` | Shared Windows reason-code/remediation vocabulary and backend dispatch | ✓ VERIFIED | Windows probe branch, reason codes, and remediation strings are present and host-facing. |
| `opengui/cli.py` | CLI app-class propagation into the shared Windows probe | ✓ VERIFIED | Adds `--target-app-class`, Windows-only defaulting, and probe forwarding before mode resolution. |
| `nanobot/agent/tools/gui.py` | Nanobot app-class propagation and pre-agent unsupported-path handling | ✓ VERIFIED | Schema, forwarding, defaulting, and JSON failure semantics are wired. |
| `tests/test_opengui_p14_windows_desktop.py` | Phase 14 code-level regression coverage for handle ownership, worker RPC, routing, and cleanup | ✓ VERIFIED | The key gap-closing tests exist and passed in the 50-test phase slice. |
| `.planning/phases/14-windows-isolated-desktop-execution/14-MANUAL-SMOKE.md` | Windows host smoke checklist for the behaviors automation cannot prove honestly | ✓ VERIFIED | The checklist covers supported Win32 apps, blocked contexts, unsupported app classes, and cleanup paths. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `background_runtime._probe_windows_isolated_support` | `win32desktop.probe_windows_isolated_desktop_support` | Shared Windows capability probe | ✓ WIRED | `opengui/backends/background_runtime.py:247` through `opengui/backends/background_runtime.py:262` imports and forwards `target_app_class` into the Win32 probe. |
| `Win32DesktopManager.desktop_name` | `windows_worker.launch_windows_worker` | `STARTUPINFO.lpDesktop` at child-process creation | ✓ WIRED | `opengui/backends/windows_isolated.py:192` through `opengui/backends/windows_isolated.py:197` forwards `desktop_name`; `opengui/backends/windows_worker.py:62` binds `WinSta0\\{desktop_name}`. |
| `WindowsIsolatedBackend.observe/execute/list_apps` | `windows_worker` command loop | JSON-line worker RPC via `_send_worker_command()` | ✓ WIRED | `opengui/backends/windows_isolated.py:108`, `opengui/backends/windows_isolated.py:129`, and `opengui/backends/windows_isolated.py:146` send commands consumed by `opengui/backends/windows_worker.py:110` through `opengui/backends/windows_worker.py:126`. |
| `WindowsIsolatedBackend.shutdown` | `Win32DesktopManager.stop` | Worker-first cleanup ordering | ✓ WIRED | `opengui/backends/windows_isolated.py:219` sends worker shutdown before `opengui/backends/windows_isolated.py:244` stops the desktop manager. |
| `cli.run_cli` | `probe_isolated_background_support` | CLI forwards Windows `target_app_class` into shared probe | ✓ WIRED | `opengui/cli.py:458` through `opengui/cli.py:462` forwards the resolved value. |
| `GuiSubagentTool.execute` | `probe_isolated_background_support` | Nanobot forwards Windows `target_app_class` into shared probe | ✓ WIRED | `nanobot/agent/tools/gui.py:132` through `nanobot/agent/tools/gui.py:140` forwards the resolved value. |
| `14-MANUAL-SMOKE.md` | `windows_isolated.shutdown` | Cleanup-path checklist mirrors runtime tokens | ✓ WIRED | The smoke checklist explicitly requires `cleanup_reason=normal`, `startup_failed`, and `cancelled`, matching the backend log contract. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `WIN-01` | `14-01`, `14-02`, `14-03`, `14-04`, `14-05`, `14-06` | User can run desktop automation on Windows inside an alternate isolated desktop within the interactive user session | ? NEEDS HUMAN | The real desktop-handle path, worker launch, and worker-routed IO are implemented and covered by tests, but actual alternate-desktop rendering/input behavior still requires a live Windows smoke run. |
| `WIN-02` | `14-01`, `14-03`, `14-04`, `14-06` | User receives a clear warning or block when the Windows launch context or target app class cannot support isolated desktop execution | ✓ SATISFIED | Probe reason codes and remediation strings are wired end to end, and CLI/nanobot tests prove explicit/default app-class forwarding plus pre-agent warning/block behavior. |
| `WIN-03` | `14-01`, `14-02`, `14-03`, `14-04`, `14-05`, `14-06` | Windows isolated-desktop resources are cleaned up on success, failure, and cancellation without leaving orphaned desktops or leaked handles | ? NEEDS HUMAN | Cleanup order, worker shutdown, control-path deletion, and real-handle stop are implemented and tested, but leak-free behavior still needs end-to-end inspection on a Windows host. |

All requirement IDs declared across the Phase 14 plans are accounted for in `.planning/REQUIREMENTS.md`. No orphaned Phase 14 requirement IDs were found.

### Anti-Patterns Found

No blocker or warning-level stub patterns were found in the inspected Phase 14 implementation files. The only `rg` matches for empty returns were benign helper returns in `opengui/cli.py`.

### Human Verification Required

### 1. Real Windows Alternate-Desktop Run

**Test:** Run an isolated Windows background task against a classic Win32 app such as Notepad from an interactive signed-in Windows session.
**Expected:** The worker launches on `WinSta0\\{desktop_name}`, the run stays on the alternate desktop, and the user foreground desktop does not switch away.
**Why human:** Alternate-desktop rendering/input behavior cannot be proven honestly on this non-Windows verifier host.

### 2. Unsupported Windows Context/App-Class Smoke

**Test:** Attempt one run from Session 0 or another non-interactive context, and one run targeting a UWP, DirectX, or GPU-heavy surface.
**Expected:** The non-interactive run blocks with `windows_non_interactive_session`, and the unsupported app-class run warns or blocks before the first agent step with `windows_app_class_unsupported`.
**Why human:** Session topology and app-surface behavior depend on a real Windows host.

### 3. Cleanup Leak Check

**Test:** Exercise normal success, forced startup failure after desktop creation, and cancellation mid-flight on a real Windows host.
**Expected:** Logs include `cleanup_reason=normal`, `cleanup_reason=startup_failed`, and `cleanup_reason=cancelled`, with no stale desktops or orphaned child processes left behind.
**Why human:** Resource leaks can only be confirmed end to end on Windows.

### Gaps Summary

No code-level gaps remain relative to the prior failed verification. The three failed truths from the earlier report are now implemented, wired, and covered by the phase regression slice.

The remaining work is human verification on a real Windows host. Phase 14 is ready for that smoke pass, but the phase should not be marked fully passed until those host checks confirm real alternate-desktop behavior and leak-free cleanup.

---

_Verified: 2026-03-20T18:32:39Z_
_Verifier: Codex (gsd-verifier)_
