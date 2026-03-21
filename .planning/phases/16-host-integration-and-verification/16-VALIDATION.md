---
phase: 16
slug: host-integration-and-verification
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-21
---

# Phase 16 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.3+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` - `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_opengui_p16_host_integration.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -k "phase16 or background_decision_tokens or cleanup_and_intervention" -q` |
| **Full suite command** | `uv run pytest tests/test_opengui_p16_host_integration.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p10_background.py tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p13_macos_display.py tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p15_intervention.py -q` |
| **Estimated runtime** | ~35 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task-specific command from the Per-Task Verification Map below; for early parity work default to `uv run pytest tests/test_opengui_p16_host_integration.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -k "phase16 or background_decision_tokens or cleanup_and_intervention" -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p16_host_integration.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p10_background.py tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p13_macos_display.py tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p15_intervention.py -q`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 35 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | INTG-05 | unit/integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_background_decision_tokens_stay_consistent_across_supported_hosts tests/test_opengui_p5_cli.py::test_run_cli_handoff_and_cleanup_tokens_stay_visible_without_leaking_sensitive_reason -q` | ❌ W0 | ⬜ pending |
| 16-01-02 | 01 | 1 | INTG-05 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_background_decision_tokens_stay_consistent_across_supported_hosts tests/test_opengui_p5_cli.py::test_run_cli_handoff_and_cleanup_tokens_stay_visible_without_leaking_sensitive_reason tests/test_opengui_p5_cli.py::test_run_cli_warns_for_windows_unsupported_app_class_before_agent_start -q` | ✅ | ⬜ pending |
| 16-02-01 | 02 | 1 | INTG-06 | unit/integration | `uv run pytest tests/test_opengui_p11_integration.py::test_gui_tool_background_decision_tokens_stay_consistent_across_supported_hosts tests/test_opengui_p11_integration.py::test_gui_tool_preserves_cleanup_and_intervention_tokens_in_structured_payloads -q` | ❌ W0 | ⬜ pending |
| 16-02-02 | 02 | 1 | INTG-06 | integration | `uv run pytest tests/test_opengui_p11_integration.py::test_gui_tool_background_decision_tokens_stay_consistent_across_supported_hosts tests/test_opengui_p11_integration.py::test_gui_tool_preserves_cleanup_and_intervention_tokens_in_structured_payloads tests/test_opengui_p11_integration.py::test_gui_tool_blocks_windows_unsupported_app_class_before_agent_start -q` | ✅ | ⬜ pending |
| 16-03-01 | 03 | 2 | INTG-05, INTG-06 | unit | `uv run pytest tests/test_opengui_p16_host_integration.py::test_cli_and_gui_tool_share_windows_default_app_class_contract tests/test_opengui_p16_host_integration.py::test_cli_and_gui_tool_share_reason_codes_and_remediation_copy tests/test_opengui_p16_host_integration.py::test_phase16_host_matrix_preserves_cleanup_and_intervention_tokens -q` | ❌ W0 | ⬜ pending |
| 16-03-02 | 03 | 2 | TEST-V12-01 | suite | `uv run pytest tests/test_opengui_p16_host_integration.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p10_background.py tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p13_macos_display.py tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p15_intervention.py -q` | ❌ W0 | ⬜ pending |
| 16-04-01 | 04 | 3 | TEST-V12-01 | suite | `uv run pytest tests/test_opengui_p16_host_integration.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p10_background.py tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p13_macos_display.py tests/test_opengui_p14_windows_desktop.py tests/test_opengui_p15_intervention.py -q` | ❌ W0 | ⬜ pending |
| 16-04-02 | 04 | 3 | INTG-05, INTG-06, TEST-V12-01 | docs/traceability | `rg -n "^## Linux Xvfb Regression|^## macOS Capability Messaging|^## Windows Isolated Desktop and App Class|^## Intervention and Cleanup Closeout|BGND-05|BGND-06|BGND-07|MAC-01|MAC-02|MAC-03|WIN-01|WIN-02|WIN-03|SAFE-01|SAFE-02|SAFE-03|SAFE-04|INTG-05|INTG-06|TEST-V12-01" .planning/phases/16-host-integration-and-verification/16-MANUAL-SMOKE.md .planning/phases/16-host-integration-and-verification/16-VERIFICATION.md` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p16_host_integration.py` - phase-local parity matrix for shared CLI/nanobot behavior
- [ ] `tests/test_opengui_p5_cli.py` additions - CLI decision-token, cleanup-token, and scrubbed intervention-output coverage
- [ ] `tests/test_opengui_p11_integration.py` additions - nanobot parity coverage for reason tokens, cleanup evidence, and scrubbed intervention results
- [ ] Existing pytest infrastructure already covers framework setup; no new test framework install is required

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Linux background mode still reports isolated/fallback behavior honestly when Xvfb is present or missing | TEST-V12-01 | Requires a real Linux host environment with and without the Xvfb binary available | Follow `16-MANUAL-SMOKE.md` Linux section and compare CLI plus nanobot operator-visible behavior |
| macOS capability, permission-remediation, and isolated-mode messaging stay aligned between CLI and nanobot | INTG-05, INTG-06 | Real macOS permissions and CGVirtualDisplay availability cannot be validated honestly from this host | Follow `16-MANUAL-SMOKE.md` macOS section and record the first supportability or remediation message from both hosts |
| Windows isolated-desktop support, unsupported app-class behavior, and cleanup evidence stay aligned between CLI and nanobot | INTG-05, INTG-06, TEST-V12-01 | Real alternate-desktop rendering, cleanup leaks, and app-class behavior need a Windows interactive session | Follow `16-MANUAL-SMOKE.md` Windows section and record `display_id`, `desktop_name`, `windows_app_class_unsupported`, and `cleanup_reason=...` evidence |
| Intervention handoff output remains scrubbed while preserving safe target metadata and lifecycle tokens | TEST-V12-01 | Needs a real handoff flow and inspection of host-visible output plus trace artifacts | Follow `16-MANUAL-SMOKE.md` intervention section and verify CLI/nanobot surface scrubbed reasons and safe target keys only |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or a manual-only verification dependency
- [x] Sampling continuity: no 3 consecutive tasks without automated verification
- [x] Wave 0 covers all new test references
- [x] No watch-mode flags
- [x] Feedback latency < 40s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
