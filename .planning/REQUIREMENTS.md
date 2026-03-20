# Requirements: OpenGUI

**Defined:** 2026-03-20
**Core Value:** Any host agent can spawn a GUI subagent to complete device tasks autonomously.

## v1 Requirements

Requirements for milestone v1.2: Cross-Platform Background Execution.

### Background Runtime

- [x] **BGND-05**: User can start a background desktop run only after the runtime probes whether isolated execution is supported on the current host
- [x] **BGND-06**: User is told explicitly whether the run will be isolated, downgraded with warning, or blocked before automation begins
- [x] **BGND-07**: Background desktop execution rejects or serializes overlapping desktop background runs on the same host to avoid shared global-state interference

### macOS Background Execution

- [x] **MAC-01**: User can run desktop automation on macOS in an isolated background target when the OS version and permissions support it
- [x] **MAC-02**: User receives actionable remediation when macOS background execution cannot start because required permissions or platform capabilities are missing
- [ ] **MAC-03**: User actions on macOS isolated runs land on the correct target surface across display offsets and scale factors

### Windows Background Execution

- [ ] **WIN-01**: User can run desktop automation on Windows inside an alternate isolated desktop within the interactive user session
- [ ] **WIN-02**: User receives a clear warning or block when the Windows launch context or target app class cannot support isolated desktop execution
- [ ] **WIN-03**: Windows isolated-desktop resources are cleaned up on success, failure, and cancellation without leaving orphaned desktops or leaked handles

### Intervention and Handoff

- [ ] **SAFE-01**: Agent can request user intervention explicitly when it reaches a sensitive, blocked, or uncertain state
- [ ] **SAFE-02**: Background runs pause autonomous input and screenshot capture while waiting for user intervention
- [ ] **SAFE-03**: User can switch into the automation target, complete the manual step, and resume the run from a fresh observation
- [ ] **SAFE-04**: Intervention events are recorded with scrubbed trace data that does not leak sensitive input

### Host Integration and Verification

- [ ] **INTG-05**: CLI background execution exposes consistent configuration, capability messaging, and mode reporting for macOS and Windows
- [ ] **INTG-06**: Nanobot background execution exposes the same behavior and capability messaging as the CLI path
- [ ] **TEST-V12-01**: Regression coverage verifies capability handling, lifecycle cleanup, and intervention pause/resume behavior without regressing Linux Xvfb support

## v2 Requirements

### Notifications and Remote Operation

- **NOTIFY-01**: User can route intervention requests through pluggable notification transports beyond terminal output
- **NOTIFY-02**: Remote operators can acknowledge or resume intervention flows without direct local terminal access

### Expanded Background Surfaces

- **ANDROID-01**: Android runs can use the same intervention notification and resume semantics as desktop runs
- **OBS-01**: Operators can attach a live viewer or observer stream to a background run without taking foreground focus

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automatic password, payment, or OTP entry after intervention detection | Violates the milestone safety boundary and increases credential-handling risk |
| Full live VNC / remote viewer stack | Expands v1.2 into remote-observer infrastructure instead of background execution core |
| Universal guarantee for every Windows app class in hidden desktops | Rendering behavior varies by app class; v1.2 will ship capability checks and documented limits instead |
| Silent fallback from background mode to foreground execution | Breaks user trust; the runtime must report degraded behavior explicitly |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BGND-05 | Phase 12 | Complete |
| BGND-06 | Phase 12 | Complete |
| BGND-07 | Phase 12 | Complete |
| MAC-01 | Phase 13 | Complete |
| MAC-02 | Phase 13 | Complete |
| MAC-03 | Phase 13 | Pending |
| WIN-01 | Phase 14 | Pending |
| WIN-02 | Phase 14 | Pending |
| WIN-03 | Phase 14 | Pending |
| SAFE-01 | Phase 15 | Pending |
| SAFE-02 | Phase 15 | Pending |
| SAFE-03 | Phase 15 | Pending |
| SAFE-04 | Phase 15 | Pending |
| INTG-05 | Phase 16 | Pending |
| INTG-06 | Phase 16 | Pending |
| TEST-V12-01 | Phase 16 | Pending |

**Coverage:**
- v1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-20*
*Last updated: 2026-03-20 after Phase 12 completion*
