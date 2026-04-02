---
phase: 28
slug: shortcut-extraction-productionization
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 28 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_opengui_p8_trajectory.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py` |
| **Full suite command** | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p8_trajectory.py tests/test_opengui_p11_integration.py tests/test_opengui_p28_shortcut_productionization.py` |
| **Estimated runtime** | ~20 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p8_trajectory.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p8_trajectory.py tests/test_opengui_p11_integration.py tests/test_opengui_p28_shortcut_productionization.py`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 28-01-01 | 01 | 1 | SXTR-01 | unit/integration | `uv run pytest tests/test_opengui_p8_trajectory.py tests/test_opengui_p28_shortcut_productionization.py -k "promotion or postprocessing or final_successful_attempt"` | ❌ W0 | ⬜ pending |
| 28-01-02 | 01 | 1 | SXTR-01 | unit/integration | `uv run pytest tests/test_opengui_p8_trajectory.py tests/test_opengui_p28_shortcut_productionization.py -k "promotion or postprocessing or final_successful_attempt"` | ❌ W0 | ⬜ pending |
| 28-02-01 | 02 | 2 | SXTR-02 | unit/integration | `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py -k "provenance or promotion_store_roundtrip or low_value or add_or_merge or round_trip"` | ❌ W0 | ⬜ pending |
| 28-02-02 | 02 | 2 | SXTR-02,SXTR-03,SXTR-04 | unit/integration | `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py -k "provenance or promotion_store_roundtrip or low_value or add_or_merge or round_trip"` | ❌ W0 | ⬜ pending |
| 28-03-01 | 03 | 3 | SXTR-04 | unit/integration | `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py -k "summary_result_noise or retry_noise or duplicate_promotions or canonical"` | ❌ W0 | ⬜ pending |
| 28-03-02A | 03 | 3 | SXTR-01,SXTR-02,SXTR-03,SXTR-04 | integration | `uv run pytest tests/test_opengui_p8_trajectory.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py` | ❌ W0 | ⬜ pending |
| 28-03-02B | 03 | 3 | SXTR-01,SXTR-02,SXTR-03,SXTR-04 | integration/full-slice | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p8_trajectory.py tests/test_opengui_p11_integration.py tests/test_opengui_p28_shortcut_productionization.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p28_shortcut_productionization.py` — phase-local promotion, provenance, gating, and dedup/version tests
- [ ] Extend `tests/test_opengui_p8_trajectory.py` — assert GUI postprocessing still returns immediately and promotion failures stay non-fatal
- [ ] Extend `tests/test_opengui_p27_storage_search_agent.py` — prove shortcut store still round-trips and searches with added metadata/version behavior
- [ ] Extend `tests/test_opengui_p11_integration.py` — keep GUI tool integration confidence after the promotion seam replaces the legacy extractor

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
