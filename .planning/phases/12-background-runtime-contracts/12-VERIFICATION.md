---
phase: 12-background-runtime-contracts
verified: 2026-03-20T14:17:03Z
status: passed
score: 10/10 must-haves verified
re_verification: false
---

# Phase 12: Background Runtime Contracts Verification Report

**Phase Goal:** The shared background-execution runtime can determine whether a host supports isolated execution, expose that mode decision clearly, and prevent overlapping desktop runs from corrupting process-global state.
**Verified:** 2026-03-20T14:17:03Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The runtime normalizes host platforms and probes isolated support before background startup | VERIFIED | `guiclaw/backends/background_runtime.py:57`, `guiclaw/backends/background_runtime.py:94`, `tests/test_guiclaw_p12_runtime_contracts.py:13` |
| 2 | Resolved run modes preserve stable reason codes and include actionable remediation text | VERIFIED | `guiclaw/backends/background_runtime.py:94`, `guiclaw/backends/background_runtime.py:120`, `tests/test_guiclaw_p12_runtime_contracts.py:43` |
| 3 | BackgroundDesktopBackend acquires a process-wide lease before display startup and releases it on shutdown | VERIFIED | `guiclaw/backends/background.py:63`, `guiclaw/backends/background.py:101` |
| 4 | The CLI logs one resolved background-runtime line before automation starts | VERIFIED | `guiclaw/cli.py:420`, `guiclaw/cli.py:461`, `tests/test_guiclaw_p5_cli.py:469` |
| 5 | The CLI can block early when `--require-isolation` is set and isolated execution is unavailable | VERIFIED | `guiclaw/cli.py:218`, `guiclaw/cli.py:249`, `tests/test_guiclaw_p5_cli.py:552` |
| 6 | Nanobot returns an explicit acknowledgement-required fallback response instead of silently continuing | VERIFIED | `nanobot/agent/tools/gui.py:104`, `nanobot/agent/tools/gui.py:132`, `tests/test_guiclaw_p11_integration.py:202` |
| 7 | Nanobot can continue on the raw backend after explicit fallback acknowledgement | VERIFIED | `nanobot/agent/tools/gui.py:140`, `tests/test_guiclaw_p11_integration.py:236` |
| 8 | Isolated nanobot background runs attach owner/task/model metadata to the wrapper | VERIFIED | `nanobot/agent/tools/gui.py:150` |
| 9 | Overlapping background runs serialize and emit busy metadata identifying the active task | VERIFIED | `guiclaw/backends/background_runtime.py:157`, `tests/test_guiclaw_p12_runtime_contracts.py:93`, `tests/test_guiclaw_p11_integration.py:245` |
| 10 | The full Phase 12 regression slice is green | VERIFIED | `uv run pytest tests/test_guiclaw_p12_runtime_contracts.py tests/test_guiclaw_p5_cli.py tests/test_guiclaw_p11_integration.py -q` -> `30 passed in 1.78s` |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `guiclaw/backends/background_runtime.py` | Shared probe, resolution, logging, and coordination contract | VERIFIED | Contains `IsolationProbeResult`, `ResolvedRunMode`, `probe_isolated_background_support()`, `resolve_run_mode()`, `log_mode_resolution()`, and `BackgroundRuntimeCoordinator` |
| `guiclaw/backends/background.py` | Lease-aware wrapper lifecycle | VERIFIED | Stores `run_metadata`, acquires coordinator lease in `preflight()`, releases in `shutdown()` |
| `guiclaw/cli.py` | Shared runtime contract consumption for CLI background runs | VERIFIED | Adds `--require-isolation`, probes before agent execution, logs resolution, and owns wrapper shutdown |
| `nanobot/agent/tools/gui.py` | Shared runtime contract consumption for nanobot GUI runs | VERIFIED | Adds `require_background_isolation` / `acknowledge_background_fallback`, early-return fallback/block payloads, and isolated wrapper metadata |
| `tests/test_guiclaw_p12_runtime_contracts.py` | Runtime contract test coverage | VERIFIED | Covers probe normalization, run-mode variants, and serialized waiters |
| `tests/test_guiclaw_p5_cli.py` | CLI runtime-contract integration coverage | VERIFIED | Covers pre-run logging order and strict isolation blocking |
| `tests/test_guiclaw_p11_integration.py` | Nanobot runtime-contract integration coverage | VERIFIED | Covers fallback acknowledgement and busy metadata serialization |

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| BGND-05 | Probe isolated support before any background run starts | SATISFIED | Shared probe in `background_runtime.py`; CLI and nanobot both call it before `_execute_agent()` / `_run_task()` |
| BGND-06 | Tell users whether the run is isolated, fallback, or blocked before automation begins | SATISFIED | Shared resolved-mode logging plus explicit CLI `RuntimeError` and nanobot JSON fallback/block summaries |
| BGND-07 | Reject or serialize overlapping background runs on the same host | SATISFIED | Coordinator lease in `BackgroundDesktopBackend` plus busy-metadata tests proving serialized nanobot runs |

No gaps found. All requirement IDs referenced by Phase 12 plans are accounted for and satisfied.

### Human Verification Required

None. Phase 12 behavior is fully covered by automated tests with mocked runtime seams and CI-safe display managers.

### Test Run Result

```text
30 passed in 1.78s
```

- `tests/test_guiclaw_p12_runtime_contracts.py` - 3 passed
- `tests/test_guiclaw_p5_cli.py` - 19 passed
- `tests/test_guiclaw_p11_integration.py` - 8 passed

---

_Verified: 2026-03-20T14:17:03Z_
_Verifier: Codex inline fallback during gsd-execute-phase_
