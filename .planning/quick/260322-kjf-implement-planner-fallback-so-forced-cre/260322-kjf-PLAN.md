# Quick Task 260322-kjf Plan

**Description:** Implement planner fallback so forced `create_plan` tool_choice automatically retries with `auto` on unsupported thinking-mode tool_choice errors, preserving diagnostics and tests.
**Date:** 2026-03-22
**Mode:** quick

## Tasks

1. Update `TaskPlanner` to keep the forced `create_plan` path as the primary behavior, but detect provider errors that explicitly reject forced `tool_choice` in thinking mode and retry once with `tool_choice="auto"`.
2. Preserve the new planner diagnostics so the initial incompatibility and the fallback path remain visible in logs.
3. Add focused regression coverage proving the second planner request switches to `auto` and still returns a valid plan.

## Verification

- Run `uv run pytest tests/test_opengui_agent_loop.py tests/test_opengui_p2_integration.py -q`
