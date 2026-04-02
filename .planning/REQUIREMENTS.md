# Requirements: OpenGUI v1.5

**Defined:** 2026-04-01
**Core Value:** Any host agent can spawn a GUI subagent to complete device tasks autonomously, while accumulating reusable skills and execution history over time.

## v1.5 Requirements

Requirements for the new OpenGUI skills architecture milestone. Replaces the flat single-layer skill system with a two-layer tree (shortcut + task-level), backed by a pluggable grounding protocol, quality-gated extraction, and layer-aware storage.

### SCHEMA — New Skill Data Models

- [x] **SCHEMA-01**: Shortcut skill defines pre/post conditions as structured, checkable state descriptors (not free-form strings)
- [x] **SCHEMA-02**: Shortcut skill declares typed parameter slots (name, type, description) for runtime grounding
- [x] **SCHEMA-03**: Task-level skill references shortcut skills by ID with parameter binding declarations
- [x] **SCHEMA-04**: Task-level skill supports inline ATOM fallback steps for actions not covered by a shortcut
- [x] **SCHEMA-05**: Task-level skill supports conditional branch nodes with checkable condition expressions
- [x] **SCHEMA-06**: Task-level skill carries an optional pointer to an app memory context entry in the existing memory system

### GRND — Pluggable Grounding Protocol

- [x] **GRND-01**: GrounderProtocol defines a common async interface for resolving semantic step targets to concrete action parameters
- [x] **GRND-02**: LLMGrounder implements GrounderProtocol wrapping the existing vision-LLM grounding path
- [x] **GRND-03**: Grounding results expose the grounder used, confidence score, and fallback metadata

### EXEC — Multi-layer Execution Engine

- [x] **EXEC-01**: ShortcutExecutor verifies pre/post contracts at each step boundary and reports violations
- [x] **EXEC-02**: TaskSkillExecutor resolves shortcut references, executes ATOM fallback steps, and evaluates conditional branches
- [x] **EXEC-03**: Both executors route all action parameter resolution through GrounderProtocol

### EXTR — Quality-Gated Skill Extraction

- [ ] **EXTR-01**: Step-level critic evaluates each trajectory step for correctness before skill extraction
- [ ] **EXTR-02**: Trajectory-level critic evaluates overall trajectory quality before a skill is promoted to the library
- [ ] **EXTR-03**: Extraction pipeline only promotes skills from trajectories passing both critics
- [ ] **EXTR-04**: Extractor produces shortcut-layer skill candidates from validated trajectory step sequences

### STOR — Two-Layer Skill Store

- [ ] **STOR-01**: Shortcut skills and task-level skills are persisted in separate, versioned JSON stores
- [ ] **STOR-02**: Unified skill search covers both layers with layer-aware relevance scoring

### INTEG — Agent Integration

- [ ] **INTEG-01**: GuiAgent searches both skill layers during pre-task skill lookup and selects the most appropriate match
- [ ] **INTEG-02**: GuiAgent injects the app memory context referenced by a task-level skill into the execution context before running

## Future Requirements (v1.6+)

### Orchestration Layer (deferred)

- **ORCH-01**: Orchestration-layer skills define high-level strategy templates composed of task-level skills and explicit OR-branch nodes
- **ORCH-02**: Main agent can delegate orchestration skill execution with OR-branch resolution at the agent level
- **ORCH-03**: Orchestration skills support GUI + tool/MCP collaborative workflows with explicit capability boundaries

### Grounding Extensions (deferred)

- **GRND-04**: OmniParser implements GrounderProtocol for structured element detection as an alternative to LLM grounding
- **GRND-05**: Grounding cache avoids redundant LLM/OmniParser calls for repeated screen elements within a session

### Skill Promotion Pipeline (deferred)

- **EXTR-05**: Extractor can synthesize task-level skill candidates by composing shortcut sequences from validated trajectories
- **EXTR-06**: Skill promotion includes a live sandbox verification step before a candidate enters the stable library

## Out of Scope

| Feature | Reason |
|---------|--------|
| Migration of existing skills.json | Old skills carry pixel-coordinate data that doesn't generalize; quality-gated re-extraction is safer |
| Orchestration layer | Deferred to v1.6 — shortcut + task-level must be stable first |
| OmniParser grounding backend | Deferred to v1.6 via GrounderProtocol — LLM grounder covers v1.5 needs |
| Skill sandbox verification before promotion | Deferred — critics provide sufficient quality gate for v1.5 |
| Persistent FAISS index | Deferred — in-session FAISS rebuild is acceptable at current scale |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCHEMA-01 | Phase 24 | Complete |
| SCHEMA-02 | Phase 24 | Complete |
| SCHEMA-03 | Phase 24 | Complete |
| SCHEMA-04 | Phase 24 | Complete |
| SCHEMA-05 | Phase 24 | Complete |
| SCHEMA-06 | Phase 24 | Complete |
| GRND-01 | Phase 24 | Complete |
| GRND-02 | Phase 24 | Complete |
| GRND-03 | Phase 24 | Complete |
| EXEC-01 | Phase 25 | Complete |
| EXEC-02 | Phase 25 | Complete |
| EXEC-03 | Phase 25 | Complete |
| EXTR-01 | Phase 26 | Pending |
| EXTR-02 | Phase 26 | Pending |
| EXTR-03 | Phase 26 | Pending |
| EXTR-04 | Phase 26 | Pending |
| STOR-01 | Phase 27 | Pending |
| STOR-02 | Phase 27 | Pending |
| INTEG-01 | Phase 27 | Pending |
| INTEG-02 | Phase 27 | Pending |

**Coverage:**
- v1.5 requirements: 20 total
- Mapped to phases: 20 (roadmap complete)
- Unmapped: 0

---
*Requirements defined: 2026-04-01*
*Last updated: 2026-04-01 after roadmap creation — all 20 requirements mapped to phases 24-27*
