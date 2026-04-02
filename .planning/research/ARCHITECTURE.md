# Architecture Research

**Domain:** GUI-agent shortcut extraction and stable shortcut execution
**Researched:** 2026-04-02
**Confidence:** MEDIUM

## Standard Architecture

### System Overview

```text
┌──────────────────────────────────────────────────────────────┐
│                 GUI task execution entrypoint               │
│      nanobot GuiSubagentTool / OpenGUI GuiAgent run()      │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               v
┌──────────────────────────────────────────────────────────────┐
│         Pre-run shortcut discovery and applicability         │
│   task query + app/platform + current screen -> candidates   │
│   -> applicability evaluator -> selected shortcut or none    │
└──────────────────────────────┬───────────────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                v                             v
┌──────────────────────────────┐   ┌───────────────────────────┐
│   Stable shortcut execution  │   │ Default agent/task path   │
│ live binding + settle/verify │   │ planner / atom fallback   │
│ + structured fallback        │   │ remains available         │
└──────────────────────────────┘   └───────────────────────────┘
                │
                v
┌──────────────────────────────────────────────────────────────┐
│          Post-run trace processing and library health        │
│  trace step filter -> critics/gates -> store merge/version   │
│  -> telemetry / evaluation / future demotion signals         │
└──────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Trace promotion pipeline | Convert successful traces into trustworthy shortcut candidates | Reuse trajectory artifacts, explicit critics/gates, and `ShortcutSkillStore` persistence |
| Applicability evaluator | Decide whether a retrieved shortcut is safe to run on the current screen | Use structured preconditions, current observation, task text, and optional LLM judgment with explicit outputs |
| Stable shortcut executor | Execute shortcut steps with live bindings, settle checks, post-state validation, and fallback | Centralize in `ShortcutExecutor` / `TaskSkillExecutor` instead of ad-hoc callers |
| Health/observability layer | Record why shortcuts were promoted, selected, skipped, failed, or merged | Trace events, evaluation artifacts, and store metadata |

## Recommended Project Structure

```text
opengui/
├── skills/
│   ├── shortcut.py              # Canonical shortcut contract
│   ├── shortcut_extractor.py    # Promotion pipeline and critics
│   ├── shortcut_store.py        # Persistent stores and unified search
│   ├── multi_layer_executor.py  # Stable shortcut/task execution path
│   └── ...                      # Existing legacy compatibility while v1.6 lands
├── agent.py                     # Pre-run shortcut search and runtime integration
└── trajectory/                  # Trace artifacts and supporting summaries

nanobot/
└── agent/tools/gui.py           # Production entrypoint, post-run extraction hook, evaluation hook
```

### Structure Rationale

- **`opengui/skills/` stays the canonical ownership boundary:** v1.6 is about finishing the new shortcut architecture, not scattering shortcut rules across host layers.
- **`nanobot/agent/tools/gui.py` remains the production integration seam:** it already owns run artifacts, extraction scheduling, and evaluation hooks.

## Architectural Patterns

### Pattern 1: Evidence-first promotion

**What:** Promote shortcuts only from trace-backed step events that pass explicit gates.
**When to use:** For all automatic shortcut creation.
**Trade-offs:** Slower library growth, much higher trust.

### Pattern 2: Retrieval plus applicability, not retrieval alone

**What:** Search narrows candidates; a second decision layer checks whether one is safe now.
**When to use:** Before any shortcut execution.
**Trade-offs:** More runtime work, fewer false-positive shortcut launches.

### Pattern 3: Execute through one stable path

**What:** All shortcut reuse flows through the same executor contracts for binding, settle, validate, and fallback.
**When to use:** Always; avoid caller-specific shortcut replay.
**Trade-offs:** Centralized complexity, but much better long-term maintainability.

## Data Flow

### Shortcut Promotion Flow

```text
Trace JSONL + screenshots
    -> filter to step events
    -> step critic(s)
    -> trajectory critic(s)
    -> candidate normalization + provenance
    -> merge/version decision
    -> shortcut store
```

### Shortcut Runtime Flow

```text
Task + current app/screen
    -> unified search
    -> applicability evaluation
    -> live parameter/target binding
    -> execute step
    -> settle / re-observe
    -> post-step validation
    -> continue or fallback
```

## Anti-Patterns

### Anti-Pattern 1: Dual production paths

**What people do:** Keep legacy extraction/use in production while also introducing a new shortcut path.
**Why it's wrong:** The library semantics diverge and stability bugs become impossible to reason about.
**Do this instead:** Make v1.6 explicitly transition production shortcut creation/use onto the new shortcut/task architecture.

### Anti-Pattern 2: Search score equals execution safety

**What people do:** Execute the top search result directly once it clears a threshold.
**Why it's wrong:** Relevance to the task text is not the same as current-screen applicability.
**Do this instead:** Add an applicability decision step with structured diagnostics.

## Integration Points

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `nanobot/agent/tools/gui.py` <-> `opengui.skills.*` | direct imports and structured calls | Keep host integration thin; shortcut semantics live in OpenGUI |
| `GuiAgent` <-> `UnifiedSkillSearch` | ranked candidate lookup | Extend to include current-screen-aware selection behavior |
| `GuiAgent` / executors <-> trajectory recorder | structured events | Needed for diagnosable shortcut health and stability |

## Sources

- `/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/shortcut_extractor.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/multi_layer_executor.py`
- `/Users/jinli/Documents/Personal/AppAgentX/deployment.py`

---
*Architecture research for: shortcut extraction and stable shortcut execution*
*Researched: 2026-04-02*
