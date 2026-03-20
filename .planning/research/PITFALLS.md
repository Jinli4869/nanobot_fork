# Pitfalls Research

**Domain:** Cross-platform background GUI automation for macOS virtual displays, Windows isolated desktops, and intervention-safe user handoff
**Researched:** 2026-03-20
**Confidence:** MEDIUM

## Suggested Prevention Phases

- **Phase A — Contract Hardening:** tighten `VirtualDisplayManager` / backend contracts before adding new platforms.
- **Phase B — macOS Background Execution:** ship virtual-display support, TCC onboarding, and macOS-specific capture/input routing.
- **Phase C — Windows Isolated Desktop Execution:** ship alternate-desktop worker process, lifecycle, and launch model.
- **Phase D — Intervention Detection and Safe Handoff:** detect user takeover and leave the machine in a safe state.
- **Phase E — Platform Verification and Observability:** add smoke coverage, telemetry, and failure diagnostics.

## Critical Pitfalls

### Pitfall 1: Assuming the Existing Local Desktop Backend Can Be Reused Unchanged

**What goes wrong:**
The new feature is implemented as “just add a new `VirtualDisplayManager`,” but screenshots and input still target the wrong surface. In the current stack, `BackgroundDesktopBackend` only changes process state and absolute offsets, while `LocalDesktopBackend.observe()` always captures `mss.monitors[1]` and `execute()` uses process-global `pyautogui` input. That is good enough for Linux `DISPLAY`, but not for macOS virtual displays or Windows alternate desktops.

**Why it happens:**
The abstraction looks ready because `DisplayInfo` already has `offset_x`, `offset_y`, and `monitor_index`. In practice, the inner backend still owns capture and input routing, so the wrapper cannot fix a backend that fundamentally points at the wrong display/desktop.

**How to avoid:**
- Split “background execution” into two contracts: display lifecycle and target-surface IO.
- Add a platform-specific worker boundary for macOS and Windows instead of reusing the same in-process `pyautogui`/`mss` path.
- Treat `display_id`, `monitor_index`, and platform-native display/desktop handles as execution inputs, not advisory metadata.
- Add a contract test that proves `observe()` and `execute()` hit the same target surface.

**Warning signs:**
- Screenshots show the primary/user display while clicks land elsewhere.
- The same task passes on Linux `Xvfb` but fails on macOS/Windows background mode.
- Only monitor `1` ever appears in traces.

**Phase to address:**
Phase A — Contract Hardening

---

### Pitfall 2: Mixing Coordinate Systems, Scale Factors, and Offsets

**What goes wrong:**
Clicks, drags, and scroll anchors land in the wrong place on Retina or scaled displays. The agent “looks” right on screenshots but input is off by 2x, shifted, or wrong only on one display arrangement.

**Why it happens:**
macOS mixes global display coordinates, screen points, and backing-store pixels. Apple’s high-resolution guidance explicitly warns to use backing conversion APIs rather than manually multiplying by scale factors, and Quartz display APIs return points in modern macOS. The current desktop backend also downscales screenshots from physical pixels to logical dimensions, while `BackgroundDesktopBackend` only adjusts execute-time absolute coordinates.

**How to avoid:**
- Declare one canonical coordinate space for the agent. Recommendation: logical coordinates relative to the target surface, plus explicit target-surface metadata.
- Extend observation metadata to include `capture_bounds`, `scale_factor`, and stable target identity.
- Convert exactly once: native capture space -> canonical agent space on observe, then canonical agent space -> native injection space on execute.
- Add platform tests for Retina/scaled display layouts and non-zero display origins.

**Warning signs:**
- Off-by-2 failures on Retina only.
- Swipes start correctly but end on the wrong monitor.
- The same screenshot replay fails after moving the virtual display in System Settings.

**Phase to address:**
Phase B — macOS Background Execution

---

### Pitfall 3: Treating macOS Permissions as a One-Time Setup Instead of a Runtime Capability Check

**What goes wrong:**
Background execution works for one developer machine and then fails in packaging, helper processes, or after rebuilds with opaque “cannot capture” / “cannot post events” errors. Users get stuck in TCC dialogs with no remediation path.

**Why it happens:**
macOS gates screen capture, accessibility, and event posting separately. Apple exposes preflight/request APIs such as `CGPreflightScreenCaptureAccess`, `CGPreflightPostEventAccess`, and `AXIsProcessTrustedWithOptions`, but teams often only discover missing permissions after a failed action. Apple DTS also explicitly warns that unstable/ad hoc signing breaks TCC behavior.

**How to avoid:**
- Add explicit preflight before starting a background run: screen capture, accessibility trust, and post-event access.
- Package the automation helper with a stable bundle identity and signing path; do not rely on ad hoc or constantly changing binaries for shipped flows.
- Return platform-specific remediation messages, not generic backend failures.
- Record permission state in traces so support can distinguish “permission denied” from “display routing bug.”

**Warning signs:**
- Works from one launcher path but not another.
- Permissions re-prompt after rebuild, restart, or helper relaunch.
- Event tap creation or screen capture returns `NULL` / empty output without a clear app-side explanation.

**Phase to address:**
Phase B — macOS Background Execution

---

### Pitfall 4: Underestimating macOS Virtual Display Fragility Across OS Updates, Sleep, and Topology Changes

**What goes wrong:**
The virtual display disappears, stops mirroring, strands windows off-screen, or destabilizes `WindowServer` after sleep/resume or an OS update. The feature appears “done” on one macOS version but regresses badly on the next.

**Why it happens:**
The CGVirtualDisplay-style ecosystem is operationally fragile. Recent BetterDisplay issues show macOS Sequoia regressions, sleep problems, and even `WindowServer` crashes around virtual display flows. This is not strong enough evidence to say “the API is unusable,” but it is strong enough to treat the area as version-sensitive and failure-prone.

**How to avoid:**
- Hide the feature behind a capability probe and feature flag.
- Detect topology changes, display disappearance, and sleep/resume, then abort or hand off cleanly instead of continuing blindly.
- Keep a foreground fallback path and make downgrade explicit in UX.
- Maintain a macOS-version compatibility matrix in tests and release notes.

**Warning signs:**
- Background runs fail only after sleep or only on one macOS release.
- Windows/apps reopen on a missing display.
- `WindowServer` or display arrangement logs spike around virtual-display creation/removal.

**Phase to address:**
Phase B — macOS Background Execution

---

### Pitfall 5: Confusing Windows Alternate Desktops with “Background Windows Automation” in General

**What goes wrong:**
The implementation launches under a service, scheduled task, or Session 0 context and assumes it can still automate user-visible UI. Processes run, but windows are invisible, capture is blank, and input appears to do nothing.

**Why it happens:**
Microsoft’s guidance is explicit: services do not directly interact with users on modern Windows, and Session 0 is isolated from interactive user sessions. Teams often discover this too late because the process exists and APIs do not always fail loudly.

**How to avoid:**
- Decide early whether Windows background execution means “alternate desktop inside the interactive user session” or “non-interactive job.” Only the former fits GUI automation.
- If a service is required, make it a broker that launches a per-user helper in the interactive session.
- Reject unsupported launch contexts up front with a hard preflight failure.

**Warning signs:**
- The worker is running as `SYSTEM` or in Session 0.
- Child GUI apps exist in Task Manager but are not visible anywhere.
- Capture/input failures correlate with “Run whether user is logged on or not.”

**Phase to address:**
Phase C — Windows Isolated Desktop Execution

---

### Pitfall 6: Setting the Windows Desktop Context Too Late

**What goes wrong:**
`SetThreadDesktop` fails, hooks stop working, or windows get created on the default desktop even though the code “switched” desktops. Child processes appear on the wrong desktop because only the parent thread changed.

**Why it happens:**
`SetThreadDesktop` is thread-scoped, not process-scoped, and Microsoft documents that it fails if the calling thread already has windows or hooks. Separately, child GUI processes need `STARTUPINFO.lpDesktop` set at creation time if they are supposed to start on a specific desktop.

**How to avoid:**
- Use a dedicated worker process for each isolated desktop.
- Set the target desktop before importing GUI libraries, installing hooks, or creating any windows.
- Launch child apps with `STARTUPINFO.lpDesktop`.
- Do not reuse the main host thread/process for alternate-desktop work.

**Warning signs:**
- Desktop switching works in toy tests but fails once hooks or GUI libs are added.
- Alternate-desktop child windows appear on the default desktop.
- Cleanup is inconsistent because some objects belong to the wrong desktop.

**Phase to address:**
Phase C — Windows Isolated Desktop Execution

---

### Pitfall 7: Leaking Desktop Handles and Desktop Heap on Windows

**What goes wrong:**
Runs succeed initially, then later fail with increasingly strange errors because hidden desktops accumulate or the desktop heap is exhausted. Crash recovery leaves orphaned desktops behind.

**Why it happens:**
`CreateDesktop` consumes desktop heap, Microsoft documents that the number of desktops is limited by that heap, and every handle must be closed with `CloseDesktop`. This failure mode is easy to miss in development because it appears only after repeated runs or crash loops.

**How to avoid:**
- Make one component the sole owner of desktop lifecycle.
- Guarantee `CloseDesktop` on success, failure, and cancellation paths.
- Cap concurrent Windows background runs per user/session.
- Emit metrics for desktop create/close counts and leaked-handle suspicion.

**Warning signs:**
- First run passes, repeated runs fail.
- A cancelled run leaves windows/desktops around.
- Reboot “fixes” the issue temporarily.

**Phase to address:**
Phase C — Windows Isolated Desktop Execution

---

### Pitfall 8: Building Intervention Detection on a Single Weak Signal

**What goes wrong:**
The agent pauses itself during its own injected input, or worse, keeps typing while the user has already taken over. Handoff is either too sensitive or not sensitive enough.

**Why it happens:**
The available OS signals are partial. On Windows, `GetLastInputInfo` is session-specific and Microsoft notes its tick count can move backward, including around `SendInput`. `SetWinEventHook` only sees the current desktop and requires a message loop. On macOS, event taps require accessibility trust and can fail silently if permissions are missing; workspace notifications are useful but coarse.

**How to avoid:**
- Combine signals instead of trusting one:
  - own action ledger and “agent is currently injecting input” window
  - foreground window/app changes
  - desktop/space/session changes
  - raw user input hooks where permitted
- Add a short grace window to ignore the agent’s own injected events.
- Record the reason for takeover decisions in the trace.

**Warning signs:**
- Every long drag or hotkey sequence triggers a false intervention.
- The user can move the mouse and the agent continues anyway.
- Detection quality changes drastically depending on permission state.

**Phase to address:**
Phase D — Intervention Detection and Safe Handoff

---

### Pitfall 9: Stopping the Agent Without Returning the Machine to a Safe State

**What goes wrong:**
User takeover “works,” but the system is left with stuck modifiers, a pressed mouse button, modified clipboard contents, an invisible desktop, or an undisclosed active target display. The product feels dangerous even if the detection logic is technically correct.

**Why it happens:**
Teams model handoff as a boolean cancel instead of a state transition. Windows `SendInput` does not reset existing keyboard state, and the current desktop backend pastes via clipboard, so half-finished cleanup is easy to leave behind.

**How to avoid:**
- Implement a quiesce sequence:
  - stop the action queue
  - release pressed keys/buttons
  - finish or cancel in-flight drags safely
  - restore clipboard if mutated
  - disclose which display/desktop is active
  - mark the run as `interrupted_by_user`
- Make takeover reversible only by explicit user action, not by automatic resume.

**Warning signs:**
- “Cmd/Ctrl is stuck” reports.
- The next paste operation contains agent text.
- Users do not know how to return from the hidden/isolated surface.

**Phase to address:**
Phase D — Intervention Detection and Safe Handoff

---

### Pitfall 10: Letting Multiple Background Runs Share Process-Global State

**What goes wrong:**
Two runs interfere with each other through `DISPLAY`, clipboard contents, input hooks, or shared backend objects. Bugs look nondeterministic because they depend on timing.

**Why it happens:**
The current Linux path mutates process-global environment state in `BackgroundDesktopBackend`, and the broader codebase already has known global-state/thread-safety concerns. macOS and Windows will add more process-global behavior unless execution is isolated deliberately.

**How to avoid:**
- Serialize background desktop runs per host machine unless proven safe otherwise.
- Move platform-specific background execution into dedicated subprocesses.
- Treat clipboard and global hooks as shared resources with explicit ownership.
- Add “background execution already active” failures instead of best-effort overlap.

**Warning signs:**
- One run changes another run’s capture target.
- Flakes only appear under concurrent tool use.
- Debug logs show rapid target-surface churn without user action.

**Phase to address:**
Phase A — Contract Hardening

---

### Pitfall 11: Shipping Platform Support Without Platform-Specific Test Strategy

**What goes wrong:**
The code is “covered” by mocks, but the real failures are permissions, topology, desktop ownership, and session behavior. Teams either skip all live tests or make CI depend on fragile local OS features.

**Why it happens:**
These features are inherently hard to test in generic CI. The existing Linux `Xvfb` path is CI-friendly because the subprocess boundary is mockable; macOS virtual displays and Windows alternate desktops are not equivalently disposable.

**How to avoid:**
- Preserve unit tests around contract and lifecycle seams.
- Add explicit contract tests for:
  - display identity
  - scale/offset conversion
  - permission failure mapping
  - intervention quiesce behavior
- Add gated smoke suites on dedicated macOS and Windows hosts for real background execution.
- Require manual verification for sleep/resume, session switch, and permission onboarding.

**Warning signs:**
- Most new tests are `@skipif(platform...)`.
- The only real validation is “worked once on my laptop.”
- Bugs concentrate in packaging and OS upgrade paths, not core logic.

**Phase to address:**
Phase E — Platform Verification and Observability

---

### Pitfall 12: Not Logging Enough to Reconstruct Which Surface the Agent Actually Owned

**What goes wrong:**
When a click lands on the wrong display or the wrong desktop takes focus, there is no way to tell whether the failure was permission-related, coordinate-related, or ownership-related. Root cause analysis becomes guesswork.

**Why it happens:**
Most automation traces record screenshot paths and action summaries, but not the display/desktop/session metadata needed for background execution debugging.

**How to avoid:**
- Include per-step metadata in traces:
  - platform
  - display ID / UUID / monitor index
  - desktop name/handle
  - session ID
  - offsets and scale factor
  - foreground app/window
  - handoff/intervention reason
- Snapshot preflight results for permission state and launch context.

**Warning signs:**
- Support tickets say “clicked the wrong screen” with no reproducible artifact.
- Engineers cannot tell whether observe and execute targeted the same surface.
- Bugs are closed as unreproducible after one or two guesses.

**Phase to address:**
Phase E — Platform Verification and Observability

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Reuse `LocalDesktopBackend` unchanged behind new display managers | Minimal code churn | Wrong capture/input routing on macOS and Windows | Never for shipped background execution |
| Keep background execution in the main host process | Simpler wiring | Global env, clipboard, hook, and concurrency collisions | Only for short-lived prototypes |
| Detect permissions only after the first failed action | Faster first implementation | Opaque UX and hard-to-diagnose support issues | Never |
| Treat intervention as `cancel = true` without quiesce/restore | Quick demo | Unsafe handoff, stuck modifiers, clipboard corruption | Never |
| Rely on manual testing only | Avoids CI complexity | Regressions after OS updates and packaging changes | Only for exploratory spikes before Phase E |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `BackgroundDesktopBackend` | Assuming wrapper-only logic can retarget any backend | Make target-surface routing an explicit backend responsibility |
| `mss` capture path | Always reading `monitors[1]` and assuming it is the owned surface | Resolve and persist the target monitor/display for each background run |
| `pyautogui` / injected input | Assuming global input goes to an alternate desktop/virtual display automatically | Use platform-native worker logic and verify input target ownership |
| macOS TCC | Granting permissions to one binary path and assuming helpers inherit them | Preflight each shipped identity and keep code signing stable |
| Windows child process launch | Starting apps with plain `CreateProcess` and expecting them to land on the isolated desktop | Set `STARTUPINFO.lpDesktop` explicitly |
| Windows event hooks | Registering `SetWinEventHook` without a message loop or on the wrong desktop | Run a dedicated hook loop on the target desktop and skip own events |
| Nanobot/OpenGUI integration | Extending today’s Linux-only `background` flag implicitly to all platforms | Add explicit per-platform capabilities and failure modes in config/CLI/tooling |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Recreating the virtual display/desktop on every observation or action | Slow steps, flicker, intermittent launch failures | Create once per run; reuse until clean shutdown | Long tasks and retry-heavy runs |
| Full-resolution capture plus resize on every step without target scoping | High CPU/GPU use, laggy loops | Capture only the owned surface and persist scale metadata | High-DPI and multi-monitor systems |
| Polling for intervention with tight timers | Idle CPU burn, battery drain | Prefer event-driven hooks/notifications with bounded fallback polling | Long background sessions |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Running Windows GUI automation as a service on the interactive desktop | Shatter-style message attacks and broken security model | Keep services non-interactive; use a per-user helper in the interactive session |
| Requesting `DF_ALLOWOTHERACCOUNTHOOK` without a hard requirement | Cross-account hook surface you likely do not need | Use the minimum desktop access rights and hook flags |
| Continuing automation after ambiguous ownership changes | Inputs land in the user’s active session/app unexpectedly | Fail closed: pause or hand off on ownership uncertainty |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Background mode that silently falls back to foreground mode | Surprising cursor/window movement on the user’s desktop | Make fallback explicit and require confirmation or a clearly labeled mode change |
| Permission errors surfaced as generic backend failures | Users cannot self-remediate | Tell the user exactly which macOS/Windows capability is missing and how to fix it |
| Intervention detection that is too eager | The agent feels broken and unreliable | Use multi-signal detection with a grace window |
| Intervention detection that is too lax | The agent feels unsafe | Pause on ambiguity and resume only explicitly |
| Hidden/isolated surfaces with no return path | Users think apps disappeared or the machine is stuck | Provide a clear “return control” / “switch back” affordance and log it |

## "Looks Done But Isn't" Checklist

- [ ] **macOS background mode:** Verify Screen Recording, Accessibility, and post-event preflight before the first step.
- [ ] **macOS coordinate handling:** Verify Retina/scaled-display clicks on a non-zero-offset target display.
- [ ] **macOS virtual display lifecycle:** Verify sleep/resume and display removal do not strand windows or crash the run.
- [ ] **Windows isolated desktop:** Verify child GUI apps launch onto the intended desktop via `lpDesktop`.
- [ ] **Windows lifecycle:** Verify every created desktop handle is closed on success, failure, and cancellation.
- [ ] **Intervention handoff:** Verify key/button release, clipboard restore, and explicit user-visible run state.
- [ ] **Cross-run isolation:** Verify two background runs cannot execute concurrently on the same machine unless explicitly supported.
- [ ] **Traceability:** Verify traces include display/desktop/session identity and handoff reason.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong target surface routing | MEDIUM | Abort run, dump target-surface metadata, force foreground fallback, fix contract mismatch before retry |
| macOS permission drift | LOW/MEDIUM | Re-run preflight, surface missing permission, relaunch under the signed helper identity, retry only after confirmation |
| macOS virtual display disappears | MEDIUM | Stop the run, move any stranded app windows back if possible, switch to foreground or mark platform unsupported on that OS build |
| Windows desktop leak / heap exhaustion | HIGH | Kill orphan workers, close leaked handles if possible, reboot if required, then add lifecycle telemetry and crash-safe cleanup |
| Unsafe user handoff | HIGH | Release inputs, restore clipboard, switch back to the user-owned surface, mark the run interrupted, require explicit resume |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Reusing the local backend unchanged | Phase A | Contract test proves observe/execute target the same owned surface |
| Mixed coordinate systems and scale factors | Phase B | Retina/scaled-display smoke tests pass on non-zero-offset targets |
| macOS permission identity drift | Phase B | Preflight returns actionable failures for each missing capability |
| macOS virtual display fragility | Phase B / Phase E | Sleep/resume and OS-version smoke tests have explicit expected outcomes |
| Windows session confusion | Phase C | Launch preflight rejects Session 0 / non-interactive contexts |
| Windows desktop context set too late | Phase C | Worker/child processes demonstrably bind to the intended desktop |
| Windows desktop leaks | Phase C | Repeated create/run/teardown cycles leave no leaked desktops |
| Weak intervention detection | Phase D | Tests cover false-positive and false-negative takeover scenarios |
| Unsafe handoff cleanup | Phase D | Quiesce test verifies key/button release, clipboard restore, and explicit status |
| Global-state collisions across runs | Phase A | Parallel-run guard prevents overlapping background sessions |
| Missing platform test strategy | Phase E | Unit, smoke, and manual verification matrix exists for each platform |
| Missing observability | Phase E | Trace artifacts contain display/desktop/session metadata for each step |

## Sources

- Project context: `.planning/PROJECT.md`
- Current code seam: `opengui/backends/background.py`
- Current code seam: `opengui/backends/desktop.py`
- Existing background tests: `tests/test_opengui_p10_background.py`
- Existing display contract tests: `tests/test_opengui_p9_virtual_display.py`
- Apple High Resolution Guidelines for OS X, “APIs for Supporting High Resolution” (points vs backing coordinates, conversions): https://developer.apple.com/library/archive/documentation/GraphicsAnimation/Conceptual/HighResolutionOSX/APIs/APIs.html
- Apple Core Graphics docs index (includes `CGDisplayBounds`, `CGCaptureAllDisplays`, `CGDisplayCapture`): https://developer.apple.com/documentation/coregraphics/core-graphics-functions
- Apple docs result for `CGEventCreateMouseEvent` (global coordinates): https://developer.apple.com/documentation/coregraphics/cgevent/init%28mouseeventsource%3Amousetype%3Amousecursorposition%3Amousebutton%3A%29?language=objc
- Apple docs result for `CGEventTapCreate` (permissions and event tap failure modes): https://developer.apple.com/documentation/coregraphics/cgevent/tapcreate%28tap%3Aplace%3Aoptions%3Aeventsofinterest%3Acallback%3Auserinfo%3A%29?language=objc
- Apple docs result for `AXIsProcessTrustedWithOptions`: https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions?changes=l_2&language=objc
- Apple docs result for `CGPreflightScreenCaptureAccess`: https://developer.apple.com/documentation/coregraphics/cgpreflightscreencaptureaccess%28%29?language=objc
- Apple docs result for `CGPreflightPostEventAccess`: https://developer.apple.com/documentation/coregraphics/cgpreflightposteventaccess%28%29
- Apple docs result for `NSWorkspace` notifications (`didActivateApplicationNotification`, `didDeactivateApplicationNotification`, `sessionDidBecomeActiveNotification`, `activeSpaceDidChangeNotification`): https://developer.apple.com/documentation/appkit/nsworkspace/didhideapplicationnotification
- Apple DTS forum note on stable code signing identity and TCC behavior: https://developer.apple.com/forums/thread/760112
- Microsoft `CreateDesktopW` docs (desktop association, access rights, heap limits): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createdesktopw
- Microsoft `SetThreadDesktop` docs (fails if thread already has windows/hooks): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddesktop
- Microsoft `OpenInputDesktop` docs (input desktop and session behavior): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-openinputdesktop
- Microsoft `SwitchDesktop` docs (visible/active desktop, secure desktop failure cases): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-switchdesktop
- Microsoft `STARTUPINFOW` docs (`lpDesktop` for child process launch): https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-startupinfow
- Microsoft `SendInput` docs (UIPI, keyboard state caveat): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
- Microsoft `GetLastInputInfo` docs (session-specific, non-monotonic caveat): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo
- Microsoft `SetWinEventHook` docs (current desktop scope, message loop requirement, reentrancy): https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwineventhook
- Microsoft “Interactive Services” guidance (services must not directly interact with users on modern Windows): https://learn.microsoft.com/en-us/windows/win32/services/interactive-services
- BetterDisplay discussion showing sleep / virtual display fragility around `CGVirtualDisplay`-style features: https://github.com/waydabber/BetterDisplay/discussions/122
- BetterDisplay discussion showing Sequoia virtual display regression: https://github.com/waydabber/BetterDisplay/discussions/3467
- BetterDisplay discussion showing `WindowServer` crashes around virtual display setup: https://github.com/waydabber/BetterDisplay/discussions/3199

---
*Pitfalls research for: background GUI automation on macOS and Windows*
*Researched: 2026-03-20*
