# Pitfalls Research

**Domain:** GUI-agent shortcut extraction and stable shortcut execution
**Researched:** 2026-04-02
**Confidence:** MEDIUM

## Critical Pitfalls

### Pitfall 1: Promoting brittle traces as shortcuts

**What goes wrong:**
The library fills with shortcuts extracted from noisy traces, failed runs, duplicate flows, or non-step events.

**Why it happens:**
Automatic promotion feels like free leverage, so teams skip explicit gates and provenance requirements.

**How to avoid:**
Promote only from filtered step events, require minimum trace quality, store provenance, and merge or reject near-duplicates.

**Warning signs:**
Many shortcuts have nearly identical names, missing state descriptors, or fail on their second use.

**Phase to address:**
Phase 28

---

### Pitfall 2: Executing shortcuts based on search score alone

**What goes wrong:**
The agent retrieves a shortcut that sounds relevant to the task but does not match the current screen state, then immediately drifts.

**Why it happens:**
Text similarity is easier to implement than true applicability evaluation.

**How to avoid:**
Split shortcut reuse into retrieval and applicability evaluation, and log why candidates were accepted or rejected.

**Warning signs:**
Runs choose a shortcut quickly, then fail on the first step or require manual fallback despite a high retrieval score.

**Phase to address:**
Phase 29

---

### Pitfall 3: Replaying stale coordinates or stale assumptions

**What goes wrong:**
The shortcut assumes the same target position, visible state, or animation timing as the source trace.

**Why it happens:**
Recorded actions look concrete enough to reuse directly.

**How to avoid:**
Re-ground live targets, wait for the device to settle, and verify post-step state before continuing.

**Warning signs:**
Shortcuts work on exactly one layout or require repeated ad-hoc sleeps.

**Phase to address:**
Phase 30

---

### Pitfall 4: Shortcut failure poisons the entire run

**What goes wrong:**
When a shortcut becomes invalid mid-run, the agent loses context or exits instead of continuing through the normal path.

**Why it happens:**
Shortcut execution is treated as a special mode instead of a safe optimization.

**How to avoid:**
Make fallback a first-class outcome with explicit diagnostics and seamless return to task-level or normal agent execution.

**Warning signs:**
Shortcut errors produce terminal failures for tasks that the base agent could have finished.

**Phase to address:**
Phase 30

---

### Pitfall 5: No way to tell which shortcuts are actually healthy

**What goes wrong:**
The team cannot distinguish a good shortcut from one that is silently flaky.

**Why it happens:**
Success/failure is only recorded at the whole-run level, not at shortcut decision and step boundaries.

**How to avoid:**
Emit structured shortcut telemetry for selection, grounding, settle, validation, fallback, and final outcome; add focused regression tests.

**Warning signs:**
People argue from anecdotes because there is no shortcut-level evidence.

**Phase to address:**
Phase 31

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Keep legacy extraction in production while building new shortcut flow | Lower immediate migration risk | Library semantics diverge and bugs become harder to isolate | Only temporarily during Phase 28 behind clear cutover criteria |
| Add fixed sleeps instead of settle checks | Fastest way to reduce flaky timing once | Slow, brittle runs across devices and apps | Only as a temporary targeted mitigation with a follow-up to replace it |
| Store every candidate without merge/version policy | Fast library growth | Noise overwhelms useful shortcuts | Never as the default v1.6 behavior |

## "Looks Done But Isn't" Checklist

- [ ] **Shortcut extraction:** Only step events should count; verify summaries/results are excluded.
- [ ] **Shortcut selection:** Retrieval alone is not enough; verify current-screen applicability is checked.
- [ ] **Shortcut execution:** Verify screenshots are taken after action completion / settle, not before effects land.
- [ ] **Fallback:** Verify a rejected or drifting shortcut can return to the normal path without killing the task.
- [ ] **Observability:** Verify logs show why a shortcut was chosen, skipped, failed, or demoted.

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Promoting brittle traces as shortcuts | Phase 28 | Candidate gating and merge/version tests |
| Executing shortcuts based on search score alone | Phase 29 | Applicability decision tests and logs |
| Replaying stale coordinates or stale assumptions | Phase 30 | Live binding and settle/validation tests |
| Shortcut failure poisons the run | Phase 30 | Fallback continuity tests |
| No way to tell which shortcuts are healthy | Phase 31 | Telemetry assertions and focused regression coverage |

## Sources

- `/Users/jinli/Documents/Personal/AppAgentX/deployment.py`
- `/Users/jinli/Documents/Personal/MobileAgent/Mobile-Agent-v3.5/mobile_use/utils.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py`
- `/Users/jinli/Documents/Personal/nanobot_fork/opengui/skills/shortcut_extractor.py`

---
*Pitfalls research for: shortcut extraction and stable shortcut execution*
*Researched: 2026-04-02*
