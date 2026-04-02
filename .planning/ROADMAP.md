# Roadmap: OpenGUI

## Overview

OpenGUI has shipped two milestones so far: v1.0 established the reusable GUI subagent core, and v1.1 added Linux background desktop execution through a virtual display abstraction and integration-safe wrappers. Milestone v1.2 closes the remaining cross-platform background-execution work, milestone v1.3 expands the nanobot host surface with an isolated local web workspace, and the next milestone v1.4 upgrades nanobot's planner and router to be capability-aware instead of GUI-biased by default.

## Milestones

- ✅ **v1.0 Core Foundations** — Phases 1-8 (shipped 2026-03-19)
- ✅ **v1.1 Background Execution** — Phases 9-11 (shipped 2026-03-20) — [Archive](/Users/jinli/Documents/Personal/nanobot_fork/.planning/milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Cross-Platform Background Execution** — Phases 12-16 (shipped 2026-03-21)
- ✅ **v1.3 Nanobot Web Workspace** — Phases 17-20 (shipped 2026-03-22)
- ✅ **v1.4 Capability-Aware Planning And Routing** — Phases 21-23 (shipped 2026-03-28)
- 🚧 **v1.5 New OpenGUI Skills Architecture** — Phases 24-27 (in progress)

## Completed Milestone: v1.3 Nanobot Web Workspace

**Goal:** Add a local-first browser workspace for nanobot that combines chat and operations in one app while keeping the new FastAPI + React + Vite stack isolated under `nanobot/tui`.

**Requirements:** 11 mapped / 11 total

| Phase | Name | Goal | Requirements | Success Criteria |
|-------|------|------|--------------|------------------|
| 17 | Web Runtime Boundary | Establish an isolated FastAPI service shell, local-first web runtime defaults, and adapter contracts under `nanobot/tui` without destabilizing existing nanobot or OpenGUI flows. | ISO-01, ISO-02 | 4 |
| 18 | Chat Workspace | Expose session-backed chat APIs and streaming updates so the browser can create, continue, and recover nanobot conversations. | CHAT-01, CHAT-02, CHAT-03 | 4 |
| 19 | Operations Console | Surface task launch, runtime status, and trace/log inspection for supported nanobot and OpenGUI workflows. | OPS-01, OPS-02, OPS-03 | 4 |
| 20 | Web App Integration and Verification | Deliver the React/Vite workspace shell, unify chat and operations navigation, and ship runnable entrypoints and regression coverage. | WEB-01, WEB-02, SHIP-01 | 4 |

## Phase Details

### Phase 17: Web Runtime Boundary

**Goal:** Establish an isolated FastAPI service shell, local-first web runtime defaults, and adapter contracts under `nanobot/tui` without destabilizing existing nanobot or OpenGUI flows.

**Depends on:** Phase 16
**Requirements:** ISO-01, ISO-02
**Plans:** 2/2 plans complete

Plans:
- [x] 17-01-PLAN.md — Define `nanobot/tui` package layout, FastAPI app shell, and shared adapter contracts
- [x] 17-02-PLAN.md — Add local-first config, startup wiring, and regression-safe integration seams

**Success criteria:**
1. Web backend code lives primarily under `nanobot/tui` with only thin shared shims elsewhere when truly necessary.
2. FastAPI startup, shutdown, and config loading can run without breaking the current CLI and channel entry points.
3. Local-first defaults bind safely and document the boundary between browser UI, web API, and existing runtime code.
4. Adapter contracts for chat, task launch, and runtime inspection are explicit enough to support the React app without deep imports.

### Phase 18: Chat Workspace

**Goal:** Expose session-backed chat APIs and streaming updates so the browser can create, continue, and recover nanobot conversations.

**Depends on:** Phase 17
**Requirements:** CHAT-01, CHAT-02, CHAT-03
**Plans:** 3/3 plans complete

Plans:
- [x] 18-01-PLAN.md — Reuse nanobot session state through chat-focused FastAPI endpoints
- [x] 18-02-PLAN.md — Add streaming transport for assistant output and progress events
- [x] 18-03-PLAN.md — Verify reconnect and session recovery behavior

**Success criteria:**
1. A browser user can start a new chat session and continue it without touching the terminal.
2. Assistant text and progress events stream incrementally into the web client instead of appearing only at the end.
3. Refreshing or reconnecting the page preserves recent session history from backend state.
4. Existing CLI chat behavior remains intact and testable.

### Phase 19: Operations Console

**Goal:** Surface task launch, runtime status, and trace/log inspection for supported nanobot and OpenGUI workflows.

**Depends on:** Phases 17-18
**Requirements:** OPS-01, OPS-02, OPS-03
**Plans:** 3/3 plans complete

Plans:
- [x] 19-01-PLAN.md — Define status and inspection endpoints for sessions, runs, and recent failures
- [x] 19-02-PLAN.md — Add web-triggerable task launch flows for supported nanobot and OpenGUI actions
- [x] 19-03-PLAN.md — Expose structured traces and logs with regression-safe filtering

**Success criteria:**
1. The browser can show current runtime state for sessions, background runs, and recent failures.
2. Users can launch supported tasks from the operations console with explicit, validated parameters.
3. Web-triggered runs expose logs or traces that are useful for diagnosis without requiring terminal access.
4. Sensitive or noisy internals stay filtered behind stable inspection contracts.

### Phase 20: Web App Integration and Verification

**Goal:** Deliver the React/Vite workspace shell, unify chat and operations navigation, and ship runnable entrypoints and regression coverage.

**Depends on:** Phases 18-19
**Requirements:** WEB-01, WEB-02, SHIP-01
**Plans:** 3/3 plans executed

Plans:
- [x] 20-01-PLAN.md — Build the React/Vite shell for chat and operations navigation
- [x] 20-02-PLAN.md — Wire the FastAPI static/dev bridge and typed frontend route integration
- [x] 20-03-PLAN.md — Preserve packaged startup seams, then add end-to-end smoke coverage and documentation

**Success criteria:**
1. A user can open a single web app and move between chat and operations without losing context.
2. The React/Vite frontend and FastAPI backend can run in development and packaged modes with documented commands.
3. Regression coverage proves the web surface works without regressing existing CLI-first behavior.
4. The milestone closes with a verification pass and manual smoke path for local browser usage.

## Completed Milestone: v1.4 Capability-Aware Planning And Routing

**Goal:** Upgrade nanobot planning and execution so mixed tasks can prefer live shell/tool/MCP routes when they are more appropriate than GUI automation, while retaining GUI as a reliable fallback.

**Requirements:** 5 mapped / 5 total

| Phase | Name | Goal | Requirements | Success Criteria |
|-------|------|------|--------------|------------------|
| 21 | Capability Catalog And Planner Context | Give the planner a compact live route inventory and routing-relevant memory hints so capability choice is grounded in real runtime options. | CAP-01, CAP-02 | 4 |
| 22 | 2/2 | Complete    | 2026-03-22 | 4 |
| 23 | Routing Memory Feedback And Verification | Learn from route outcomes and prove that mixed-capability tasks choose better routes than the current GUI-biased default. | CAP-05 | 4 |

### Phase 21: Capability Catalog And Planner Context

**Goal:** Give the planner a compact live route inventory and routing-relevant memory hints so capability choice is grounded in real runtime options.

**Depends on:** Phase 20
**Requirements:** CAP-01, CAP-02
**Plans:** 2/2 plans complete

Plans:
- [x] 21-01-PLAN.md — Build compact capability catalog summaries from ToolRegistry, MCP inventory, and host/runtime availability
- [x] 21-02-PLAN.md — Inject routing-relevant memory hints into planner context with prompt-size guardrails

**Success criteria:**
1. Planner receives a bounded catalog of currently available routes rather than only coarse capability labels.
2. Planner prompt includes routing-relevant memory summaries without dumping raw `memory.md` content.
3. Planned ATOM nodes can express route identity and fallback metadata in addition to capability type.
4. Planner logs expose both the human-readable tree and the chosen route metadata for inspection.

### Phase 22: Route-Aware Tool And MCP Dispatch

**Goal:** Turn `tool` and `mcp` plan nodes into real executable routes with validation, observability, and fallback behavior.

**Depends on:** Phase 21
**Requirements:** CAP-03, CAP-04
**Plans:** 2/2 plans complete

Plans:
- [ ] 22-01-PLAN.md — Add route resolver and replace placeholder _run_tool/_run_mcp with real ToolRegistry dispatch
- [ ] 22-02-PLAN.md — Implement fallback chain dispatch, GUI fallback delegation, and regression test updates

**Success criteria:**
1. Router can execute `tool` atoms through real local dispatch instead of placeholder success responses.
2. Router can execute `mcp` atoms through real route resolution and invocation logic.
3. Invalid or unavailable routes surface structured diagnostics and can fall back safely when the plan allows it.
4. Execution logs and traces show planned route, resolved route, and any fallback that occurred.

### Phase 23: Routing Memory Feedback And Verification

**Goal:** Learn from route outcomes and prove that mixed-capability tasks choose better routes than the current GUI-biased default.

**Depends on:** Phase 22
**Requirements:** CAP-05
**Plans:** 0/2 plans complete

Plans:
- [ ] 23-01-PLAN.md — Persist normalized route success and failure summaries as future planning hints
- [ ] 23-02-PLAN.md — Add verification coverage for representative mixed-capability tasks and route-quality outcomes

**Success criteria:**
1. Successful route selections produce reusable planning hints that can bias later planning decisions.
2. Failed routes record enough structured context to inform future fallbacks without poisoning unrelated tasks.
3. Mixed-capability regression scenarios demonstrate fewer unnecessary GUI choices on host-side operations.
4. The milestone closes with both automated verification and a manual sanity pass over representative planner outputs.

## Current Milestone: v1.5 New OpenGUI Skills Architecture

**Goal:** Replace the flat single-layer skill system with a two-layer tree architecture — shortcut layer (verifiable macro actions with typed contracts and parameter slots) and task-level layer (shortcut composition with ATOM fallbacks and conditional branches) — backed by a pluggable grounding protocol, a quality-gated extraction pipeline with step-level and trajectory-level critics, and separate layer-aware skill stores.

**Requirements:** 20 mapped / 20 total

| Phase | Name | Goal | Requirements | Success Criteria |
|-------|------|------|--------------|------------------|
| 24 | 3/3 | Complete    | 2026-04-02 | 4 |
| 25 | 2/2 | Complete    | 2026-04-02 | 4 |
| 26 | Quality-Gated Extraction | Complete    | 2026-04-02 | 4 |
| 27 | 2/2 | Complete    | 2026-04-02 | 4 |

### Phase 24: Schema and Grounding

**Goal:** Define the two-layer skill data models and the pluggable grounding protocol so all downstream execution and extraction have stable typed contracts to build against.

**Depends on:** Phase 23
**Requirements:** SCHEMA-01, SCHEMA-02, SCHEMA-03, SCHEMA-04, SCHEMA-05, SCHEMA-06, GRND-01, GRND-02, GRND-03
**Plans:** 3/3 plans complete

Plans:
- [x] 24-01-PLAN.md — Define shared schema primitives and the `ShortcutSkill` round-trip contract
- [x] 24-02-PLAN.md — Add the recursive `TaskSkill` node grammar with explicit tagged serialization
- [x] 24-03-PLAN.md — Add `GrounderProtocol`, `LLMGrounder`, and import-safe grounding contract coverage

**Success Criteria** (what must be TRUE):
1. A ShortcutSkill can be instantiated with structured pre/post condition descriptors, typed parameter slots, and validated round-trip through its serialization format.
2. A TaskSkill can be instantiated with shortcut references, inline ATOM fallback steps, conditional branch nodes, and an optional memory context pointer, and validated round-trip through its serialization format.
3. GrounderProtocol is importable as an abstract async interface, and LLMGrounder can be instantiated and invoked with a step target, returning a result that exposes grounder identity, confidence score, and fallback metadata.
4. Both skill schemas and the grounding protocol are free of circular imports with the existing opengui module tree and pass a type-check pass.

### Phase 25: Multi-layer Execution

**Goal:** Implement ShortcutExecutor and TaskSkillExecutor so shortcut-layer and task-level skills can execute with contract verification and grounded parameter resolution.

**Depends on:** Phase 24
**Requirements:** EXEC-01, EXEC-02, EXEC-03
**Plans:** 2/2 plans complete

Plans:
- [x] 25-01-PLAN.md — Add the new Phase 25 executor module, shortcut contract enforcement, and the shared grounding seam (completed 2026-04-02)
- [x] 25-02-PLAN.md — Implement task-skill traversal, explicit contiguous fallback semantics, and regression coverage

**Success Criteria** (what must be TRUE):
1. ShortcutExecutor runs a ShortcutSkill step-by-step, and a detectable pre/post contract violation at any boundary produces a structured violation report rather than a silent failure.
2. TaskSkillExecutor resolves a shortcut reference by ID, executes its steps, evaluates a conditional branch node by its condition expression, and falls back to an inline ATOM step when no shortcut reference is provided.
3. Both executors resolve all action parameter targets through the GrounderProtocol interface, so swapping LLMGrounder for a stub grounder changes grounding results without touching executor logic.
4. Executor behavior is testable in isolation with a stub backend and stub grounder, with no dependency on a live device or LLM call.

### Phase 26: Quality-Gated Extraction

**Goal:** Build the step-level and trajectory-level critics and the extraction pipeline that converts validated trajectories into shortcut-layer skill candidates.

**Depends on:** Phase 24
**Requirements:** EXTR-01, EXTR-02, EXTR-03, EXTR-04
**Plans:** 2/2 plans complete

Plans:
- [x] 26-01-PLAN.md — Define critic protocols, verdict/result dataclasses, and ShortcutSkillProducer
- [x] 26-02-PLAN.md — Add ExtractionPipeline orchestrator with critic sequencing and package exports

**Success Criteria** (what must be TRUE):
1. Step-level critic evaluates an individual trajectory step and returns a structured verdict (pass/fail with reason), and a trajectory containing a step that fails the critic is not passed to the trajectory-level critic.
2. Trajectory-level critic evaluates a complete trajectory and returns a structured verdict; a trajectory that fails is not promoted to the skill library.
3. Extraction pipeline ingests a validated trajectory, applies both critics in order, and only calls the skill candidate producer when both critics pass.
4. Extractor produces a well-formed ShortcutSkill candidate from a validated step sequence, with parameter slots inferred from the step targets and conditions mapped to pre/post descriptors.

### Phase 27: Storage, Search, and Agent Integration

**Goal:** Stand up the two separate versioned skill stores with unified hybrid search, then wire GuiAgent to search both layers and inject referenced app memory context.

**Depends on:** Phases 25-26
**Requirements:** STOR-01, STOR-02, INTEG-01, INTEG-02
**Plans:** 2/2 plans complete

Plans:
- [ ] 27-01-PLAN.md — Create versioned ShortcutSkillStore, TaskSkillStore, and UnifiedSkillSearch with hybrid BM25+FAISS search
- [ ] 27-02-PLAN.md — Wire GuiAgent two-layer skill lookup and memory context injection, update GuiSubagentTool wiring

**Success Criteria** (what must be TRUE):
1. ShortcutSkill and TaskSkill records persist to separate, versioned JSON files on disk; loading each store back produces the same typed objects that were saved.
2. A unified search call against both stores returns ranked results with layer-aware relevance scoring, so a query can surface shortcut-layer candidates alongside task-level candidates in one response.
3. GuiAgent performs a pre-task skill lookup against both stores and selects the highest-ranked match when one exceeds the relevance threshold, verifiable by inspecting the lookup log entry.
4. When GuiAgent selects a task-level skill that carries a memory context pointer, the referenced app memory context entry is injected into the execution context before the first skill step runs.

## Phase Ordering Rationale

- Phase 17 comes first because the web surface needs a clean boundary under `nanobot/tui` before any UI code or API growth begins.
- Chat comes before operations because browser chat is the narrowest host-facing vertical slice and reuses more existing session behavior.
- Operations follows once the web runtime and chat transport are stable enough to support broader task launch and inspection flows.
- Integration and verification are last so the React/Vite shell and packaged entrypoints validate the final contracts rather than an intermediate prototype.
- Phase 24 defines schemas and grounding first because executors, critics, and storage all depend on stable typed contracts; no downstream phase can be built without them.
- Phase 25 (execution) and Phase 26 (extraction) both depend on Phase 24 schemas but are independent of each other; extraction only needs the schema shapes, not a running executor.
- Phase 27 (storage and agent integration) closes last because it depends on both the executor outputs (Phase 25) and the extraction pipeline (Phase 26) to produce the skill records that storage must persist.

## Archived Phase Ranges

- v1.0: Phases 1-8
- v1.1: Phases 9-11

## Progress

| Milestone | Phase Range | Status | Shipped |
|-----------|-------------|--------|---------|
| v1.0 Core Foundations | 1-8 | Complete | 2026-03-19 |
| v1.1 Background Execution | 9-11 | Complete | 2026-03-20 |
| v1.2 Cross-Platform Background Execution | 12-16 | Closeout In Progress | — |
| v1.3 Nanobot Web Workspace | 17-20 | In Progress | — |
| v1.4 Capability-Aware Planning And Routing | 21-23 | Planned | — |
| v1.5 New OpenGUI Skills Architecture | 24-27 | Planned | — |

---
*Roadmap defined: 2026-03-21*
*Last updated: 2026-04-02 after planning Phase 27 storage, search, and agent integration (2 plans)*
