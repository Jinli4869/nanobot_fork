---
phase: 11
slug: integration-tests
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-20
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.3+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| **Quick run command** | `.venv/bin/pytest tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | INTG-01 | unit | `.venv/bin/pytest tests/test_opengui_p5_cli.py::test_cli_parses_background_flags -x` | ❌ W0 | ⬜ pending |
| 11-01-02 | 01 | 1 | INTG-01 | unit | `.venv/bin/pytest tests/test_opengui_p5_cli.py::test_background_implies_local_backend -x` | ❌ W0 | ⬜ pending |
| 11-02-01 | 02 | 1 | INTG-02 | unit | `.venv/bin/pytest tests/test_opengui_p11_integration.py::test_guiconfig_background_fields -x` | ❌ W0 | ⬜ pending |
| 11-02-02 | 02 | 1 | INTG-02 | unit | `.venv/bin/pytest tests/test_opengui_p11_integration.py::test_guiconfig_background_requires_local -x` | ❌ W0 | ⬜ pending |
| 11-03-01 | 01 | 1 | INTG-03 | integration | `.venv/bin/pytest tests/test_opengui_p5_cli.py::test_run_cli_background_wraps_backend -x` | ❌ W0 | ⬜ pending |
| 11-03-02 | 01 | 1 | INTG-03 | unit | `.venv/bin/pytest tests/test_opengui_p5_cli.py::test_run_cli_background_nonlinux_fallback -x` | ❌ W0 | ⬜ pending |
| 11-04-01 | 02 | 1 | INTG-04 | integration | `.venv/bin/pytest tests/test_opengui_p11_integration.py::test_gui_tool_execute_background_wraps_backend -x` | ❌ W0 | ⬜ pending |
| 11-04-02 | 02 | 1 | INTG-04 | unit | `.venv/bin/pytest tests/test_opengui_p11_integration.py::test_gui_tool_execute_background_nonlinux_fallback -x` | ❌ W0 | ⬜ pending |
| 11-05-01 | 01/02 | 2 | TEST-V11-01 | suite | `.venv/bin/pytest tests/ -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p11_integration.py` — stubs for INTG-02, INTG-04
- [ ] `tests/test_opengui_p5_cli.py` additions — stubs for INTG-01, INTG-03
- [ ] Framework install: already present — pytest and pytest-asyncio in `pyproject.toml`

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
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
