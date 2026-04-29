# Roadmap: OpenGUI

## Overview

OpenGUI has shipped five milestones so far: v1.0 established the reusable GUI subagent core, v1.1-v1.2 completed safe background execution across major desktop targets, v1.3 added a local-first nanobot web workspace, v1.4 made planning and routing capability-aware, and v1.5 shipped the new shortcut/task skill architecture. Milestone v1.6 turns that architecture into a stable production shortcut path, then closes the remaining production gaps around concise extraction, low-token validation, and reliable reuse.

## Milestones

- ✅ **v1.0 Core Foundations** - Phases 1-8 (shipped 2026-03-19)
- ✅ **v1.1 Background Execution** - Phases 9-11 (shipped 2026-03-20)
- ✅ **v1.2 Cross-Platform Background Execution** - Phases 12-16 (shipped 2026-03-21)
- ✅ **v1.3 Nanobot Web Workspace** - Phases 17-20 (shipped 2026-03-22)
- ✅ **v1.4 Capability-Aware Planning and Routing** - Phases 21-23 (shipped 2026-03-28)
- ✅ **v1.5 New OpenGUI Skills Architecture** - Phases 24-27 (shipped 2026-04-02)
- 🚧 **v1.6 Shortcut Extraction and Stable Execution** - Phases 28-33 (current)

## Completed Milestone: v1.5 New OpenGUI Skills Architecture

**Goal:** Replace the flat single-layer skill system with a two-layer tree architecture: a shortcut layer with typed contracts and parameter slots, and a task-level layer with shortcut composition, inline ATOM fallbacks, and conditional branches.

**Requirements:** 20 mapped / 20 total

| Phase | Name | Goal | Requirements | Success Criteria |
|-------|------|------|--------------|------------------|
| 24 | Schema and Grounding | Define typed shortcut/task contracts and pluggable grounding seams | SCHEMA-01..06, GRND-01..03 | 4 |
| 25 | Multi-layer Execution | Execute shortcut/task skills with contract verification and grounded parameter resolution | EXEC-01..03 | 4 |
| 26 | Quality-Gated Extraction | Build shortcut extraction critics and pipeline primitives | EXTR-01..04 | 4 |
| 27 | Storage, Search, and Agent Integration | Persist both layers and expose unified lookup in GuiAgent | STOR-01..02, INTEG-01..02 | 4 |

## Current Milestone: v1.6 Shortcut Extraction and Stable Execution

**Goal:** Turn the shipped shortcut architecture into a stable production path by extracting trustworthy shortcuts from traces, selecting them with screen-aware applicability checks, and executing them with live binding, low-token verification, and safe fallback behavior.

**Requirements:** 17 mapped / 17 total

| Phase | Name | Goal | Requirements | Success Criteria |
|-------|------|------|--------------|------------------|
| 28 | Shortcut Extraction Productionization | Replace legacy post-run extraction with trace-backed shortcut promotion into the new shortcut store, including gating, provenance, and merge/version behavior. | SXTR-01, SXTR-02, SXTR-03, SXTR-04 | 4 |
| 29 | 2/2 | Complete    | 2026-04-03 | 4 |
| 30 | 3/3 | Complete   | 2026-04-03 | 4 |
| 31 | 2/2 | Complete    | 2026-04-03 | 4 |
| 32 | 3/3 | Complete   | 2026-04-07 | 4 |
| 33 | Low-Token Applicability and Step-Scoped Validation | Match shortcuts once at entry, execute them with step-local validation, and keep reuse stable without paying avoidable token cost. | SUSE-03, SSTA-05, SSTA-06 | 4 |

### Phase 28: Shortcut Extraction Productionization

**Goal:** Replace the legacy post-run extraction path with trace-backed shortcut promotion into `ShortcutSkillStore`, including quality gates, provenance, and duplicate/version handling.
**Status:** Complete (2026-04-02)

**Depends on:** Phase 27
**Requirements:** SXTR-01, SXTR-02, SXTR-03, SXTR-04
**Plans:** 3/3 plans complete

Plans:
- [x] 28-01-PLAN.md - Cut over GUI postprocessing from legacy extraction to the new shortcut promotion pipeline
- [x] 28-02-PLAN.md - Add provenance, gating, and merge/version handling for promoted shortcuts
- [x] 28-03-PLAN.md - Lock the productionized extraction path with focused regression coverage

**Success Criteria** (what must be TRUE):
1. Successful GUI runs can promote shortcut candidates from trace step events directly into the new shortcut store without depending on the legacy `SkillLibrary` path.
2. Every stored shortcut includes normalized app/platform identity plus trace provenance and enough structured metadata for later applicability checks.
3. The promotion path rejects or merges low-value duplicate candidates instead of growing the store with repeated brittle shortcuts.
4. Regression tests prove malformed traces, summary/result noise, and low-quality candidates do not become promoted shortcuts.

### Phase 29: Shortcut Retrieval and Applicability Routing

**Goal:** Retrieve shortcut candidates for the current task and decide whether any shortcut is safe to execute on the live screen.

**Depends on:** Phase 28
**Requirements:** SUSE-01, SUSE-02
**Plans:** 2/2 plans complete

Plans:
- [ ] 29-01-PLAN.md - Build shortcut candidate retrieval using task plus current app/platform context
- [ ] 29-02-PLAN.md - Add screen-aware applicability evaluation and explicit "run / skip / fallback" decision logging

**Success Criteria** (what must be TRUE):
1. GuiAgent can retrieve shortcut candidates before the full loop using the current task and active app/platform context.
2. Shortcut execution is gated by an explicit applicability decision that checks the live screen, rather than relying on retrieval score alone.
3. Runs that do not have a safe shortcut continue through the normal path without regression.
4. Logs and trace artifacts show why a shortcut was selected, skipped, or rejected.

### Phase 30: Stable Shortcut Execution and Fallback

**Goal:** Execute selected shortcuts through live binding, settle/verification checks, and clean fallback to non-shortcut flows.

**Depends on:** Phase 29
**Requirements:** SUSE-03, SUSE-04, SSTA-01, SSTA-02
**Plans:** 3/3 plans complete

Plans:
- [x] 30-01-PLAN.md - Add live target/parameter binding for selected shortcuts in the runtime path
- [x] 30-02-PLAN.md - Add settle timing and post-step validation for each shortcut step
- [x] 30-03-PLAN.md - Implement safe fallback from shortcut drift back to task-level or default execution

**Success Criteria** (what must be TRUE):
1. Selected shortcuts bind live targets and parameters from the current observation instead of replaying stale recorded coordinates.
2. Each shortcut step waits for UI settle and performs a fresh observation before the next decision depends on the prior action.
3. Contract violations or drift produce structured failure signals and a recoverable fallback path when the task can still continue.
4. A failed shortcut never makes the task path worse than if shortcut reuse had been skipped entirely.

### Phase 31: Shortcut Observability and Regression Hardening

**Goal:** Make shortcut health diagnosable and prove the new path stays stable across representative execution seams.

**Depends on:** Phase 30
**Requirements:** SSTA-03, SSTA-04
**Plans:** 2/2 plans complete

Plans:
- [ ] 31-01-PLAN.md - Emit structured shortcut telemetry for selection, grounding, settle, validation, fallback, and outcome
- [ ] 31-02-PLAN.md - Add focused regression coverage for representative mobile and desktop shortcut flows

**Success Criteria** (what must be TRUE):
1. Shortcut-specific telemetry is present in logs or trace artifacts for every important decision and failure boundary.
2. Engineers can determine from artifacts why a shortcut was promoted, selected, skipped, failed, or fell back.
3. Focused regression coverage proves shortcut extraction/use is stable on representative mobile and desktop seams or CI-safe equivalents.
4. The milestone closes with enough evidence to trust shortcut behavior as a production optimization rather than an experimental side path.

### Phase 32: Prefix-Only Shortcut Extraction and Canonicalization

**Goal:** Make promoted shortcuts concise and reusable by extracting only the stable prefix of long GUI trajectories, removing redundant path noise, and parameterizing dynamic action arguments instead of freezing them into brittle recorded literals.
**Status:** Complete (2026-04-08)

**Depends on:** Phase 31
**Requirements:** SXTR-05, SXTR-06, SXTR-07
**Plans:** 3/3 plans complete

Plans:
- [x] 32-01-PLAN.md - Replace coarse long-horizon truncation with deterministic reusable-boundary extraction
- [x] 32-02-PLAN.md - Canonicalize replay noise before extraction so stored shortcuts stay concise
- [x] 32-03-PLAN.md - Widen placeholder emission and lock the cleaned promotion path with end-to-end regressions

**Success Criteria** (what must be TRUE):
1. Long-chain traces no longer promote full end-to-end task paths when only the prefix is reusable; stored shortcuts stop at the last stable reusable boundary.
2. Promoted shortcut steps are canonicalized so repeated/no-op path noise is removed and stored paths stay concise rather than replay-like.
3. Parameters that can be grounded at runtime are represented as placeholders/parameter slots instead of stale hard-coded values wherever that improves reuse stability.
4. Regression coverage proves long-trace extraction, prefix truncation, redundant-step removal, and placeholder emission behave deterministically on representative traces.

### Phase 33: Low-Token Applicability and Step-Scoped Validation

**Goal:** Make shortcut reuse cheaper and more reliable by separating one-time shortcut applicability checks from per-step validation, and by validating only the local state needed to keep execution on track.
**Status:** Pending gap-closure phase

**Depends on:** Phase 32
**Requirements:** SUSE-03, SSTA-05, SSTA-06
**Plans:** 0/0 plans complete

Planned focus:
- Evaluate shortcut-level preconditions once before execution instead of rechecking global contracts at every step
- Move runtime validation toward step-local `valid_state` / `expected_state` checks with a bounded verification policy
- Add low-token validation policy controls so reuse stays efficient on long or high-frequency shortcut runs

**Success Criteria** (what must be TRUE):
1. Shortcut-level applicability is evaluated once at entry using live screen evidence, and shortcuts that fail this gate are skipped before execution begins.
2. Runtime validation uses step-local state requirements rather than re-evaluating the full shortcut contract before and after every single step.
3. Verification policy keeps token usage bounded through deterministic skip rules, key-step validation, or other explicit budgeting controls without hiding drift.
4. Shortcut execution remains recoverable and observable when local validation fails, with telemetry explaining which checks ran, which were skipped, and why fallback happened.

## Phase Ordering Rationale

- **Phase 28 comes first** because the current production gap begins after a GUI run completes; until new shortcuts are actually promoted into the new store, later runtime work cannot learn from real traces.
- **Phase 29 isolates applicability routing** because retrieval and execution safety are different problems; splitting them avoids conflating search quality with runtime correctness.
- **Phase 30 focuses on execution stability** only after candidate selection is trustworthy, so runtime work can target the real execution path instead of hypothetical candidates.
- **Phase 31 closes with observability and regression hardening** because shortcut stability claims are only credible once the team can inspect and test them directly.
- **Phase 32 revisits extraction quality after productionization** because real traces revealed that some promoted shortcuts are still too long, too redundant, or too frozen to be dependable reusable units.
- **Phase 33 tightens runtime cost and validation scope** so the newly-concise shortcuts stay cheap enough to reuse frequently while still failing safely when screen state drifts.

## Research Flags

Phases likely needing deeper research during planning:
- **Phase 29:** If applicability evaluation needs a stronger structured prompt or heuristic contract than currently visible in the repo.
- **Phase 30:** If settle timing differs materially between desktop and mobile backends and needs backend-specific policy.

Phases with standard patterns (likely skip deeper research-phase):
- **Phase 28:** The codebase already exposes the main seams for productionizing extraction.
- **Phase 31:** Telemetry and regression hardening should follow established repo patterns once the runtime path is defined.

---
*Roadmap created: 2026-04-02*
*Current milestone: v1.6 Shortcut Extraction and Stable Execution*
