# Quick Task 260403-rhj Summary

## Outcome

Implemented an explicit OpenGUI agent-profile seam so `general_e2e`, `qwen3vl`, `mai_ui`, `gelab`, and `seed` style GUI agents can customize prompt contract, action schema, response parsing, and coordinate behavior without branching the main `GuiAgent` loop.

## What Changed

- Added [`opengui/agent_profiles.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent_profiles.py) to centralize supported profile names, prompt contracts, content-only response parsers, and coordinate-mode selection.
- Updated [`opengui/agent.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/agent.py) so `GuiAgent` accepts `agent_profile`, disables native tool calls for content-only profiles, normalizes profile-specific text output into synthetic `computer_use` calls, and keeps relative-coordinate handling profile-aware.
- Updated [`opengui/prompts/system.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/prompts/system.py) so the system prompt can render profile-specific response contracts and action schemas.
- Updated [`opengui/cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py) to support `--agent-profile` plus config-level `agent_profile` wiring into `GuiAgent`.
- Added regression coverage in [`tests/test_opengui.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui.py) and [`tests/test_opengui_p5_cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_cli.py) for prompt shaping, qwen3vl content parsing, profile-driven runs, and CLI propagation.

## Verification

- `uv run pytest tests/test_opengui.py tests/test_opengui_p5_cli.py -q`
- `uv run pytest tests/test_opengui.py tests/test_opengui_p5_cli.py tests/test_opengui_p15_intervention.py tests/test_opengui_p2_integration.py -q`

## Implementation Commit

- `fe5fa36` — `feat(opengui): add MobileWorld agent profiles`
