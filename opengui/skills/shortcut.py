"""
opengui.skills.shortcut
~~~~~~~~~~~~~~~~~~~~~~~
Shortcut-layer schema primitives and skill contract.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from opengui.skills.data import SkillStep


@dataclass(frozen=True)
class StateDescriptor:
    kind: str
    value: str
    negated: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "value": self.value,
        }
        if self.negated:
            payload["negated"] = True
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateDescriptor:
        return cls(
            kind=data["kind"],
            value=data["value"],
            negated=data.get("negated", False),
        )


@dataclass(frozen=True)
class ParameterSlot:
    name: str
    type: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParameterSlot:
        return cls(
            name=data["name"],
            type=data["type"],
            description=data["description"],
        )


@dataclass(frozen=True)
class ShortcutSkill:
    skill_id: str
    name: str
    description: str
    app: str
    platform: str
    steps: tuple[SkillStep, ...] = ()
    parameter_slots: tuple[ParameterSlot, ...] = ()
    preconditions: tuple[StateDescriptor, ...] = ()
    postconditions: tuple[StateDescriptor, ...] = ()
    tags: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "app": self.app,
            "platform": self.platform,
            "steps": [step.to_dict() for step in self.steps],
            "parameter_slots": [slot.to_dict() for slot in self.parameter_slots],
            "preconditions": [state.to_dict() for state in self.preconditions],
            "postconditions": [state.to_dict() for state in self.postconditions],
            "tags": list(self.tags),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShortcutSkill:
        return cls(
            skill_id=data.get("skill_id", str(uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            app=data.get("app", ""),
            platform=data.get("platform", "unknown"),
            steps=tuple(SkillStep.from_dict(step) for step in data.get("steps", [])),
            parameter_slots=tuple(
                ParameterSlot.from_dict(slot)
                for slot in data.get("parameter_slots", [])
            ),
            preconditions=tuple(
                StateDescriptor.from_dict(state)
                for state in data.get("preconditions", [])
            ),
            postconditions=tuple(
                StateDescriptor.from_dict(state)
                for state in data.get("postconditions", [])
            ),
            tags=tuple(data.get("tags", ())),
            created_at=data.get("created_at", time.time()),
        )
