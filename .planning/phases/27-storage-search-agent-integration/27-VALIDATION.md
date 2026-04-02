---
phase: 27
slug: storage-search-agent-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 27 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=9.0.0,<10.0.0 + pytest-asyncio >=1.3.0,<2.0.0 |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p25_multi_layer_execution.py tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p24_schema_grounding.py -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 27-01-01 | 01 | 1 | STOR-01 | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k shortcut_store_round_trip` | ❌ W0 | ⬜ pending |
| 27-01-02 | 01 | 1 | STOR-01 | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k task_store_round_trip` | ❌ W0 | ⬜ pending |
| 27-01-03 | 01 | 1 | STOR-01 | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k version_field` | ❌ W0 | ⬜ pending |
| 27-02-01 | 02 | 2 | STOR-02 | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k unified_search` | ❌ W0 | ⬜ pending |
| 27-03-01 | 03 | 3 | INTEG-01 | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k agent_skill_lookup` | ❌ W0 | ⬜ pending |
| 27-03-02 | 03 | 3 | INTEG-02 | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k memory_context_injection` | ❌ W0 | ⬜ pending |
| 27-03-03 | 03 | 3 | INTEG-02 | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k missing_memory_context` | ❌ W0 | ⬜ pending |
| 27-00-01 | 00 | 0 | — | smoke | `uv run python -m py_compile opengui/skills/shortcut_store.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p27_storage_search_agent.py` — stubs for STOR-01, STOR-02, INTEG-01, INTEG-02, and import safety
- [ ] `opengui/skills/shortcut_store.py` — new module with `ShortcutSkillStore`, `TaskSkillStore`, `UnifiedSkillSearch`, `SkillSearchResult`
- [ ] Export `ShortcutSkillStore`, `TaskSkillStore`, `UnifiedSkillSearch`, `SkillSearchResult` from `opengui/skills/__init__.py`

*Existing infrastructure covers pytest framework and asyncio configuration.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
