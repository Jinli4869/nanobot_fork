---
phase: 31
slug: shortcut-observability-and-regression-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 31 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest with pytest-asyncio |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run python -m pytest tests/test_opengui_p31_shortcut_observability.py -x -q --tb=short` |
| **Full suite command** | `uv run python -m pytest tests/ -q --tb=short` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run python -m pytest tests/test_opengui_p31_shortcut_observability.py -x -q --tb=short`
- **After every plan wave:** Run `uv run python -m pytest tests/ -q --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 31-01-01 | 01 | 1 | SSTA-03 | unit | `pytest tests/ -k "test_grounding_telemetry" -x -q` | ❌ W0 | ⬜ pending |
| 31-01-02 | 01 | 1 | SSTA-03 | unit | `pytest tests/ -k "test_settle_telemetry" -x -q` | ❌ W0 | ⬜ pending |
| 31-01-03 | 01 | 1 | SSTA-03 | unit | `pytest tests/ -k "test_full_trace_event_coverage" -x -q` | ❌ W0 | ⬜ pending |
| 31-02-01 | 02 | 2 | SSTA-04 | integration-safe | `pytest tests/ -k "test_android_extraction_execution_seam" -x -q` | ❌ W0 | ⬜ pending |
| 31-02-02 | 02 | 2 | SSTA-04 | integration-safe | `pytest tests/ -k "test_macos_extraction_execution_seam" -x -q` | ❌ W0 | ⬜ pending |
| 31-02-03 | 02 | 2 | SSTA-04 | regression | `pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py tests/test_opengui_p30_stable_shortcut_execution.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p31_shortcut_observability.py` — stubs for SSTA-03 (grounding/settle telemetry) and SSTA-04 (android + desktop seams)

*Existing test infrastructure covers all prior-phase regression checks; only the new Phase 31 file is missing.*
*Plan 02 verification is Wave 2 because it appends seam coverage to the shared Phase 31 test module created/populated by Plan 01.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Grounding + settle events appear in a real JSONL trace artifact on a live device run | SSTA-03 | Live device runs cannot be automated in CI per established repo convention | Run a shortcut-eligible task on a real Android or macOS device; inspect the resulting `.jsonl` trace file for `shortcut_grounding` and `shortcut_settle` event entries |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
