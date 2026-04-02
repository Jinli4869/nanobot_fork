from __future__ import annotations

from opengui import skills as exported_skills
from opengui.skills.data import SkillStep
from opengui.skills.shortcut import ParameterSlot, ShortcutSkill, StateDescriptor


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
