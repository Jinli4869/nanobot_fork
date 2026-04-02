---
phase: 29
slug: shortcut-retrieval-applicability-routing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py -q` |
| **Full suite command** | `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py -q` |
| **Estimated runtime** | ~8 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p29_retrieval_applicability.py -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 8 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 29-01-01 | 01 | 1 | SUSE-01 | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_retrieval_filters_by_platform -x` | ❌ W0 | ⬜ pending |
| 29-01-02 | 01 | 1 | SUSE-01 | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_retrieval_permissive_without_foreground_app -x` | ❌ W0 | ⬜ pending |
| 29-01-03 | 01 | 1 | SUSE-01 | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_retrieval_emits_trajectory_event -x` | ❌ W0 | ⬜ pending |
| 29-02-01 | 02 | 1 | SUSE-02 | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_applicability_run_when_conditions_pass -x` | ❌ W0 | ⬜ pending |
| 29-02-02 | 02 | 1 | SUSE-02 | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_applicability_skip_when_condition_fails -x` | ❌ W0 | ⬜ pending |
| 29-02-03 | 02 | 1 | SUSE-02 | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_fallback_when_no_candidates -x` | ❌ W0 | ⬜ pending |
| 29-02-04 | 02 | 1 | SUSE-02 | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_applicability_emits_trajectory_event -x` | ❌ W0 | ⬜ pending |
| 29-02-05 | 02 | 1 | SUSE-02 | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_applicability_exception_produces_fallback -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p29_retrieval_applicability.py` — stubs for all SUSE-01 and SUSE-02 behaviors
- [ ] `opengui/skills/shortcut_router.py` — new module for `ApplicabilityDecision` and `ShortcutApplicabilityRouter`

*Existing `ShortcutSkillStore`, `UnifiedSkillSearch`, `ConditionEvaluator`, and `TrajectoryRecorder` infrastructure already covers Phase 29's dependencies.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 8s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
