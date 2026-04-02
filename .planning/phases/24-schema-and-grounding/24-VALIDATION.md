---
phase: 24
slug: schema-and-grounding
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-02
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest -q tests/test_opengui_p1_skills.py tests/test_opengui_p1_memory.py tests/test_opengui_p24_schema_grounding.py` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~20 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q tests/test_opengui_p1_skills.py tests/test_opengui_p1_memory.py tests/test_opengui_p24_schema_grounding.py`
- **After every plan wave:** Run `uv run pytest -q tests/test_opengui_p1_skills.py tests/test_opengui_p1_memory.py tests/test_opengui_p24_schema_grounding.py`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 24-01-01 | 01 | 1 | SCHEMA-01, SCHEMA-02 | unit | `uv run pytest -q tests/test_opengui_p24_schema_grounding.py -k "shortcut or parameter_slot or state_descriptor"` | ❌ W0 | ⬜ pending |
| 24-02-01 | 02 | 2 | SCHEMA-03, SCHEMA-04, SCHEMA-05, SCHEMA-06 | unit | `uv run pytest -q tests/test_opengui_p24_schema_grounding.py -k "task_skill or branch or memory_context"` | ❌ W0 | ⬜ pending |
| 24-03-01 | 03 | 2 | GRND-01, GRND-02, GRND-03 | unit | `uv run pytest -q tests/test_opengui_p24_schema_grounding.py -k "grounder or protocol or grounding_result"` | ❌ W0 | ⬜ pending |
| 24-03-02 | 03 | 2 | Phase 24 SC-4 | smoke | `uv run python -m py_compile opengui/skills/data.py opengui/skills/shortcut.py opengui/skills/task_skill.py opengui/grounding/__init__.py opengui/grounding/protocol.py opengui/grounding/llm.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p24_schema_grounding.py` — schema round-trip, recursive task-node serialization, grounding protocol/result shape, and import-safety coverage
- [ ] Update `tests/test_opengui_p1_skills.py` — legacy `SkillStep` coexistence and export compatibility checks
- [ ] `uv run python -m py_compile ...` sanity gate for new `opengui/skills` and `opengui/grounding` modules

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | — | Phase 24 is a pure contract phase; all required behaviors should be automatable through unit, serialization, and compile/import checks | No manual-only verification expected |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
