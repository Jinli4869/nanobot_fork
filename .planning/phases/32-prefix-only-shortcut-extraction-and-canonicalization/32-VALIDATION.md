---
phase: 32
slug: prefix-only-shortcut-extraction-and-canonicalization
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-07
---

# Phase 32 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p31_shortcut_observability.py -k "dynamic_fields_beyond_input_text or placeholder_explosion or reusable_boundary or canonicalizes_duplicate_waits or richer_state_evidence or canonicalized_prefix or grounded_placeholders" -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~28 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p31_shortcut_observability.py -k "dynamic_fields_beyond_input_text or placeholder_explosion or reusable_boundary or canonicalizes_duplicate_waits or richer_state_evidence or canonicalized_prefix or grounded_placeholders" -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p30_stable_shortcut_execution.py tests/test_opengui_p31_shortcut_observability.py -q`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 28 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 32-01-01 | 01 | 1 | SXTR-05,SXTR-06 | unit | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py -k "reusable_boundary or canonicalizes_duplicate_waits or richer_state_evidence" -q` | ✅ | ⬜ pending |
| 32-01-02 | 01 | 1 | SXTR-05,SXTR-06 | unit | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py -k "reusable_boundary or canonicalizes_duplicate_waits or richer_state_evidence" -q` | ✅ | ⬜ pending |
| 32-02-01 | 02 | 2 | SXTR-07 | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -k "dynamic_fields_beyond_input_text or placeholder_explosion" -q` | ✅ | ⬜ pending |
| 32-02-02 | 02 | 2 | SXTR-07 | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -k "dynamic_fields_beyond_input_text or placeholder_explosion" -q` | ✅ | ⬜ pending |
| 32-03-01 | 03 | 3 | SXTR-05,SXTR-06,SXTR-07 | integration | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p31_shortcut_observability.py -k "canonicalized_prefix or grounded_placeholders" -q` | ✅ | ⬜ pending |
| 32-03-02 | 03 | 3 | SXTR-05,SXTR-06,SXTR-07 | integration | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p30_stable_shortcut_execution.py tests/test_opengui_p31_shortcut_observability.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p28_shortcut_productionization.py` — add canonicalization-specific cases for duplicate waits, repeated unchanged-UI taps, and richer prefix-boundary decisions
- [ ] `tests/test_opengui_p26_quality_gated_extraction.py` — add broader placeholder inference cases beyond `input_text.text`
- [ ] `tests/test_opengui_p31_shortcut_observability.py` — add end-to-end seam coverage showing canonicalized promoted steps still execute with grounding

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
