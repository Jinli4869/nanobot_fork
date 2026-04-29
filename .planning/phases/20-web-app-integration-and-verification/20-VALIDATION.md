---
phase: 20
slug: web-app-integration-and-verification
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-21
---

# Phase 20 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + vitest |
| **Config file** | `pyproject.toml` and `nanobot/tui/web/package.json` |
| **Quick run command** | `npm --prefix nanobot/tui/web run test -- --run && uv run --extra dev pytest tests/test_tui_p20_static.py tests/test_tui_p20_entrypoints.py tests/test_commands.py -q` |
| **Full suite command** | `npm --prefix nanobot/tui/web run build && npm --prefix nanobot/tui/web run test -- --run && uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py tests/test_tui_p20_static.py tests/test_tui_p20_entrypoints.py tests/test_commands.py -q` |
| **Estimated runtime** | ~30 seconds |

**Fallback command (if frontend tests are not ready yet):** `uv run --extra dev pytest tests/test_tui_p20_static.py tests/test_tui_p20_entrypoints.py tests/test_tui_p17_config.py tests/test_commands.py -q`

---

## Sampling Rate

- **After `20-01-01`:** Run `npm --prefix nanobot/tui/web run build`
- **After `20-01-02`:** Run `npm --prefix nanobot/tui/web run test -- --run src/app/shell.test.tsx --reporter=dot`
- **After every `20-02` task commit:** Run `npm --prefix nanobot/tui/web run build && npm --prefix nanobot/tui/web run test -- --run && uv run --extra dev pytest tests/test_tui_p20_static.py -q`
- **After `20-03-01`:** Run `npm --prefix nanobot/tui/web run build && uv run --extra dev pytest tests/test_tui_p20_entrypoints.py tests/test_tui_p17_config.py tests/test_commands.py -q`
- **After `20-03-02`:** Run `npm --prefix nanobot/tui/web run build && npm --prefix nanobot/tui/web run test -- --run && uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py tests/test_tui_p20_static.py tests/test_tui_p20_entrypoints.py tests/test_commands.py -q`
- **After every plan wave:** Run the smallest test/build slice that covers the newly added frontend, startup, or CLI seam
- **Before `$gsd-verify-work`:** Frontend build, frontend tests, and the full Phase 17-20 regression slice must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Wave 0 Seed | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 20-01-01 | 01 | 1 | WEB-01 | frontend/build | `npm --prefix nanobot/tui/web run build` | planned | ⬜ pending |
| 20-01-02 | 01 | 1 | WEB-02 | frontend/component | `npm --prefix nanobot/tui/web run test -- --run src/app/shell.test.tsx --reporter=dot` | planned | ⬜ pending |
| 20-02-01 | 02 | 2 | WEB-01, SHIP-01 | static/dev/unit | `npm --prefix nanobot/tui/web run test -- --run && uv run --extra dev pytest tests/test_tui_p20_static.py -q` | planned | ⬜ pending |
| 20-02-02 | 02 | 2 | WEB-01, SHIP-01 | dev/build/integration | `npm --prefix nanobot/tui/web run build && npm --prefix nanobot/tui/web run test -- --run && uv run --extra dev pytest tests/test_tui_p20_static.py -q` | planned | ⬜ pending |
| 20-03-01 | 03 | 3 | SHIP-01 | packaging/entrypoint/regression | `npm --prefix nanobot/tui/web run build && uv run --extra dev pytest tests/test_tui_p20_entrypoints.py tests/test_tui_p17_config.py tests/test_commands.py -q` | planned | ⬜ pending |
| 20-03-02 | 03 | 3 | WEB-01, WEB-02, SHIP-01 | closeout/regression/docs | `npm --prefix nanobot/tui/web run build && npm --prefix nanobot/tui/web run test -- --run && uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_tui_p19_runtime.py tests/test_tui_p19_tasks.py tests/test_tui_p19_traces.py tests/test_tui_p20_static.py tests/test_tui_p20_entrypoints.py tests/test_commands.py -q` | planned | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [ ] `nanobot/tui/web/package.json` - add frontend scripts for `dev`, `build`, and `test`
- [ ] `nanobot/tui/web/src/` - create the shell source tree for chat and operations navigation
- [ ] `tests/test_tui_p20_static.py` - static-serving and startup regression coverage for Phase 20
- [ ] `tests/test_tui_p20_entrypoints.py` - canonical `python -m nanobot.tui` entrypoint regression coverage
- [ ] Frontend shell test file(s) under `nanobot/tui/web/src/` - verify navigation and shared workspace state
- [ ] Existing Phase 17-19 backend slices remain runnable without forcing an unnecessary frontend build

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| A local user can open one browser workspace, switch between chat and operations, and keep the active workspace context intact | WEB-01, WEB-02 | Final confidence depends on a real browser and live API interactions rather than isolated component tests | Start the backend and frontend with the documented dev commands, open the workspace in a browser, create or resume a chat session, switch to operations, then return to chat and confirm the session context is still present |
| The built/local runtime serves the web app from `python -m nanobot.tui` without extra manual backend wiring | SHIP-01 | Static asset serving and browser fallback behavior are easiest to validate end-to-end with a real local run | Build the frontend, run `python -m nanobot.tui`, open the root URL, confirm the app shell loads instead of a raw API-only surface, and verify chat + operations navigation both work |
| Existing CLI-first usage still works after the web workspace ships | SHIP-01 | The phase must not regress host entrypoints that are outside the frontend toolchain | Run a representative existing CLI command after Phase 20 changes land and confirm it behaves the same as before the web workspace integration |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 dependencies are explicitly listed for missing frontend and static-serving files
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter
- [ ] `wave_0_complete` remains false until execution creates the planned frontend and test artifacts

**Approval:** pending
