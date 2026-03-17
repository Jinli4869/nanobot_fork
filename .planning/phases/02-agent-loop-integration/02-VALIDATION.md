---
phase: 2
slug: agent-loop-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_opengui_p2_integration.py -x -q` |
| **Full suite command** | `uv run pytest tests/ -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui.py tests/test_opengui_p1_memory.py tests/test_opengui_p1_skills.py tests/test_opengui_p1_trajectory.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | AGENT-04 | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_memory_injected_into_system_prompt -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | MEM-05 | unit | `uv run pytest tests/test_opengui_p2_memory.py::test_policy_always_included -x` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | AGENT-05 | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_skill_path_chosen_above_threshold -x` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 1 | SKILL-08 | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_skill_execution_fast_path -x` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 2 | AGENT-06 | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_trajectory_recorded_on_run -x` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 2 | TRAJ-03 | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_trajectory_step_count -x` | ❌ W0 | ⬜ pending |
| 02-04-01 | 04 | 3 | TEST-05 | integration | `uv run pytest tests/test_opengui_p2_integration.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p2_integration.py` — covers AGENT-04, AGENT-05, AGENT-06, SKILL-08, TRAJ-03, TEST-05
- [ ] `tests/test_opengui_p2_memory.py` — covers MEM-05 (markdown migration + POLICY always-include)
- [ ] `tests/test_opengui_p1_memory.py` — UPDATE existing tests to pass with markdown MemoryStore

*Existing framework and shared fixtures cover all setup needs — no additional installation required.*

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
