---
phase: 11-integration-tests
plan: 02
subsystem: nanobot-gui-config
tags: [pydantic, background-mode, gui-tool, integration-tests]
dependency_graph:
  requires: [opengui.backends.background.BackgroundDesktopBackend, opengui.backends.displays.xvfb.XvfbDisplayManager]
  provides: [GuiConfig background fields, GuiSubagentTool background wrapping, 8 integration tests]
  affects: [nanobot/config/schema.py, nanobot/agent/tools/gui.py, tests/test_opengui_p11_integration.py]
tech_stack:
  added: []
  patterns: [pydantic model_validator, async context manager wrapping, lazy platform-conditional imports, _run_task refactor]
key_files:
  created: [tests/test_opengui_p11_integration.py]
  modified: [nanobot/config/schema.py, nanobot/agent/tools/gui.py]
decisions:
  - "GuiConfig.background=True raises ValidationError for non-local backends at config load time via model_validator"
  - "execute() extracts _run_task() helper to avoid duplicating 20+ lines across wrapped and unwrapped paths"
  - "BackgroundDesktopBackend and XvfbDisplayManager imported lazily inside execute() to avoid import-time cost on non-Linux"
  - "Non-Linux fallback runs task in foreground with a WARNING log containing 'Linux-only' — no exception raised"
  - "Test file uses patch.object for _build_backend/_get_skill_library in helper to keep test construction clean"
metrics:
  duration: 155s
  completed: "2026-03-20"
  tasks: 2
  files: 3
---

# Phase 11 Plan 02: GuiConfig Background Fields and execute() Wrapping Summary

Extended `GuiConfig` with 4 background display fields and a `model_validator`, then wired `BackgroundDesktopBackend` wrapping into `GuiSubagentTool.execute()` with Linux guard and non-Linux fallback warning, plus a full 8-test suite covering schema validation and execute() wrapping behavior.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add background fields and model_validator to GuiConfig + wrapping in execute() | 84cebaf | nanobot/config/schema.py, nanobot/agent/tools/gui.py |
| 2 | Create test_opengui_p11_integration.py with GuiConfig and execute() tests | 7219505 | tests/test_opengui_p11_integration.py |

## What Was Built

**GuiConfig schema (nanobot/config/schema.py):**
- Added 4 new fields: `background: bool = False`, `display_num: int | None = None`, `display_width: int = 1280`, `display_height: int = 720`
- All fields inherit camelCase aliases from the `Base` model (`displayNum`, `displayWidth`, `displayHeight`)
- Added `model_validator(mode="after")` that raises `ValueError("background mode requires backend='local', got backend=...")` when `background=True` with non-local backend
- Added `model_validator` to pydantic import line

**GuiSubagentTool.execute() refactor (nanobot/agent/tools/gui.py):**
- Extracted `_run_task(self, active_backend, task, **kwargs)` helper containing all the GuiAgent construction, trajectory recording, summarization, and skill extraction logic
- `execute()` now handles background wrapping before delegating to `_run_task()`
- On Linux: imports `BackgroundDesktopBackend` and `XvfbDisplayManager` lazily, constructs `XvfbDisplayManager` with configured `display_num` (default 99), `display_width`, `display_height`, wraps active backend, uses `async with` for clean lifecycle
- On non-Linux: logs a WARNING containing "Linux-only" and falls through to `_run_task()` without wrapping

**Test file (tests/test_opengui_p11_integration.py):**
- 5 GuiConfig schema tests: defaults check, `local+background` succeeds, `adb+background` raises ValidationError, `dry-run+background` raises ValidationError, camelCase aliases accepted
- 3 execute() wrapping tests: Linux wraps backend in BackgroundDesktopBackend, non-Linux logs warning and skips wrapping, background=False calls `_run_task` with raw backend
- All tests pass without a real Xvfb binary (no subprocess spawning, all display managers mocked)

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria met on first attempt.

## Test Results

```
8 passed in 1.50s (tests/test_opengui_p11_integration.py)
670 passed, 1 pre-existing failure in full suite (test_exec_head_tail_truncation unrelated)
```

## Self-Check: PASSED

Files exist:
- FOUND: nanobot/config/schema.py (modified)
- FOUND: nanobot/agent/tools/gui.py (modified)
- FOUND: tests/test_opengui_p11_integration.py (created)

Commits exist:
- FOUND: 84cebaf (Task 1)
- FOUND: 7219505 (Task 2)
