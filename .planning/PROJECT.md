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

### Active

- [ ] P1 modules: memory (FAISS+BM25), skills (library+extractor+executor with valid_state), trajectory (recorder+summarizer)
- [ ] P1 unit test coverage for all new modules
- [ ] Agent loop integration: wire memory/skills/trajectory into GuiAgent.run()
- [ ] Nanobot subagent: GuiSubagentTool + LLM adapter
- [ ] Desktop backend: pyautogui + pyperclip for macOS/Linux/Windows
- [ ] Standalone CLI entry point
- [ ] Other claw adapters (openclaw, nanoclaw, zeroclaw)

### Out of Scope

- Multi-action batching per turn — single-step single-tool-call only
- Human-in-the-loop interactive prompts during agent execution
- XML `<tool_call>` parsing — OpenAI-compatible native tool calls only
- Local embedding models (SentenceTransformer) — use external API via EmbeddingProvider
- SQLite storage — JSON files sufficient for current scale
- Multi-stage vision grounding (UITARS/Phi-V) — single LLM approach for now

## Context

- **Brownfield**: opengui/ already exists with P0 (core) and P1 (memory/skills/trajectory) code
- **Reference projects**: KnowAct (skill lifecycle + memory layers), CUA-Skill (parameter grounding), Mobile-Agent-v3.5 (prompt patterns)
- **Host agent**: nanobot is the primary integration target (layered agent-bus-channel architecture with tool registry)
- **P0 verified**: MockLLM → GuiAgent → DryRunBackend → trace.jsonl passes end-to-end
- **8 existing tests** pass; P1 modules need dedicated test coverage before integration

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

---
*Last updated: 2026-03-17 after project initialization*
