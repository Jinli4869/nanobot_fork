---
phase: 17
slug: web-runtime-boundary
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-21
---

# Phase 17 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.3+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` - `asyncio_mode = "auto"` |
| **Wave 1 quick command** | `uv run --extra dev pytest tests/test_tui_p17_runtime.py -q` |
| **Wave 2 quick command** | `uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py -q` |
| **Full suite command** | `uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_commands.py tests/test_session_manager_history.py tests/test_config_paths.py -q` |
| **Estimated runtime** | ~35 seconds |

---

## Sampling Rate

- **After every Wave 1 task commit:** Run `uv run --extra dev pytest tests/test_tui_p17_runtime.py -q`
- **After every Wave 2 task commit:** Run `uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py -q`
- **After every plan wave:** Run the highest completed-wave command, then the full suite at the end of Wave 2
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 35 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 1 | ISO-01 | unit | `uv run --extra dev pytest tests/test_tui_p17_runtime.py::test_create_app_builds_isolated_tui_routes tests/test_tui_p17_runtime.py::test_tui_service_contracts_are_lazy_and_typed tests/test_tui_p17_runtime.py::test_task_launch_contract_is_declared_without_mutating_routes -q` | ❌ W0 | ⬜ pending |
| 17-01-02 | 01 | 1 | ISO-01 | unit | `uv run --extra dev pytest tests/test_tui_p17_runtime.py -q` | ❌ W0 | ⬜ pending |
| 17-02-01 | 02 | 2 | ISO-02 | unit | `uv run --extra dev pytest tests/test_tui_p17_config.py::test_tui_defaults_bind_to_localhost tests/test_tui_p17_config.py::test_load_config_accepts_explicit_tui_section tests/test_tui_p17_config.py::test_tui_runtime_normalization_does_not_reuse_gateway_defaults -q` | ❌ W0 | ⬜ pending |
| 17-02-02 | 02 | 2 | ISO-01, ISO-02 | integration | `uv run --extra dev pytest tests/test_tui_p17_runtime.py::test_tui_routes_expose_read_only_session_runtime_and_task_contracts tests/test_tui_p17_config.py::test_tui_startup_wiring_uses_create_app_and_local_runtime_config tests/test_tui_p17_config.py::test_tui_module_import_does_not_boot_cli_runtime tests/test_commands.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_tui_p17_runtime.py` - app factory, router isolation, typed adapter-contract coverage, and later read-only route exposure
- [ ] `tests/test_tui_p17_config.py` - local-first defaults and startup regression coverage
- [ ] `fastapi` / `uvicorn[standard]` added to both `web` and `dev` dependency extras so all Phase 17 validation can run via `uv run --extra dev pytest ...`

*Existing pytest infrastructure covers the framework requirements once the new test files exist.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Local developer can start the backend on localhost and reach the health route | ISO-02 | Final port binding and local host behavior are easiest to confirm with a real local startup | Run the chosen dev startup command, confirm it binds to `127.0.0.1`, and hit the health endpoint from the same machine |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency < 35s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
