"""
opengui.skills.continuation
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Deterministic suffix-skill matching for lightweight skill chaining.

This module intentionally avoids full graph planning.  It indexes every
contract-anchored suffix of existing skills, then selects a suffix only when
the current observation locally satisfies the suffix first-step state contract.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from typing import Any

from opengui.observation import Observation
from opengui.skills.data import Skill, SkillStep
from opengui.skills.state_contract import (
    evaluate_state_contract,
    normalize_state_contract,
)
from opengui.skills.static_selector_filter import selector_is_static

ENTRY_ACTIONS: frozenset[str] = frozenset({"open_app", "open_deeplink", "open_intent"})
_GENERIC_SELECTOR_TEXTS: frozenset[str] = frozenset({
    "more options",
    "back",
    "cancel",
    "ok",
    "search",
    "menu",
    "navigate up",
    "返回",
    "取消",
    "确定",
    "搜索",
    "更多选项",
    "更多",
})


@dataclass(frozen=True)
class SkillContinuationCandidate:
    """A concrete suffix of a stored skill that may continue from a page."""

    source_skill: Skill
    suffix_skill: Skill
    start_step: int
    first_step: SkillStep


@dataclass(frozen=True)
class SkillContinuationDecision:
    """Result of local continuation matching."""

    candidate: SkillContinuationCandidate | None
    reason: str
    checked_count: int = 0
    failed_count: int = 0
    unevaluable_count: int = 0


class CodeSkillContinuationIndex:
    """Index contract-anchored suffixes from code-backed or legacy skills."""

    def __init__(self, candidates: list[SkillContinuationCandidate] | None = None) -> None:
        self._candidates = tuple(candidates or ())

    @property
    def candidates(self) -> tuple[SkillContinuationCandidate, ...]:
        return self._candidates

    @classmethod
    async def from_library(
        cls,
        library: Any,
        *,
        platform: str | None = None,
        app: str | None = None,
    ) -> "CodeSkillContinuationIndex":
        skills = await _list_library_skills(library, platform=platform, app=app)
        return cls.from_skills(skills, platform=platform, app=app)

    @classmethod
    def from_skills(
        cls,
        skills: list[Skill] | tuple[Skill, ...],
        *,
        platform: str | None = None,
        app: str | None = None,
    ) -> "CodeSkillContinuationIndex":
        candidates: list[SkillContinuationCandidate] = []
        for skill in skills:
            if platform is not None and getattr(skill, "platform", None) != platform:
                continue
            if app is not None and getattr(skill, "app", None) != app:
                continue
            steps = tuple(getattr(skill, "steps", ()) or ())
            for start_step, step in enumerate(steps):
                action_type = str(getattr(step, "action_type", "") or "")
                if action_type in ENTRY_ACTIONS:
                    continue
                if not _is_continuation_contract_usable(getattr(step, "state_contract", None)):
                    continue
                candidates.append(
                    SkillContinuationCandidate(
                        source_skill=skill,
                        suffix_skill=replace(skill, steps=steps[start_step:]),
                        start_step=start_step,
                        first_step=step,
                    )
                )
        return cls(candidates)

    def find_next(
        self,
        observation: Observation,
        *,
        current_skill_id: str | None = None,
        excluded_skill_ids: set[str] | frozenset[str] | None = None,
        app: str | None = None,
    ) -> SkillContinuationDecision:
        """Return the first suffix whose first contract matches *observation*."""
        if not self._candidates:
            return SkillContinuationDecision(candidate=None, reason="no_candidates")

        ordered = sorted(
            self._candidates,
            key=lambda candidate: (
                0 if app and candidate.source_skill.app == app else 1,
                -len(candidate.suffix_skill.steps),
                candidate.source_skill.name,
                candidate.start_step,
            ),
        )
        app_filtered = [
            candidate
            for candidate in ordered
            if app is None or candidate.source_skill.app == app
        ]
        if not app_filtered:
            return SkillContinuationDecision(candidate=None, reason="app_mismatch")

        checked = 0
        failed = 0
        unevaluable = 0
        excluded_ids = {str(skill_id) for skill_id in (excluded_skill_ids or set()) if skill_id}
        for candidate in app_filtered:
            if candidate.source_skill.skill_id in excluded_ids:
                continue
            if (
                current_skill_id
                and candidate.source_skill.skill_id == current_skill_id
                and candidate.start_step == 0
            ):
                continue
            checked += 1
            contract_result = evaluate_state_contract(
                candidate.first_step.state_contract,
                observation=observation,
            )
            if contract_result is True:
                return SkillContinuationDecision(
                    candidate=candidate,
                    reason="matched_state_contract",
                    checked_count=checked,
                    failed_count=failed,
                    unevaluable_count=unevaluable,
                )
            if contract_result is False:
                failed += 1
            else:
                unevaluable += 1

        if checked == 0:
            return SkillContinuationDecision(candidate=None, reason="no_candidates")
        reason = "no_evaluable_contracts" if unevaluable and failed == 0 else "no_matching_contract"
        return SkillContinuationDecision(
            candidate=None,
            reason=reason,
            checked_count=checked,
            failed_count=failed,
            unevaluable_count=unevaluable,
        )


async def _list_library_skills(
    library: Any,
    *,
    platform: str | None,
    app: str | None,
) -> list[Skill]:
    list_all = getattr(library, "list_all", None)
    if not callable(list_all):
        return []
    try:
        result = list_all(platform=platform, app=app)
    except TypeError:
        result = list_all()
    if inspect.isawaitable(result):
        result = await result
    return list(result or [])


def _is_continuation_contract_usable(contract: Any) -> bool:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return False
    required = normalized.get("signature", {}).get("required", [])
    if not required:
        return False
    return any(_is_required_element_usable(element) for element in required)


def _is_required_element_usable(element: Any) -> bool:
    if not isinstance(element, dict):
        return False
    selector = element.get("selector")
    if not isinstance(selector, dict) or not selector:
        return False
    if _is_generic_selector(selector):
        return False
    return selector_is_static(selector)


def _is_generic_selector(selector: dict[str, Any]) -> bool:
    text_value = selector.get("text") or selector.get("content_desc")
    if text_value is None:
        return False
    return str(text_value).strip().lower() in _GENERIC_SELECTOR_TEXTS


__all__ = [
    "CodeSkillContinuationIndex",
    "ENTRY_ACTIONS",
    "SkillContinuationCandidate",
    "SkillContinuationDecision",
]
