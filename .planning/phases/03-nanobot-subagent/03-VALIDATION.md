---
phase: 3
slug: nanobot-subagent
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `pytest tests/test_opengui_p3_nanobot.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_opengui_p3_nanobot.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | NANO-01 | unit | `pytest tests/test_opengui_p3_nanobot.py::test_gui_tool_registered -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | NANO-02 | unit | `pytest tests/test_opengui_p3_nanobot.py::test_llm_adapter_maps_response -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | NANO-02 | unit | `pytest tests/test_opengui_p3_nanobot.py::test_llm_adapter_empty_tool_calls -x` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | NANO-03 | unit | `pytest tests/test_opengui_p3_nanobot.py::test_backend_selection -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | NANO-04 | integration | `pytest tests/test_opengui_p3_nanobot.py::test_trajectory_saved_to_workspace -x` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | NANO-05 | integration | `pytest tests/test_opengui_p3_nanobot.py::test_auto_skill_extraction -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p3_nanobot.py` — stubs for NANO-01 through NANO-05
- [ ] Reuse `_FakeEmbedder`, `_ScriptedLLM` patterns from existing test files
- [ ] Use `DryRunBackend` from opengui for integration tests (no real device needed)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| ADB backend connects to real device | NANO-03 | Requires physical Android device | Connect device, set `gui.backend: adb` in config, run `GuiSubagentTool.execute(task="open settings")` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
