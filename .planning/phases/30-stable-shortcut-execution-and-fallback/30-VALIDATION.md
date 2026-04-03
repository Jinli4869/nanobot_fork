---
phase: 30
slug: stable-shortcut-execution-and-fallback
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 30 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x -q --tb=short` |
| **Full suite command** | `python -m pytest tests/ -q --tb=short` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `python -m pytest tests/ -q --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 30-01-01 | 01 | 1 | SUSE-03 | unit | `python -m pytest tests/ -k "test_llm_condition_evaluator" -x -q` | ❌ W0 | ⬜ pending |
| 30-01-02 | 01 | 1 | SUSE-03 | unit | `python -m pytest tests/ -k "test_shortcut_executor_wiring" -x -q` | ❌ W0 | ⬜ pending |
| 30-01-03 | 01 | 1 | SUSE-03 | unit | `python -m pytest tests/ -k "test_live_binding" -x -q` | ❌ W0 | ⬜ pending |
| 30-02-01 | 02 | 1 | SSTA-01 | unit | `python -m pytest tests/ -k "test_settle_timing" -x -q` | ❌ W0 | ⬜ pending |
| 30-02-02 | 02 | 1 | SSTA-01 | unit | `python -m pytest tests/ -k "test_post_step_observation" -x -q` | ❌ W0 | ⬜ pending |
| 30-02-03 | 02 | 1 | SSTA-02 | unit | `python -m pytest tests/ -k "test_post_step_validation" -x -q` | ❌ W0 | ⬜ pending |
| 30-03-01 | 03 | 2 | SUSE-04 | unit | `python -m pytest tests/ -k "test_contract_violation_fallback" -x -q` | ❌ W0 | ⬜ pending |
| 30-03-02 | 03 | 2 | SUSE-04 | unit | `python -m pytest tests/ -k "test_fallback_no_worse" -x -q` | ❌ W0 | ⬜ pending |
| 30-03-03 | 03 | 2 | SSTA-02 | unit | `python -m pytest tests/ -k "test_shortcut_trajectory_event" -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_phase30_shortcut_execution.py` — stubs for SUSE-03, SUSE-04, SSTA-01, SSTA-02
- [ ] `tests/conftest.py` — shared fixtures (extend existing if present)

*Existing pytest infrastructure is present; Wave 0 adds new test stubs only.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end shortcut execution with live grounding | SUSE-03 | Requires running GUI agent with real backend | Run agent on a task with a known applicable shortcut; verify it executes via `ShortcutExecutor` and not `SkillExecutor` |
| Fallback to non-shortcut flow on contract violation | SUSE-04 | Requires live UI state that triggers `ContractViolationReport` | Inject a drift condition (mismatched element) and confirm the agent continues task execution via standard path |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
