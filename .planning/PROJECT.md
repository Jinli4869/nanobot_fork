# OpenGUI

## What This Is

OpenGUI is a portable GUI subagent package that automates Android and desktop environments through a vision-action loop, while nanobot remains the primary host shell that exposes those capabilities to end users. The next milestone extends that host experience with a browser-based workspace so chat and GUI orchestration can run from a local web app instead of a terminal-only surface.

## Core Value

Any host agent can spawn a GUI subagent to complete device tasks autonomously, while accumulating reusable skills and execution history over time.

## Current State

- **Shipped through:** v1.1 Background Execution
- **Core surfaces:** Android ADB backend, DryRun backend, local desktop backend, standalone CLI, nanobot GUI tool integration
- **Background execution:** Linux background desktop automation is supported through `XvfbDisplayManager` and `BackgroundDesktopBackend`
- **Runtime contracts:** Phase 12 adds shared probe, mode-resolution, and process-wide serialization contracts for background execution
- **Verification state:** Milestone v1.2 implementation is in host-integration closeout while planning begins for the next host-facing surface
- **Accepted debt:** v1.1 shipped with audit-only traceability gaps in `11-02-SUMMARY.md` and partial Nyquist validation for phases 10 and 11

## Current Milestone: v1.3 Nanobot Web Workspace

**Goal:** Add a local-first web workspace for nanobot that combines browser chat and GUI operations while keeping the new FastAPI + React + Vite stack isolated under `nanobot/tui` and minimizing changes to the existing nanobot runtime.

**Target features:**
- Browser chat workspace with streaming replies, recent sessions, and recovery after refresh
- Operations console for launching and monitoring supported nanobot/OpenGUI tasks
- Thin FastAPI adapter layer and React/Vite frontend packaged under `nanobot/tui`

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

### Active

- [ ] Browser-based chat workspace for nanobot sessions
- [ ] Browser-based operations console for OpenGUI and runtime visibility
- [ ] FastAPI + React + Vite implementation isolated under `nanobot/tui`

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
| Keep the web stack under `nanobot/tui` | Minimize pollution of the existing nanobot and OpenGUI modules while adding a new surface area | — Pending |
| Use FastAPI + React + Vite for v1.3 | Match the desired local-first stack and keep backend/frontend responsibilities cleanly separated | — Pending |

## Constraints

- OpenGUI must not import nanobot or claw internals directly.
- Embedding remains external and protocol-driven.
- FAISS is still the intended similarity-search path when embeddings are enabled.
- Memory and skill persistence remain file-backed JSON/markdown stores for now.
- The web backend and frontend should live under `nanobot/tui` unless a smaller shared shim is clearly justified.
- Existing CLI, channel, and background-execution flows must keep working without requiring the web surface.
- The first web release is local-first and should default to localhost-safe behavior rather than assuming cloud hosting.

---
*Last updated: 2026-03-21 after starting milestone v1.3 planning*
