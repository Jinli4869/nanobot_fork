from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from opengui import skills as exported_skills
from opengui.interfaces import LLMResponse, ToolCall
from opengui.observation import Observation
from opengui.skills.data import SkillStep
from opengui.skills.shortcut import ParameterSlot, ShortcutSkill, StateDescriptor
from opengui.skills.shortcut import ParameterSlot, ShortcutSkill, StateDescriptor
from opengui.skills.task_skill import (
    BranchNode,
    ShortcutRefNode,
    TaskSkill,
    _task_node_from_dict,
)


class _ScriptedGroundingLLM:
    def __init__(self, response: LLMResponse) -> None:
        self._response = response

    async def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        return self._response


def test_state_descriptor_round_trip() -> None:
    descriptor = StateDescriptor(
        kind="element_visible",
        value="Settings button",
    )

    payload = descriptor.to_dict()

    assert payload == {
        "kind": "element_visible",
        "value": "Settings button",
    }
    assert StateDescriptor.from_dict(payload) == descriptor


def test_parameter_slot_round_trip() -> None:
    slot = ParameterSlot(
        name="panel",
        type="str",
        description="Settings panel name",
    )

    payload = slot.to_dict()

    assert payload == {
        "name": "panel",
        "type": "str",
        "description": "Settings panel name",
    }
    assert ParameterSlot.from_dict(payload) == slot


def test_shortcut_skill_round_trip() -> None:
    shortcut = ShortcutSkill(
        skill_id="shortcut-open-settings",
        name="Open Settings Panel",
        description="Navigate to the requested settings panel.",
        app="com.android.settings",
        platform="android",
        steps=(
            SkillStep(
                action_type="tap",
                target="Settings icon",
                parameters={"panel": "{{panel}}"},
            ),
        ),
        parameter_slots=(
            ParameterSlot(
                name="panel",
                type="str",
                description="Settings panel name",
            ),
        ),
        preconditions=(
            StateDescriptor(
                kind="element_visible",
                value="Settings icon",
            ),
        ),
        postconditions=(
            StateDescriptor(
                kind="app_foreground",
                value="Settings",
            ),
        ),
        tags=("settings", "navigation"),
        created_at=1_700_000_000.0,
    )

    payload = shortcut.to_dict()
    round_tripped = ShortcutSkill.from_dict(payload)

    assert payload["steps"] == [
        {
            "action_type": "tap",
            "target": "Settings icon",
            "parameters": {"panel": "{{panel}}"},
        }
    ]
    assert payload["parameter_slots"] == [
        {
            "name": "panel",
            "type": "str",
            "description": "Settings panel name",
        }
    ]
    assert payload["preconditions"] == [
        {
            "kind": "element_visible",
            "value": "Settings icon",
        }
    ]
    assert payload["postconditions"] == [
        {
            "kind": "app_foreground",
            "value": "Settings",
        }
    ]
    assert round_tripped == shortcut
    assert round_tripped.steps[0] == shortcut.steps[0]


def test_opengui_skills_exports_shortcut_schema() -> None:
    assert "StateDescriptor" in exported_skills.__all__
    assert "ParameterSlot" in exported_skills.__all__
    assert "ShortcutSkill" in exported_skills.__all__
    assert "Skill" in exported_skills.__all__
    assert "SkillStep" in exported_skills.__all__


def test_shortcut_ref_node_round_trip() -> None:
    node = ShortcutRefNode(
        shortcut_id="open_settings",
        param_bindings={"panel": "{{panel}}"},
    )

    skill = TaskSkill(
        skill_id="task-shortcut-ref",
        name="Shortcut Ref Only",
        description="Task wrapper for a shortcut ref.",
        app="com.android.settings",
        platform="android",
        steps=(node,),
    )

    payload = skill.to_dict()
    round_tripped = TaskSkill.from_dict(payload)

    assert payload["steps"] == [
        {
            "kind": "shortcut_ref",
            "shortcut_id": "open_settings",
            "param_bindings": {"panel": "{{panel}}"},
        }
    ]
    assert round_tripped == skill
    assert round_tripped.steps[0] == node


def test_branch_node_round_trip() -> None:
    branch = BranchNode(
        condition=StateDescriptor(
            kind="element_visible",
            value="Advanced settings",
        ),
        then_steps=(
            ShortcutRefNode(
                shortcut_id="open_settings",
                param_bindings={"panel": "{{panel}}"},
            ),
        ),
        else_steps=(
            SkillStep(
                action_type="tap",
                target="Settings",
            ),
        ),
    )

    skill = TaskSkill(
        skill_id="task-branch",
        name="Branch Task",
        description="Task with recursive branch nodes.",
        app="com.android.settings",
        platform="android",
        steps=(branch,),
    )

    payload = skill.to_dict()
    round_tripped = TaskSkill.from_dict(payload)

    assert payload["steps"] == [
        {
            "kind": "branch",
            "condition": {
                "kind": "element_visible",
                "value": "Advanced settings",
            },
            "then_steps": [
                {
                    "kind": "shortcut_ref",
                    "shortcut_id": "open_settings",
                    "param_bindings": {"panel": "{{panel}}"},
                }
            ],
            "else_steps": [
                {
                    "kind": "atom_step",
                    "step": {
                        "action_type": "tap",
                        "target": "Settings",
                    },
                }
            ],
        }
    ]
    assert round_tripped == skill
    assert round_tripped.steps[0] == branch


def test_task_skill_round_trip() -> None:
    inline_step = SkillStep(action_type="tap", target="Settings")
    task_skill = TaskSkill(
        skill_id="task-open-settings",
        name="Open Settings",
        description="Use shortcut when available, otherwise tap directly.",
        app="com.android.settings",
        platform="android",
        steps=(
            ShortcutRefNode(
                shortcut_id="open_settings",
                param_bindings={"panel": "{{panel}}"},
            ),
            inline_step,
            BranchNode(
                condition=StateDescriptor(
                    kind="app_foreground",
                    value="Settings",
                ),
                then_steps=(
                    ShortcutRefNode(
                        shortcut_id="open_settings",
                        param_bindings={"panel": "{{panel}}"},
                    ),
                ),
                else_steps=(inline_step,),
            ),
        ),
        memory_context_id="entry-123",
        tags=("settings", "task"),
        created_at=1_700_000_001.0,
    )

    payload = task_skill.to_dict()
    round_tripped = TaskSkill.from_dict(payload)

    assert payload["steps"][0]["kind"] == "shortcut_ref"
    assert payload["steps"][1] == {
        "kind": "atom_step",
        "step": {
            "action_type": "tap",
            "target": "Settings",
        },
    }
    assert payload["steps"][2]["kind"] == "branch"
    assert payload["memory_context_id"] == "entry-123"
    assert round_tripped == task_skill


def test_task_node_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unsupported task node type"):
        _task_node_from_dict({"kind": "mystery_node"})


def test_grounding_result_round_trip() -> None:
    from opengui.grounding.protocol import GroundingResult

    result = GroundingResult(
        grounder_id="llm:test",
        confidence=0.85,
        resolved_params={"text": "wifi"},
        fallback_metadata={"strategy": "none"},
    )

    payload = result.to_dict()

    assert payload == {
        "grounder_id": "llm:test",
        "confidence": 0.85,
        "resolved_params": {"text": "wifi"},
        "fallback_metadata": {"strategy": "none"},
    }
    assert GroundingResult.from_dict(payload) == result


def test_fake_grounder_conforms_to_protocol() -> None:
    from opengui.grounding.protocol import GrounderProtocol, GroundingContext, GroundingResult

    class FakeGrounder:
        async def ground(
            self,
            target: str,
            context: GroundingContext,
        ) -> GroundingResult:
            return GroundingResult(
                grounder_id="fake:grounder",
                confidence=1.0,
                resolved_params={"target": target, "task_hint": context.task_hint},
                fallback_metadata=None,
            )

    assert isinstance(FakeGrounder(), GrounderProtocol)


@pytest.mark.asyncio
async def test_llm_grounder_returns_grounding_result() -> None:
    from opengui.grounding.llm import LLMGrounder
    from opengui.grounding.protocol import GroundingContext, GroundingResult

    llm = _ScriptedGroundingLLM(
        LLMResponse(content='{"confidence": 0.91, "resolved_params": {"text": "wifi"}}')
    )
    grounder = LLMGrounder(llm=llm, grounder_id="llm:test")
    context = GroundingContext(
        screenshot_path=Path("/tmp/fake.png"),
        observation=Observation(
            screenshot_path="/tmp/fake.png",
            screen_width=1080,
            screen_height=1920,
            foreground_app="Settings",
            platform="android",
        ),
        parameter_slots=(
            ParameterSlot(
                name="text",
                type="str",
                description="Text to enter",
            ),
        ),
        task_hint="Toggle wifi",
    )

    result = await grounder.ground("wifi search box", context)

    assert isinstance(result, GroundingResult)
    assert result.grounder_id == "llm:test"
    assert result.confidence == 0.91
    assert result.resolved_params == {"text": "wifi"}


def test_grounding_modules_import_cleanly() -> None:
    grounding_pkg = importlib.import_module("opengui.grounding")
    protocol_mod = importlib.import_module("opengui.grounding.protocol")
    llm_mod = importlib.import_module("opengui.grounding.llm")

    assert hasattr(grounding_pkg, "GrounderProtocol")
    assert hasattr(protocol_mod, "GrounderProtocol")
    assert hasattr(llm_mod, "LLMGrounder")
