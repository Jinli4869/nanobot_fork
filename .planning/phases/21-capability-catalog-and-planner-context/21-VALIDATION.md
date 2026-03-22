---
phase: 21
slug: capability-catalog-and-planner-context
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-22
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_mcp_tool.py tests/test_opengui_p21_planner_context.py` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_mcp_tool.py tests/test_opengui_p21_planner_context.py`
- **After every plan wave:** Run `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_mcp_tool.py tests/test_opengui_p21_planner_context.py`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 21-01-01 | 01 | 1 | CAP-01 | unit | `uv run pytest -q tests/test_opengui_p21_planner_context.py -k "catalog or route_metadata"` | ❌ W0 | ⬜ pending |
| 21-01-02 | 01 | 1 | CAP-01 | unit | `uv run pytest -q tests/test_opengui_p8_planning.py -k "plan or route"` | ✅ | ⬜ pending |
| 21-02-01 | 02 | 2 | CAP-02 | unit | `uv run pytest -q tests/test_opengui_p21_planner_context.py -k "memory_hint or guardrail"` | ❌ W0 | ⬜ pending |
| 21-02-02 | 02 | 2 | CAP-01, CAP-02 | regression | `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_mcp_tool.py tests/test_opengui_p21_planner_context.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_opengui_p21_planner_context.py` — capability catalog builder, route classification, prompt serialization, and memory-hint guardrails
- [ ] Update `tests/test_opengui_p8_planning.py` — `PlanNode` route metadata serialization, planner logging with route info, and `_plan_and_execute()` context injection
- [ ] Update `tests/test_mcp_tool.py` if MCP wrapper or inventory helpers are added to support planner catalog normalization

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Planner output for a mixed task distinguishes GUI application work from direct host routes and shows route metadata in logs | CAP-01, CAP-02 | Final confidence depends on a real `nanobot agent` run with current config and connected tools, not only unit tests | Run `uv run nanobot agent -c ~/.nanobot/config.json --logs --no-markdown -m "帮我打开obsidian,在今天的记录中新建一个task, 内容为--打卡;顺便帮我把蓝牙关了"` and confirm the decomposed plan logs a non-GUI route for the Bluetooth step when an appropriate route is available |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
