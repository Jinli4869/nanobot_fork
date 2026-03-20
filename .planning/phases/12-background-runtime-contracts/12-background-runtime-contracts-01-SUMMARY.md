---
phase: 12-background-runtime-contracts
plan: "01"
subsystem: background-runtime
tags: [background, runtime, xvfb, concurrency, lease, tests]

requires:
  - phase: 10-background-backend-wrapper
    provides: "BackgroundDesktopBackend lifecycle wrapper"
  - phase: 11-integration-tests
    provides: "CLI and nanobot background execution seams"

provides:
  - "Shared background runtime probe, resolution, and logging contract"
  - "Process-wide runtime coordinator that serializes overlapping background runs"
  - "Lease-aware BackgroundDesktopBackend that holds the coordinator slot across preflight/shutdown"
  - "Green runtime contract tests covering probe, mode resolution, and serialized waiters"

affects:
  - 12-02
  - 12-03
  - 13
  - 14

tech-stack:
  added: []
  patterns:
    - "Side-effect-free capability probe before background startup"
    - "Shared mode-resolution contract with stable reason codes and remediation text"
    - "Asyncio.Condition lease coordinator for process-global background serialization"

key-files:
  created:
    - opengui/backends/background_runtime.py
    - tests/test_opengui_p12_runtime_contracts.py
  modified:
    - opengui/backends/background.py
    - tests/test_opengui_p5_cli.py
    - tests/test_opengui_p11_integration.py

requirements-completed:
  - BGND-05
  - BGND-06
  - BGND-07

duration: 18min
completed: "2026-03-20"
---

# Phase 12 Plan 01 Summary

Shared runtime contracts are now centralized in `opengui/backends/background_runtime.py`. The new module provides host normalization, Xvfb capability probing, policy-based mode resolution, stable resolved-mode logging, and a `BackgroundRuntimeCoordinator` that serializes overlapping background runs with explicit busy metadata.

`BackgroundDesktopBackend` now acquires a process-wide runtime lease before display startup and keeps it until shutdown completes. That closes the process-global overlap gap from BGND-07 without changing the wrapper's public lifecycle shape for callers.

The runtime test file was promoted from placeholder coverage to green contract tests. `uv run pytest tests/test_opengui_p12_runtime_contracts.py -q` passes, covering Linux Xvfb availability detection, fallback/blocked mode resolution, and waiter serialization.

## Issues Encountered

None.

## Self-Check: PASSED

- `opengui/backends/background_runtime.py` - FOUND
- `opengui/backends/background.py` - FOUND
- `tests/test_opengui_p12_runtime_contracts.py` - FOUND

