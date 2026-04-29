---
phase: 19
slug: operations-console
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-21
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run --extra dev pytest tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py -q` |
| **Full suite command** | `uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py tests/test_opengui_p3_nanobot.py tests/test_opengui_p16_host_integration.py -q` |
| **Estimated runtime** | ~30 seconds |

**Fallback command (current local sandbox):** `.venv/bin/python -m pytest tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py -q`

---

## Sampling Rate

- **After every 19-01 task commit:** Run `uv run --extra dev pytest tests/test_tui_p19_runtime.py tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py -q`
- **After every 19-02 task commit:** Run `uv run --extra dev pytest tests/test_tui_p19_tasks.py tests/test_tui_p19_runtime.py tests/test_opengui_p3_nanobot.py tests/test_opengui_p16_host_integration.py -q`
- **After every 19-03 task commit:** Run `uv run --extra dev pytest tests/test_tui_p19_traces.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py -q`
- **After every plan wave:** Run the smallest task slice for that wave, then promote to the full Phase 17-19 regression slice after `19-03` Task 2
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Wave 0 Seed | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 1 | OPS-01 | unit/api | `uv run --extra dev pytest tests/test_tui_p19_runtime.py::test_runtime_endpoint_reports_sessions_runs_and_recent_failures tests/test_tui_p19_runtime.py::test_runtime_recent_failures_are_filtered_to_browser_safe_fields -q` | planned | ⬜ pending |
| 19-01-02 | 01 | 1 | OPS-01 | integration/api | `uv run --extra dev pytest tests/test_tui_p19_runtime.py tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py -q` | planned | ⬜ pending |
| 19-02-01 | 02 | 2 | OPS-02 | unit/api | `uv run --extra dev pytest tests/test_tui_p19_tasks.py::test_launch_endpoint_accepts_only_supported_task_kinds tests/test_tui_p19_tasks.py::test_launch_endpoint_rejects_untyped_or_unsafe_parameters -q` | planned | ⬜ pending |
| 19-02-02 | 02 | 2 | OPS-02 | integration/runtime | `uv run --extra dev pytest tests/test_tui_p19_tasks.py tests/test_tui_p19_runtime.py tests/test_opengui_p3_nanobot.py tests/test_opengui_p16_host_integration.py -q` | planned | ⬜ pending |
| 19-03-01 | 03 | 3 | OPS-03 | unit/api | `uv run --extra dev pytest tests/test_tui_p19_traces.py::test_trace_endpoint_returns_filtered_events_for_browser_consumers tests/test_tui_p19_traces.py::test_log_endpoint_returns_filtered_lines_without_raw_paths_or_prompts -q` | planned | ⬜ pending |
| 19-03-02 | 03 | 3 | OPS-03 | regression | `uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py tests/test_opengui_p3_nanobot.py tests/test_opengui_p16_host_integration.py -q` | planned | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_tui_p19_runtime.py` — stubs for `OPS-01` runtime status, run summary, and recent failure inspection
- [ ] `tests/test_tui_p19_tasks.py` — stubs for `OPS-02` typed launch requests and safe orchestration
- [ ] `tests/test_tui_p19_traces.py` — stubs for `OPS-03` filtered trace and log inspection
- [ ] Existing Phase 17 and Phase 18 slices stay green as Phase 19 routes are added under `nanobot/tui`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Browser polling after a long-running GUI launch shows queued/running/completed state transitions with useful summaries | OPS-01, OPS-02 | Best confirmed against a real browser client in Phase 20 after the React shell exists | Start `python -m nanobot.tui`, trigger a supported operations task from the future web UI, poll the runtime and run detail endpoints, verify state transitions and summaries remain stable without terminal access |
| Browser run detail shows filtered trace/log information that is diagnostic but does not leak prompt text, raw artifact paths, or future sensitive fields | OPS-03 | Final UX verification requires a browser consumer and real generated artifacts | Trigger a web-launched run, inspect the future operations panel, confirm event ordering and failure summaries are useful while raw internal file layout stays hidden |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 dependencies are explicitly listed for every missing test file
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter
- [ ] `wave_0_complete` remains false until execution creates the planned test files

**Approval:** pending
