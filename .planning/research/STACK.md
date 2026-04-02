# Stack Research

**Domain:** GUI-agent shortcut extraction and stable shortcut execution
**Researched:** 2026-04-02
**Confidence:** MEDIUM

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Existing OpenGUI `ShortcutSkill` / `TaskSkill` schema | current repo | Canonical shortcut and task-skill contracts | The codebase already ships typed shortcut/task contracts, executors, and versioned stores; v1.6 should productionize them rather than invent a third format |
| Existing JSON stores + BM25/optional FAISS retrieval | current repo | Persist and retrieve shortcut/task skills | The current store/search path is simple, already integrated, and good enough for stabilizing shortcut behavior before introducing graph storage |
| Existing trajectory recorder artifacts (`trace.jsonl`, screenshots, evaluation.json) | current repo | Source of truth for extraction, gating, and diagnostics | Shortcut extraction needs provenance and replay evidence; the repo already records these artifacts in a way that can support promotion gates |
| LLM-based applicability and grounding with explicit contracts | current repo | Decide whether a shortcut is safe to use now and bind live targets | AppAgentX shows value in screen-aware shortcut evaluation, but the repo already has `GrounderProtocol`, structured conditions, and step execution seams to implement this without a new dependency stack |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Existing `GrounderProtocol` / `LLMGrounder` | current repo | Live parameter binding and target resolution | Use when shortcut steps depend on current screen context instead of fixed coordinates |
| Existing `ShortcutExecutor` / `TaskSkillExecutor` | current repo | Structured execution, contract checks, and fallback traversal | Use as the only runtime execution path for promoted shortcuts so stability rules stay centralized |
| Existing GUI evaluation hook | current repo | Post-run quality signal for shortcut promotion or demotion | Use as supporting evidence for shortcut health; do not make it the only gate |
| Existing memory retrieval stack | current repo | Optional context injection for task-level skills and app memory | Use when shortcut reuse depends on app-specific context, but keep shortcut gating screen-first |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest` regression coverage | Lock shortcut extraction, gating, fallback, and stability behavior | Critical because the current gap is not schema definition but production-path reliability |
| Structured trace logging | Diagnose why a shortcut was selected, skipped, retried, or rejected | Needed to identify brittle shortcuts and false-positive matches |
| Existing planning docs + milestone phase folders | Keep v1.6 decomposed into extraction, routing, runtime stability, and verification | Important because the new milestone crosses several already-shipped seams |

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Reuse existing JSON stores and search | Neo4j/Pinecone-style graph + vector stack like AppAgentX | Consider only after shortcut semantics are stable and store/search quality becomes the bottleneck |
| Reuse existing LLM grounding and contract checks | Full OmniParser-first shortcut runtime | Consider later if grounding quality, not control-flow stability, becomes the dominant blocker |
| Promote shortcuts from trace artifacts already emitted by OpenGUI | Build a separate shortcut authoring pipeline disconnected from traces | Only useful if manual curation becomes the primary path, which is not the v1.6 goal |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| A brand-new shortcut storage model | Adds migration and maintenance cost while the repo already has `ShortcutSkillStore` / `TaskSkillStore` | Extend the existing schema and stores with missing provenance/health metadata if needed |
| Raw coordinate replay as the shortcut contract | Brittle across screen drift, animation timing, and element movement | Re-ground live targets and verify post-step state |
| Graph or cloud dependencies as a prerequisite for v1.6 | Makes stabilization dependent on new infrastructure instead of closing the current product gap | Keep the milestone local-first and repo-native |

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `ShortcutSkill` / `TaskSkill` schema | `ShortcutExecutor`, `TaskSkillExecutor`, `UnifiedSkillSearch` | These are already aligned in-repo and should remain the single source of truth |
| Trajectory recorder artifacts | GUI evaluation hook and future extraction gates | v1.6 should consume only step events and trace-backed evidence to avoid artifact drift |

## Sources

- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/shortcut_extractor.py` - current shortcut promotion primitives and gaps
- `/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py` - current production postprocessing path still uses legacy extraction
- `/Users/jinli/Documents/Personal/AppAgentX/README.md` - evolutionary shortcut framing
- `/Users/jinli/Documents/Personal/AppAgentX/deployment.py` - screen-aware shortcut evaluation and template generation flow
- `/Users/jinli/Documents/Personal/MobileAgent/Mobile-Agent-v3.5/mobile_use/utils.py` - action semantics and observation/wait discipline

---
*Stack research for: shortcut extraction and stable shortcut execution*
*Researched: 2026-04-02*
