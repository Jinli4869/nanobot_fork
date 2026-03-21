"""Typed lazy contracts for future browser-facing seams."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable


@dataclass(slots=True)
class SessionContract:
    """Lazy contract for reading persisted session metadata."""

    workspace_path: Path
    list_sessions: Callable[[], list[dict[str, Any]]]


@dataclass(slots=True)
class RuntimeInspectionContract:
    """Lazy contract for non-mutating runtime inspection."""

    inspect_runtime: Callable[[], dict[str, Any]]


@dataclass(slots=True)
class TaskLaunchContract:
    """Future-facing task launch contract kept non-executing in Phase 17."""

    describe_capability: Callable[[], dict[str, Any]]
    launch_task: Callable[[str, dict[str, Any] | None], Any] | None = None


@dataclass(slots=True)
class ChatWorkspaceContract:
    """Future-facing browser chat contract for persisted session workflows."""

    create_session: Callable[[], dict[str, Any]]
    get_session: Callable[[str], dict[str, Any]]
    send_message: Callable[[str, str], Any]
