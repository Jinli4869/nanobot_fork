---
phase: 26
slug: quality-gated-extraction
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 26 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=9.0.0,<10.0.0 + pytest-asyncio >=1.3.0,<2.0.0 |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p24_schema_grounding.py tests/test_opengui_p25_multi_layer_execution.py -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 26-01-01 | 01 | 0 | EXTR-01..04 | stub | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q` | ❌ W0 | ⬜ pending |
| 26-01-02 | 01 | 1 | EXTR-01 | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q -k step_critic` | ❌ W0 | ⬜ pending |
| 26-01-03 | 01 | 1 | EXTR-02 | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q -k trajectory_critic` | ❌ W0 | ⬜ pending |
| 26-01-04 | 01 | 2 | EXTR-03 | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q -k pipeline` | ❌ W0 | ⬜ pending |
| 26-01-05 | 01 | 2 | EXTR-04 | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q -k producer` | ❌ W0 | ⬜ pending |
| 26-01-06 | 01 | 2 | Phase 26 | smoke | `uv run python -m py_compile opengui/skills/shortcut_extractor.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p26_quality_gated_extraction.py` — stubs for EXTR-01 through EXTR-04
- [ ] `opengui/skills/shortcut_extractor.py` — new module (empty stub or TDD RED stubs)
- [ ] Add Phase 26 public symbols to `opengui/skills/__init__.py` exports

*Wave 0 must be completed before any implementation tasks.*

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
