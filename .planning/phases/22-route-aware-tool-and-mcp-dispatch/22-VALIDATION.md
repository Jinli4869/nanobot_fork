---
phase: 22
slug: route-aware-tool-and-mcp-dispatch
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=9.0.0,<10.0.0 + pytest-asyncio >=1.3.0,<2.0.0 |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_opengui_p22_route_dispatch.py` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_opengui_p22_route_dispatch.py`
- **After every plan wave:** Run `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_opengui_p21_planner_context.py tests/test_opengui_p22_route_dispatch.py`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 22-01-01 | 01 | 1 | CAP-03 | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "route_resolver"` | ❌ W0 | ⬜ pending |
| 22-01-02 | 01 | 1 | CAP-03 | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "no_route_id"` | ❌ W0 | ⬜ pending |
| 22-02-01 | 02 | 1 | CAP-03 | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "tool_dispatch"` | ❌ W0 | ⬜ pending |
| 22-02-02 | 02 | 1 | CAP-04 | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "mcp_dispatch"` | ❌ W0 | ⬜ pending |
| 22-02-03 | 02 | 1 | CAP-04 | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "fallback"` | ❌ W0 | ⬜ pending |
| 22-02-04 | 02 | 1 | CAP-04 | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "gui_fallback"` | ❌ W0 | ⬜ pending |
| 22-02-05 | 02 | 1 | CAP-03/04 | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "logging"` | ❌ W0 | ⬜ pending |
| 22-02-06 | 02 | 1 | CAP-03 | regression | `uv run pytest -q tests/test_opengui_p8_planning.py` | ✅ (update needed) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p22_route_dispatch.py` — route resolver, tool dispatch, MCP dispatch, fallback chain, GUI fallback, and logging coverage
- [ ] Update `tests/test_opengui_p8_planning.py` — remove assumptions about placeholder return values in tool/MCP dispatch

*No new framework install needed — existing pytest + pytest-asyncio infrastructure covers all Phase 22 tests.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
