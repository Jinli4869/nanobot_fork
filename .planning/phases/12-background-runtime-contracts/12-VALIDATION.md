---
phase: 12
slug: background-runtime-contracts
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-20
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.3+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/test_opengui_p12_runtime_contracts.py -q` |
| **Full suite command** | `uv run pytest tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q` |
| **Estimated runtime** | ~20 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p12_runtime_contracts.py -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | BGND-05 | unit | `uv run pytest tests/test_opengui_p12_runtime_contracts.py::test_probe_result_shape_and_platform_normalization -q` | ✅ | ✅ green |
| 12-01-02 | 01 | 1 | BGND-06 | unit | `uv run pytest tests/test_opengui_p12_runtime_contracts.py::test_resolve_run_mode_variants -q` | ✅ | ✅ green |
| 12-01-03 | 01 | 1 | BGND-07 | unit | `uv run pytest tests/test_opengui_p12_runtime_contracts.py::test_runtime_coordinator_serializes_waiters_and_releases_on_exit -q` | ✅ | ✅ green |
| 12-02-01 | 02 | 2 | BGND-05 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_logs_resolved_background_mode_before_agent_start -q` | ✅ | ✅ green |
| 12-02-02 | 02 | 2 | BGND-06 | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_blocks_when_isolation_required_but_unavailable -q` | ✅ | ✅ green |
| 12-03-01 | 03 | 2 | BGND-06 | integration | `uv run pytest tests/test_opengui_p11_integration.py::test_gui_tool_requires_ack_for_background_fallback -q` | ✅ | ✅ green |
| 12-03-02 | 03 | 2 | BGND-07 | integration | `uv run pytest tests/test_opengui_p11_integration.py::test_gui_tool_reports_busy_waiting_metadata_for_serialized_background_runs -q` | ✅ | ✅ green |
| 12-04-01 | 04 | 3 | BGND-05 | suite | `uv run pytest tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q` | ✅ | ✅ green |
| 12-04-02 | 04 | 3 | BGND-06 | suite | `uv run pytest tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q` | ✅ | ✅ green |
| 12-04-03 | 04 | 3 | BGND-07 | suite | `uv run pytest tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_opengui_p12_runtime_contracts.py` — stubs promoted to green probe/resolution/coordinator coverage
- [x] `tests/test_opengui_p5_cli.py` additions — stubs promoted to green pre-run mode logging order and isolation-required block behavior
- [x] `tests/test_opengui_p11_integration.py` additions — stubs promoted to green nanobot fallback acknowledgement and serialized busy-status reporting

*Existing infrastructure covers framework requirements.*

---

## Manual-Only Verifications

*All phase behaviors should have automated verification. Manual verification is not required if the planned tests are implemented.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
