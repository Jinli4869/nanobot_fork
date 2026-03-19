---
phase: 8
slug: dead-export-cleanup
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x with pytest-asyncio |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| **Quick run command** | `pytest tests/test_opengui_p8_planning.py tests/test_opengui_p8_trajectory.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_opengui_p8_planning.py tests/test_opengui_p8_trajectory.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | SC-1 (no orphaned exports) | unit | `pytest tests/test_opengui_p8_planning.py::test_complexity_gate_skip -x` | ❌ W0 | ⬜ pending |
| 08-01-02 | 01 | 1 | SC-1 (no orphaned exports) | unit | `pytest tests/test_opengui_p8_planning.py::test_router_gui_dispatch -x` | ❌ W0 | ⬜ pending |
| 08-01-03 | 01 | 1 | SC-1 (no orphaned exports) | unit | `pytest tests/test_opengui_p8_planning.py::test_and_parallel -x` | ❌ W0 | ⬜ pending |
| 08-01-04 | 01 | 1 | SC-1 (no orphaned exports) | unit | `pytest tests/test_opengui_p8_planning.py::test_or_priority_order -x` | ❌ W0 | ⬜ pending |
| 08-02-01 | 02 | 1 | SC-1 (no orphaned exports) | unit | `pytest tests/test_opengui_p8_trajectory.py::test_summarizer_called_post_run -x` | ❌ W0 | ⬜ pending |
| 08-XX-XX | all | 2 | SC-2 (all tests pass) | regression | `pytest tests/ -x -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p8_planning.py` — stubs for TaskPlanner+TreeRouter integration tests
- [ ] `tests/test_opengui_p8_trajectory.py` — stubs for TrajectorySummarizer wiring tests

*Existing test infrastructure (conftest, fixtures) covers all other needs.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
