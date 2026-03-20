# Feature Research

**Domain:** Cross-platform background GUI automation
**Researched:** 2026-03-20
**Confidence:** MEDIUM

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| macOS background execution path | Linux background mode already shipped; users will expect parity on supported desktop OSes | HIGH | Must either create a real off-screen display or fail explicitly when permissions/API support are missing. |
| Windows background execution path | Cross-platform desktop automation feels incomplete without Windows support | HIGH | Hidden-desktop rendering differences mean capability checks must be part of the feature. |
| Safe intervention request action | Background automation needs a sanctioned way to pause for passwords, OTP, payment, or manual review | MEDIUM | The agent loop should surface this as an explicit action, not an implementation detail. |
| Foreground handoff and resume | A notification alone is not enough; users need a predictable way to enter and leave the automation context | MEDIUM | Resume must refresh observation state before continuing. |
| Clear platform fallback behavior | Users need to know whether a run is isolated, degraded to foreground, or blocked | LOW | Avoid silent fallback because it breaks trust. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Multi-layer intervention detection | Reduces unsafe autonomous actions and cuts false positives | MEDIUM | Combine model signaled intervention with deterministic policy gates. |
| Notification abstraction for local and remote operators | Makes background runs practical beyond a single interactive terminal | MEDIUM | Keep transport behind a protocol so CLI/nanobot can choose channels later. |
| Capability-aware handoff UX | Lets the same CLI / nanobot flow explain platform limitations cleanly | MEDIUM | Important on Windows where some app classes may not render in hidden desktops. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Automatic password / payment completion after intervention detection | Seems like a smoother user flow | Violates the milestone’s safety boundary and creates credential leakage risk | Require explicit user intervention and resume confirmation. |
| Full live remote viewing / VNC streaming in v1.2 | Sounds helpful for monitoring | Adds substantial infrastructure and testing scope unrelated to the core milestone | Defer to later milestone after basic handoff works. |
| Silent fallback from background to foreground | Feels convenient | Users lose trust when automation suddenly steals focus | Emit a visible warning or block the run with a capability error. |

## Feature Dependencies

```text
Platform background execution
    └──requires──> platform capability detection
                         └──requires──> explicit runtime errors / fallback policy

Intervention handoff
    └──requires──> request_intervention action
                         └──requires──> agent-loop pause/resume semantics

Notifications ──enhances──> intervention handoff

Silent fallback ──conflicts──> trustworthy background execution
```

### Dependency Notes

- **Platform background execution requires capability detection:** the backend has to know whether the OS/API/permissions make isolation possible before it starts.
- **Intervention handoff requires an explicit action type:** otherwise pause/resume becomes ad hoc logic scattered across the backend and agent loop.
- **Notifications enhance intervention handoff:** they are not the handoff itself, but they make background execution usable outside a watched terminal.
- **Silent fallback conflicts with trustworthy background execution:** if the product promises background mode, unannounced foreground execution is a behavioral regression.

## MVP Definition

### Launch With (v1)

- [ ] macOS background execution capability with explicit permission/capability checks — essential platform parity milestone goal
- [ ] Windows background execution capability with documented app-class limits — essential platform parity milestone goal
- [ ] `request_intervention` / equivalent pause-resume flow in the agent loop — required safety primitive
- [ ] Foreground handoff and resume path for desktop runs — required to make intervention usable
- [ ] Regression tests for lifecycle, fallbacks, and sensitive-state pauses — required to keep shipped Linux behavior stable

### Add After Validation (v1.x)

- [ ] Cross-platform desktop notification transports — add once the core handoff state machine is stable
- [ ] Android-specific intervention UX improvements — add once desktop handoff semantics are proven

### Future Consideration (v2+)

- [ ] Live observer / remote attach views — defer until background execution semantics are stable
- [ ] Rich intervention policy packs per app domain — defer until real usage shows recurring patterns

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| macOS isolated background execution | HIGH | HIGH | P1 |
| Windows isolated background execution | HIGH | HIGH | P1 |
| Intervention request + pause/resume | HIGH | MEDIUM | P1 |
| Foreground handoff UX | HIGH | MEDIUM | P1 |
| Notification abstraction | MEDIUM | MEDIUM | P2 |
| Android intervention parity | MEDIUM | MEDIUM | P2 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Competitor A | Competitor B | Our Approach |
|---------|--------------|--------------|--------------|
| Background desktop isolation | Browser/GUI testing stacks often use virtual displays or hidden sessions | Power-user desktop tools often rely on OS-specific isolation and warn about limits | Match the proven OS-native isolation model, but keep it behind the existing backend abstraction. |
| Human handoff | Many automation systems rely on manual pause buttons | Some RPA tools expose “attended” checkpoints | Make intervention a first-class model/backend signal rather than a separate operator-only workflow. |
| Fallback handling | Some tools silently degrade | Better tools explain capability gaps up front | Prefer explicit warnings or hard block over silent degradation. |

## Sources

- `.planning/todos/pending/2026-03-20-background-gui-execution-with-user-intervention-handoff.md`
- Existing OpenGUI milestone goals in `.planning/PROJECT.md`
- Windows desktop/session documentation and known hidden-desktop constraints

---
*Feature research for: cross-platform background GUI automation*
*Researched: 2026-03-20*
