# Project Research Summary

**Project:** OpenGUI
**Domain:** GUI-agent shortcut extraction and stable shortcut execution
**Researched:** 2026-04-02
**Confidence:** MEDIUM

## Executive Summary

OpenGUI already shipped the schema, execution contracts, and storage/search pieces for a two-layer shortcut architecture in v1.5, but the production GUI path still extracts legacy skills and does not yet treat shortcuts as a stable, screen-aware optimization. That makes v1.6 a brownfield finishing milestone, not a greenfield invention milestone.

The strongest pattern from AppAgentX is not its storage choices but its runtime discipline: retrieve associated shortcuts, evaluate whether they fit the current screen and task, then generate an execution plan from live context. The strongest pattern from Mobile-Agent-v3.5/mobile_use is its strict action/observation rhythm: actions need time to land, screenshots must reflect the resulting state, and history should stay concise and actionable. Together, they imply that v1.6 should focus on three things: trustworthy shortcut promotion, safe shortcut selection, and stable shortcut execution.

## Key Findings

### Recommended Stack

Reuse the existing OpenGUI shortcut/task contracts, JSON stores, unified search, trajectory artifacts, and grounding protocol. The codebase already has the right seams; the current gap is that the shipped production path still routes post-run extraction through the legacy `SkillExtractor` and `SkillLibrary` path.

**Core technologies:**
- Existing `ShortcutSkill` / `TaskSkill` contracts: canonical reusable skill format
- Existing `ShortcutSkillStore` / `TaskSkillStore` / `UnifiedSkillSearch`: persistence and retrieval
- Existing `GrounderProtocol` / `LLMGrounder` / executors: live binding and stable runtime enforcement

### Expected Features

**Must have (table stakes):**
- Promote shortcut candidates from successful trace step events into the new shortcut store
- Evaluate whether a shortcut is applicable to the current screen before executing it
- Re-bind live targets and validate each shortcut step with settle/fallback behavior

**Should have (competitive):**
- Shortcut health telemetry for diagnosing unstable or low-value shortcuts
- Merge/version handling so repeated traces improve the library instead of polluting it

**Defer (v2+):**
- Graph-backed shortcut association memory
- OmniParser-first shortcut routing
- Task-level synthesis from repeated shortcut compositions

### Architecture Approach

V1.6 should insert one explicit decision layer between retrieval and execution: search narrows candidates, then applicability evaluation decides whether a shortcut is safe now. Successful traces should feed a gated promotion pipeline that emits provenance-rich shortcut candidates into the existing stores. All runtime reuse should flow through the existing shortcut/task executors so settle, validation, and fallback rules live in one place.

**Major components:**
1. Trace promotion pipeline - filters and promotes trustworthy shortcut candidates
2. Applicability evaluator - decides whether a retrieved shortcut fits the current screen/task
3. Stable executor path - binds live targets, waits for settle, validates state, and falls back safely
4. Observability layer - records selection, failure, and health evidence for shortcuts

### Critical Pitfalls

1. **Promoting brittle traces as shortcuts** - require explicit gating, provenance, and merge/version behavior
2. **Executing shortcuts from search score alone** - add a screen-aware applicability decision step
3. **Replaying stale coordinates or stale assumptions** - use live binding plus settle-and-verify execution
4. **Letting shortcut failures poison the whole run** - make fallback first-class
5. **Operating without shortcut-level evidence** - add structured telemetry and regression coverage

## Implications for Roadmap

### Phase 28: Shortcut Extraction Productionization
**Rationale:** The current production gap starts after the run finishes; until extraction writes into the new shortcut system, the rest of the architecture cannot learn.
**Delivers:** Trace filtering, promotion gates, provenance, merge/version behavior, and store write path.
**Avoids:** Brittle trace promotion and duplicate library growth.

### Phase 29: Shortcut Retrieval and Applicability Routing
**Rationale:** Retrieval without applicability checks is unsafe, so selection needs its own phase before heavier runtime changes.
**Delivers:** Candidate lookup plus explicit "run / skip / fallback" shortcut decisioning.
**Avoids:** False-positive shortcut launches caused by text similarity alone.

### Phase 30: Stable Shortcut Execution and Fallback
**Rationale:** Once a shortcut is selected safely, execution needs live binding, settle semantics, state validation, and clean fallback.
**Delivers:** Stable runtime shortcut path on top of the existing executor contracts.
**Avoids:** Stale coordinate replay and terminal failures from shortcut drift.

### Phase 31: Shortcut Observability and Regression Hardening
**Rationale:** Shortcut stability is not believable without evidence, and v1.6 explicitly promises stability.
**Delivers:** Shortcut telemetry, health diagnostics, and focused regression coverage.
**Avoids:** Silent flakiness and library trust erosion.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Driven mostly by shipped repo seams rather than speculative additions |
| Features | MEDIUM | The milestone direction is clear, but exact selector/executor UX can still evolve during phase planning |
| Architecture | HIGH | The core integration boundaries are already visible in the codebase |
| Pitfalls | HIGH | Confirmed by the current gap between new shortcut architecture and legacy production behavior |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- Exact shortcut health scoring / demotion policy should be decided during phase planning, after telemetry format is clearer.
- If v1.6 needs desktop-specific settle heuristics beyond the current generic contracts, that should be validated in the execution phase rather than guessed now.

## Sources

- `/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/shortcut_extractor.py`
- `/Users/jinli/Documents/Personal/AppAgentX/README.md`
- `/Users/jinli/Documents/Personal/AppAgentX/deployment.py`
- `/Users/jinli/Documents/Personal/MobileAgent/Mobile-Agent-v3.5/mobile_use/utils.py`

---
*Research completed: 2026-04-02*
*Ready for roadmap: yes*
