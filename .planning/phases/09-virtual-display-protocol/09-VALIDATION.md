---
phase: 9
slug: virtual-display-protocol
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| **Quick run command** | `python -m pytest tests/test_virtual_display.py tests/test_xvfb.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_virtual_display.py tests/test_xvfb.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | VDISP-01 | unit | `pytest tests/test_virtual_display.py::test_protocol_importable -x` | ❌ W0 | ⬜ pending |
| 09-01-02 | 01 | 1 | VDISP-02 | unit | `pytest tests/test_virtual_display.py::test_display_info_frozen -x` | ❌ W0 | ⬜ pending |
| 09-01-03 | 01 | 1 | VDISP-03 | unit | `pytest tests/test_virtual_display.py::test_noop_manager -x` | ❌ W0 | ⬜ pending |
| 09-02-01 | 02 | 1 | VDISP-04 | unit | `pytest tests/test_xvfb.py::test_xvfb_start_stop -x` | ❌ W0 | ⬜ pending |
| 09-02-02 | 02 | 1 | VDISP-04 | unit | `pytest tests/test_xvfb.py::test_xvfb_not_found -x` | ❌ W0 | ⬜ pending |
| 09-02-03 | 02 | 1 | VDISP-04 | unit | `pytest tests/test_xvfb.py::test_xvfb_auto_increment -x` | ❌ W0 | ⬜ pending |
| 09-02-04 | 02 | 1 | VDISP-04 | unit | `pytest tests/test_xvfb.py::test_xvfb_crash_detection -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_virtual_display.py` — stubs for VDISP-01, VDISP-02, VDISP-03
- [ ] `tests/test_xvfb.py` — stubs for VDISP-04 (mocked subprocess)
- [ ] `tests/conftest.py` — shared fixtures (if needed)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Xvfb launches real process | VDISP-04 | Requires Xvfb binary installed | Install xvfb, run `python -c "import asyncio; from opengui.backends.displays.xvfb import XvfbDisplayManager; m=XvfbDisplayManager(); asyncio.run(m.start()); asyncio.run(m.stop())"` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
