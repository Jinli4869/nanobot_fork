---
phase: 5
slug: cli-extensions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_opengui_p5_cli.py tests/test_opengui_p5_adapters.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_opengui_p5_cli.py tests/test_opengui_p5_adapters.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 0 | CLI-01 | unit | `pytest tests/test_opengui_p5_cli.py::test_cli_parses_task_and_backend_flags -x` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 0 | CLI-01 | unit | `pytest tests/test_opengui_p5_cli.py::test_load_config_env_fallback -x` | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 0 | CLI-01 | unit | `pytest tests/test_opengui_p5_cli.py::test_build_backend_variants -x` | ❌ W0 | ⬜ pending |
| 05-01-04 | 01 | 1 | CLI-01 | integration | `pytest tests/test_opengui_p5_cli.py::test_cli_runs_dry_run_agent_loop -x` | ❌ W0 | ⬜ pending |
| 05-01-05 | 01 | 1 | CLI-01 | integration | `pytest tests/test_opengui_p5_cli.py::test_cli_json_output -x` | ❌ W0 | ⬜ pending |
| 05-01-06 | 01 | 1 | CLI-01 | unit | `pytest tests/test_opengui_p5_cli.py::test_package_main_delegates_to_cli -x` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 1 | EXT-01 | docs | `pytest tests/test_opengui_p5_adapters.py::test_adapters_doc_contains_required_sections -x` | ❌ W0 | ⬜ pending |
| 05-02-02 | 02 | 1 | EXT-01 | docs | `pytest tests/test_opengui_p5_adapters.py::test_adapter_pointer_exists_in_code -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p5_cli.py` — parsing, config, backend factory, dry-run integration, and JSON output assertions
- [ ] `tests/test_opengui_p5_adapters.py` — adapter documentation and protocol-pointer assertions
- [ ] `pyproject.toml` — add runtime YAML dependency for `config.yaml`
- [ ] CLI test fixtures — fake provider + monkeypatched backend/agent seams so no live model, device, or desktop is required

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `python -m opengui.cli --backend adb --task "Open Settings"` runs a real agent loop | CLI-01 | Requires a real ADB device/emulator and configured model endpoint | Configure `~/.opengui/config.yaml`, connect a device, run the command, verify a non-error result plus generated trace/screenshot artifacts |
| `python -m opengui.cli --backend local --task "Open Chrome"` runs on the local desktop | CLI-01 | Requires a real desktop session and Accessibility / display permissions | Configure the CLI, run locally on macOS/Linux/Windows, verify the task completes without crashing and artifacts are written |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
