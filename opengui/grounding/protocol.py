"""
opengui.grounding.protocol
~~~~~~~~~~~~~~~~~~~~~~~~~~
Grounding contracts for resolving semantic targets into structured action
parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from opengui.interfaces import LLMProvider
from opengui.observation import Observation
from opengui.skills.shortcut import ParameterSlot


@dataclass(frozen=True)
class GroundingContext:
    screenshot_path: Path
    observation: Observation
    parameter_slots: tuple[ParameterSlot, ...] = ()
    task_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "screenshot_path": str(self.screenshot_path),
            "observation": {
                "screenshot_path": self.observation.screenshot_path,
                "screen_width": self.observation.screen_width,
                "screen_height": self.observation.screen_height,
                "foreground_app": self.observation.foreground_app,
                "platform": self.observation.platform,
                "extra": dict(self.observation.extra),
            },
            "parameter_slots": [slot.to_dict() for slot in self.parameter_slots],
        }
        if self.task_hint is not None:
            payload["task_hint"] = self.task_hint
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroundingContext":
        observation = data["observation"]
        return cls(
            screenshot_path=Path(data["screenshot_path"]),
            observation=Observation(
                screenshot_path=observation.get("screenshot_path"),
                screen_width=observation["screen_width"],
                screen_height=observation["screen_height"],
                foreground_app=observation.get("foreground_app"),
                platform=observation.get("platform", "unknown"),
                extra=dict(observation.get("extra", {})),
            ),
            parameter_slots=tuple(
                ParameterSlot.from_dict(slot)
                for slot in data.get("parameter_slots", [])
            ),
            task_hint=data.get("task_hint"),
        )


@dataclass(frozen=True)
class GroundingResult:
    grounder_id: str
    confidence: float
    resolved_params: dict[str, Any]
    fallback_metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "grounder_id": self.grounder_id,
            "confidence": self.confidence,
            "resolved_params": dict(self.resolved_params),
        }
        payload["fallback_metadata"] = (
            dict(self.fallback_metadata) if self.fallback_metadata is not None else None
        )
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroundingResult":
        fallback_metadata = data.get("fallback_metadata")
        return cls(
            grounder_id=data["grounder_id"],
            confidence=float(data["confidence"]),
            resolved_params=dict(data.get("resolved_params", {})),
            fallback_metadata=dict(fallback_metadata) if fallback_metadata is not None else None,
        )


@runtime_checkable
class GrounderProtocol(Protocol):
    async def ground(self, target: str, context: GroundingContext) -> GroundingResult: ...


__all__ = [
    "GrounderProtocol",
    "GroundingContext",
    "GroundingResult",
    "LLMProvider",
]
