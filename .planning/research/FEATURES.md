# Feature Research

**Domain:** GUI-agent shortcut extraction and stable shortcut execution
**Researched:** 2026-04-02
**Confidence:** MEDIUM

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Trace-to-shortcut extraction on successful runs | The repo already defines shortcut schemas; users expect successful traces to feed them automatically | MEDIUM | The current production path still extracts only legacy skills |
| Screen-aware shortcut applicability checks before execution | AppAgentX-style shortcut use only works if the current screen really matches | HIGH | Selection should combine task text, app/platform, and current screen evidence |
| Live parameter binding instead of stale replay | Reusable shortcuts must adapt to current text targets, elements, and slight UI drift | HIGH | Existing grounding contracts are the right integration seam |
| Safe fallback when shortcut reuse is unsafe or fails | Shortcut use must never make the base agent worse | HIGH | Fallback path should preserve run continuity and diagnostics |
| Step-by-step stability guards | Users care less about shortcut elegance than whether it actually finishes reliably | HIGH | Requires settle/wait semantics plus post-step validation |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Shortcut health telemetry and demotion signals | Makes shortcut quality observable instead of mysterious | MEDIUM | Helps prune brittle shortcuts over time |
| Merge/version handling for duplicate shortcuts | Keeps the library clean as more traces arrive | MEDIUM | Avoids store pollution from repeated near-identical traces |
| Cross-surface shortcut stability contract | Reuse the same architecture on Android, local desktop, iOS, and HDC | HIGH | Important for OpenGUI's portable-agent positioning |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Immediate graph database adoption | AppAgentX uses richer memory/graph storage | Adds infrastructure before the shortcut pipeline itself is trustworthy | Stabilize schema, gating, and runtime first; revisit storage later |
| Promote every successful trace automatically | Feels like the fastest way to grow the library | Creates brittle, duplicate, low-value shortcuts that reduce trust | Require explicit gates, provenance, and health signals |
| Replay recorded coordinates exactly | Seems simple and efficient | Breaks under layout drift, animation timing, and partial page changes | Re-ground live targets and verify observable state transitions |

## Feature Dependencies

`Stable shortcut execution`
    `requires` -> `Shortcut applicability evaluation`
    `requires` -> `Live target/parameter binding`
    `requires` -> `Post-step validation`

`Shortcut applicability evaluation`
    `requires` -> `Persisted shortcut metadata + provenance`

`Shortcut health telemetry`
    `enhances` -> `Promotion gates`
    `enhances` -> `Shortcut demotion / cleanup`

### Dependency Notes

- **Execution requires applicability evaluation:** running a shortcut without current-screen checks is the fastest path to instability.
- **Applicability evaluation requires richer metadata:** extraction has to emit enough structured state and provenance for safe runtime decisions.
- **Telemetry enhances promotion and cleanup:** without observable failure patterns, the library only grows and never improves.

## MVP Definition

### Launch With (v1.6)

- [ ] Shortcut candidates promoted from successful trace step events into the new shortcut store
- [ ] Screen-aware retrieval and selection before shortcut execution
- [ ] Stable execution path with settle/verify/fallback behavior
- [ ] Regression coverage and logs proving shortcut use is safer than naive replay

### Add After Validation (v1.6.x)

- [ ] Shortcut health scoring and automatic demotion once enough runtime evidence exists
- [ ] Better duplicate clustering / version lineage for similar shortcuts

### Future Consideration (v2+)

- [ ] Task-level skill synthesis from repeated shortcut compositions
- [ ] OmniParser-first shortcut binding and graph-backed association memory

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Trace-to-shortcut extraction in production path | HIGH | MEDIUM | P1 |
| Screen-aware shortcut applicability checks | HIGH | HIGH | P1 |
| Live binding and safe fallback | HIGH | HIGH | P1 |
| Step settle/verification guarantees | HIGH | HIGH | P1 |
| Shortcut telemetry and library hygiene | MEDIUM | MEDIUM | P2 |
| Graph-backed shortcut association memory | MEDIUM | HIGH | P3 |

## Competitor / Reference Analysis

| Feature | AppAgentX | Mobile-Agent-v3.5/mobile_use | Our Approach |
|---------|-----------|-------------------------------|--------------|
| Shortcut concept | Evolves high-level shortcuts from history and evaluates execution conditions | Does not emphasize shortcut libraries, but enforces disciplined action/observation loops | Keep OpenGUI's shortcut/task schema but make the runtime production-ready |
| Shortcut use gate | Explicit shortcut association, evaluation, prioritization, and template generation | Emphasizes step-by-step action correctness and waiting for screen changes | Add a screen-aware shortcut selector before execution |
| Runtime stability | Template generation from current screen context | Explicit wait action and screenshot/history discipline | Combine live grounding with settle-and-verify execution contracts |

## Sources

- `/Users/jinli/Documents/Personal/AppAgentX/README.md`
- `/Users/jinli/Documents/Personal/AppAgentX/deployment.py`
- `/Users/jinli/Documents/Personal/MobileAgent/Mobile-Agent-v3.5/mobile_use/utils.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py`

---
*Feature research for: shortcut extraction and stable shortcut execution*
*Researched: 2026-04-02*
