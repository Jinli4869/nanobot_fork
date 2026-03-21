---
phase: 15
slug: intervention-safety-and-handoff
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-21
---

# Phase 15 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.3+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` - `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_opengui_p15_intervention.py -k "request_intervention or pauses_backend_io or resumes_with_fresh_observation or scrubs_sensitive_trace_fields" -q` |
| **Full suite command** | `uv run pytest tests/test_opengui_p15_intervention.py tests/test_opengui.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p10_background.py tests/test_opengui_p14_windows_desktop.py -q` |
| **Estimated runtime** | ~25 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task-specific command from the Per-Task Verification Map below; for Wave 1 red/green work default to `uv run pytest tests/test_opengui_p15_intervention.py -k "request_intervention or pauses_backend_io or resumes_with_fresh_observation or scrubs_sensitive_trace_fields" -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p15_intervention.py tests/test_opengui.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p10_background.py tests/test_opengui_p14_windows_desktop.py -q`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 25 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 15-01-01 | 01 | 1 | SAFE-01 | unit | `uv run pytest tests/test_opengui_p15_intervention.py::test_parse_action_accepts_request_intervention tests/test_opengui_p15_intervention.py::test_system_prompt_lists_request_intervention_action -q` | ❌ W0 | ⬜ pending |
| 15-01-02 | 01 | 1 | SAFE-01 | unit | `uv run pytest tests/test_opengui_p15_intervention.py::test_agent_requests_intervention_without_using_done tests/test_opengui_p15_intervention.py::test_request_intervention_requires_reason_text -q` | ❌ W0 | ⬜ pending |
| 15-02-01 | 02 | 2 | SAFE-02 | unit | `uv run pytest tests/test_opengui_p15_intervention.py::test_intervention_request_pauses_backend_execute_and_observe tests/test_opengui_p15_intervention.py::test_intervention_waits_for_explicit_resume_confirmation -q` | ❌ W0 | ⬜ pending |
| 15-02-02 | 02 | 2 | SAFE-03 | unit | `uv run pytest tests/test_opengui_p15_intervention.py::test_resume_uses_fresh_observation_after_intervention tests/test_opengui_p15_intervention.py::test_handler_receives_target_surface_metadata -q` | ❌ W0 | ⬜ pending |
| 15-02-03 | 02 | 2 | SAFE-04 | unit | `uv run pytest tests/test_opengui_p15_intervention.py::test_trace_and_trajectory_scrub_sensitive_intervention_fields tests/test_opengui_p15_intervention.py::test_input_text_is_redacted_in_logged_action_payloads -q` | ❌ W0 | ⬜ pending |
| 15-03-01 | 03 | 3 | SAFE-03 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_intervention_flow_resumes_after_confirmation tests/test_opengui_p11_integration.py::test_gui_tool_intervention_flow_returns_structured_resume_result -q` | ✅ | ⬜ pending |
| 15-03-02 | 03 | 3 | SAFE-02, SAFE-03 | integration | `uv run pytest tests/test_opengui_p10_background.py::test_background_backend_exposes_handoff_target_metadata tests/test_opengui_p14_windows_desktop.py::test_windows_isolated_backend_exposes_handoff_target_metadata -q` | ✅ | ⬜ pending |
| 15-03-03 | 03 | 3 | SAFE-04 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_intervention_logs_are_scrubbed tests/test_opengui_p11_integration.py::test_gui_tool_intervention_trace_payload_is_scrubbed -q` | ✅ | ⬜ pending |
| 15-04-01 | 04 | 4 | SAFE-01, SAFE-02, SAFE-03, SAFE-04 | suite | `uv run pytest tests/test_opengui_p15_intervention.py tests/test_opengui.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p10_background.py tests/test_opengui_p14_windows_desktop.py -q` | ✅ | ⬜ pending |
| 15-04-02 | 04 | 4 | SAFE-02, SAFE-03, SAFE-04 | manual | `.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md` checklist completed on real host background targets | ❌ P4 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p15_intervention.py` - red/green coverage for intervention action parsing, pause semantics, resume semantics, and trace scrubbing
- [ ] `tests/test_opengui_p5_cli.py` additions - CLI intervention confirmation and scrubbed logging coverage
- [ ] `tests/test_opengui_p11_integration.py` additions - nanobot intervention contract and trace scrubbing coverage
- [ ] `tests/test_opengui_p10_background.py` or `tests/test_opengui_p14_windows_desktop.py` additions - target-surface handoff metadata coverage for background wrappers

*Existing pytest infrastructure covers the framework requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Human can enter the macOS or Linux background automation target, complete the manual step, and resume without stray screenshots during the pause window | SAFE-02, SAFE-03 | Real foreground switching and no-capture behavior cannot be trusted from mocks alone | Follow `15-MANUAL-SMOKE.md` for a login or OTP scenario and confirm no screenshots are created between intervention request and explicit resume |
| Human can switch into the Windows isolated desktop target, complete the manual step, and resume from a fresh observation | SAFE-03 | Real isolated-desktop handoff cannot be honestly simulated in CI | Follow `15-MANUAL-SMOKE.md` on a Windows host and confirm the resumed run uses a new screenshot after confirmation |
| Intervention artifacts do not leak typed secrets or raw sensitive reason text | SAFE-04 | End-to-end artifact inspection across real host flows is still needed even with unit tests | Inspect `trace.jsonl` and the trajectory JSONL after a credential-like handoff and verify sensitive strings are redacted |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or a manual-only verification dependency
- [x] Sampling continuity: no 3 consecutive tasks without automated verification
- [x] Wave 0 covers all new test references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
