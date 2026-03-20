# OpenGUI

## What This Is

A portable, zero-dependency GUI SubAgent package (`opengui`) that automates Android and desktop devices through vision-action loops. It plugs into any host agent (nanobot, openclaw, nanoclaw, zeroclaw) via two protocols (`LLMProvider` + `DeviceBackend`), bringing skills, memory, and trajectory recording as an independent subsystem.

## Core Value

Any host agent can spawn a GUI subagent to complete device tasks autonomously — with reusable skills that improve over time through trajectory extraction.

## Requirements

### Validated

- ✓ **CORE-01**: Protocol-based architecture (LLMProvider + DeviceBackend) — P0
- ✓ **CORE-02**: Action dataclass with [0,999] relative coordinates and alias support — P0
- ✓ **CORE-03**: ADB backend for Android automation (screencap, tap, swipe, scroll, text input) — P0
- ✓ **CORE-04**: DryRun backend for testing — P0
- ✓ **CORE-05**: GuiAgent vision-action loop with Mobile-Agent-style prompting — P0
- ✓ **CORE-06**: History window with sliding image context + text summaries for older steps — P0
- ✓ **P1-01**: Memory (FAISS+BM25), skills (library+extractor+executor), trajectory (recorder+summarizer) — v1.0
- ✓ **P1-02**: Agent loop integration with memory/skills/trajectory — v1.0
- ✓ **P1-03**: Nanobot subagent (GuiSubagentTool + adapters) — v1.0
- ✓ **P1-04**: Desktop backend (pyautogui + pyperclip for macOS/Linux/Windows) — v1.0
- ✓ **P1-05**: Standalone CLI entry point — v1.0
- ✓ **P1-06**: Integration wiring, dead export cleanup — v1.0

### Active

- ✓ **VDISP-01–04**: VirtualDisplayManager protocol, DisplayInfo, NoOpDisplayManager, XvfbDisplayManager — Validated in Phase 9
- ✓ **BGND-01–04**: BackgroundDesktopBackend decorator with lifecycle guards, DISPLAY management, coordinate offsets, idempotent shutdown — Validated in Phase 10
- [ ] CLI --background flag and GuiConfig.background integration
- [ ] macOS CGVirtualDisplay implementation (deferred to v1.2)
- [ ] Windows CreateDesktop implementation (deferred to v1.2)
- [ ] Intervention detection and user handoff (deferred to v1.2)

### Out of Scope

- Multi-action batching per turn — single-step single-tool-call only
- Human-in-the-loop interactive prompts during agent execution
- XML `<tool_call>` parsing — OpenAI-compatible native tool calls only
- Local embedding models (SentenceTransformer) — use external API via EmbeddingProvider
- SQLite storage — JSON files sufficient for current scale
- Multi-stage vision grounding (UITARS/Phi-V) — single LLM approach for now

## Current Milestone: v1.1 Background Execution

**Goal:** Enable GUI automation to run in the background on a virtual display, freeing the user's screen.

**Target features:**
- VirtualDisplayManager protocol with DisplayInfo data type
- Linux Xvfb implementation (production-ready, CI-testable)
- BackgroundDesktopBackend decorator pattern (wraps any DeviceBackend)
- CLI `--background` flag and nanobot GuiConfig.background integration
- Full test suite with mocked subprocess (no real Xvfb needed in CI)

## Context

- **Brownfield**: opengui/ has complete P0+P1 code with 29+ passing tests
- **Reference projects**: KnowAct (skill lifecycle + memory layers), CUA-Skill (parameter grounding), Mobile-Agent-v3.5 (prompt patterns)
- **Host agent**: nanobot is the primary integration target (layered agent-bus-channel architecture with tool registry)
- **v1.0 complete**: All 8 phases shipped — core, tests, agent loop, subagent, desktop backend, CLI, wiring fixes, cleanup
- **Background research**: Xvfb (Linux), CGVirtualDisplay (macOS 13+), CreateDesktop (Windows), ADB naturally background

## Constraints

- **Zero host dependency**: opengui must not import any nanobot/claw code; only Protocol interfaces
- **Embedding API**: External embedding (qwen3-vl-embedding via DashScope) through EmbeddingProvider protocol
- **FAISS required**: Embedding similarity search uses faiss-cpu, not pure Python cosine
- **KnowAct patterns**: Skill lifecycle follows extraction→library→retrieval→execution→validation with dedup/merge and per-step valid_state verification
- **JSON storage**: Memory and skill persistence via JSON files (not SQLite)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Protocol-based (LLMProvider + DeviceBackend) | Zero coupling to any host agent | ✓ Good |
| Mobile-Agent-style prompting | Proven prompt structure from Mobile-Agent-v3.5 | ✓ Good |
| [0,999] relative coordinates | Cross-resolution portability | ✓ Good |
| FAISS for embedding similarity | User requirement for production-grade vector search | — Pending |
| JSON storage over SQLite | Simplicity and portability for current scale | — Pending |
| Single LLM (no vision grounding) | Simpler pipeline, fewer dependencies | — Pending |
| EmbeddingProvider as protocol | Pluggable: qwen3-vl-embedding or any future provider | — Pending |
| KnowAct-style valid_state per step | LLM-based screen verification before each skill step | — Pending |

| Decorator pattern for BackgroundDesktopBackend | Thin wrapper + DISPLAY env var; sentinel-based save/restore | ✓ Good |
| Xvfb subprocess management | No Python deps; invoke Xvfb binary via asyncio.subprocess | — Pending |

---
*Last updated: 2026-03-20 after Phase 10 (background-backend-wrapper) complete*
