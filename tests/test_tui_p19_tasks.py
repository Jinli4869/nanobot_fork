"""Phase 19 Plan 02 launch-contract tests for the TUI backend."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, get_type_hints
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nanobot.tui.app import create_app
from nanobot.tui.contracts import TaskLaunchContract
from nanobot.tui.schemas.tasks import LaunchRunResponse, TaskLaunchRequest


def _make_contract_test_app() -> FastAPI:
    app = FastAPI()

    @app.post("/tasks/runs", response_model=LaunchRunResponse)
    def launch_task(payload: TaskLaunchRequest) -> LaunchRunResponse:
        return LaunchRunResponse(
            run_id="run-contract-001",
            status="queued",
            accepted_at="2026-03-21T15:00:00Z",
        )

    return app


def test_launch_endpoint_accepts_only_supported_task_kinds() -> None:
    client = TestClient(_make_contract_test_app())

    accepted_payloads = [
        {
            "kind": "nanobot_open_url",
            "url": "https://example.com/docs",
            "require_background_isolation": True,
            "acknowledge_background_fallback": False,
        },
        {
            "kind": "nanobot_open_settings",
            "panel": "privacy",
            "require_background_isolation": False,
            "acknowledge_background_fallback": True,
        },
        {
            "kind": "opengui_launch_app",
            "app_id": "calculator",
            "backend": "dry-run",
        },
        {
            "kind": "opengui_open_settings",
            "panel": "network",
            "backend": "local",
        },
    ]

    run_ids: list[str] = []
    for payload in accepted_payloads:
        response = client.post("/tasks/runs", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["run_id"] == "run-contract-001"
        assert body["status"] == "queued"
        assert body["accepted_at"] == "2026-03-21T15:00:00Z"
        run_ids.append(body["run_id"])

    assert run_ids == ["run-contract-001"] * 4


@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        ({"kind": "unsupported_operation"}, "kind"),
        ({"kind": "nanobot_open_url", "task": "open docs"}, "url"),
        ({"kind": "opengui_launch_app", "prompt": "open calculator"}, "app_id"),
        ({"kind": "opengui_open_settings", "panel": "network", "params": {"backend": "local"}}, "backend"),
        ({"kind": "nanobot_open_settings", "panel": "network", "command": ["python", "-m", "opengui.cli"]}, "command"),
    ],
)
def test_launch_endpoint_rejects_untyped_or_unsafe_parameters(
    payload: dict[str, Any],
    missing_field: str,
) -> None:
    client = TestClient(_make_contract_test_app())

    response = client.post("/tasks/runs", json=payload)

    assert response.status_code == 422
    assert missing_field in response.text


def test_launch_request_contract_exposes_only_typed_requests() -> None:
    contract_hints = get_type_hints(TaskLaunchContract)

    assert "launch_task" in contract_hints
    launch_repr = repr(contract_hints["launch_task"])
    assert "TaskLaunchRequest" in launch_repr
    assert "LaunchRunResponse" in launch_repr
    assert "dict[str, Any]" not in launch_repr


def test_tui_app_keeps_mutating_launch_routes_opt_in_only() -> None:
    with (
        patch("nanobot.cli.commands.sync_workspace_templates") as sync_templates,
        patch("nanobot.agent.loop.ChannelManager", create=True) as channel_manager,
        patch("nanobot.agent.loop.AgentLoop") as agent_loop,
    ):
        app = create_app()

    paths = {route.path for route in app.routes}

    assert "/tasks/runs" not in paths
    sync_templates.assert_not_called()
    channel_manager.assert_not_called()
    agent_loop.assert_not_called()
