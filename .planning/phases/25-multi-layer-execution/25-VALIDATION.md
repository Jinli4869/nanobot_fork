---
phase: 25
slug: multi-layer-execution
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-02
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~20 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p24_schema_grounding.py tests/test_opengui_p1_skills.py tests/test_opengui_p25_multi_layer_execution.py -q`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 25-01-01 | 01 | 1 | EXEC-01 | unit | `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q -k contract` | ❌ W0 | ⬜ pending |
| 25-01-02 | 01 | 1 | EXEC-03 | unit | `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q -k grounder` | ❌ W0 | ⬜ pending |
| 25-02-01 | 02 | 2 | EXEC-02 | unit | `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q -k task_executor` | ❌ W0 | ⬜ pending |
| 25-02-02 | 02 | 2 | Phase 25 SC-4 | regression | `uv run pytest tests/test_opengui_p24_schema_grounding.py tests/test_opengui_p1_skills.py tests/test_opengui_p25_multi_layer_execution.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p25_multi_layer_execution.py` — covers EXEC-01, EXEC-02, EXEC-03 with stub backend, grounder, evaluator, and resolver seams
- [ ] Reuse `tests/test_opengui_p24_schema_grounding.py` — guard Phase 24 schema/grounding contracts while executors are added
- [ ] Reuse `tests/test_opengui_p1_skills.py` — guard legacy skill exports and executor compatibility while new exports land

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | — | Phase 25 behaviors should be fully automatable with stubbed backend and grounder seams | No manual-only verification expected |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
