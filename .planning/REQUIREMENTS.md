# Requirements: OpenGUI

**Defined:** 2026-03-17
**Core Value:** Any host agent can spawn a GUI subagent with reusable skills that improve over time.

## v1 Requirements

### Core Agent

- [x] **AGENT-01**: GuiAgent runs vision-action loop with retry logic
- [x] **AGENT-02**: Mobile-Agent-style system prompt with `<tools>` XML + `Action:` prefix
- [x] **AGENT-03**: History window: recent screenshots as images, older steps as text summaries
- [ ] **AGENT-04**: GuiAgent.run() integrates memory retrieval into system prompt
- [ ] **AGENT-05**: GuiAgent.run() integrates skill search → execute matched skill or free explore
- [ ] **AGENT-06**: GuiAgent.run() records trajectory via TrajectoryRecorder

### Memory

- [x] **MEM-01**: MemoryEntry with 4 types (OS_GUIDE, APP_GUIDE, ICON_GUIDE, POLICY)
- [x] **MEM-02**: MemoryStore with JSON persistence and atomic writes
- [x] **MEM-03**: MemoryRetriever with BM25 + FAISS hybrid search
- [x] **MEM-04**: EmbeddingProvider protocol for external API (qwen3-vl-embedding)
- [ ] **MEM-05**: Memory context formatted and injected into system prompt

### Skills

- [x] **SKILL-01**: Skill + SkillStep dataclasses with valid_state field
- [x] **SKILL-02**: SkillLibrary with JSON storage organized by platform/app
- [x] **SKILL-03**: SkillLibrary hybrid search (BM25 + FAISS)
- [x] **SKILL-04**: SkillLibrary deduplication with multi-factor similarity + merge decisions
- [x] **SKILL-05**: SkillExtractor from successful and failed trajectories via LLM
- [x] **SKILL-06**: SkillExecutor with per-step valid_state verification
- [x] **SKILL-07**: LLMStateValidator for screenshot-based state checks
- [ ] **SKILL-08**: Skill execution integrated into agent loop (search → match → execute)

### Trajectory

- [x] **TRAJ-01**: TrajectoryRecorder with JSONL format and execution phase tracking
- [x] **TRAJ-02**: TrajectorySummarizer via LLM for natural language summaries
- [ ] **TRAJ-03**: Trajectory recording integrated into agent loop

### Backends

- [x] **BACK-01**: ADB backend for Android (screencap, tap, swipe, scroll, text input, CJK broadcast)
- [x] **BACK-02**: DryRun backend for testing
- [ ] **BACK-03**: LocalDesktop backend (pyautogui + pyperclip) for macOS/Linux/Windows

### Testing

- [x] **TEST-01**: P0 regression tests (8 tests passing)
- [ ] **TEST-02**: Unit tests for memory module (store, retrieval, types)
- [ ] **TEST-03**: Unit tests for skills module (library CRUD, search, dedup, executor, extractor)
- [ ] **TEST-04**: Unit tests for trajectory module (recorder events, summarizer)
- [ ] **TEST-05**: Integration test: full agent loop with DryRunBackend + mock LLM + memory + skills

### Nanobot Integration

- [ ] **NANO-01**: GuiSubagentTool registered in nanobot tool registry
- [ ] **NANO-02**: NanobotLLMAdapter wrapping nanobot's provider to opengui LLMProvider protocol
- [ ] **NANO-03**: Backend selection from nanobot config (adb/local/dry-run)
- [ ] **NANO-04**: Trajectory saved to nanobot workspace for later skill extraction
- [ ] **NANO-05**: Main agent trajectory_summary skill for post-run skill extraction

### CLI & Extensions

- [ ] **CLI-01**: `python -m opengui.cli` standalone entry point
- [ ] **EXT-01**: Other claw adapter pattern documented

## v2 Requirements

### Advanced Memory

- **MEM-V2-01**: SQLite storage backend for memory (better querying, eviction)
- **MEM-V2-02**: Memory eviction policies (LRU, access-count-based)
- **MEM-V2-03**: Experience memory (successful trajectory outcomes)

### Advanced Grounding

- **GND-V2-01**: GroundingProvider protocol for vision model coordinate refinement
- **GND-V2-02**: UITARS/Phi-V grounding integration

### Multi-Agent

- **MULTI-V2-01**: Planner → Executor → Verifier roles (Mobile-Agent-v3.5 style)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-action batching | Single-step single-tool-call is current design |
| Human-in-the-loop during execution | Agent runs autonomously |
| XML tool_call parsing | OpenAI-compatible native tool calls only |
| Local embedding models | External API via EmbeddingProvider protocol |
| SQLite storage | JSON files sufficient, defer to v2 |
| Real-time streaming of agent steps | Host agent can poll trajectory file |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| AGENT-01..03 | Phase 0 (done) | Complete |
| MEM-01..04 | Phase 0 (done) | Complete |
| SKILL-01..07 | Phase 0 (done) | Complete |
| TRAJ-01..02 | Phase 0 (done) | Complete |
| BACK-01..02 | Phase 0 (done) | Complete |
| TEST-01 | Phase 0 (done) | Complete |
| TEST-02..05 | Phase 1 | Pending |
| AGENT-04..06, MEM-05, SKILL-08, TRAJ-03 | Phase 2 | Pending |
| NANO-01..05 | Phase 3 | Pending |
| BACK-03 | Phase 4 | Pending |
| CLI-01, EXT-01 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 28 total
- Complete: 15
- Mapped to phases: 28
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-17 after initial definition*
