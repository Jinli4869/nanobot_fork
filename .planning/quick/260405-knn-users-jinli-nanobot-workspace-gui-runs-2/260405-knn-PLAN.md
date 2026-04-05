# Quick Task 260405-knn: 根据 /Users/jinli/.nanobot/workspace/gui_runs/2026-04-05_144819_197174 中出现 exception 的原因进行 debug 并修复

**Status:** Completed
**Date:** 2026-04-05

## Tasks

### 1. Reconstruct the failure from the GUI run trace
- Files: `/Users/jinli/.nanobot/workspace/gui_runs/2026-04-05_144819_197174`, `opengui/agent.py`, `opengui/agent_profiles.py`
- Action: Inspect the recorded attempts, locate the exact parser boundary, and identify the malformed payload shape that triggers the exception.
- Verify: Trace evidence shows the failing payload form and the code path that raises `RuntimeError`.
- Done: Confirmed the failure happens inside `normalize_profile_response()` / `parse_action()` handling for qwen3vl-compatible provider tool calls.

### 2. Confirm the fix path already present in the working tree
- Files: `opengui/action.py`, `opengui/agent_profiles.py`, `tests/test_opengui.py`
- Action: Review existing local modifications to determine whether they already address provider fallback and stringified coordinate coercion.
- Verify: Code inspection shows fallback to provider tool calls plus stringified coordinate list handling.
- Done: Existing working-tree changes already cover the root cause; no extra production code change was needed in this turn.

### 3. Lock the regression with a trace-shaped test and run a focused slice
- Files: `tests/test_opengui.py`
- Action: Add an end-to-end regression test that uses a qwen3vl `computer_use` tool call with `x: "[410, 125]"`, then run targeted pytest coverage.
- Verify: `uv run pytest tests/test_opengui.py -k "stringified_x_list or qwen3vl_profile or provider_mobile_use_tool_call or stringified_x_coordinates"`
- Done: Added the regression test and verified the focused slice passes.
