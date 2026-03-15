from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest

from nanobot.gui.backend import (
    DryRunDesktopBackend,
    GUIBackendError,
    LocalDesktopBackend,
    parse_computer_action,
)
from nanobot.gui.runtime import GuiRuntime
from nanobot.providers.base import LLMResponse, ToolCallRequest


class TestDangerousKeySafety:
    """Verify that dangerous shortcuts are blocked by the backend."""

    def test_cmd_q_is_blocked(self) -> None:
        assert LocalDesktopBackend._check_dangerous_keys(("cmd", "q")) is not None

    def test_command_w_is_blocked(self) -> None:
        assert LocalDesktopBackend._check_dangerous_keys(("command", "w")) is not None

    def test_cmd_delete_is_blocked(self) -> None:
        assert LocalDesktopBackend._check_dangerous_keys(("cmd", "delete")) is not None

    def test_force_quit_is_blocked(self) -> None:
        assert LocalDesktopBackend._check_dangerous_keys(("cmd", "option", "escape")) is not None

    def test_force_quit_alias_order_is_blocked(self) -> None:
        assert LocalDesktopBackend._check_dangerous_keys(("escape", "command", "option")) is not None

    def test_safe_combo_is_allowed(self) -> None:
        assert LocalDesktopBackend._check_dangerous_keys(("cmd", "c")) is None

    def test_single_key_is_allowed(self) -> None:
        assert LocalDesktopBackend._check_dangerous_keys(("enter",)) is None


class _ScriptedProvider:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict] = []

    async def chat_with_retry(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return next(self._responses)


def test_parse_computer_action_supports_relative_tap() -> None:
    action = parse_computer_action(
        {
            "action_type": "tap",
            "x": 500,
            "y": 250,
            "relative": True,
        }
    )

    assert action.action_type == "tap"
    assert action.relative is True
    assert action.x == 500
    assert action.y == 250


def test_parse_computer_action_rejects_legacy_payload() -> None:
    with pytest.raises(GUIBackendError, match="action_type"):
        parse_computer_action({"action": "left_click", "coordinate": [10, 20]})


def test_parse_computer_action_normalizes_hotkey_aliases() -> None:
    action = parse_computer_action({"action_type": "hotkey", "key": "command+option+escape"})

    assert action.key == ("command", "option", "esc")


@pytest.mark.asyncio
async def test_gui_runtime_runs_with_function_calls(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="computer_use",
                        arguments={"action_type": "tap", "x": 320, "y": 240, "relative": False},
                    )
                ],
            ),
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_2",
                        name="computer_use",
                        arguments={"action_type": "terminate", "status": "success"},
                    )
                ],
            ),
        ]
    )
    runtime = GuiRuntime(
        provider=provider,  # type: ignore[arg-type]
        model="test-model",
        backend=DryRunDesktopBackend(),
        artifacts_root=tmp_path,
        max_steps=5,
        step_timeout_seconds=5,
    )

    result = await runtime.run(task="Click once and finish")

    assert "status=success" in result
    assert "Artifacts:" in result
    assert len(provider.calls) == 2

    second_messages = provider.calls[1]["messages"]
    assert second_messages[1]["role"] == "user"
    assert second_messages[2]["role"] == "assistant"
    assert second_messages[2]["content"] is None
    assert second_messages[2]["tool_calls"][0]["function"]["name"] == "computer_use"
    assert second_messages[3]["role"] == "tool"
    assert second_messages[4]["role"] == "user"
    assert second_messages[4]["content"][0]["type"] == "image_url"


@pytest.mark.asyncio
async def test_gui_runtime_retries_invalid_model_output(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        [
            LLMResponse(content="I will just explain instead.", tool_calls=[]),
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="computer_use",
                        arguments={"action_type": "terminate", "status": "success"},
                    )
                ],
            ),
        ]
    )
    runtime = GuiRuntime(
        provider=provider,  # type: ignore[arg-type]
        model="test-model",
        backend=DryRunDesktopBackend(),
        artifacts_root=tmp_path,
        max_steps=3,
        step_timeout_seconds=5,
    )

    result = await runtime.run(task="Terminate after retry")

    assert "status=success" in result
    assert len(provider.calls) == 2
    corrective_turn = provider.calls[1]["messages"][-1]
    assert corrective_turn["role"] == "user"
    assert "exactly one computer_use" in corrective_turn["content"]


@pytest.mark.asyncio
async def test_gui_runtime_retries_multiple_tool_calls_with_tool_results_first(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="computer_use",
                        arguments={"action_type": "wait", "duration_ms": 0},
                    ),
                    ToolCallRequest(
                        id="call_2",
                        name="computer_use",
                        arguments={"action_type": "wait", "duration_ms": 0},
                    ),
                ],
            ),
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_done",
                        name="computer_use",
                        arguments={"action_type": "terminate", "status": "success"},
                    )
                ],
            ),
        ]
    )
    runtime = GuiRuntime(
        provider=provider,  # type: ignore[arg-type]
        model="test-model",
        backend=DryRunDesktopBackend(),
        artifacts_root=tmp_path,
        max_steps=3,
        step_timeout_seconds=5,
    )

    result = await runtime.run(task="Retry after multiple tool calls")

    assert "status=success" in result
    retry_messages = provider.calls[1]["messages"]
    assert retry_messages[-3]["role"] == "tool"
    assert retry_messages[-3]["tool_call_id"] == "call_1"
    assert retry_messages[-2]["role"] == "tool"
    assert retry_messages[-2]["tool_call_id"] == "call_2"
    assert retry_messages[-1]["role"] == "user"
    assert "exactly one computer_use" in retry_messages[-1]["content"]


@pytest.mark.asyncio
async def test_gui_runtime_degrades_old_screenshots_without_deleting_messages(tmp_path: Path) -> None:
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id=f"call_{index}",
                    name="computer_use",
                    arguments={"action_type": "wait", "duration_ms": 0},
                )
            ],
        )
        for index in range(4)
    ]
    responses.append(
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_done",
                    name="computer_use",
                    arguments={"action_type": "terminate", "status": "success"},
                )
            ],
        )
    )
    provider = _ScriptedProvider(responses)
    runtime = GuiRuntime(
        provider=provider,  # type: ignore[arg-type]
        model="test-model",
        backend=DryRunDesktopBackend(),
        artifacts_root=tmp_path,
        max_steps=6,
        step_timeout_seconds=5,
    )

    result = await runtime.run(task="Wait a few times then finish")

    assert "status=success" in result
    last_messages = provider.calls[-1]["messages"]
    user_messages = [msg for msg in last_messages if msg.get("role") == "user"]
    assert len(user_messages) >= 5
    assert user_messages[0]["content"][0]["type"] == "text"
    assert "[screenshot degraded: step 1]" == user_messages[0]["content"][0]["text"]
    assert user_messages[-1]["content"][0]["type"] == "image_url"


@pytest.mark.asyncio
async def test_gui_runtime_times_out_a_step(tmp_path: Path) -> None:
    class _SlowBackend(DryRunDesktopBackend):
        def observe(self, output_path: Path, timeout_seconds: int):
            if "obs_001" in output_path.name:
                import time

                time.sleep(timeout_seconds + 0.2)
            return super().observe(output_path, timeout_seconds)

    provider = _ScriptedProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="computer_use",
                        arguments={"action_type": "tap", "x": 10, "y": 10, "relative": False},
                    )
                ],
            )
        ]
    )
    runtime = GuiRuntime(
        provider=provider,  # type: ignore[arg-type]
        model="test-model",
        backend=_SlowBackend(),
        artifacts_root=tmp_path,
        max_steps=2,
        step_timeout_seconds=1,
    )

    result = await runtime.run(task="This should time out")

    assert "timed out" in result


@pytest.mark.asyncio
async def test_gui_runtime_formats_startup_backend_error(tmp_path: Path) -> None:
    class _FailingPreflightBackend(DryRunDesktopBackend):
        def preflight(self, artifacts_dir: Path, timeout_seconds: int) -> list[str]:
            del artifacts_dir, timeout_seconds
            raise GUIBackendError("preflight boom")

    runtime = GuiRuntime(
        provider=_ScriptedProvider([]),  # type: ignore[arg-type]
        model="test-model",
        backend=_FailingPreflightBackend(),
        artifacts_root=tmp_path,
        max_steps=2,
        step_timeout_seconds=1,
    )

    result = await runtime.run(task="This should fail during preflight")

    assert "GUI task failed: preflight boom" in result


@pytest.mark.asyncio
async def test_gui_runtime_formats_startup_timeout(tmp_path: Path) -> None:
    class _SlowStartupBackend(DryRunDesktopBackend):
        def observe(self, output_path: Path, timeout_seconds: int):
            import time

            time.sleep(timeout_seconds + 0.2)
            return super().observe(output_path, timeout_seconds)

    runtime = GuiRuntime(
        provider=_ScriptedProvider([]),  # type: ignore[arg-type]
        model="test-model",
        backend=_SlowStartupBackend(),
        artifacts_root=tmp_path,
        max_steps=2,
        step_timeout_seconds=1,
    )

    result = await runtime.run(task="This should fail during startup")

    assert "GUI initialization timed out" in result
