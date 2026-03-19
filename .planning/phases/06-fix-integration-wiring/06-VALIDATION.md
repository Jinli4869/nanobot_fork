---
phase: 6
slug: fix-integration-wiring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py -x -q` |
| **Full suite command** | `PATH="$(pwd)/.venv/bin:$PATH" ./.venv/bin/python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py -x -q`
- **After every plan wave:** Run `PATH="$(pwd)/.venv/bin:$PATH" ./.venv/bin/python -m pytest tests/ -x -q`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 0 | NANO-03 | unit | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_gui_config_accepts_embedding_model_alias -x -q` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 0 | NANO-03 | unit | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_gui_tool_wires_embedding_adapter_when_configured -x -q` | ❌ W0 | ⬜ pending |
| 06-01-03 | 01 | 0 | NANO-03 | unit | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_gui_tool_skips_embedding_adapter_without_config -x -q` | ❌ W0 | ⬜ pending |
| 06-01-04 | 01 | 0 | BACK-03 | packaging | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_pyproject_declares_pillow_for_desktop_and_dev -x -q` | ❌ W0 | ⬜ pending |
| 06-01-05 | 01 | 0 | CLI-01 | packaging | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_pyproject_declares_opengui_console_script -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p6_wiring.py` — config field, embedding adapter wiring, and packaging metadata assertions
- [ ] `GuiConfig.embedding_model` — config surface for the optional embedding path
- [ ] `GuiSubagentTool` embedding wrapper — `litellm.aembedding(...)` normalized into `numpy.float32`
- [ ] `pyproject.toml` — `Pillow>=10.0` in `desktop` and `dev`, plus `opengui = "opengui.cli:main"` in `[project.scripts]`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `pip install .[desktop]` succeeds and `python -c "from PIL import Image"` exits 0 | BACK-03 | Requires a real install transaction in a clean environment | Create a clean virtualenv, run `pip install .[desktop]`, then run the import check |
| installed `opengui --help` resolves the console script entry point | CLI-01 | Requires package installation to validate generated wrapper scripts | Install the package into a clean virtualenv and run `opengui --help` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
