---
phase: 14
slug: windows-isolated-desktop-execution
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-20
---

# Phase 14 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.3+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` - `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_probe_windows_isolated_desktop_available tests/test_opengui_p14_windows_desktop.py::test_windows_isolated_backend_launches_worker_on_named_desktop -q` |
| **Full suite command** | `uv run pytest tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q` |
| **Estimated runtime** | ~28 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_probe_windows_isolated_desktop_available tests/test_opengui_p14_windows_desktop.py::test_windows_isolated_backend_launches_worker_on_named_desktop -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 28 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 1 | WIN-01 | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_probe_windows_isolated_desktop_available tests/test_opengui_p14_windows_desktop.py::test_win32desktop_manager_returns_display_info -q` | ❌ W0 | ⬜ pending |
| 14-01-02 | 01 | 1 | WIN-02 | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_probe_reports_non_interactive_windows_context tests/test_opengui_p14_windows_desktop.py::test_probe_reports_unsupported_app_class_with_actionable_message -q` | ❌ W0 | ⬜ pending |
| 14-01-03 | 01 | 1 | WIN-03 | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_win32desktop_manager_stop_is_idempotent -q` | ❌ W0 | ⬜ pending |
| 14-02-01 | 02 | 2 | WIN-01 | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_windows_isolated_backend_launches_worker_on_named_desktop tests/test_opengui_p14_windows_desktop.py::test_windows_isolated_backend_observe_and_execute_use_target_desktop -q` | ❌ W0 | ⬜ pending |
| 14-02-02 | 02 | 2 | WIN-03 | unit | `uv run pytest tests/test_opengui_p14_windows_desktop.py::test_windows_isolated_backend_cleans_up_on_cancellation tests/test_opengui_p14_windows_desktop.py::test_windows_isolated_backend_cleans_up_after_startup_failure -q` | ❌ W0 | ⬜ pending |
| 14-03-01 | 03 | 3 | WIN-01 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_uses_windows_isolated_desktop_backend_for_windows_isolated_mode tests/test_opengui_p11_integration.py::test_gui_tool_uses_windows_isolated_desktop_backend_for_windows_isolated_mode -q` | ✅ | ⬜ pending |
| 14-03-02 | 03 | 3 | WIN-02 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_warns_for_windows_unsupported_app_class_before_agent_start tests/test_opengui_p11_integration.py::test_gui_tool_blocks_windows_non_interactive_isolation_request -q` | ✅ | ⬜ pending |
| 14-03-03 | 03 | 3 | WIN-03 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_logs_windows_target_surface_metadata tests/test_opengui_p11_integration.py::test_gui_tool_reports_windows_cleanup_reason_codes_in_failure_payload -q` | ✅ | ⬜ pending |
| 14-04-01 | 04 | 4 | WIN-01 | suite | `uv run pytest tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q` | ✅ | ⬜ pending |
| 14-04-02 | 04 | 4 | WIN-03 | manual | `.planning/phases/14-windows-isolated-desktop-execution/14-MANUAL-SMOKE.md` checklist completed on a real Windows host | ❌ P4 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_opengui_p14_windows_desktop.py` - new probe, manager, lifecycle, and cleanup coverage
- [x] `tests/test_opengui_p5_cli.py` additions - Windows isolated manager selection, warning/block ordering, and trace metadata coverage
- [x] `tests/test_opengui_p11_integration.py` additions - nanobot Windows isolated manager selection and remediation coverage

*Existing pytest infrastructure covers the framework requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Classic Win32 app launches and renders on the alternate desktop without switching the user away | WIN-01 | Real alternate-desktop rendering and process launch behavior cannot be trusted from mocks alone | Follow `14-MANUAL-SMOKE.md` `Supported Win32 App` and confirm the run logs `windows_isolated_desktop_available`, launches inside the isolated desktop, and the user desktop remains unchanged |
| Unsupported app classes are warned or blocked before automation begins | WIN-02 | Real app-class behavior depends on OS/runtime integration and cannot be represented honestly in CI | Follow `14-MANUAL-SMOKE.md` `Unsupported App Class` with a UWP, DirectX, or GPU-heavy app and confirm the warning/block message appears before the first agent step |
| Success, failure, and cancellation all clean up desktop handles and child processes | WIN-03 | Handle leaks and child-process teardown need a real Windows host to validate end to end | Follow `14-MANUAL-SMOKE.md` `Cleanup Paths` and confirm no orphaned desktops/processes remain after normal exit, forced failure, and cancellation |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or a manual-only verification dependency
- [x] Sampling continuity: no 3 consecutive tasks without automated verification
- [x] Wave 0 covers all new test references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
