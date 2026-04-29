---
phase: 13
slug: macos-background-execution
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-20
---

# Phase 13 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.3+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` - `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py -q` |
| **Full suite command** | `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | MAC-01 | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_probe_macos_virtual_display_available -q` | ✅ | ⬜ pending |
| 13-01-02 | 01 | 1 | MAC-02 | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_probe_reports_actionable_permission_remediation tests/test_opengui_p13_macos_display.py::test_probe_reports_macos_version_unsupported -q` | ✅ | ⬜ pending |
| 13-02-01 | 02 | 2 | MAC-03 | unit | `uv run pytest tests/test_opengui_p4_desktop.py::test_observe_uses_configured_monitor_index tests/test_opengui_p4_desktop.py::test_observe_defaults_to_primary_monitor_when_target_display_missing -q` | ✅ | ⬜ pending |
| 13-02-02 | 02 | 2 | MAC-03 | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_background_wrapper_configures_target_display_before_preflight tests/test_opengui_p13_macos_display.py::test_macos_target_surface_routing_keeps_observe_and_execute_aligned -q` | ✅ | ⬜ pending |
| 13-03-01 | 03 | 3 | MAC-01 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_uses_cgvirtualdisplay_manager_for_macos_isolated_mode tests/test_opengui_p5_cli.py::test_run_cli_logs_macos_permission_remediation_before_agent_start -q` | ✅ | ⬜ pending |
| 13-03-02 | 03 | 3 | MAC-02 | integration | `uv run pytest tests/test_opengui_p11_integration.py::test_gui_tool_uses_cgvirtualdisplay_manager_for_macos_isolated_mode tests/test_opengui_p11_integration.py::test_gui_tool_surfaces_macos_permission_remediation_for_background_fallback -q` | ✅ | ⬜ pending |
| 13-04-01 | 04 | 4 | MAC-01 | suite | `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q` | ✅ | ⬜ pending |
| 13-04-02 | 04 | 4 | MAC-03 | manual | `.planning/phases/13-macos-background-execution/13-MANUAL-SMOKE.md` checklist completed on a real macOS host | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_opengui_p13_macos_display.py` - new probe, manager, and routing contract coverage
- [x] `tests/test_opengui_p4_desktop.py` additions - target monitor selection coverage
- [x] `tests/test_opengui_p5_cli.py` additions - CLI macOS isolated manager and remediation ordering coverage
- [x] `tests/test_opengui_p11_integration.py` additions - nanobot macOS isolated manager and remediation coverage

*Existing pytest infrastructure covers the framework requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real macOS host can create and tear down the isolated target display | MAC-01 | `CGVirtualDisplay` viability and topology behavior are platform-specific and cannot be honestly exercised in generic CI | Follow `13-MANUAL-SMOKE.md` `Supported Host` and confirm isolated mode logs `macos_virtual_display_available`, captures the target monitor, and tears down cleanly |
| Permission-denied flows point to the right remediation path before automation begins | MAC-02 | CI can mock the message shape, but real TCC dialogs and host policy behavior must be checked on macOS | Follow `13-MANUAL-SMOKE.md` `Denied Permissions` and confirm the run blocks or warns before the first agent step with `System Settings > Privacy & Security` remediation |
| Non-zero offsets and scaled layouts keep capture/input aligned | MAC-03 | Real display topology and Retina scaling behavior cannot be fully trusted from mocks alone | Follow `13-MANUAL-SMOKE.md` `Scaled / Offset Layout` with a non-zero-origin display and a tap/drag scenario |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or a manual-only verification dependency
- [x] Sampling continuity: no 3 consecutive tasks without automated verification
- [x] Wave 0 covers all new test references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
