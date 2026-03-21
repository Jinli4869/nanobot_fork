"""Dependency providers for the isolated TUI backend."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Request

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.config.schema import Config
from nanobot.config.paths import get_cron_dir
from nanobot.cron.service import CronService
from nanobot.session.manager import SessionManager

from nanobot.cli.commands import _load_runtime_config, _make_provider
from nanobot.tui.contracts import (
    RuntimeInspectionContract,
    SessionContract,
    TaskLaunchContract,
)
from nanobot.tui.services import (
    ChatWorkspaceService,
    RuntimeService,
    SessionService,
    TaskLaunchService,
)


def _resolve_workspace_path(
    workspace: Path | None = None,
) -> Path:
    if workspace is not None:
        return workspace
    return workspace or load_config().workspace_path


def _resolve_runtime_config(request: Request | None = None) -> Config:
    if request is not None:
        config = getattr(request.app.state, "nanobot_config", None)
        if isinstance(config, Config):
            return config
    return _load_runtime_config()


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


def get_chat_runtime_factory(
    *,
    config: Config | None = None,
    session_manager: SessionManager | None = None,
) -> Callable[[], AgentLoop]:
    """Build a browser-chat runtime factory without importing Typer routing."""

    resolved_config = config or _load_runtime_config()
    shared_sessions = session_manager or SessionManager(resolved_config.workspace_path)

    def _factory() -> AgentLoop:
        provider = _make_provider(resolved_config)
        cron_store_path = get_cron_dir() / "jobs.json"
        cron = CronService(cron_store_path)
        return AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=resolved_config.workspace_path,
            model=resolved_config.agents.defaults.model,
            max_iterations=resolved_config.agents.defaults.max_tool_iterations,
            context_window_tokens=resolved_config.agents.defaults.context_window_tokens,
            web_search_config=resolved_config.tools.web.search,
            web_proxy=resolved_config.tools.web.proxy or None,
            exec_config=resolved_config.tools.exec,
            cron_service=cron,
            restrict_to_workspace=resolved_config.tools.restrict_to_workspace,
            session_manager=shared_sessions,
            mcp_servers=resolved_config.tools.mcp_servers,
            channels_config=resolved_config.channels,
            gui_config=resolved_config.gui,
        )

    return _factory


def get_chat_workspace_service(request: Request) -> ChatWorkspaceService:
    """Build the browser chat workspace service."""

    config = _resolve_runtime_config(request)
    session_manager = SessionManager(config.workspace_path)
    return ChatWorkspaceService(
        session_manager=session_manager,
        runtime_factory=get_chat_runtime_factory(
            config=config,
            session_manager=session_manager,
        ),
    )
