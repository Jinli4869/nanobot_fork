---
phase: 12-background-runtime-contracts
plan: "03"
subsystem: nanobot
tags: [nanobot, gui-tool, background, fallback-ack, serialization]

requires:
  - phase: 12-background-runtime-contracts/12-01
    provides: "Shared runtime probe, mode resolution, and coordinator contract"

provides:
  - "GuiSubagentTool background mode resolution aligned with the CLI"
  - "Explicit `acknowledge_background_fallback` gate before raw-backend fallback"
  - "Minimal JSON early-return payloads for blocked and unacknowledged fallback runs"
  - "Busy-metadata test coverage for serialized concurrent nanobot background runs"

affects:
  - 12-04

key-files:
  created: []
  modified:
    - nanobot/agent/tools/gui.py
    - tests/test_opengui_p11_integration.py

requirements-completed:
  - BGND-06
  - BGND-07

duration: 17min
completed: "2026-03-20"
---

# Phase 12 Plan 03 Summary

`GuiSubagentTool.execute()` now uses the same background runtime vocabulary as the CLI. Background runs probe support, resolve the mode, and log the decision before any GUI automation starts.

Nanobot is intentionally stricter than the CLI on fallback: unsupported background runs return a minimal JSON failure payload unless the caller explicitly sets `acknowledge_background_fallback=true`. When fallback is acknowledged, nanobot continues on the raw backend; when isolation is available, it wraps the backend with explicit `run_metadata` so overlapping background runs surface actionable busy logs.

The Phase 12 nanobot tests are green, including the new fallback-acknowledgement contract and the concurrency test that proves overlapping isolated runs serialize with `background runtime busy:` metadata.

## Issues Encountered

None.

## Self-Check: PASSED

- `nanobot/agent/tools/gui.py` - FOUND
- `tests/test_opengui_p11_integration.py` - FOUND

