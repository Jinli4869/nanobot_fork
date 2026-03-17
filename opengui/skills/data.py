"""
opengui.skills.data
~~~~~~~~~~~~~~~~~~~
Skill and SkillStep dataclasses — the atomic unit of reusable GUI knowledge.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillStep:
    """One atomic action within a skill sequence."""

    action_type: str
    target: str
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_state: str | None = None
    valid_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "action_type": self.action_type,
            "target": self.target,
        }
        if self.parameters:
            d["parameters"] = self.parameters
        if self.expected_state is not None:
            d["expected_state"] = self.expected_state
        if self.valid_state is not None:
            d["valid_state"] = self.valid_state
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillStep:
        return cls(
            action_type=data["action_type"],
            target=data.get("target", ""),
            parameters=data.get("parameters", {}),
            expected_state=data.get("expected_state"),
            valid_state=data.get("valid_state"),
        )


@dataclass(frozen=True)
class Skill:
    """A reusable, parameterized GUI skill extracted from trajectories.

    Parameters use ``{{param_name}}`` placeholders in step targets/parameters
    that are grounded at execution time.
    """

    skill_id: str
    name: str
    description: str
    app: str
    platform: str
    steps: tuple[SkillStep, ...] = ()
    parameters: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)
    success_count: int = 0
    failure_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "app": self.app,
            "platform": self.platform,
            "steps": [s.to_dict() for s in self.steps],
            "parameters": list(self.parameters),
            "preconditions": list(self.preconditions),
            "tags": list(self.tags),
            "created_at": self.created_at,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        return cls(
            skill_id=data.get("skill_id", str(uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            app=data.get("app", ""),
            platform=data.get("platform", "unknown"),
            steps=tuple(SkillStep.from_dict(s) for s in data.get("steps", [])),
            parameters=tuple(data.get("parameters", ())),
            preconditions=tuple(data.get("preconditions", ())),
            tags=tuple(data.get("tags", ())),
            created_at=data.get("created_at", time.time()),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
        )
