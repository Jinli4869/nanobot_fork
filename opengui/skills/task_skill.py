"""
opengui.skills.task_skill
~~~~~~~~~~~~~~~~~~~~~~~~~
Task-layer schema contracts for composing shortcut references, inline steps,
and conditional branches.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from opengui.skills.data import SkillStep
from opengui.skills.shortcut import StateDescriptor


@dataclass(frozen=True)
class ShortcutRefNode:
    shortcut_id: str
    param_bindings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BranchNode:
    condition: StateDescriptor
    then_steps: tuple["TaskNode", ...] = ()
    else_steps: tuple["TaskNode", ...] = ()


TaskNode = ShortcutRefNode | SkillStep | BranchNode


def _task_node_to_dict(node: TaskNode) -> dict[str, Any]:
    if isinstance(node, ShortcutRefNode):
        payload: dict[str, Any] = {
            "kind": "shortcut_ref",
            "shortcut_id": node.shortcut_id,
        }
        if node.param_bindings:
            payload["param_bindings"] = dict(node.param_bindings)
        return payload
    if isinstance(node, SkillStep):
        return {
            "kind": "atom_step",
            "step": node.to_dict(),
        }
    if isinstance(node, BranchNode):
        return {
            "kind": "branch",
            "condition": node.condition.to_dict(),
            "then_steps": [_task_node_to_dict(step) for step in node.then_steps],
            "else_steps": [_task_node_to_dict(step) for step in node.else_steps],
        }
    raise TypeError(f"unsupported task node instance: {type(node)!r}")


def _task_node_from_dict(data: dict[str, Any]) -> TaskNode:
    kind = data.get("kind")
    if kind == "shortcut_ref":
        return ShortcutRefNode(
            shortcut_id=data["shortcut_id"],
            param_bindings=dict(data.get("param_bindings", {})),
        )
    if kind == "atom_step":
        return SkillStep.from_dict(data["step"])
    if kind == "branch":
        return BranchNode(
            condition=StateDescriptor.from_dict(data["condition"]),
            then_steps=tuple(
                _task_node_from_dict(step) for step in data.get("then_steps", [])
            ),
            else_steps=tuple(
                _task_node_from_dict(step) for step in data.get("else_steps", [])
            ),
        )
    raise ValueError(f"unsupported task node type: {kind}")


@dataclass(frozen=True)
class TaskSkill:
    skill_id: str
    name: str
    description: str
    app: str
    platform: str
    steps: tuple[TaskNode, ...] = ()
    memory_context_id: str | None = None
    tags: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "app": self.app,
            "platform": self.platform,
            "steps": [_task_node_to_dict(step) for step in self.steps],
            "tags": list(self.tags),
            "created_at": self.created_at,
        }
        if self.memory_context_id is not None:
            payload["memory_context_id"] = self.memory_context_id
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSkill":
        return cls(
            skill_id=data.get("skill_id", str(uuid.uuid4())),
            name=data["name"],
            description=data.get("description", ""),
            app=data.get("app", ""),
            platform=data.get("platform", "unknown"),
            steps=tuple(_task_node_from_dict(step) for step in data.get("steps", [])),
            memory_context_id=data.get("memory_context_id"),
            tags=tuple(data.get("tags", ())),
            created_at=data.get("created_at", time.time()),
        )
