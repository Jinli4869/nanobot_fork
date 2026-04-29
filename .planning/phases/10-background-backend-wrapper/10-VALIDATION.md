---
phase: 10
slug: background-backend-wrapper
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-20
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.3.x |
| **Config file** | `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| **Quick run command** | `pytest tests/test_opengui_p10_background.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~3 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_opengui_p10_background.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | BGND-01 | unit | `pytest tests/test_opengui_p10_background.py::test_isinstance_device_backend -x` | ❌ W0 | ⬜ pending |
| 10-01-02 | 01 | 1 | BGND-01 | unit | `pytest tests/test_opengui_p10_background.py::test_preflight_calls_start_and_inner_preflight -x` | ❌ W0 | ⬜ pending |
| 10-01-03 | 01 | 1 | BGND-01 | unit | `pytest tests/test_opengui_p10_background.py::test_observe_before_preflight_raises -x` | ❌ W0 | ⬜ pending |
| 10-01-04 | 01 | 1 | BGND-01 | unit | `pytest tests/test_opengui_p10_background.py::test_async_context_manager -x` | ❌ W0 | ⬜ pending |
| 10-01-05 | 01 | 1 | BGND-02 | unit | `pytest tests/test_opengui_p10_background.py::test_display_env_set_after_preflight -x` | ❌ W0 | ⬜ pending |
| 10-01-06 | 01 | 1 | BGND-02 | unit | `pytest tests/test_opengui_p10_background.py::test_display_env_restored_after_shutdown -x` | ❌ W0 | ⬜ pending |
| 10-01-07 | 01 | 1 | BGND-02 | unit | `pytest tests/test_opengui_p10_background.py::test_noop_display_does_not_set_display_env -x` | ❌ W0 | ⬜ pending |
| 10-01-08 | 01 | 1 | BGND-03 | unit | `pytest tests/test_opengui_p10_background.py::test_zero_offset_passthrough -x` | ❌ W0 | ⬜ pending |
| 10-01-09 | 01 | 1 | BGND-03 | unit | `pytest tests/test_opengui_p10_background.py::test_nonzero_offset_applied -x` | ❌ W0 | ⬜ pending |
| 10-01-10 | 01 | 1 | BGND-03 | unit | `pytest tests/test_opengui_p10_background.py::test_relative_action_offset_skipped -x` | ❌ W0 | ⬜ pending |
| 10-01-11 | 01 | 1 | BGND-04 | unit | `pytest tests/test_opengui_p10_background.py::test_shutdown_stops_manager -x` | ❌ W0 | ⬜ pending |
| 10-01-12 | 01 | 1 | BGND-04 | unit | `pytest tests/test_opengui_p10_background.py::test_shutdown_idempotent -x` | ❌ W0 | ⬜ pending |
| 10-01-13 | 01 | 1 | BGND-04 | unit | `pytest tests/test_opengui_p10_background.py::test_shutdown_suppresses_stop_error -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p10_background.py` — stubs for BGND-01 through BGND-04 (all 13 test cases)
- [ ] No new framework config needed — `asyncio_mode = "auto"` in `pyproject.toml` covers async tests

*Existing infrastructure covers framework requirements.*

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
