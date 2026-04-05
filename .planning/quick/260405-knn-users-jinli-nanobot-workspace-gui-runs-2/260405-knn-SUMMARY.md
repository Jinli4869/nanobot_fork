# Quick Task 260405-knn Summary

## Outcome

Debugged the exception from `/Users/jinli/.nanobot/workspace/gui_runs/2026-04-05_144819_197174` and confirmed the root cause:

- The qwen3vl-compatible provider sometimes returns a `computer_use` tool call instead of the expected `<tool_call>` content block.
- In the failing runs, the provider encoded tap coordinates as a stringified pair such as `"[410, 125]"` on the `x` field.
- Without compatibility handling, the parser path eventually attempted `float("[410, 125]")`, which surfaced as `could not convert string to float: '[235'`, `"[938'"`, and `"[931'"` across retries.

## Evidence

- Trace step 2 in attempt 1 contains:
  - `name="computer_use"`
  - `arguments={"action_type":"click","x":"[410, 125]"}`
- The exception is raised from `opengui/agent.py` when `normalize_profile_response()` cannot recover a valid action payload after retries.

## Fix Status

The needed production fix was already present in the local working tree before this turn:

- `opengui/agent_profiles.py` falls back to provider tool calls when the content contract is missing and normalizes provider-native tool calls.
- `opengui/action.py` now coerces stringified coordinate lists like `"[903, 130]"` into paired numeric coordinates before numeric parsing.

This turn added one more regression test for the exact trace shape:

- `tests/test_opengui.py`: `test_agent_runs_with_qwen3vl_provider_computer_use_stringified_x_coordinates`

## Verification

Passed:

```bash
uv run pytest tests/test_opengui.py -k "stringified_x_list or qwen3vl_profile or provider_mobile_use_tool_call or stringified_x_coordinates"
```

Result: `7 passed, 31 deselected`
