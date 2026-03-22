---
phase: 20-web-app-integration-and-verification
verified: 2026-03-22T02:38:00Z
status: human_needed
score: 3/3 requirements mapped
human_verification:
  - test: "Real browser workspace continuity"
    expected: "A local user can open the web shell, create or resume a chat session, switch to operations, then return to chat without losing session context."
    why_human: "This requires a real browser and live local runtime behavior that automated route and component tests cannot fully prove."
  - test: "Built/local runtime smoke path"
    expected: "After `npm --prefix nanobot/tui/web run build`, both `python -m nanobot.tui` and `nanobot-tui` serve the app shell locally instead of a raw API-only surface."
    why_human: "Installed-package and browser deep-link behavior should be confirmed end to end on a real local run."
---

# Phase 20: Web App Integration and Verification Verification Report

**Phase Goal:** Deliver the React/Vite workspace shell, unify chat and operations navigation, and ship runnable entrypoints and regression coverage.
**Verified:** 2026-03-22T02:38:00Z
**Status:** human_needed
**Re-verification:** No - initial Phase 20 closeout mapping

## Goal Achievement

Phase 20 achieved the planned implementation and automated regression goals:

- The React/Vite workspace exists under `nanobot/tui/web` with one shared shell for chat and operations navigation.
- Built frontend assets can be served safely from FastAPI through the opt-in `serve_frontend=True` seam.
- `python -m nanobot.tui` now serves the runtime routes plus frontend shell, while `nanobot-tui` provides the same packaged startup path without replacing the existing `nanobot` CLI.
- The Phase 17-20 regression slice passed green:
  - `npm --prefix nanobot/tui/web run build`
  - `npm --prefix nanobot/tui/web run test -- --run --reporter=dot`
  - `.venv/bin/python -m pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py tests/test_tui_p20_static.py tests/test_tui_p20_entrypoints.py tests/test_commands.py -q`

## Requirements Coverage

| Requirement | Automated Evidence | Manual Verification Required | Evidence Artifact / Status |
| --- | --- | --- | --- |
| `WEB-01` | `nanobot/tui/web/src/app/shell.test.tsx`, `nanobot/tui/web/src/features/workspace-routes.test.tsx`, `tests/test_tui_p20_static.py` | Yes | Browser shell, route continuity, and FastAPI static serving are test-backed; final real-browser confirmation remains manual |
| `WEB-02` | `nanobot/tui/web/src/app/shell.test.tsx`, `nanobot/tui/web/src/features/workspace-routes.test.tsx` | Yes | URL-backed session and run continuity are automated; end-to-end browser continuity still needs manual confirmation |
| `SHIP-01` | `tests/test_tui_p17_config.py`, `tests/test_tui_p20_entrypoints.py`, `tests/test_commands.py`, `pyproject.toml`, `README.md` | Yes | Startup seams, package metadata, and CLI preservation are automated; real local smoke for built mode remains manual |

## Manual Carry-Forward

- `.planning/phases/20-web-app-integration-and-verification/20-MANUAL-SMOKE.md`

This checklist covers the real browser and local runtime behavior that automation cannot honestly prove from this session alone.

## Gaps Summary

No automated code gaps remain for Phase 20. The remaining work is manual local validation:

- open the browser workspace and confirm chat/operations continuity with a real session
- confirm the built/local startup path from `python -m nanobot.tui` or `nanobot-tui`

Phase 20 is therefore implementation-complete and regression-green, but it still needs the documented manual smoke pass before it can be marked fully passed.
