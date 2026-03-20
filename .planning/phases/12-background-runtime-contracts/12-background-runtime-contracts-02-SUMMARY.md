---
phase: 12-background-runtime-contracts
plan: "02"
subsystem: cli
tags: [cli, background, runtime-contract, fallback, blocking]

requires:
  - phase: 12-background-runtime-contracts/12-01
    provides: "Shared runtime probe, mode resolution, and coordinator contract"

provides:
  - "CLI background runs probe and log resolved runtime mode before automation starts"
  - "`--require-isolation` flag that blocks instead of silently falling back"
  - "Explicit shutdown ownership in the CLI isolated wrapper path"
  - "Green CLI tests for pre-run mode logging and strict-isolation blocking"

affects:
  - 12-04

key-files:
  created: []
  modified:
    - opengui/cli.py
    - tests/test_opengui_p5_cli.py

requirements-completed:
  - BGND-05
  - BGND-06

duration: 14min
completed: "2026-03-20"
---

# Phase 12 Plan 02 Summary

`opengui/cli.py` now consumes the shared runtime contract instead of branching on Linux inline. When `--background` is set, the CLI probes support, resolves the run mode, logs a single `background runtime resolved:` line before agent construction, and either blocks, falls back to the raw backend, or wraps the backend in `BackgroundDesktopBackend`.

The isolated path no longer uses `async with backend:`. The CLI creates the wrapped backend explicitly and always calls `await wrapped_backend.shutdown()` in `finally`, which matches the new lease-aware wrapper lifecycle.

The promoted CLI tests verify log ordering, remediation-bearing fallback messages, and strict isolation blocking. The targeted CLI Phase 12 tests and the full `tests/test_opengui_p5_cli.py` file both pass.

## Issues Encountered

None.

## Self-Check: PASSED

- `opengui/cli.py` - FOUND
- `tests/test_opengui_p5_cli.py` - FOUND

