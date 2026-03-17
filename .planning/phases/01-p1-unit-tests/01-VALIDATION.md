---
phase: 1
slug: p1-unit-tests
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_opengui_p1_*.py -v` |
| **Full suite command** | `uv run pytest tests/ -v` |
| **Estimated runtime** | ~2 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p1_*.py -v`
- **After every plan wave:** Run `uv run pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | TEST-02 | unit | `uv run pytest tests/test_opengui_p1_memory.py -k "memory_store" -x` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | TEST-02 | unit | `uv run pytest tests/test_opengui_p1_memory.py -k "retriever" -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | TEST-03 | unit | `uv run pytest tests/test_opengui_p1_skills.py -k "skill_library_crud" -x` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 2 | TEST-03 | unit | `uv run pytest tests/test_opengui_p1_skills.py -k "skill_library_search" -x` | ❌ W0 | ⬜ pending |
| 01-02-03 | 02 | 2 | TEST-03 | unit | `uv run pytest tests/test_opengui_p1_skills.py -k "dedup" -x` | ❌ W0 | ⬜ pending |
| 01-02-04 | 02 | 2 | TEST-03 | unit | `uv run pytest tests/test_opengui_p1_skills.py -k "executor" -x` | ❌ W0 | ⬜ pending |
| 01-02-05 | 02 | 2 | TEST-03 | unit | `uv run pytest tests/test_opengui_p1_skills.py -k "extractor" -x` | ❌ W0 | ⬜ pending |
| 01-03-01 | 03 | 2 | TEST-04 | unit | `uv run pytest tests/test_opengui_p1_trajectory.py -k "recorder" -x` | ❌ W0 | ⬜ pending |
| 01-03-02 | 03 | 2 | TEST-04 | unit | `uv run pytest tests/test_opengui_p1_trajectory.py -k "summarizer" -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — add `faiss-cpu>=1.13.0` and `numpy>=1.26.0` to dependencies
- [ ] `uv sync --extra dev` — install missing deps
- [ ] `tests/test_opengui_p1.py` — main deliverable covering TEST-02, TEST-03, TEST-04

*All test files are created as part of this phase's plans.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
