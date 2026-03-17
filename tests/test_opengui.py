from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from opengui.action import ActionError, parse_action, resolve_coordinate
from opengui.agent import GuiAgent
from opengui.backends.adb import AdbBackend
from opengui.backends.dry_run import DryRunBackend
from opengui.interfaces import LLMResponse, ToolCall
from opengui.prompts.system import build_system_prompt
from opengui.trajectory.recorder import TrajectoryRecorder


def _make_recorder(tmp_path: Path, task: str = "test task") -> TrajectoryRecorder:
    return TrajectoryRecorder(output_dir=tmp_path / "traj", task=task)


class _ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
        if not self._responses:
            raise AssertionError("No scripted responses left.")
        return self._responses.pop(0)


class _RecordingLLM(_ScriptedLLM):
    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__(responses)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
        self.calls.append(copy.deepcopy(messages))
        return await super().chat(messages, tools=tools, tool_choice=tool_choice)


def test_parse_scroll_allows_center_default() -> None:
    action = parse_action({
        "action_type": "scroll",
        "direction": "left",
        "pixels": 180,
    })

    assert action.x is None
    assert action.y is None
    assert action.text == "left"


def test_parse_scroll_rejects_partial_coordinates() -> None:
    with pytest.raises(ActionError, match="requires both 'x' and 'y'"):
        parse_action({
            "action_type": "scroll",
            "x": 100,
            "pixels": 180,
        })


def test_build_system_prompt_uses_mobile_agent_style_sections() -> None:
    prompt = build_system_prompt(
        platform="android",
        tool_definition={"type": "function", "function": {"name": "computer_use"}},
    )

    assert "# Tools" in prompt
    assert "<tools>" in prompt
    assert '"name": "computer_use"' in prompt
    assert "# Response format" in prompt
    assert "native tool-calling mechanism" in prompt


@pytest.mark.asyncio
async def test_adb_backend_resolves_relative_tap(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = AdbBackend()
    backend._screen_width = 200
    backend._screen_height = 400
    run_mock = AsyncMock(return_value="")
    monkeypatch.setattr(backend, "_run", run_mock)

    action = parse_action({
        "action_type": "tap",
        "x": 500,
        "y": 250,
        "relative": True,
    })
    await backend.execute(action)

    expected_x = resolve_coordinate(500, 200, relative=True)
    expected_y = resolve_coordinate(250, 400, relative=True)
    run_mock.assert_awaited_once_with(
        "shell", "input", "tap", str(expected_x), str(expected_y), timeout=5.0,
    )


@pytest.mark.asyncio
async def test_adb_backend_scrolls_horizontally_from_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    backend._screen_width = 400
    backend._screen_height = 800
    run_mock = AsyncMock(return_value="")
    monkeypatch.setattr(backend, "_run", run_mock)

    action = parse_action({
        "action_type": "scroll",
        "direction": "left",
        "pixels": 120,
    })
    await backend.execute(action)

    run_mock.assert_awaited_once_with(
        "shell", "input", "swipe", "200", "400", "80", "400", "300", timeout=5.0,
    )


@pytest.mark.asyncio
async def test_agent_failure_keeps_last_trace_path(tmp_path: Path) -> None:
    agent = GuiAgent(
        _ScriptedLLM([
            LLMResponse(
                content="wait",
                tool_calls=[ToolCall(
                    id="call-1",
                    name="computer_use",
                    arguments={"action_type": "wait", "duration_ms": 1},
                )],
            ),
        ]),
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "never finishes"),
        artifacts_root=tmp_path / "runs",
        max_steps=1,
    )

    result = await agent.run("never finishes", max_retries=1)

    assert not result.success
    assert result.error == "max_steps_exceeded"
    assert result.steps_taken == 1
    assert result.trace_path is not None
    assert Path(result.trace_path).exists()


@pytest.mark.asyncio
async def test_agent_uses_history_summary_and_recent_image_window(tmp_path: Path) -> None:
    llm = _RecordingLLM([
        LLMResponse(
            content="wait briefly",
            tool_calls=[ToolCall(
                id="call-1",
                name="computer_use",
                arguments={"action_type": "wait", "duration_ms": 1},
            )],
        ),
        LLMResponse(
            content="wait again",
            tool_calls=[ToolCall(
                id="call-2",
                name="computer_use",
                arguments={"action_type": "wait", "duration_ms": 1},
            )],
        ),
        LLMResponse(
            content="finish task",
            tool_calls=[ToolCall(
                id="call-3",
                name="computer_use",
                arguments={"action_type": "done", "status": "success"},
            )],
        ),
    ])
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "Open Settings"),
        artifacts_root=tmp_path / "runs",
        max_steps=3,
        history_image_window=1,
        include_date_context=False,
    )

    result = await agent.run("Open Settings")

    assert result.success
    assert len(llm.calls) == 3

    third_call = llm.calls[2]
    assert "# Tools" in third_call[0]["content"]

    history_user = third_call[1]
    history_text = "\n".join(
        block["text"]
        for block in history_user["content"]
        if block.get("type") == "text"
    )
    assert "Please generate the next move according to the UI screenshot, instruction and previous actions." in history_text
    assert "Instruction: Open Settings" in history_text
    assert "Previous actions:\nStep 1: wait briefly" in history_text

    assert third_call[2]["content"] == "Action: wait again"
    assert third_call[3]["content"] == "[dry-run] wait 1 ms"

    current_user = third_call[4]
    current_text = "\n".join(
        block["text"]
        for block in current_user["content"]
        if block.get("type") == "text"
    )
    assert "Step 3" in current_text
    assert "Task: Open Settings" in current_text


def test_pyproject_includes_opengui_in_build() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    include = pyproject["tool"]["hatch"]["build"]["include"]
    assert "opengui/**/*.py" in include

    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert "opengui" in wheel["packages"]

    sdist_include = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "opengui/" in sdist_include
