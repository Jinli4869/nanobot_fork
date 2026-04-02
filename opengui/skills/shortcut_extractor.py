"""
opengui.skills.shortcut_extractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Quality-gated extraction primitives for Phase 26.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from opengui.skills.data import SkillStep
from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.shortcut import ParameterSlot, ShortcutSkill, StateDescriptor

_PARAM_RE = re.compile(r"\{\{(\w+)\}\}")
_SKIP_STATE_VALUES = {"", "no need to verify"}


@dataclass(frozen=True)
class StepVerdict:
    step_index: int
    passed: bool
    reason: str


@dataclass(frozen=True)
class TrajectoryVerdict:
    passed: bool
    reason: str
    failed_step_index: int | None = None


@dataclass(frozen=True)
class ExtractionSuccess:
    candidate: ShortcutSkill
    step_verdicts: tuple[StepVerdict, ...]
    trajectory_verdict: TrajectoryVerdict


@dataclass(frozen=True)
class ExtractionRejected:
    reason: str
    failed_step_verdict: StepVerdict | None
    failed_trajectory_verdict: TrajectoryVerdict | None


@runtime_checkable
class StepCritic(Protocol):
    async def evaluate(self, step: dict[str, Any], step_index: int) -> StepVerdict:
        ...


@runtime_checkable
class TrajectoryCritic(Protocol):
    async def evaluate(self, steps: list[dict[str, Any]], metadata: dict[str, Any]) -> TrajectoryVerdict:
        ...


class ShortcutSkillProducer:
    def produce(self, steps: list[dict[str, Any]], *, app: str, platform: str) -> ShortcutSkill:
        skill_steps = tuple(self._to_skill_step(step) for step in steps)
        normalized_app = normalize_app_identifier(platform, app)
        first_step = skill_steps[0] if skill_steps else SkillStep(action_type="unknown", target="")

        return ShortcutSkill(
            skill_id=str(uuid.uuid4()),
            name=self._build_name(first_step),
            description=self._build_description(steps),
            app=normalized_app,
            platform=platform,
            steps=skill_steps,
            parameter_slots=self._infer_parameter_slots(skill_steps),
            preconditions=self._collect_conditions(steps, "valid_state"),
            postconditions=self._collect_conditions(steps, "expected_state"),
            created_at=time.time(),
        )

    def _to_skill_step(self, step: dict[str, Any]) -> SkillStep:
        action = step.get("action", {})
        parameters = {
            key: value
            for key, value in action.items()
            if key != "action_type"
        }
        return SkillStep(
            action_type=str(action.get("action_type", "")),
            target=str(step.get("model_output", "")),
            parameters=parameters,
            expected_state=self._extract_state(step, "expected_state"),
            valid_state=self._extract_state(step, "valid_state"),
        )

    def _infer_parameter_slots(self, steps: tuple[SkillStep, ...]) -> tuple[ParameterSlot, ...]:
        seen: dict[str, ParameterSlot] = {}
        for step in steps:
            for name in _PARAM_RE.findall(step.target):
                if name not in seen:
                    seen[name] = ParameterSlot(
                        name=name,
                        type="string",
                        description=f"Value for {name}",
                    )
        return tuple(seen.values())

    def _collect_conditions(
        self,
        steps: list[dict[str, Any]],
        field_name: str,
    ) -> tuple[StateDescriptor, ...]:
        conditions: list[StateDescriptor] = []
        seen: set[str] = set()
        for step in steps:
            value = self._extract_state(step, field_name)
            normalized = self._normalize_state_value(value)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            conditions.append(StateDescriptor(kind="screen_state", value=normalized))
        return tuple(conditions)

    def _build_name(self, step: SkillStep) -> str:
        raw = f"{step.action_type}_{self._slugify(step.target)}".strip("_")
        if not raw:
            return "extracted_shortcut"
        return raw[:50].rstrip("_") or "extracted_shortcut"

    def _build_description(self, steps: list[dict[str, Any]]) -> str:
        for step in steps:
            for key in ("task_description", "task", "description"):
                value = str(step.get(key, "")).strip()
                if value:
                    return value
            metadata = step.get("metadata")
            if isinstance(metadata, dict):
                for key in ("task_description", "task", "description"):
                    value = str(metadata.get(key, "")).strip()
                    if value:
                        return value
        return "Extracted from trajectory"

    def _extract_state(self, step: dict[str, Any], field_name: str) -> str | None:
        direct_value = step.get(field_name)
        if direct_value is not None:
            return str(direct_value)
        observation = step.get("observation", {})
        if isinstance(observation, dict):
            value = observation.get(field_name)
            if value is not None:
                return str(value)
        return None

    def _normalize_state_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        if cleaned.lower() in _SKIP_STATE_VALUES:
            return None
        return cleaned

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return slug or "step"
