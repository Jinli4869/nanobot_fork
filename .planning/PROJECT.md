# OpenGUI

## What This Is

OpenGUI is a portable GUI subagent package that automates Android and desktop environments through a vision-action loop, while nanobot remains the primary host shell that exposes those capabilities to end users. With v1.5, the codebase now has a two-layer shortcut/task skill architecture; v1.6 focuses on turning that architecture into a stable production shortcut system that can extract reusable shortcuts from traces, decide when they are safe to use, and execute them reliably.

## Core Value

Any host agent can spawn a GUI subagent to complete device tasks autonomously, while accumulating reusable skills and execution history over time.

## Current State

- **Shipped through:** v1.6 Phase 29 Shortcut Retrieval and Applicability Routing
- **Core surfaces:** Android ADB backend, DryRun backend, local desktop backend, iOS WDA backend, HarmonyOS HDC backend, standalone CLI, nanobot GUI tool integration
- **Shortcut architecture status:** Phase 24 shipped `ShortcutSkill`, `TaskSkill`, and grounding contracts; Phase 25 shipped multi-layer executors; Phases 26-27 shipped quality-gated primitives plus versioned stores and unified search; Phase 28 shipped production trace-backed shortcut promotion with provenance, gates, and merge/version handling; Phase 29 shipped multi-candidate retrieval with app/platform filtering and screen-aware applicability evaluation (`shortcut_router.py`, `_retrieve_shortcut_candidates`, `_evaluate_shortcut_applicability`)
- **Current production gap:** Retrieval and applicability routing are now live; the remaining v1.6 gap is stable shortcut execution with live target binding, post-step settle/verification, and safe fallback
- **Reference direction for v1.6:** AppAgentX demonstrates screen-aware shortcut applicability evaluation and template generation from live context; Mobile-Agent-v3.5 reinforces action/observation discipline so shortcut execution stays stable instead of brittle

## Current Milestone: v1.6 Shortcut Extraction and Stable Execution

**Goal:** Turn the shipped shortcut architecture into a stable production path by extracting trustworthy shortcuts from traces, selecting them with screen-aware applicability checks, and executing them with live binding, settle/verification guards, and safe fallback behavior.

**Target features:**
- Production trace-to-shortcut promotion into `ShortcutSkillStore` with explicit quality gates, provenance, and duplicate/version handling
- Screen-aware shortcut retrieval and applicability evaluation before shortcut execution
- Stable shortcut execution with live target binding, post-step settle/verification, and clean fallback to non-shortcut flows
- Shortcut telemetry and regression coverage so unstable shortcuts can be diagnosed and pruned

## Previous Milestone: v1.5 New OpenGUI Skills Architecture (Completed)

**Goal:** Replace the flat single-layer skill system with a two-layer tree architecture: a shortcut layer (verifiable macro actions with typed contracts and parameter slots) and a task-level layer (shortcut composition with ATOM fallbacks and conditional branches), backed by a pluggable grounding protocol, a quality-gated extraction pipeline, and separate layer-aware skill stores.

**Target features:**
- Two-layer skill schema: `ShortcutSkill` and `TaskSkill`
- `GrounderProtocol` interface with `LLMGrounder` implementation
- Multi-layer execution engine: `ShortcutExecutor` and `TaskSkillExecutor`
- Quality-gated extraction primitives and separate versioned stores
- Unified search plus GuiAgent integration across both layers

## Requirements

### Validated

- ✓ **CORE-01**: Protocol-based architecture (`LLMProvider` + `DeviceBackend`) - P0
- ✓ **CORE-02**: Action dataclass with `[0,999]` relative coordinates and alias support - P0
- ✓ **CORE-03**: ADB backend for Android automation - P0
- ✓ **CORE-04**: DryRun backend for testing - P0
- ✓ **CORE-05**: GuiAgent vision-action loop with Mobile-Agent-style prompting - P0
- ✓ **CORE-06**: History window with sliding image context and older-step summaries - P0
- ✓ **P1-01**: Memory, skills, and trajectory subsystems - v1.0
- ✓ **P1-02**: Agent loop integration with memory, skills, and trajectory - v1.0
- ✓ **P1-03**: Nanobot subagent integration path - v1.0
- ✓ **P1-04**: Desktop backend for macOS/Linux/Windows foreground execution - v1.0
- ✓ **P1-05**: Standalone CLI entry point - v1.0
- ✓ **P1-06**: Cross-phase wiring and dead export cleanup - v1.0
- ✓ **P1-07**: Virtual display protocol and Linux Xvfb implementation - v1.1
- ✓ **P1-08**: Background desktop backend wrapper with lifecycle safety - v1.1
- ✓ **P1-09**: CLI and nanobot background execution integration with CI-safe tests - v1.1
- ✓ **BGND-05**: Background runtime probes isolated support before any desktop background run starts - v1.2 Phase 12
- ✓ **BGND-06**: Background runtime reports isolated, fallback, or blocked mode before automation begins - v1.2 Phase 12
- ✓ **BGND-07**: Overlapping background desktop runs serialize with explicit busy metadata - v1.2 Phase 12
- ✓ **CAP-01**: Planner sees a compact summary of currently available GUI, tool, shell/exec, and MCP routes - v1.4 Phase 21
- ✓ **CAP-02**: Planner context can include routing-relevant memory hints without dumping unrelated memory - v1.4 Phase 21
- ✓ **CAP-03**: Router can execute `tool` plan nodes through real dispatch instead of placeholder-only success responses - v1.4 Phase 22
- ✓ **CAP-04**: Router can execute `mcp` plan nodes through real dispatch with route validation and fallback behavior - v1.4 Phase 22
- ✓ **SCHEMA-01**: Shortcut skill defines structured pre/post condition descriptors - v1.5 Phase 24
- ✓ **SCHEMA-02**: Shortcut skill declares typed parameter slots for runtime grounding - v1.5 Phase 24
- ✓ **SCHEMA-03**: Task-level skill references shortcut skills by ID with parameter bindings - v1.5 Phase 24
- ✓ **SCHEMA-04**: Task-level skill supports inline ATOM fallback steps - v1.5 Phase 24
- ✓ **SCHEMA-05**: Task-level skill supports conditional branch nodes with structured conditions - v1.5 Phase 24
- ✓ **SCHEMA-06**: Task-level skill carries an optional app-memory context pointer - v1.5 Phase 24
- ✓ **GRND-01**: `GrounderProtocol` defines the common async grounding interface - v1.5 Phase 24
- ✓ **GRND-02**: `LLMGrounder` implements the pluggable grounding protocol - v1.5 Phase 24
- ✓ **GRND-03**: Grounding results expose grounder identity, confidence, and fallback metadata - v1.5 Phase 24
- ✓ **EXEC-01**: `ShortcutExecutor` verifies pre/post contracts at each step boundary and reports violations - v1.5 Phase 25
- ✓ **EXEC-02**: `TaskSkillExecutor` resolves shortcut references, executes ATOM fallback steps, and evaluates conditional branches - v1.5 Phase 25
- ✓ **EXEC-03**: Both executors route all action parameter resolution through `GrounderProtocol` - v1.5 Phase 25
- ✓ **EXTR-01..04**: Quality-gated extraction primitives, pipeline, and shortcut-skill production - v1.5 Phase 26
- ✓ **STOR-01**: Shortcut skills and task-level skills persist in separate, versioned JSON stores - v1.5 Phase 27
- ✓ **STOR-02**: Unified search covers shortcut and task skill layers with layer-aware scoring - v1.5 Phase 27
- ✓ **INTEG-01**: GuiAgent searches both skill layers during pre-task lookup and selects the best match - v1.5 Phase 27
- ✓ **INTEG-02**: GuiAgent injects referenced app memory context before execution when a task skill points to stored memory - v1.5 Phase 27
- ✓ **SXTR-01..04**: Production shortcut promotion now uses trace-backed step filtering, persisted provenance, explicit quality gates, and duplicate/version handling - v1.6 Phase 28

### Active

- [ ] Shortcut reuse includes screen-aware applicability checks before execution
- [ ] Shortcut runtime execution is stabilized with live binding, settle/verification, and safe fallback
- [ ] Shortcut health is diagnosable through telemetry and regression coverage

### Out of Scope

- Neo4j / Pinecone or other new infrastructure as a prerequisite for v1.6
- Full orchestration-layer skills before shortcut extraction and execution are stable
- OmniParser-first runtime rewrite before the current grounding path is fully exercised
- Manual human review for every shortcut promotion in the default path

## Context

- **Brownfield status:** The codebase now includes shipped P0, v1.0-v1.5 functionality, including the new shortcut/task architecture and unified search.
- **Host integration:** nanobot remains the primary host-agent target; the OpenGUI core loop should stay reusable across host surfaces.
- **Testing posture:** Background and cross-platform execution paths should remain CI-safe by mocking subprocess/device boundaries instead of depending on live displays.
- **Milestone framing:** v1.6 is not about inventing more shortcut schema; it is about closing the production gap between the shipped architecture and the live GUI task path.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Protocol-based boundaries between host and GUI agent | Keep OpenGUI reusable across host agents | ✓ Good |
| Mobile-Agent-style prompting | Proven prompt structure for GUI action loops | ✓ Good |
| `[0,999]` relative coordinates | Preserve resolution portability | ✓ Good |
| JSON storage before graph or SQL migration | Lower complexity at current scale | ✓ Good |
| Three-layer skills tree: shortcut -> task-level -> orchestration (v1.5 built shortcut + task-level) | Current flat SkillStep list had no composition semantics, no typed contracts, and no quality gate | ✓ Good |
| v1.6 should finish the shipped shortcut architecture instead of creating a parallel one | The repo already has shortcut/task schemas, stores, search, and executors; the missing part is production-path adoption | ✓ Good |
| Shortcut selection must check current-screen applicability, not just retrieval score | Search relevance alone is not a safe execution signal | - Pending |
| Shortcut execution must re-bind live targets and verify post-step state | Replay-only shortcuts are too brittle across UI drift and timing changes | - Pending |

## Constraints

- OpenGUI must not import nanobot or claw internals directly.
- Existing CLI, nanobot, and background-execution flows must keep working while shortcut productionization lands.
- V1.6 must preserve a safe non-shortcut fallback path for any task where shortcut reuse is unsafe.
- The milestone should not require Neo4j, Pinecone, OmniParser, or cloud-only services to become usable.
- Shortcut stability should rely on observable contracts and logs, not opaque one-shot LLM guesses.

---
*Last updated: 2026-04-03 after completing Phase 28 of milestone v1.6 Shortcut Extraction and Stable Execution*
