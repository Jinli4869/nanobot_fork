from __future__ import annotations

import pytest

from opengui.action import ActionError, parse_action
from opengui.agent import _COMPUTER_USE_TOOL
from opengui.prompts.system import build_system_prompt


def test_parse_action_accepts_request_intervention() -> None:
    action = parse_action({
        "action_type": "request_intervention",
        "text": "Need the user to complete a login challenge.",
    })

    assert action.action_type == "request_intervention"
    assert action.text == "Need the user to complete a login challenge."


def test_request_intervention_requires_reason_text() -> None:
    with pytest.raises(ActionError, match="requires a non-empty 'text' field"):
        parse_action({"action_type": "request_intervention"})

    with pytest.raises(ActionError, match="requires a non-empty 'text' field"):
        parse_action({
            "action_type": "request_intervention",
            "text": "   ",
        })


def test_system_prompt_lists_request_intervention_action() -> None:
    prompt = build_system_prompt()

    assert '"request_intervention"' in prompt
    assert "sensitive, blocked, or unsafe state" in prompt
    assert 'action_type="request_intervention"' in prompt


def test_agent_tool_schema_lists_request_intervention() -> None:
    action_types = _COMPUTER_USE_TOOL["function"]["parameters"]["properties"]["action_type"]["enum"]

    assert "request_intervention" in action_types
