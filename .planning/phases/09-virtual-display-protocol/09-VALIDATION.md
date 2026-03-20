---
phase: 9
slug: virtual-display-protocol
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-20
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/test_opengui_p9_virtual_display.py tests/test_opengui_p9_xvfb.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_opengui_p9_virtual_display.py tests/test_opengui_p9_xvfb.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 09-00-01 | 00 | 1 | VDISP-01..04 | stub | `pytest tests/test_opengui_p9_virtual_display.py tests/test_opengui_p9_xvfb.py -v --tb=no` | W0 creates | ⬜ pending |
| 09-01-01 | 01 | 2 | VDISP-01 | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_protocol_importable -x` | W0 stub | ⬜ pending |
| 09-01-02 | 01 | 2 | VDISP-02 | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_display_info_frozen -x` | W0 stub | ⬜ pending |
| 09-01-03 | 01 | 2 | VDISP-03 | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_noop_start_returns_display_info -x` | W0 stub | ⬜ pending |
| 09-02-01 | 02 | 2 | VDISP-04 | unit | `pytest tests/test_opengui_p9_xvfb.py::test_xvfb_start_returns_display_info -x` | W0 stub | ⬜ pending |
| 09-02-02 | 02 | 2 | VDISP-04 | unit | `pytest tests/test_opengui_p9_xvfb.py::test_xvfb_not_found_error -x` | W0 stub | ⬜ pending |
| 09-02-03 | 02 | 2 | VDISP-04 | unit | `pytest tests/test_opengui_p9_xvfb.py::test_xvfb_auto_increment -x` | W0 stub | ⬜ pending |
| 09-02-04 | 02 | 2 | VDISP-04 | unit | `pytest tests/test_opengui_p9_xvfb.py::test_xvfb_crash_detection -x` | W0 stub | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_opengui_p9_virtual_display.py` — xfail stubs for VDISP-01, VDISP-02, VDISP-03 (Plan 00)
- [x] `tests/test_opengui_p9_xvfb.py` — xfail stubs for VDISP-04 with guarded imports (Plan 00)
- [ ] `tests/conftest.py` — shared fixtures (if needed)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Xvfb launches real process | VDISP-04 | Requires Xvfb binary installed | Install xvfb, run `python -c "import asyncio; from opengui.backends.displays.xvfb import XvfbDisplayManager; m=XvfbDisplayManager(); asyncio.run(m.start()); asyncio.run(m.stop())"` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
