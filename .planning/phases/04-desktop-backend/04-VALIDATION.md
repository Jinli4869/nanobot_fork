---
phase: 4
slug: desktop-backend
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| **Quick run command** | `pytest tests/test_opengui_p4_desktop.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_opengui_p4_desktop.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | BACK-03 | unit | `pytest tests/test_opengui_p4_desktop.py::test_observe_returns_observation -x` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | BACK-03 | unit | `pytest tests/test_opengui_p4_desktop.py::test_observe_writes_png -x` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | BACK-03 | unit | `pytest tests/test_opengui_p4_desktop.py::test_execute_tap -x` | ❌ W0 | ⬜ pending |
| 04-01-04 | 01 | 1 | BACK-03 | unit | `pytest tests/test_opengui_p4_desktop.py::test_execute_scroll -x` | ❌ W0 | ⬜ pending |
| 04-01-05 | 01 | 1 | BACK-03 | unit | `pytest tests/test_opengui_p4_desktop.py::test_execute_input_text_uses_clipboard -x` | ❌ W0 | ⬜ pending |
| 04-01-06 | 01 | 1 | BACK-03 | unit | `pytest tests/test_opengui_p4_desktop.py::test_execute_swipe -x` | ❌ W0 | ⬜ pending |
| 04-01-07 | 01 | 1 | BACK-03 | unit | `pytest tests/test_opengui_p4_desktop.py::test_preflight_raises_on_permission_error -x` | ❌ W0 | ⬜ pending |
| 04-01-08 | 01 | 1 | BACK-03 | integration | `pytest tests/test_opengui_p4_desktop.py::test_gui_tool_builds_local_backend -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p4_desktop.py` — all BACK-03 unit + integration test stubs
- [ ] Existing `pytest` + `pytest-asyncio` infrastructure covers all needs

*No new framework config needed — pytest + pytest-asyncio already configured in pyproject.toml.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Running GuiAgent with LocalDesktopBackend on a real task completes without crashing | BACK-03 (SC4) | Requires real display + Accessibility permission | Run `python -m nanobot` with `backend: local` config on macOS; verify agent loop completes a simple task (e.g., "open Calculator") |
| HiDPI screenshot dimensions match pyautogui.size() | BACK-03 | Requires Retina display | Run smoke test: `mss.monitors[1]["width"] == pyautogui.size()[0]` on dev machine |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
