---
phase: 2
slug: agent-loop-integration
status: draft
nyquist_compliant: true
wave_0_complete: true
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
| **Quick run command** | `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py -x -q` |
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
| 02-00-01 | 00 | 0 | ALL | stub | `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py -v --tb=no` | Wave 0 creates | ⬜ pending |
| 02-01-01 | 01 | 1 | SKILL-08 | unit | `uv run pytest tests/test_opengui_p1_skills.py tests/test_opengui.py -x -q` | ✅ exists | ⬜ pending |
| 02-01-02 | 01 | 1 | MEM-05 | unit | `uv run pytest tests/test_opengui_p1_memory.py tests/test_opengui.py -x -q` | ✅ exists | ⬜ pending |
| 02-02-01 | 02 | 2 | AGENT-04, AGENT-05, AGENT-06, MEM-05, SKILL-08, TRAJ-03 | integration | `uv run pytest tests/test_opengui.py -x -q` | ✅ exists | ⬜ pending |
| 02-02-02 | 02 | 2 | AGENT-04 | unit | python -c signature check (see plan 02-02 verify) | N/A | ⬜ pending |
| 02-03-01 | 03 | 1 | AGENT-04 | unit | python -c import check (see plan 02-03 verify) | N/A | ⬜ pending |
| 02-04-01 | 04 | 3 | TEST-05, AGENT-04, AGENT-05, AGENT-06, MEM-05, SKILL-08, TRAJ-03 | integration | `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py -x -q` | ✅ W0 stubs | ⬜ pending |
| 02-04-02 | 04 | 3 | TEST-05 | regression | `uv run pytest tests/ -x -q` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Plan

Plan `02-00-PLAN.md` (Wave 0) creates xfail test stubs for all requirements before any production code runs:

- [x] `tests/test_opengui_p2_integration.py` — 8 xfail stubs covering AGENT-04, AGENT-05, AGENT-06, SKILL-08, TRAJ-03, TEST-05, plus router replan test
- [x] `tests/test_opengui_p2_memory.py` — 2 xfail stubs covering MEM-05 (POLICY always-include, memory formatting)

These stubs are replaced with real implementations in plan 02-04 (Wave 3).

*Existing framework and shared fixtures cover all setup needs — no additional installation required.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending execution
