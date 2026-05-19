from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from opengui.observation import Observation
from opengui.skills.continuation import CodeSkillContinuationIndex
from opengui.skills.data import Skill, SkillStep
from opengui.skills.state_contract import normalize_state_contract


def _contract(
    text: str,
    *,
    app: str = "com.example.contacts",
    clickable: bool = True,
) -> dict[str, Any]:
    state = ["visible"]
    if clickable:
        state.append("clickable")
    return normalize_state_contract({
        "anchor": {"app_package": app},
        "signature": {
            "required": [{"selector": {"text": text}, "state": state}],
            "forbidden": [],
        },
    })


def _skill(
    skill_id: str,
    name: str,
    steps: tuple[SkillStep, ...],
    *,
    app: str = "com.example.contacts",
) -> Skill:
    return Skill(
        skill_id=skill_id,
        name=name,
        description=name.replace("_", " "),
        app=app,
        platform="android",
        steps=steps,
        parameters=("name",),
        created_at=1_700_000_000.0,
    )


def _observation(
    text: str,
    *,
    app: str = "com.example.contacts",
    include_ui_evidence: bool = True,
) -> Observation:
    extra: dict[str, Any] = {}
    if include_ui_evidence:
        extra = {
            "visible_text": [text],
            "ui_tree": [{"text": text, "clickable": True, "enabled": True}],
        }
    return Observation(
        screenshot_path="",
        screen_width=1080,
        screen_height=2400,
        foreground_app=app,
        platform="android",
        extra=extra,
    )


def test_continuation_index_builds_contract_suffix_candidates() -> None:
    entry_skill = _skill(
        "open-contact-form",
        "open_contact_insert_form",
        (
            SkillStep(
                action_type="open_intent",
                target="insert contact",
                state_contract=_contract("First name"),
            ),
            SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),
        ),
    )
    details_skill = _skill(
        "enter-details",
        "enter_contact_details",
        (
            SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),
            SkillStep(action_type="input_text", target="{{name}}", state_contract=_contract("First name")),
        ),
    )

    index = CodeSkillContinuationIndex.from_skills([entry_skill, details_skill])

    assert len(index.candidates) == 3
    candidate = [c for c in index.candidates if c.source_skill.skill_id == "enter-details"][0]
    assert candidate.start_step == 0
    assert candidate.first_step.action_type == "tap"
    assert candidate.suffix_skill == replace(details_skill, steps=details_skill.steps[0:])
    assert candidate.suffix_skill.parameters == ("name",)


def test_continuation_index_skips_entry_actions_and_missing_contracts() -> None:
    skill = _skill(
        "mixed",
        "mixed_entry",
        (
            SkillStep(action_type="open_app", target="Contacts", state_contract=_contract("First name")),
            SkillStep(action_type="open_deeplink", target="content://contacts", state_contract=_contract("First name")),
            SkillStep(action_type="open_intent", target="insert contact", state_contract=_contract("First name")),
            SkillStep(action_type="tap", target="Unanchored"),
            SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),
        ),
    )

    index = CodeSkillContinuationIndex.from_skills([skill])

    assert len(index.candidates) == 1
    assert index.candidates[0].start_step == 4
    assert index.candidates[0].first_step.target == "First name"


def test_continuation_search_selects_matching_contract() -> None:
    skill = _skill(
        "enter-details",
        "enter_contact_details",
        (
            SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),
            SkillStep(action_type="input_text", target="{{name}}", state_contract=_contract("First name")),
        ),
    )
    index = CodeSkillContinuationIndex.from_skills([skill])

    decision = index.find_next(_observation("First name"), app="com.example.contacts")

    assert decision.reason == "matched_state_contract"
    assert decision.candidate is not None
    assert decision.candidate.source_skill.skill_id == "enter-details"
    assert decision.candidate.suffix_skill.steps == skill.steps
    assert decision.checked_count == 1


def test_continuation_search_rejects_failed_contract() -> None:
    skill = _skill(
        "enter-details",
        "enter_contact_details",
        (SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),),
    )
    index = CodeSkillContinuationIndex.from_skills([skill])

    decision = index.find_next(_observation("Last name"), app="com.example.contacts")

    assert decision.candidate is None
    assert decision.reason == "no_matching_contract"
    assert decision.failed_count == 1


def test_continuation_search_rejects_unevaluable_contract() -> None:
    skill = _skill(
        "enter-details",
        "enter_contact_details",
        (SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),),
    )
    index = CodeSkillContinuationIndex.from_skills([skill])

    decision = index.find_next(
        _observation("First name", include_ui_evidence=False),
        app="com.example.contacts",
    )

    assert decision.candidate is None
    assert decision.reason == "no_evaluable_contracts"
    assert decision.unevaluable_count == 1


def test_continuation_search_skips_exact_current_skill_replay() -> None:
    current = _skill(
        "current",
        "current_skill",
        (
            SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),
            SkillStep(action_type="tap", target="Last name", state_contract=_contract("Last name")),
        ),
    )
    next_skill = _skill(
        "next",
        "enter_contact_details",
        (SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),),
    )
    index = CodeSkillContinuationIndex.from_skills([current, next_skill])

    decision = index.find_next(
        _observation("First name"),
        current_skill_id="current",
        app="com.example.contacts",
    )

    assert decision.candidate is not None
    assert decision.candidate.source_skill.skill_id == "next"


def test_continuation_search_skips_excluded_source_skills() -> None:
    first = _skill(
        "first",
        "first_skill",
        (SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),),
    )
    second = _skill(
        "second",
        "second_skill",
        (SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),),
    )
    index = CodeSkillContinuationIndex.from_skills([first, second])

    decision = index.find_next(
        _observation("First name"),
        excluded_skill_ids={"first"},
        app="com.example.contacts",
    )

    assert decision.candidate is not None
    assert decision.candidate.source_skill.skill_id == "second"


def test_continuation_index_rejects_weak_generic_contract() -> None:
    weak_skill = _skill(
        "weak",
        "tap_more_options",
        (
            SkillStep(
                action_type="tap",
                target="More options",
                state_contract=_contract("More options"),
            ),
        ),
    )

    index = CodeSkillContinuationIndex.from_skills([weak_skill])

    assert index.candidates == ()


def test_continuation_index_rejects_multi_required_page_contract() -> None:
    page_contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.contacts"},
        "signature": {
            "required": [
                {"selector": {"text": "Cancel"}, "state": ["visible"]},
                {"selector": {"text": "First name"}, "state": ["visible"]},
                {"selector": {"text": "Save"}, "state": ["visible"]},
            ],
            "forbidden": [],
        },
    })
    skill = _skill(
        "page-contract",
        "page_contract",
        (SkillStep(action_type="tap", target="First name", state_contract=page_contract),),
    )

    index = CodeSkillContinuationIndex.from_skills([skill])

    assert index.candidates == ()


def test_continuation_index_rejects_tab_menu_background_contract() -> None:
    tab_contract = normalize_state_contract({
        "anchor": {"app_package": "com.google.android.deskclock"},
        "signature": {
            "required": [
                {
                    "selector": {
                        "resource_id": "com.google.android.deskclock:id/tab_menu_stopwatch"
                    },
                    "state": ["visible", "clickable"],
                }
            ],
            "forbidden": [],
        },
    })
    skill = _skill(
        "run-stopwatch",
        "run_stopwatch",
        (SkillStep(action_type="tap", target="Stopwatch", state_contract=tab_contract),),
        app="com.google.android.deskclock",
    )

    index = CodeSkillContinuationIndex.from_skills([skill])

    assert index.candidates == ()


@pytest.mark.asyncio
async def test_continuation_index_lists_skills_from_library() -> None:
    skill = _skill(
        "enter-details",
        "enter_contact_details",
        (SkillStep(action_type="tap", target="First name", state_contract=_contract("First name")),),
    )

    class _Library:
        def list_all(self, **kwargs: Any) -> list[Skill]:
            self.kwargs = kwargs
            return [skill]

    library = _Library()

    index = await CodeSkillContinuationIndex.from_library(
        library,
        platform="android",
        app="com.example.contacts",
    )

    assert library.kwargs == {"platform": "android", "app": "com.example.contacts"}
    assert len(index.candidates) == 1
