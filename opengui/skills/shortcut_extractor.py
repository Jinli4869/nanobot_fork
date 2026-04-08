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
_COORD_KEYS = frozenset({"x", "y", "x2", "y2"})
_TEXTUAL_ACTIONS = frozenset({"input_text"})
_POINTER_ACTIONS = frozenset({"tap", "click", "long_press", "double_tap"})
_GENERALIZABLE_STRING_KEYS = frozenset(
    {"text", "label", "value", "query", "selector", "resource_id", "accessibility_id"}
)
_STABLE_CONTROL_LITERALS = frozenset({"send", "back", "compose", "cancel", "ok"})


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
        action_type = str(action.get("action_type", ""))
        target = self._generalize_target(
            raw_target=str(step.get("model_output", "")),
            action_type=action_type,
            action=action,
        )
        parameters = self._generalize_parameters(
            action_type=action_type,
            target=target,
            action=action,
        )
        return SkillStep(
            action_type=action_type,
            target=target,
            parameters=parameters,
            expected_state=self._extract_state(step, "expected_state"),
            valid_state=self._extract_state(step, "valid_state"),
        )

    def _infer_parameter_slots(self, steps: tuple[SkillStep, ...]) -> tuple[ParameterSlot, ...]:
        seen: dict[str, ParameterSlot] = {}
        for step in steps:
            for name in _PARAM_RE.findall(step.target):
                self._register_slot(seen, name)
            for value in step.parameters.values():
                if not isinstance(value, str):
                    continue
                for name in _PARAM_RE.findall(value):
                    self._register_slot(seen, name)
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

    def _generalize_target(
        self,
        *,
        raw_target: str,
        action_type: str,
        action: dict[str, Any],
    ) -> str:
        target = raw_target.strip()
        if not target and action_type in _TEXTUAL_ACTIONS:
            target = "Type {{text}}"
        action_text = action.get("text")
        if action_type in _TEXTUAL_ACTIONS and isinstance(action_text, str):
            placeholder_name = self._infer_placeholder_name(action_type, "text", target, action_text)
            if action_text and action_text in target and "{{" not in target:
                return target.replace(action_text, f"{{{{{placeholder_name}}}}}")
        return target

    def _generalize_parameters(
        self,
        *,
        action_type: str,
        target: str,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        parameters: dict[str, Any] = {}
        placeholder_names = _PARAM_RE.findall(target)
        if action_type in _TEXTUAL_ACTIONS and not placeholder_names:
            placeholder_names = [self._infer_placeholder_name(action_type, "text", target, action.get("text"))]

        for key, value in action.items():
            if key == "action_type":
                continue
            if (action_type in _POINTER_ACTIONS or action_type in _TEXTUAL_ACTIONS) and key in _COORD_KEYS:
                continue
            if self._should_generalize_parameter(
                action_type=action_type,
                key=key,
                target=target,
                value=value,
                placeholder_names=placeholder_names,
            ):
                placeholder_name = self._infer_placeholder_name(action_type, key, target, value)
                parameters[key] = f"{{{{{placeholder_name}}}}}"
                continue
            parameters[key] = value

        if action_type in _TEXTUAL_ACTIONS and "text" not in parameters:
            placeholder_name = placeholder_names[0]
            parameters["text"] = f"{{{{{placeholder_name}}}}}"

        return parameters

    def _register_slot(self, seen: dict[str, ParameterSlot], name: str) -> None:
        if name in seen:
            return
        seen[name] = ParameterSlot(
            name=name,
            type=self._infer_slot_type(name),
            description=f"Value for {name}",
        )

    def _infer_slot_type(self, name: str) -> str:
        lowered = name.lower()
        if lowered in {"x", "y", "x2", "y2", "coord", "coordinate"}:
            return "coordinate"
        if any(token in lowered for token in ("text", "message", "query", "term", "keyword")):
            return "text"
        return "string"

    def _should_generalize_parameter(
        self,
        *,
        action_type: str,
        key: str,
        target: str,
        value: Any,
        placeholder_names: list[str],
    ) -> bool:
        if key not in _GENERALIZABLE_STRING_KEYS:
            return False
        if not isinstance(value, str) or not value.strip():
            return False
        if action_type in _TEXTUAL_ACTIONS and key == "text":
            return True
        if self._is_stable_control_literal(key, value):
            return False
        inferred_name = self._infer_placeholder_name(action_type, key, target, value)
        if inferred_name in placeholder_names:
            return True
        if placeholder_names and key in {"selector", "resource_id", "accessibility_id", "value"}:
            return True
        return self._value_looks_variable(key=key, target=target, value=value)

    def _infer_placeholder_name(
        self,
        action_type: str,
        key: str,
        target: str,
        value: Any,
    ) -> str:
        lowered_target = target.lower()
        lowered_value = str(value).lower()
        combined = f"{lowered_target} {lowered_value}"
        if "recipient" in combined or "thread" in lowered_value or "chat" in lowered_target:
            return "recipient"
        if "message" in combined or (action_type in _TEXTUAL_ACTIONS and key == "text"):
            return "message"
        if "search" in combined:
            return "search_term"
        if "query" in combined:
            return "query"
        if "selector" in combined or key in {"selector", "resource_id", "accessibility_id"}:
            return "selector" if "selector" in combined else key
        if key == "value":
            return "value"
        if key in {"x", "y"}:
            return key
        return "text"

    def _is_stable_control_literal(self, key: str, value: str) -> bool:
        if key not in {"label", "text", "value"}:
            return False
        normalized = value.strip().lower()
        return normalized in _STABLE_CONTROL_LITERALS

    def _value_looks_variable(self, *, key: str, target: str, value: str) -> bool:
        lowered_value = value.strip().lower()
        lowered_target = target.lower()
        if key in {"resource_id", "accessibility_id"} and (
            lowered_value.startswith(("thread_", "chat_", "recipient_", "conversation_"))
            or any(token in lowered_target for token in ("recipient", "message", "search", "query"))
        ):
            return True
        if key in {"selector", "query"} and any(
            token in lowered_target for token in ("recipient", "message", "search", "query", "selector")
        ):
            return True
        if key in {"text", "value"} and any(
            token in lowered_target for token in ("message", "search", "query", "recipient", "value")
        ):
            return True
        return False


class _AlwaysPassStepCritic:
    """Default step critic that accepts every extracted step."""

    async def evaluate(self, step: dict[str, Any], step_index: int) -> StepVerdict:
        return StepVerdict(step_index=step_index, passed=True, reason="always-pass default")


class _AlwaysPassTrajectoryCritic:
    """Default trajectory critic that accepts every extracted trajectory."""

    async def evaluate(self, steps: list[dict[str, Any]], metadata: dict[str, Any]) -> TrajectoryVerdict:
        return TrajectoryVerdict(passed=True, reason="always-pass default")


class ExtractionPipeline:
    """Run quality gates before turning a trajectory into a shortcut skill."""

    def __init__(
        self,
        *,
        step_critic: StepCritic | None = None,
        trajectory_critic: TrajectoryCritic | None = None,
        producer: ShortcutSkillProducer | None = None,
    ) -> None:
        self._step_critic: StepCritic = step_critic or _AlwaysPassStepCritic()
        self._trajectory_critic: TrajectoryCritic = trajectory_critic or _AlwaysPassTrajectoryCritic()
        self._producer: ShortcutSkillProducer = producer or ShortcutSkillProducer()

    async def run(
        self,
        steps: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> ExtractionSuccess | ExtractionRejected:
        if not steps:
            return ExtractionRejected(
                reason="too_few_steps",
                failed_step_verdict=None,
                failed_trajectory_verdict=None,
            )

        step_verdicts: list[StepVerdict] = []
        for step_index, step in enumerate(steps):
            verdict = await self._step_critic.evaluate(step, step_index)
            step_verdicts.append(verdict)
            if not verdict.passed:
                return ExtractionRejected(
                    reason="step_critic",
                    failed_step_verdict=verdict,
                    failed_trajectory_verdict=None,
                )

        trajectory_verdict = await self._trajectory_critic.evaluate(steps, metadata)
        if not trajectory_verdict.passed:
            return ExtractionRejected(
                reason="trajectory_critic",
                failed_step_verdict=None,
                failed_trajectory_verdict=trajectory_verdict,
            )

        candidate = self._producer.produce(
            steps,
            app=str(metadata.get("app", "unknown")),
            platform=str(metadata.get("platform", "unknown")),
        )
        return ExtractionSuccess(
            candidate=candidate,
            step_verdicts=tuple(step_verdicts),
            trajectory_verdict=trajectory_verdict,
        )
