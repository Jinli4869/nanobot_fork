# Requirements: OpenGUI v1.6

**Defined:** 2026-04-02
**Core Value:** Any host agent can spawn a GUI subagent to complete device tasks autonomously, while accumulating reusable skills and execution history over time.

## v1.6 Requirements

Requirements for turning the shipped shortcut architecture into a stable production path.

### SXTR - Shortcut Extraction

- [x] **SXTR-01**: Successful GUI runs can promote shortcut candidates from trace step events only, excluding summary/result noise and malformed artifacts.
- [x] **SXTR-02**: Each promoted shortcut records normalized app/platform identifiers, reusable parameter slots, structured state conditions, and provenance back to the source trace.
- [x] **SXTR-03**: The promotion pipeline rejects brittle shortcuts using explicit gates for minimum usable steps, unsupported patterns, and low-quality evidence.
- [x] **SXTR-04**: Duplicate or near-duplicate shortcut candidates are merged, versioned, or rejected instead of being stored as repeated library entries.

### SUSE - Shortcut Use

- [x] **SUSE-01**: GuiAgent can retrieve shortcut candidates using task text plus current app/platform context before entering the full step-by-step loop.
- [x] **SUSE-02**: Runtime selection executes a shortcut only when current screen evidence satisfies its applicability checks; otherwise the run continues without shortcut reuse.
- [ ] **SUSE-03**: Shortcut execution binds live parameters and targets from the current observation instead of replaying stale recorded coordinates or assumptions.
- [x] **SUSE-04**: If a shortcut becomes invalid or unavailable mid-run, execution falls back cleanly to task-level or default agent behavior without terminating an otherwise recoverable task.

### SSTA - Shortcut Stability

- [x] **SSTA-01**: Each shortcut step waits for action completion and captures the next observation only after the UI has settled enough to evaluate the effect.
- [x] **SSTA-02**: Shortcut execution verifies post-step state after every action and surfaces structured failure reasons when drift or contract violations occur.
- [x] **SSTA-03**: Shortcut runs emit structured telemetry for retrieval, applicability, grounding, settle, validation, fallback, and final outcome so unstable shortcuts can be diagnosed.
- [ ] **SSTA-04**: Regression coverage proves shortcut extraction and execution remain stable across representative mobile and desktop execution seams or their CI-safe equivalents.

## Future Requirements (v1.7+)

### STSK - Task-level Shortcut Composition

- **STSK-01**: Repeated shortcut sequences can be promoted into stable task-level skills with explicit composition semantics.
- **STSK-02**: Task-level skills can accumulate shortcut health feedback and choose between equivalent shortcut alternatives.

### OPER - Shortcut Operations and Lifecycle

- **OPER-01**: Shortcut health scores can demote or quarantine unstable shortcuts automatically after repeated failures.
- **OPER-02**: Operators can inspect shortcut provenance, merge history, and failure signatures directly from stable artifacts.

### GRND - Grounding Extensions

- **GRND-04**: Alternative grounding backends such as OmniParser can implement the same shortcut runtime contract without schema changes.
- **GRND-05**: Shortcut applicability evaluation can incorporate richer structural UI evidence without requiring a new storage model.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Neo4j/Pinecone or graph-backed shortcut storage | Infrastructure expansion is not the core blocker; v1.6 should stabilize the existing store/search architecture first |
| Full orchestration-layer skills | Shortcut extraction and execution need to be trustworthy before adding another abstraction layer |
| Manual review on every promoted shortcut | Too expensive for the default path; v1.6 should rely on explicit gates plus diagnostics |
| Direct migration of all legacy skills into the new shortcut store | Existing legacy skills do not necessarily meet the new stability and provenance requirements |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SXTR-01 | Phase 28 | Complete |
| SXTR-02 | Phase 28 | Complete |
| SXTR-03 | Phase 28 | Complete |
| SXTR-04 | Phase 28 | Complete |
| SUSE-01 | Phase 29 | Complete |
| SUSE-02 | Phase 29 | Complete |
| SUSE-03 | Phase 30 | Pending |
| SUSE-04 | Phase 30 | Complete |
| SSTA-01 | Phase 30 | Complete |
| SSTA-02 | Phase 30 | Complete |
| SSTA-03 | Phase 31 | Complete |
| SSTA-04 | Phase 31 | Pending |

**Coverage:**
- v1.6 requirements: 12 total
- Mapped to phases: 12
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-02*
*Last updated: 2026-04-03 after completing Plan 30-03 for milestone v1.6*
