"""Dependency providers for the isolated TUI backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.config.loader import load_config
from nanobot.session.manager import SessionManager

from nanobot.tui.contracts import (
    RuntimeInspectionContract,
    SessionContract,
    TaskLaunchContract,
)
from nanobot.tui.services import RuntimeService, SessionService, TaskLaunchService


def _resolve_workspace_path(
    workspace: Path | None = None,
) -> Path:
    if workspace is not None:
        return workspace
    return workspace or load_config().workspace_path


def get_session_contract(
    workspace: Path | None = None,
) -> SessionContract:
    """Return a lazy session contract backed by SessionManager."""

    resolved_workspace = _resolve_workspace_path(workspace=workspace)

    def _list_sessions() -> list[dict[str, Any]]:
        return SessionManager(resolved_workspace).list_sessions()

    return SessionContract(
        workspace_path=resolved_workspace,
        list_sessions=_list_sessions,
    )


def get_runtime_inspection_contract() -> RuntimeInspectionContract:
    """Return a lazy runtime-inspection contract without booting the agent runtime."""

    def _inspect_runtime() -> dict[str, Any]:
        return {
            "status": "not_started",
            "channel_runtime_booted": False,
            "agent_loop_booted": False,
            "task_launch_available": False,
        }

    return RuntimeInspectionContract(inspect_runtime=_inspect_runtime)


def get_task_launch_contract() -> TaskLaunchContract:
    """Return a future task-launch contract kept non-mutating for Phase 17."""

    def _describe_capability() -> dict[str, Any]:
        return {
            "name": "task-launch",
            "mutable": False,
            "phase": 17,
            "status": "contract-only",
        }

    return TaskLaunchContract(
        describe_capability=_describe_capability,
        launch_task=None,
    )


def get_session_service() -> SessionService:
    """Build the read-only session service for browser-facing routes."""

    return SessionService(get_session_contract())


def get_runtime_service() -> RuntimeService:
    """Build the read-only runtime inspection service."""

    return RuntimeService(get_runtime_inspection_contract())


def get_task_launch_service() -> TaskLaunchService:
    """Build the read-only task capability service."""

    return TaskLaunchService(get_task_launch_contract())
