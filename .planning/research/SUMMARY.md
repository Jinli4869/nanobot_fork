# Project Research Summary

**Project:** OpenGUI
**Domain:** Cross-platform background GUI automation
**Researched:** 2026-03-20
**Confidence:** MEDIUM

## Executive Summary

OpenGUI is extending a shipped Linux-only background desktop automation system into a true cross-platform background execution product for macOS and Windows. The research is consistent on the core approach: keep the existing `BackgroundDesktopBackend` composition model, but stop assuming Linux's in-process screenshot/input path can generalize. Experts build this by separating isolated-environment lifecycle from target-surface IO, then binding platform-native managers behind a shared backend contract.

The recommended path is opinionated. First harden the backend contract so observe and execute are guaranteed to target the same owned surface. Then implement macOS and Windows as platform-native managers with explicit runtime capability checks, not silent best-effort fallbacks. Finally, add an explicit intervention state machine so sensitive or blocked steps can pause safely, hand control to the user, and resume only after a fresh observation.

The main risks are not generic coding risk; they are platform-behavior risk. macOS is vulnerable to TCC permission drift, fragile virtual-display behavior, and version-specific regressions. Windows is vulnerable to session/desktop confusion, thread-affinity mistakes, and desktop-handle leaks. Both platforms will fail in ways that look random unless the roadmap includes contract hardening, subprocess or worker isolation where needed, and step-level observability.

## Key Findings

### Recommended Stack

The stack should stay Python-first and reuse the shipped desktop backend where it is still valid. On Windows, use Python `ctypes` against Win32 `user32` and `gdi32` APIs so isolated desktops can be managed without taking on a heavy dependency. On macOS, use Quartz/CoreGraphics through PyObjC first, with a native helper only if the required display APIs are not reliable from Python. Keep `mss`, `pyautogui`, and `Pillow` as the baseline desktop stack, but do not assume their current process-global behavior is safe for new background targets.

Critical version guidance is narrow but important: Python 3.11+, Windows 10/11 interactive sessions, macOS 13+, and current compatible PyObjC if the Quartz path is used. Optional notifier support should remain an additive protocol, not a launch dependency.

**Core technologies:**
- `ctypes` + Win32 `user32`/`gdi32` APIs: Windows hidden-desktop lifecycle and child launch control — keeps the implementation dependency-light and testable.
- Quartz/CoreGraphics via PyObjC: macOS virtual-display and display-enumeration access — the most pragmatic Python bridge to native display APIs.
- Existing `mss` + `pyautogui` + `Pillow` stack: screenshot and input plumbing — reuse it where the backend contract can guarantee correct target routing.
- `pytest` + `pytest-asyncio`: lifecycle and capability testing — preserves CI-safe coverage by mocking OS boundaries and reserving live smoke tests for dedicated hosts.

### Expected Features

Launch scope is clear: platform parity plus safe user handoff. The MVP is not just "macOS and Windows background mode." It also requires explicit capability detection, intervention request semantics, and a predictable foreground handoff/resume flow. Notification transports and Android-specific intervention UX are useful follow-ons, but they are second-order features after the state machine is correct.

**Must have (table stakes):**
- macOS background execution path with explicit permission and capability checks.
- Windows background execution path with documented launch-context and app-class limits.
- `request_intervention` or equivalent explicit pause/resume action in the agent loop.
- Foreground handoff and resume behavior that refreshes observation state before continuing.
- Regression coverage for lifecycle, fallback, and sensitive-state handling.

**Should have (competitive):**
- Multi-layer intervention detection that combines model intent with deterministic policy signals.
- Notification abstraction that can support local and remote operators without changing core handoff logic.
- Capability-aware UX in CLI and nanobot so degraded or blocked modes are explicit.

**Defer (v2+):**
- Live observer or VNC-style remote viewing.
- Broad app-domain-specific intervention policy packs.
- Silent convenience fallbacks from background to foreground execution.

### Architecture Approach

The architecture research is the most stable input. Keep `BackgroundDesktopBackend` as the orchestration wrapper, add platform managers for Linux, macOS, and Windows behind a shared contract, and isolate intervention handling in agent orchestration rather than backend IO code. The design pattern is a capability-checked adapter plus an explicit pause/resume state machine, with CLI and nanobot remaining thin wiring layers.

**Major components:**
1. `BackgroundDesktopBackend` — owns isolated-run lifecycle, delegates normal observe/execute calls, and coordinates platform startup/shutdown.
2. Platform managers — implement Linux/Xvfb, macOS virtual-display, and Windows alternate-desktop creation plus capability reporting.
3. Intervention handler/policy — owns pause, notify, foreground restore, quiesce, and explicit resume semantics.
4. Host wiring in CLI/nanobot — translates config and exposes the same warnings, errors, and capability outcomes everywhere.

### Critical Pitfalls

1. **Reusing the local desktop backend unchanged** — split display lifecycle from target-surface IO and prove `observe()` and `execute()` hit the same owned surface.
2. **Mixing coordinate systems and scale factors** — define one canonical coordinate space, convert exactly once on observe and once on execute, and test Retina/scaled layouts explicitly.
3. **Treating macOS permissions as setup instead of runtime preflight** — check Screen Recording, Accessibility, and post-event access before every background run and tie them to a stable signed identity.
4. **Confusing Windows background automation with Session 0 or service automation** — only support alternate desktops inside an interactive user session and reject unsupported launch contexts up front.
5. **Building intervention on a single weak signal or skipping quiesce cleanup** — combine multiple takeover signals, release inputs safely, restore clipboard state, and require explicit resume.

## Implications for Roadmap

Based on the combined research, the roadmap should be a five-phase sequence rather than a single "cross-platform background mode" tranche.

### Phase 1: Contract Hardening and Worker Boundaries
**Rationale:** The current Linux abstraction looks reusable, but the research shows it is not sufficient for macOS or Windows because capture and input still assume the wrong global surface.
**Delivers:** Explicit target-surface IO contract, display/desktop identity propagation, concurrency guardrails, and the worker/subprocess seams needed for platform-specific routing.
**Addresses:** trustworthy background execution, clear fallback behavior, regression safety.
**Avoids:** wrong-surface capture/input, process-global collisions, misleading wrapper-only reuse.

### Phase 2: macOS Background Execution
**Rationale:** macOS has the most fragile runtime constraints, so it should be implemented first while the contract is still fresh and before intervention logic depends on platform hooks.
**Delivers:** macOS display manager, TCC preflight, capture/input routing for the owned display, and explicit degrade-or-block behavior.
**Addresses:** macOS background execution parity, capability-aware UX.
**Uses:** Quartz/CoreGraphics via PyObjC first, existing desktop stack where routing is proven safe.
**Avoids:** permission-blind failures, coordinate drift, virtual-display fragility being discovered late.

### Phase 3: Windows Isolated Desktop Execution
**Rationale:** Windows depends on a distinct worker/process model and strict desktop/session handling, so it should be isolated into its own phase instead of being coupled to handoff work.
**Delivers:** alternate-desktop worker lifecycle, `lpDesktop` child process launch path, launch-context preflight, and desktop-handle cleanup.
**Addresses:** Windows background execution parity, documented app-class limits.
**Uses:** `ctypes` Win32 bindings, existing backend wrapper, dedicated worker ownership.
**Avoids:** Session 0 mistakes, late `SetThreadDesktop` calls, desktop heap leaks.

### Phase 4: Intervention Detection and Safe Handoff
**Rationale:** Handoff is only credible after both platform execution paths expose the hooks and metadata needed to pause safely and return control cleanly.
**Delivers:** `request_intervention` action, explicit paused state, notification hooks, quiesce sequence, foreground restore, and fresh-observation resume.
**Addresses:** safe intervention request action, foreground handoff and resume, multi-layer takeover detection.
**Implements:** intervention policy and handler components in agent orchestration.
**Avoids:** false-positive pauses, unsafe continued typing, stuck modifiers, clipboard corruption.

### Phase 5: Platform Verification and Observability
**Rationale:** The failure modes here are platform- and environment-specific; without dedicated trace metadata and smoke coverage, support and regression work will be guesswork.
**Delivers:** platform smoke suites on dedicated hosts, richer per-step trace metadata, manual verification matrix, and release-facing compatibility notes.
**Addresses:** clear fallback behavior, lifecycle confidence, supportability.
**Avoids:** unreproducible bugs, shipping platform claims without evidence, hidden ownership failures.

### Phase Ordering Rationale

- Phase 1 must come first because every later phase depends on a backend contract that can route both capture and input to the same target surface.
- macOS and Windows should be separate implementation phases because their native constraints are different enough that combining them would blur failure semantics and slow debugging.
- Intervention follows platform execution, not the other way around, because safe handoff needs real ownership, foreground, and lifecycle hooks from the platform layers.
- Verification and observability come last in implementation order but must be budgeted from the start; the pitfalls research shows these features break in packaging, sleep/resume, and OS updates more often than in happy-path local development.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** macOS virtual-display viability, API reachability from PyObjC, and version-specific behavior still need implementation-time validation.
- **Phase 3:** Windows app-class compatibility and alternate-desktop capture/input behavior need targeted planning assumptions and likely spike criteria.
- **Phase 5:** Dedicated host smoke strategy and compatibility-matrix scope need planning decisions, even though the testing pattern itself is standard.

Phases with standard patterns (skip research-phase):
- **Phase 1:** contract hardening and subprocess seams follow directly from current OpenGUI architecture and known code seams.
- **Phase 4:** explicit pause/resume state machines and quiesce cleanup fit the existing agent/trajectory design and do not require major discovery work.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Windows primitives are well-established; the macOS path is plausible but less formally documented and likely version-sensitive. |
| Features | MEDIUM | User need and milestone scope are clear, but several "should-have" items are inferred from operational needs rather than hard product requirements. |
| Architecture | HIGH | The current v1.1 abstraction and code seams map cleanly to the recommended wrapper-plus-manager design. |
| Pitfalls | MEDIUM | Many pitfalls are strongly grounded in official docs, but macOS virtual-display fragility still leans partly on operational/community evidence. |

**Overall confidence:** MEDIUM

### Gaps to Address

- **macOS execution path:** Validate whether PyObjC can reliably reach the required display APIs on supported macOS versions; fall back to a native helper only if the Python bridge is inadequate.
- **Target-surface IO contract:** Prove early whether existing `mss` and input plumbing can be adapted safely or whether macOS and Windows require stricter worker boundaries.
- **Windows support envelope:** Define which GUI app classes are officially supported on alternate desktops before marketing Windows parity broadly.
- **Notification scope:** Decide during planning whether local notifications are enough for v1.2 or whether remote operator channels are needed in the same milestone.

## Sources

### Primary (HIGH confidence)
- `.planning/PROJECT.md` — current milestone scope, existing architecture, and shipped Linux background model.
- `.planning/research/ARCHITECTURE.md` — recommended composition pattern, component boundaries, and data flow.
- Microsoft Learn documentation on desktop/session APIs — alternate desktop lifecycle, thread-affinity, and desktop heap constraints.
- Apple developer documentation for CoreGraphics/TCC preflight APIs — coordinate-space handling, screen capture permissions, and event-posting capability checks.

### Secondary (MEDIUM confidence)
- `.planning/research/STACK.md` — pragmatic stack recommendation and version guidance.
- `.planning/research/FEATURES.md` — feature scope, dependency chain, and anti-feature boundaries.
- `.planning/research/PITFALLS.md` — prevention-phase model, verification strategy, and operational failure patterns.
- Existing code/test seams in `opengui/backends/background.py`, `opengui/backends/desktop.py`, `tests/test_opengui_p10_background.py`, and `tests/test_opengui_p9_virtual_display.py`.

### Tertiary (LOW confidence)
- Apple Developer Forums references to `CGVirtualDisplay` behavior — useful signal for viability, but not strong enough to treat as final API certainty.
- Community issue reports around macOS virtual-display regressions after sleep or OS updates — useful for planning defensive behavior, not for defining guaranteed product behavior.

---
*Research completed: 2026-03-20*
*Ready for roadmap: yes*
