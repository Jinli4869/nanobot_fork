# Architecture Research

**Domain:** Cross-platform background GUI automation
**Researched:** 2026-03-20
**Confidence:** HIGH

## Standard Architecture

### System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                    Host Entry Surfaces                      │
├─────────────────────────────────────────────────────────────┤
│  CLI runner              Nanobot GUI tool                  │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
┌───────────────▼───────────────────────────────▼─────────────┐
│                  GuiAgent / Run Orchestration               │
├─────────────────────────────────────────────────────────────┤
│  step loop   intervention request   pause/resume policy    │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
┌───────────────▼───────────────────────────────▼─────────────┐
│                Device Backend Composition Layer             │
├─────────────────────────────────────────────────────────────┤
│ LocalDesktopBackend   BackgroundDesktopBackend decorator    │
│ adb backend           platform capability selection         │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
┌───────────────▼───────────────┐   ┌───────────▼─────────────┐
│ Virtual / Session Managers    │   │ Intervention Services   │
├───────────────────────────────┤   ├─────────────────────────┤
│ Xvfb manager (existing)       │   │ notifier / handoff      │
│ macOS display manager         │   │ foreground restore      │
│ Windows desktop manager       │   │ trajectory events       │
└───────────────────────────────┘   └─────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| `BackgroundDesktopBackend` | Own lifecycle of isolated execution context and delegate normal observe/execute calls | Decorator around `LocalDesktopBackend` plus platform manager |
| Platform manager (`Xvfb`, macOS, Windows) | Start/stop the isolated environment and return geometry/capability data | Separate classes implementing the existing virtual display/session contract |
| Intervention policy/handler | Decide when to pause, notify user, switch foreground, and resume | Agent-loop integration plus small protocol for notification and handoff |
| CLI / nanobot integration | Expose config, platform checks, and warnings consistently | Thin wiring layers, not platform-specific business logic |

## Recommended Project Structure

```text
opengui/
├── backends/
│   ├── desktop.py              # existing local desktop backend
│   ├── background.py           # wrapper / selection logic
│   └── virtual_display.py      # shared contracts + linux/mac/windows managers
├── intervention/
│   ├── policy.py               # deterministic intervention checks
│   ├── handler.py              # pause, notify, handoff, resume
│   └── notifier.py             # optional transport abstraction
├── agent.py                    # explicit request_intervention handling
├── cli.py                      # runtime flags and capability messaging
└── interfaces.py               # any new protocol surface
```

### Structure Rationale

- **`backends/`:** keep all platform isolation logic behind the existing backend boundary so the agent loop remains mostly platform-agnostic.
- **`intervention/`:** isolate handoff behavior from raw desktop/input code; this reduces coupling between safety logic and display/session plumbing.

## Architectural Patterns

### Pattern 1: Capability-Checked Adapter

**What:** A platform-specific manager advertises whether it can create an isolated execution context before the wrapper starts the run.
**When to use:** For macOS and Windows background mode where permissions and app-class support are environment-dependent.
**Trade-offs:** Slightly more setup code, but much clearer failure semantics.

### Pattern 2: Explicit Pause/Resume State Machine

**What:** The agent loop transitions into a paused state on intervention request, then resumes only after handoff completion.
**When to use:** For password, payment, captcha, login, or repeated-failure states.
**Trade-offs:** More state to test, but much safer than implicit retries or backend-side sleeps.

### Pattern 3: Thin Host Wiring

**What:** CLI and nanobot entrypoints translate config into backend/intervention objects without owning platform logic.
**When to use:** Across all current and future host integrations.
**Trade-offs:** Requires disciplined boundaries, but keeps host-specific code small and testable.

## Data Flow

### Request Flow

```text
User / host config
    ↓
CLI or nanobot tool
    ↓
backend builder + capability checks
    ↓
BackgroundDesktopBackend
    ↓
platform manager start
    ↓
GuiAgent step loop
    ↓
observe / decide / execute
    ↓
intervention request? ──yes──> handler pause/notify/handoff/resume
```

### State Management

```text
Run state
    ↓
backend lifecycle + intervention status
    ↓
trajectory events / logs / host-visible warnings
```

### Key Data Flows

1. **Background startup:** host config selects background mode, capability checks run, platform manager returns `DisplayInfo`-like metadata, wrapper enters active state.
2. **Intervention flow:** agent or policy requests intervention, handler pauses action execution, emits notification, switches/returns foreground if supported, then re-observes before resume.
3. **Fallback/error flow:** capability failure returns a structured warning/error to CLI/nanobot without mutating unrelated Linux behavior.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single operator / local runs | Current monolithic backend + handler structure is sufficient |
| Multiple operators / remote runs | Add notifier transports and richer resume coordination, but keep core state machine the same |
| Multi-host orchestration | Separate intervention events into explicit external callbacks/webhooks |

### Scaling Priorities

1. **First bottleneck:** platform-specific capability drift; fix with runtime probes and focused smoke tests.
2. **Second bottleneck:** handoff UX divergence across CLI and nanobot; fix with a shared intervention protocol.

## Anti-Patterns

### Anti-Pattern 1: Put intervention logic inside the desktop backend

**What people do:** Treat pause/notify/handoff as a special backend command path.
**Why it's wrong:** Safety logic becomes tangled with screenshot/input plumbing and is harder to verify.
**Do this instead:** Keep intervention as agent-orchestration state, with the backend only exposing the hooks needed for handoff.

### Anti-Pattern 2: Fork the entire desktop backend per platform

**What people do:** Create separate macOS and Windows desktop backends that duplicate most local-backend behavior.
**Why it's wrong:** Linux parity regresses and tests fragment quickly.
**Do this instead:** Reuse `LocalDesktopBackend` behavior behind a platform manager plus wrapper pattern.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| macOS native display APIs | PyObjC or helper bridge | Must be guarded behind runtime availability checks. |
| Windows Win32 desktop APIs | `ctypes` into `user32` / `gdi32` | Thread-affinity rules must be reflected in the implementation design. |
| Desktop notification transport | Small notifier protocol | Optional in MVP; should not block the core pause/resume path. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `agent.py` ↔ intervention handler | direct API / protocol | Agent remains owner of pause/resume semantics. |
| background wrapper ↔ platform manager | direct API | Shared contract should stay close to existing `VirtualDisplayManager` shape. |
| CLI / nanobot ↔ backend builder | config objects | Hosts should receive the same capability errors and warnings. |

## Sources

- `.planning/PROJECT.md`
- `.planning/todos/pending/2026-03-20-background-gui-execution-with-user-intervention-handoff.md`
- Existing v1.1 architecture in `BackgroundDesktopBackend` and virtual-display planning artifacts

---
*Architecture research for: cross-platform background GUI automation*
*Researched: 2026-03-20*
