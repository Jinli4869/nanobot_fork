"""Compact skill prompt helpers for MobileWorld-style GUI agents.

This module keeps prompt-only skill selection separate from the heavier
pre-run skill replay path.  Retrieved skills are exposed as ``use_skill``
choices, while curated composite actions are exposed as first-class action
aliases in the general_e2e action table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

USE_SKILL_ACTION_TYPE = "use_skill"
ALWAYS_ON_SKILL_TAG = "compact_action"
ACTION_ALIAS_TAG_PREFIXES = ("action_alias:", "alias:")

COMPACT_SKILL_INSTRUCTIONS = """\
# Optional Compact GUI Skills
You may choose one compact GUI skill as a single action when it is clearly useful
for the user's task. This is optional. If no listed skill clearly matches, keep
using the normal GUI actions above.

Skill action format:
`{{"action_type":"use_skill","skill_id":"listed_skill_id","skill_name":"listed_skill_name","arguments":{{"param":"value"}},"reason":"short reason"}}`

Rules:
- First compare the user task with the compact skill list. If a listed skill
  clearly matches the requested app/workflow, prefer `use_skill` over manual
  navigation.
- Use `use_skill` only when the skill id/name, description, app, transport, and
  parameters clearly match the user's task and would be a valid next prefix.
- When a `skill_id` is listed, copy it exactly into the `use_skill` action.
- A compact skill may include navigation/opening the target app internally; the
  current screen does not need to already show the target app.
- Fill `arguments` only when the task provides obvious values; otherwise use an
  empty object.
- If a skill is not clearly applicable, output a normal GUI action such as
  `click`, `input_text`, `scroll`, `answer`, or `status`.

Compact skills:
{catalog}
""".strip()

USE_SKILL_ACTION_ROW = (
    '| `use_skill`     | Run a listed compact GUI skill prefix when it clearly matches the task | '
    '`{"action_type":"use_skill","skill_id":"listed_skill_id","skill_name":"listed_skill_name","arguments":{}}` |'
)

USE_SKILL_DECISION_RULE = (
    "0. Before choosing a manual GUI action, compare the user task with the compact "
    "skill list. If one compact skill clearly matches the requested app/workflow, "
    "choose `use_skill` as the next action. A compact skill may open/navigate to "
    "the target app internally, so do not first open the app manually when the "
    "skill itself matches the whole requested workflow."
)

COMPOSITE_ACTION_DEFINITIONS: dict[str, tuple[str, str]] = {
    "click_and_type": (
        "Tap a visible input field and type text into it",
        '`{"action_type":"click_and_type","coordinate":[x,y],"text":"Hello"}`',
    ),
    "click_then_type": (
        "Tap a visible coordinate and type text; set auto_enter true for search submission",
        '`{"action_type":"click_then_type","coordinate":[x,y],"text":"Hello","auto_enter":false}`',
    ),
    "click_multi": (
        "Tap multiple visible coordinates in sequence",
        '`{"action_type":"click_multi","coordinates":[[x1,y1],[x2,y2]]}`',
    ),
}


@dataclass(frozen=True)
class SkillInfo:
    function_name: str
    description: str
    skill_id: str | None = None
    app: str = ""
    platform: str = ""
    tags: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    score: float | None = None
    first_action_type: str = ""
    first_action_target: str = ""
    first_action_parameters: dict[str, Any] | None = None
    first_valid_state: str | None = None


@dataclass(frozen=True)
class CompositeActionInfo:
    alias: str
    description: str
    example: str
    source_skill_id: str | None = None


@dataclass(frozen=True)
class CompactPromptParts:
    action_rows: str = ""
    decision_rules: str = ""
    compact_skill_instructions: str = ""
    skill_ids: tuple[str, ...] = ()
    composite_aliases: tuple[str, ...] = ()


def skill_info_from_flat_skill(skill: Any, *, score: float | None = None) -> SkillInfo:
    first_step = skill.steps[0] if getattr(skill, "steps", ()) else None
    first_action_parameters: dict[str, Any] | None = None
    if first_step is not None:
        first_action_parameters = dict(getattr(first_step, "parameters", {}) or {})
    return SkillInfo(
        function_name=str(getattr(skill, "name", "") or getattr(skill, "skill_id", "")),
        description=str(getattr(skill, "description", "") or ""),
        skill_id=str(getattr(skill, "skill_id", "") or ""),
        app=str(getattr(skill, "app", "") or ""),
        platform=str(getattr(skill, "platform", "") or ""),
        tags=tuple(str(tag) for tag in (getattr(skill, "tags", ()) or ())),
        parameters=tuple(str(param) for param in (getattr(skill, "parameters", ()) or ())),
        score=score,
        first_action_type=str(getattr(first_step, "action_type", "") or "") if first_step else "",
        first_action_target=str(getattr(first_step, "target", "") or "") if first_step else "",
        first_action_parameters=first_action_parameters,
        first_valid_state=str(getattr(first_step, "valid_state", "") or "") if first_step else None,
    )


def build_catalog(skills: list[SkillInfo], *, limit: int | None) -> str:
    selected = skills[:limit] if limit else skills
    return "\n".join(_format_catalog_line(skill) for skill in selected)


def is_shortcut_skill(skill: Any) -> bool:
    tags = {str(tag).lower() for tag in (getattr(skill, "tags", ()) or ())}
    if "shortcut" in tags or "deeplink" in tags or "intent" in tags:
        return True
    skill_id = str(getattr(skill, "skill_id", "") or "")
    if skill_id.startswith("shortcut:"):
        return True
    first_step = skill.steps[0] if getattr(skill, "steps", ()) else None
    return bool(first_step and getattr(first_step, "action_type", "") in {"open_deeplink", "open_intent"})


def is_always_on_skill(skill: Any, tags: tuple[str, ...] | list[str]) -> bool:
    skill_tags = {str(tag).lower() for tag in (getattr(skill, "tags", ()) or ())}
    wanted = {str(tag).lower() for tag in tags if str(tag)}
    return bool(skill_tags & wanted)


def composite_action_infos_from_skills(
    skills: list[Any],
    *,
    tags: tuple[str, ...] | list[str] = (ALWAYS_ON_SKILL_TAG,),
) -> list[CompositeActionInfo]:
    out: list[CompositeActionInfo] = []
    seen: set[str] = set()
    for skill in skills:
        if not is_always_on_skill(skill, tags):
            continue
        alias = composite_alias_from_skill(skill)
        if alias is None or alias in seen:
            continue
        description, example = COMPOSITE_ACTION_DEFINITIONS[alias]
        skill_description = str(getattr(skill, "description", "") or "").strip()
        out.append(
            CompositeActionInfo(
                alias=alias,
                description=skill_description or description,
                example=example,
                source_skill_id=str(getattr(skill, "skill_id", "") or "") or None,
            )
        )
        seen.add(alias)
    return out


def composite_alias_from_skill(skill: Any) -> str | None:
    tags = tuple(str(tag) for tag in (getattr(skill, "tags", ()) or ()))
    for tag in tags:
        lowered = tag.lower()
        for prefix in ACTION_ALIAS_TAG_PREFIXES:
            if lowered.startswith(prefix):
                alias = tag[len(prefix):].strip().lower()
                return alias if alias in COMPOSITE_ACTION_DEFINITIONS else None
    name = str(getattr(skill, "name", "") or "").strip().lower()
    return name if name in COMPOSITE_ACTION_DEFINITIONS else None


def build_compact_prompt_parts(
    *,
    retrieved_skills: list[SkillInfo],
    composite_actions: list[CompositeActionInfo],
) -> CompactPromptParts:
    action_rows: list[str] = []
    decision_rules: list[str] = []
    skill_ids: list[str] = []
    composite_aliases: list[str] = []

    if retrieved_skills:
        action_rows.append(USE_SKILL_ACTION_ROW)
        decision_rules.append(USE_SKILL_DECISION_RULE)
        skill_ids = [skill.skill_id or skill.function_name for skill in retrieved_skills]
        catalog = build_catalog(retrieved_skills, limit=None)
        compact_skill_instructions = COMPACT_SKILL_INSTRUCTIONS.format(catalog=catalog)
    else:
        compact_skill_instructions = ""

    if composite_actions:
        action_rows.extend(_format_composite_action_row(action) for action in composite_actions)
        composite_aliases = [action.alias for action in composite_actions]
        decision_rules.append(
            "0a. You may use listed composite actions directly as action_type values "
            "when they exactly match the next local UI operation. Do not invent composite "
            "actions that are not listed in the action table. When the same screen has "
            "multiple targets that need the same click and clicking them will not open a "
            "confirmation dialog, prefer `click_multi` to complete them in one action. "
            "When the next operation is tapping an input field and typing text, prefer "
            "`click_and_type` or `click_then_type` instead of separate `click` and "
            "`input_text` actions."
        )

    return CompactPromptParts(
        action_rows="\n".join(action_rows),
        decision_rules="\n".join(decision_rules),
        compact_skill_instructions=compact_skill_instructions,
        skill_ids=tuple(skill_ids),
        composite_aliases=tuple(composite_aliases),
    )


def _format_catalog_line(skill: SkillInfo) -> str:
    parts = [
        f"skill_id={skill.skill_id or skill.function_name}",
        f"skill_name={skill.function_name}",
        f"description={skill.description}",
    ]
    if skill.app:
        parts.append(f"app={skill.app}")
    if skill.tags:
        parts.append(f"tags={','.join(skill.tags)}")
    if skill.parameters:
        parts.append(f"parameters={','.join(skill.parameters)}")
    if skill.first_action_type:
        parts.append(f"first_action={skill.first_action_type}")
    if skill.first_action_target:
        parts.append(f"target={skill.first_action_target}")
    if skill.first_action_parameters:
        params = json.dumps(
            _compact_mapping(skill.first_action_parameters),
            ensure_ascii=False,
            sort_keys=True,
        )
        parts.append(f"action_parameters={params}")
    if skill.first_valid_state:
        parts.append(f"valid_state={skill.first_valid_state}")
    if skill.score is not None:
        parts.append(f"retrieval_score={skill.score:.4f}")
    return "- " + "; ".join(parts)


def _format_composite_action_row(action: CompositeActionInfo) -> str:
    return f"| `{action.alias}` | {action.description} | {action.example} |"


def _compact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _compact_value(value) for key, value in mapping.items()}


def _compact_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_compact_value(item) for item in value]
    if isinstance(value, list):
        return [_compact_value(item) for item in value]
    if isinstance(value, dict):
        return _compact_mapping(value)
    return value


__all__ = [
    "ALWAYS_ON_SKILL_TAG",
    "COMPACT_SKILL_INSTRUCTIONS",
    "COMPOSITE_ACTION_DEFINITIONS",
    "CompactPromptParts",
    "CompositeActionInfo",
    "SkillInfo",
    "USE_SKILL_ACTION_ROW",
    "USE_SKILL_ACTION_TYPE",
    "USE_SKILL_DECISION_RULE",
    "build_catalog",
    "build_compact_prompt_parts",
    "composite_action_infos_from_skills",
    "composite_alias_from_skill",
    "is_always_on_skill",
    "is_shortcut_skill",
    "skill_info_from_flat_skill",
]
