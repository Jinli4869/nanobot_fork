# OpenGUI

## What This Is

OpenGUI is a portable GUI subagent package that automates Android and desktop environments through a vision-action loop, while nanobot remains the primary host shell that exposes those capabilities to end users. The next milestone extends that host experience with a browser-based workspace so chat and GUI orchestration can run from a local web app instead of a terminal-only surface.

## Core Value

Any host agent can spawn a GUI subagent to complete device tasks autonomously, while accumulating reusable skills and execution history over time.

## Current State

- **Shipped through:** v1.4 Capability-Aware Planning And Routing
- **Core surfaces:** Android ADB backend, DryRun backend, local desktop backend, standalone CLI, nanobot GUI tool integration
- **Background execution:** Linux background desktop automation is supported through `XvfbDisplayManager` and `BackgroundDesktopBackend`
- **Runtime contracts:** Phase 12 adds shared probe, mode-resolution, and process-wide serialization contracts for background execution
- **Verification state:** v1.5 Phases 24-27 are complete, including storage/search persistence and GuiAgent two-layer skill integration
- **Accepted debt:** v1.1 shipped with audit-only traceability gaps in `11-02-SUMMARY.md` and partial Nyquist validation for phases 10 and 11
- **Planner status:** Phase 21 added a live route catalog plus bounded routing-memory hints; Phase 22 completed real route-aware `tool` and `mcp` dispatch with fallback chains and observability logging
- **Skills architecture status:** Phase 24 established `ShortcutSkill`, `TaskSkill`, and the import-safe `GrounderProtocol` / `LLMGrounder` contract layer; Phase 25 added `ShortcutExecutor` with contract verification and `TaskSkillExecutor` with same-node fallback traversal; Phases 26-27 now add quality-gated extraction, separate versioned stores, unified search, and live GuiAgent integration

## Current Milestone: v1.5 New OpenGUI Skills Architecture

**Goal:** Replace the flat single-layer skill system with a two-layer tree architecture: a shortcut layer (verifiable macro actions with typed contracts and parameter slots) and a task-level layer (shortcut composition with ATOM fallbacks and conditional branches), backed by a pluggable grounding protocol, a quality-gated extraction pipeline with step-level and trajectory-level critics, and separate layer-aware skill stores.

**Target features:**
- Two-layer skill schema: ShortcutSkill (typed pre/post contracts, parameter slots) and TaskSkill (shortcut refs + ATOM steps + branches + memory context pointer)
- GrounderProtocol interface with LLMGrounder implementation, enabling pluggable target resolution
- Multi-layer execution engine: ShortcutExecutor and TaskSkillExecutor with contract verification
- Quality-gated extraction: step-level critic + trajectory-level critic before any skill is promoted
- Separate versioned JSON stores for shortcut and task-level layers, unified hybrid search
- GuiAgent integration searching both layers with app memory context injection

## Previous Milestone: v1.4 Capability-Aware Planning And Routing (Completed)

**Goal:** Make nanobot planning and execution capability-aware so route selection can prefer shell/tool/MCP paths when they are more appropriate than GUI automation.

**Target features:**
- Compact planner-time capability catalog built from the live tool registry and MCP inventory
- Memory-derived routing hints so previous successful routes influence future planning
- Route-aware router execution for `tool` and `mcp` nodes instead of placeholder-only dispatch

## Requirements

### Validated

- ✓ **CORE-01**: Protocol-based architecture (`LLMProvider` + `DeviceBackend`) — P0
- ✓ **CORE-02**: Action dataclass with `[0,999]` relative coordinates and alias support — P0
- ✓ **CORE-03**: ADB backend for Android automation — P0
- ✓ **CORE-04**: DryRun backend for testing — P0
- ✓ **CORE-05**: GuiAgent vision-action loop with Mobile-Agent-style prompting — P0
- ✓ **CORE-06**: History window with sliding image context and older-step summaries — P0
- ✓ **P1-01**: Memory, skills, and trajectory subsystems — v1.0
- ✓ **P1-02**: Agent loop integration with memory, skills, and trajectory — v1.0
- ✓ **P1-03**: Nanobot subagent integration path — v1.0
- ✓ **P1-04**: Desktop backend for macOS/Linux/Windows foreground execution — v1.0
- ✓ **P1-05**: Standalone CLI entry point — v1.0
- ✓ **P1-06**: Cross-phase wiring and dead export cleanup — v1.0
- ✓ **P1-07**: Virtual display protocol and Linux Xvfb implementation — v1.1
- ✓ **P1-08**: Background desktop backend wrapper with lifecycle safety — v1.1
- ✓ **P1-09**: CLI and nanobot background execution integration with CI-safe tests — v1.1
- ✓ **BGND-05**: Background runtime probes isolated support before any desktop background run starts — v1.2 Phase 12
- ✓ **BGND-06**: Background runtime reports isolated, fallback, or blocked mode before automation begins — v1.2 Phase 12
- ✓ **BGND-07**: Overlapping background desktop runs serialize with explicit busy metadata — v1.2 Phase 12
- ✓ **CAP-01**: Planner sees a compact summary of currently available GUI, tool, shell/exec, and MCP routes — v1.4 Phase 21
- ✓ **CAP-02**: Planner context can include routing-relevant memory hints without dumping unrelated memory — v1.4 Phase 21
- ✓ **CAP-03**: Router can execute `tool` plan nodes through real dispatch instead of placeholder-only success responses — v1.4 Phase 22
- ✓ **CAP-04**: Router can execute `mcp` plan nodes through real dispatch with route validation and fallback behavior — v1.4 Phase 22
- ✓ **SCHEMA-01**: Shortcut skill defines structured pre/post condition descriptors — v1.5 Phase 24
- ✓ **SCHEMA-02**: Shortcut skill declares typed parameter slots for runtime grounding — v1.5 Phase 24
- ✓ **SCHEMA-03**: Task-level skill references shortcut skills by ID with parameter bindings — v1.5 Phase 24
- ✓ **SCHEMA-04**: Task-level skill supports inline ATOM fallback steps — v1.5 Phase 24
- ✓ **SCHEMA-05**: Task-level skill supports conditional branch nodes with structured conditions — v1.5 Phase 24
- ✓ **SCHEMA-06**: Task-level skill carries an optional app-memory context pointer — v1.5 Phase 24
- ✓ **GRND-01**: GrounderProtocol defines the common async grounding interface — v1.5 Phase 24
- ✓ **GRND-02**: LLMGrounder implements the pluggable grounding protocol — v1.5 Phase 24
- ✓ **GRND-03**: Grounding results expose grounder identity, confidence, and fallback metadata — v1.5 Phase 24
- ✓ **EXTR-01..04**: Quality-gated extraction primitives, pipeline, and shortcut-skill production — Validated in Phase 26: quality-gated-extraction
- ✓ **STOR-01**: Shortcut skills and task-level skills persist in separate, versioned JSON stores — Validated in Phase 27: storage-search-agent-integration
- ✓ **STOR-02**: Unified search covers shortcut and task skill layers with layer-aware scoring — Validated in Phase 27: storage-search-agent-integration
- ✓ **INTEG-01**: GuiAgent searches both skill layers during pre-task lookup and selects the best match — Validated in Phase 27: storage-search-agent-integration
- ✓ **INTEG-02**: GuiAgent injects referenced app memory context before execution when a task skill points to stored memory — Validated in Phase 27: storage-search-agent-integration

### Active

- ✓ ShortcutExecutor and TaskSkillExecutor with contract verification — Validated in Phase 25: multi-layer-execution
- ✓ v1.5 New OpenGUI Skills Architecture milestone complete — Validated in Phase 27: storage-search-agent-integration

### Out of Scope

- Multi-action batching per turn
- Human-in-the-loop prompts during the standard agent loop
- XML `<tool_call>` parsing
- Local embedding models in the default path
- SQLite persistence before JSON storage becomes a real bottleneck
- Multi-stage vision grounding before the single-LLM path is exhausted

## Context

- **Brownfield status:** The codebase now includes shipped P0, v1.0, and v1.1 functionality.
- **Host integration:** nanobot remains the primary host-agent target.
- **Testing posture:** Background execution paths are designed to be CI-safe by mocking subprocess boundaries instead of requiring real Xvfb.
- **Deferred platform work:** Linux is production-ready for background execution; v1.2 closes the remaining macOS and Windows platform gap before broader host-surface expansion.
- **Web milestone framing:** v1.3 is intentionally host-surface work, not a rewrite of the OpenGUI core loop.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Protocol-based boundaries between host and GUI agent | Keep OpenGUI reusable across host agents | ✓ Good |
| Mobile-Agent-style prompting | Proven prompt structure for GUI action loops | ✓ Good |
| `[0,999]` relative coordinates | Preserve resolution portability | ✓ Good |
| FAISS-backed embedding similarity | Production-grade retrieval quality | — Pending |
| JSON storage before SQLite | Lower complexity at current scale | — Pending |
| Single-LLM control loop before separate grounding stage | Reduce dependency surface and pipeline complexity | — Pending |
| Background execution via virtual display abstraction | Keep Linux Xvfb, future macOS, and future Windows under one contract | ✓ Good |
| `BackgroundDesktopBackend` as a decorator wrapper | Reuse any existing backend without duplicating control logic | ✓ Good |
| Xvfb via `asyncio.subprocess` | No extra Python binding dependency, CI-friendly mocking boundary | ✓ Good |
| Shared runtime probe + resolved-mode contract | Keep CLI, nanobot, and future macOS/Windows flows on one capability vocabulary | ✓ Good |
| Process-wide runtime lease coordinator | Prevent overlapping background runs from corrupting global desktop state | ✓ Good |
| Keep the web stack under `nanobot/tui` | Minimize pollution of the existing nanobot and OpenGUI modules while adding a new surface area | ✓ Good |
| Use FastAPI + React + Vite for v1.3 | Match the desired local-first stack and keep backend/frontend responsibilities cleanly separated | ✓ Good |
| Planner should consume a compact live capability catalog instead of guessing from coarse labels alone | Improves capability selection without overwhelming the prompt with raw schema dumps | ✓ Good |
| Memory should contribute routing hints, not full conversational context, to planning | Reuses prior successful tool choices while keeping planner prompts focused and bounded | ✓ Good |
| Router should dispatch by explicit route identity, not only by coarse capability type | Makes tool and MCP routes executable and inspectable in logs/traces | ✓ Good |
| Three-layer skills tree: shortcut → task-level → orchestration (v1.5 builds shortcut + task-level) | Current flat SkillStep list has no composition semantics, no typed contracts, and no quality gate | — Pending |
| GrounderProtocol as pluggable interface (LLM/OmniParser/future) | Decouples skill definitions from grounding implementation; enables OmniParser and future grounders without schema changes | — Pending |
| Fresh start on skill data: old skills.json kept as reference, new stores start empty | Migration of brittle pixel-coordinate skills would import fragility; quality-gated re-extraction produces better seeds | — Pending |
| Both step-level and trajectory-level critics required before skill promotion | Mobile-Agent-v3 approach: filters bad steps and low-quality trajectories from being crystallized as reusable skills | ✓ Good |

## Constraints

- OpenGUI must not import nanobot or claw internals directly.
- Embedding remains external and protocol-driven.
- FAISS is still the intended similarity-search path when embeddings are enabled.
- Memory and skill persistence remain file-backed JSON/markdown stores for now.
- The web backend and frontend should live under `nanobot/tui` unless a smaller shared shim is clearly justified.
- Existing CLI, channel, and background-execution flows must keep working without requiring the web surface.
- The first web release is local-first and should default to localhost-safe behavior rather than assuming cloud hosting.

---
*Last updated: 2026-04-02 after completing Phase 27 Storage, Search, and Agent Integration*
