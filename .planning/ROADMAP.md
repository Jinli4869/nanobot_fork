# Roadmap: OpenGUI

## Overview

OpenGUI has shipped two milestones so far: v1.0 established the reusable GUI subagent core, and v1.1 added Linux background desktop execution through a virtual display abstraction and integration-safe wrappers. Milestone v1.2 extends that work into true cross-platform background execution and intervention-safe handoff.

## Milestones

- ✅ **v1.0 Core Foundations** — Phases 1-8 (shipped 2026-03-19)
- ✅ **v1.1 Background Execution** — Phases 9-11 (shipped 2026-03-20) — [Archive](/Users/jinli/Documents/Personal/nanobot_fork/.planning/milestones/v1.1-ROADMAP.md)
- ◆ **v1.2 Cross-Platform Background Execution** — Phases 12-16 (planned)

## Current Milestone: v1.2 Cross-Platform Background Execution

**Goal:** Extend background execution beyond Linux so macOS and Windows runs can execute off-screen with explicit capability checks and safe user-intervention handoff.

**Requirements:** 16 mapped / 16 total

| Phase | Name | Goal | Requirements | Success Criteria |
|-------|------|------|--------------|------------------|
| 12 | Background Runtime Contracts | Harden shared background-runtime seams before adding new platform implementations | BGND-05, BGND-06, BGND-07 | 4 |
| 13 | macOS Background Execution | Add isolated macOS execution with permission-aware capability checks and correct geometry routing | MAC-01, MAC-02, MAC-03 | 4 |
| 14 | Windows Isolated Desktop Execution | Add Windows isolated-desktop execution with lifecycle-safe cleanup and clear support limits | WIN-01, WIN-02, WIN-03 | 4 |
| 15 | Intervention Safety and Handoff | Pause safely for sensitive/blocked states, hand control to the user, and resume from fresh observation | SAFE-01, SAFE-02, SAFE-03, SAFE-04 | 5 |
| 16 | Host Integration and Verification | Align CLI and nanobot behavior and close the milestone with regression coverage | INTG-05, INTG-06, TEST-V12-01 | 4 |

## Phase Details

### Phase 12: Background Runtime Contracts

**Goal:** The shared background-execution runtime can determine whether a host supports isolated execution, expose that mode decision clearly, and prevent overlapping desktop runs from corrupting process-global state.

**Depends on:** Phase 11
**Requirements:** BGND-05, BGND-06, BGND-07

**Success criteria:**
1. Background startup performs explicit capability checks before launching automation.
2. CLI/backend logs report whether a run is isolated, warned fallback, or blocked.
3. Shared runtime contracts are strong enough to support macOS and Windows without mutating Linux behavior.
4. Concurrent desktop background runs are rejected or serialized deterministically.

### Phase 13: macOS Background Execution

**Goal:** macOS background runs execute against an isolated target surface when supported, fail with actionable permission/capability messaging when not supported, and maintain correct coordinate routing across offsets and scale factors.

**Depends on:** Phase 12
**Requirements:** MAC-01, MAC-02, MAC-03

**Success criteria:**
1. Supported macOS environments can create and tear down an isolated background target for desktop automation.
2. Unsupported OS versions or missing permissions fail with actionable remediation instead of silent degradation.
3. Observe/execute paths target the same macOS background surface across display offsets and scale factors.
4. Linux background execution continues to behave exactly as before.

### Phase 14: Windows Isolated Desktop Execution

**Goal:** Windows background runs use an alternate isolated desktop inside the interactive session, advertise when the launch context or app class is unsupported, and always clean up desktop resources safely.

**Depends on:** Phase 12
**Requirements:** WIN-01, WIN-02, WIN-03

**Success criteria:**
1. Supported Windows runs launch automation inside an isolated desktop/session target.
2. Unsupported launch contexts or incompatible app classes are blocked or warned explicitly.
3. Cleanup closes isolated-desktop resources on success, failure, and cancellation.
4. Background-run traces expose enough metadata to diagnose target-surface ownership issues.

### Phase 15: Intervention Safety and Handoff

**Goal:** The agent can request intervention explicitly, pause autonomous behavior safely, hand the user into the automation target, and resume from a fresh observation with scrubbed trace data.

**Depends on:** Phases 13-14
**Requirements:** SAFE-01, SAFE-02, SAFE-03, SAFE-04

**Success criteria:**
1. Agent/runtime can emit an explicit intervention request for sensitive, blocked, or uncertain states.
2. Input execution and screenshot capture pause while intervention is pending.
3. User can enter the automation target, complete the manual step, and resume from a new observation.
4. Sensitive handoff events are recorded without leaking credential-like input.
5. Resume requires explicit confirmation instead of timing out back into automation.

### Phase 16: Host Integration and Verification

**Goal:** CLI and nanobot expose the same cross-platform background behavior, and the milestone closes with regression coverage for capability handling, lifecycle cleanup, and intervention flows.

**Depends on:** Phases 13-15
**Requirements:** INTG-05, INTG-06, TEST-V12-01

**Success criteria:**
1. CLI exposes macOS/Windows background configuration and mode messaging consistent with runtime behavior.
2. Nanobot integration exposes the same capability checks, warnings, and lifecycle semantics as CLI.
3. Regression tests cover capability handling, lifecycle cleanup, and intervention pause/resume without regressing Linux Xvfb support.
4. The milestone ends with a verification pass that shows all v1.2 requirements mapped and test-backed.

## Phase Ordering Rationale

- Phase 12 comes first because the current Linux wrapper is not sufficient by itself for macOS or Windows; the shared runtime contract must be hardened before platform-specific work begins.
- macOS and Windows are separate phases because they have different technical risks: macOS centers on permission and geometry routing, while Windows centers on interactive-session desktop ownership and cleanup.
- Intervention safety follows platform implementation so the handoff flow can use real background targets rather than speculative stubs.
- Host integration and verification are last so they exercise the final behavior rather than an intermediate abstraction.

## Archived Phase Ranges

- v1.0: Phases 1-8
- v1.1: Phases 9-11

## Progress

| Milestone | Phase Range | Status | Shipped |
|-----------|-------------|--------|---------|
| v1.0 Core Foundations | 1-8 | Complete | 2026-03-19 |
| v1.1 Background Execution | 9-11 | Complete | 2026-03-20 |
| v1.2 Cross-Platform Background Execution | 12-16 | Planned | — |

---
*Roadmap defined: 2026-03-20*
*Last updated: 2026-03-20 after v1.2 milestone planning*
