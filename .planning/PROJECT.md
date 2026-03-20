# OpenGUI

## What This Is

OpenGUI is a portable GUI subagent package that automates Android and desktop environments through a vision-action loop. It is designed to plug into host agents such as nanobot through protocol boundaries rather than direct product coupling.

## Core Value

Any host agent can spawn a GUI subagent to complete device tasks autonomously, while accumulating reusable skills and execution history over time.

## Current State

- **Shipped through:** v1.1 Background Execution
- **Core surfaces:** Android ADB backend, DryRun backend, local desktop backend, standalone CLI, nanobot GUI tool integration
- **Background execution:** Linux background desktop automation is supported through `XvfbDisplayManager` and `BackgroundDesktopBackend`
- **Verification state:** Full regression suite passes at milestone close (`678 passed`)
- **Accepted debt:** v1.1 shipped with audit-only traceability gaps in `11-02-SUMMARY.md` and partial Nyquist validation for phases 10 and 11

## Next Milestone Goals

- macOS background execution via CGVirtualDisplay
- Windows background execution via CreateDesktop or equivalent desktop session isolation
- User-intervention detection and clean foreground handoff during background execution
- Refresh milestone-scoped requirements and roadmap before resuming implementation

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

### Active

- [ ] macOS CGVirtualDisplay support
- [ ] Windows background desktop isolation support
- [ ] Intervention detection and user handoff during background runs

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
- **Deferred platform work:** Linux is production-ready for background execution; macOS and Windows remain milestone candidates.

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

## Constraints

- OpenGUI must not import nanobot or claw internals directly.
- Embedding remains external and protocol-driven.
- FAISS is still the intended similarity-search path when embeddings are enabled.
- Memory and skill persistence remain file-backed JSON/markdown stores for now.

---
*Last updated: 2026-03-20 after v1.1 milestone completion*
