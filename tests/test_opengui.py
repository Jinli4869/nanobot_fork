from __future__ import annotations

import copy
import json
import tomllib
import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from opengui.action import Action, ActionError, parse_action, resolve_coordinate
from opengui.agent import (
    GuiAgent,
    StagnationSignal,
    _AgentActionGrounder,
    _AgentSubgoalRunner,
)
from opengui.agent_profiles import normalize_profile_response
from opengui.backends.adb import AdbBackend, AdbError
from opengui.backends.dry_run import DryRunBackend
from opengui.interfaces import LLMResponse, ToolCall
from opengui.observation import Observation
from opengui.prompts.system import build_system_prompt
from opengui.skills.data import SkillStep
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


class _RecordingValidator:
    def __init__(self, returns: list[bool]) -> None:
        self._returns = list(returns)
        self.calls: list[dict[str, object]] = []

    async def validate(self, valid_state: str, screenshot=None) -> bool:
        self.calls.append({"valid_state": valid_state, "screenshot": screenshot})
        if not self._returns:
            raise AssertionError("No validator responses left.")
        return self._returns.pop(0)


class _SkillTestBackend:
    def __init__(self) -> None:
        self.platform = "dry-run"
        self.executed_actions: list[object] = []
        self.observe_calls: list[Path] = []

    async def execute(self, action, timeout: float = 5.0) -> str:
        del timeout
        self.executed_actions.append(action)
        return f"executed:{action.action_type}"

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        del timeout
        self.observe_calls.append(screenshot_path)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(b"png")
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1000,
            screen_height=1000,
            foreground_app="DryRun",
            platform=self.platform,
        )

    async def preflight(self) -> None:
        return None

    async def list_apps(self) -> list[str]:
        return []


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


def test_parse_action_unwraps_singleton_coordinate_lists() -> None:
    action = parse_action({
        "action": "tap",
        "x": [417],
        "y": [129],
        "relative": True,
    })

    assert action.action_type == "tap"
    assert action.x == 417.0
    assert action.y == 129.0
    assert action.relative is True


def test_parse_action_splits_paired_coordinates_from_x_list() -> None:
    action = parse_action({
        "action": "tap",
        "x": [498, 441],
        "relative": True,
    })

    assert action.action_type == "tap"
    assert action.x == 498.0
    assert action.y == 441.0
    assert action.relative is True


def test_parse_action_splits_paired_coordinates_from_stringified_x_list() -> None:
    action = parse_action({
        "action": "tap",
        "x": "[903, 130]",
        "relative": "true",
    })

    assert action.action_type == "tap"
    assert action.x == 903.0
    assert action.y == 130.0
    assert action.relative is True


def test_parse_swipe_splits_all_coordinates_from_x_list() -> None:
    action = parse_action({
        "action_type": "swipe",
        "x": [120, 340, 760, 355],
        "relative": True,
    })

    assert action.action_type == "swipe"
    assert action.x == 120.0
    assert action.y == 340.0
    assert action.x2 == 760.0
    assert action.y2 == 355.0
    assert action.relative is True


def test_parse_swipe_splits_all_coordinates_from_stringified_x_list() -> None:
    action = parse_action({
        "action_type": "swipe",
        "x": "[120, 340, 760, 355]",
        "relative": True,
    })

    assert action.action_type == "swipe"
    assert action.x == 120.0
    assert action.y == 340.0
    assert action.x2 == 760.0
    assert action.y2 == 355.0
    assert action.relative is True


def test_parse_action_accepts_mobileworld_navigation_aliases() -> None:
    enter = parse_action({"action_type": "keyboard_enter"})
    recents = parse_action({"action_type": "recents"})

    assert enter.action_type == "enter"
    assert recents.action_type == "app_switch"


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


def test_build_system_prompt_supports_general_e2e_profile() -> None:
    prompt = build_system_prompt(
        platform="android",
        agent_profile="general_e2e",
    )

    assert "Thought:" in prompt
    assert 'Action: {"action_type": "click"' in prompt
    assert "Do not use native tool calling" in prompt


def test_annotate_android_apps_filters_unmapped_packages() -> None:
    from opengui.skills.normalization import annotate_android_apps

    result = annotate_android_apps(["com.sankuai.meituan", "com.unknown.xyz"])

    assert len(result) == 1, f"Expected 1 entry, got {len(result)}: {result}"
    assert "美团" in result[0] or "Meituan" in result[0]
    assert not any("com.unknown.xyz" in entry for entry in result)


def test_build_system_prompt_android_apps_shows_display_names_only() -> None:
    prompt = build_system_prompt(
        platform="android",
        installed_apps=["com.sankuai.meituan", "com.unknown.dropped"],
    )

    assert "美团/Meituan" in prompt
    # Package name must not appear as an app list item
    lines = prompt.splitlines()
    app_list_lines = [ln.strip() for ln in lines if ln.strip().startswith("- ")]
    assert not any("com.sankuai.meituan" in ln for ln in app_list_lines)
    assert not any("com.unknown.dropped" in ln for ln in app_list_lines)


def test_build_system_prompt_android_apps_excludes_unmapped() -> None:
    prompt = build_system_prompt(
        platform="android",
        installed_apps=["com.totally.unknown"],
    )

    # With all packages unmapped, no "# Installed Apps" section should appear
    assert "# Installed Apps" not in prompt


@pytest.mark.asyncio
async def test_adb_backend_ensure_yadb_pushes_packaged_asset_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = AdbBackend()
    yadb_asset = tmp_path / "yadb"
    yadb_asset.write_bytes(b"jar-data")

    monkeypatch.setattr(backend, "_get_packaged_yadb_path", lambda: yadb_asset)
    run_mock = AsyncMock(side_effect=[
        AdbError("missing"),
        "",
        "",
    ])
    monkeypatch.setattr(backend, "_run", run_mock)

    assert await backend._ensure_yadb_available(timeout=5.0) is True
    assert run_mock.await_args_list[0].args == ("shell", "ls", "/data/local/tmp/yadb")
    assert run_mock.await_args_list[1].args == ("push", str(yadb_asset), "/data/local/tmp/yadb")
    assert run_mock.await_args_list[2].args == ("shell", "chmod", "755", "/data/local/tmp/yadb")


@pytest.mark.asyncio
async def test_adb_backend_ensure_yadb_skips_push_when_device_already_has_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = AdbBackend()
    yadb_asset = tmp_path / "yadb"
    yadb_asset.write_bytes(b"jar-data")

    monkeypatch.setattr(backend, "_get_packaged_yadb_path", lambda: yadb_asset)
    run_mock = AsyncMock(return_value="")
    monkeypatch.setattr(backend, "_run", run_mock)

    assert await backend._ensure_yadb_available(timeout=5.0) is True
    run_mock.assert_awaited_once_with("shell", "ls", "/data/local/tmp/yadb", timeout=5.0)


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
async def test_adb_backend_foreground_app_uses_activity_dump_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    run_mock = AsyncMock(return_value="""
      mResumedActivity: ActivityRecord{123 u0 com.coloros.calendar/.MainActivity t12}
    """)
    monkeypatch.setattr(backend, "_run", run_mock)

    assert await backend._query_foreground_app(timeout=5.0) == "com.coloros.calendar"
    run_mock.assert_awaited_once_with(
        "shell",
        "dumpsys",
        "activity",
        "activities",
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_adb_backend_foreground_app_falls_back_to_window_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    run_mock = AsyncMock(side_effect=[
        "header without resumed activity",
        "mCurrentFocus=Window{42 u0 com.android.settings/com.android.settings.Settings}",
    ])
    monkeypatch.setattr(backend, "_run", run_mock)

    assert await backend._query_foreground_app(timeout=5.0) == "com.android.settings"
    assert run_mock.await_args_list[0].args == ("shell", "dumpsys", "activity", "activities")
    assert run_mock.await_args_list[1].args == ("shell", "dumpsys", "window", "windows")


def test_adb_backend_extract_foreground_app_supports_multiple_android_signals() -> None:
    assert AdbBackend._extract_foreground_app(
        "topResumedActivity=ActivityRecord{7 u0 com.heytap.browser/.Main t11}"
    ) == "com.heytap.browser"
    assert AdbBackend._extract_foreground_app(
        "mFocusedApp=AppWindowToken{ token=Token{ ActivityRecord{7 u0 com.android.settings/.Settings t11}}}"
    ) == "com.android.settings"
    assert AdbBackend._extract_foreground_app("no foreground info here") == "unknown"


def test_agent_marks_qwen_and_gemini_coordinates_as_relative(tmp_path: Path) -> None:
    qwen_agent = GuiAgent(
        _ScriptedLLM([]),
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "qwen"),
        model="qwen-vl-max",
    )
    gemini_agent = GuiAgent(
        _ScriptedLLM([]),
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "gemini"),
        model="gemini-2.5-pro",
    )

    action = parse_action({"action_type": "tap", "x": 500, "y": 250})

    assert qwen_agent._normalize_relative_coordinates(action).relative is True
    assert gemini_agent._normalize_relative_coordinates(action).relative is True
    assert qwen_agent._coordinate_mode() == "relative_999"


def test_agent_keeps_absolute_coordinates_for_other_models(tmp_path: Path) -> None:
    agent = GuiAgent(
        _ScriptedLLM([]),
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "other"),
        model="gpt-5.2",
    )

    action = parse_action({"action_type": "tap", "x": 500, "y": 250})

    assert agent._normalize_relative_coordinates(action).relative is False
    assert agent._coordinate_mode() == "absolute"


def test_qwen3vl_profile_normalizes_content_only_response() -> None:
    response = LLMResponse(
        content=(
            'Thought: I found the target\n'
            'Action: "Tap the login button"\n'
            '<tool_call>{"name":"mobile_use","arguments":{"action":"click","coordinate":[500,250]}}</tool_call>'
        ),
        tool_calls=None,
    )

    normalized = normalize_profile_response("qwen3vl", response)

    assert normalized.tool_calls is not None
    assert normalized.tool_calls[0].name == "computer_use"
    assert normalized.tool_calls[0].arguments == {
        "action_type": "tap",
        "x": 500,
        "y": 250,
        "relative": True,
    }


def test_qwen3vl_profile_prefers_content_contract_over_provider_tool_calls() -> None:
    response = LLMResponse(
        content=(
            'Thought: Open Chrome\n'
            'Action: "Open Chrome"\n'
            '<tool_call>{"name":"mobile_use","arguments":{"action":"open","text":"chrome"}}</tool_call>'
        ),
        tool_calls=[
            ToolCall(
                id="provider-tool-call-0",
                name="computer_use",
                arguments={"action_type": "open_app", "text": "chrome"},
            )
        ],
    )

    normalized = normalize_profile_response("qwen3vl", response)

    assert normalized.tool_calls is not None
    assert normalized.tool_calls[0].id == "content-tool-call-0"
    assert normalized.tool_calls[0].name == "computer_use"
    assert normalized.tool_calls[0].arguments == {
        "action_type": "open_app",
        "text": "chrome",
    }


def test_qwen3vl_profile_falls_back_to_provider_tool_calls_when_content_contract_is_missing() -> None:
    response = LLMResponse(
        content='Thought: Continue\nAction: Tap the next result',
        tool_calls=[
            ToolCall(
                id="provider-tool-call-0",
                name="computer_use",
                arguments={"action_type": "tap", "x": 321, "y": 654, "relative": True},
            )
        ],
    )

    normalized = normalize_profile_response("qwen3vl", response)

    assert normalized.tool_calls is not None
    assert normalized.tool_calls[0].id == "provider-tool-call-0"
    assert normalized.tool_calls[0].name == "computer_use"
    assert normalized.tool_calls[0].arguments == {
        "action_type": "tap",
        "x": 321,
        "y": 654,
        "relative": True,
    }


def test_qwen3vl_profile_normalizes_provider_mobile_use_tool_calls() -> None:
    response = LLMResponse(
        content="Action: Tap the next result",
        tool_calls=[
            ToolCall(
                id="provider-tool-call-0",
                name="mobile_use",
                arguments={"action": "click", "coordinate": [903, 130]},
            )
        ],
    )

    normalized = normalize_profile_response("qwen3vl", response)

    assert normalized.tool_calls is not None
    assert normalized.tool_calls[0].id == "provider-tool-call-0"
    assert normalized.tool_calls[0].name == "computer_use"
    assert normalized.tool_calls[0].arguments == {
        "action_type": "tap",
        "x": 903,
        "y": 130,
        "relative": True,
    }


@pytest.mark.asyncio
async def test_agent_action_grounder_uses_profile_seam_for_qwen3vl(tmp_path: Path) -> None:
    screenshot = tmp_path / "grounder.png"
    screenshot.write_bytes(b"png")
    llm = _RecordingLLM([
        LLMResponse(
            content=(
                'Thought: Tap the button\n'
                'Action: "Tap login"\n'
                '<tool_call>{"name":"mobile_use","arguments":{"action":"click","coordinate":[500,250]}}</tool_call>'
            ),
            tool_calls=None,
        )
    ])
    grounder = _AgentActionGrounder(llm, model="qwen-vl-max", agent_profile="qwen3vl")
    step = SkillStep(action_type="tap", target="Login button", parameters={"x_hint": "unused"})

    action = await grounder.ground(step, screenshot, {})

    assert action.action_type == "tap"
    assert action.x == 500
    assert action.y == 250
    assert action.relative is True
    assert len(llm.calls) == 1
    assert llm.calls[0][0]["role"] == "user"


@pytest.mark.asyncio
async def test_agent_subgoal_runner_uses_profile_seam_for_qwen3vl(tmp_path: Path) -> None:
    screenshot = tmp_path / "subgoal.png"
    screenshot.write_bytes(b"png")
    llm = _RecordingLLM([
        LLMResponse(
            content=(
                'Thought: Move toward the target\n'
                'Action: "Tap settings"\n'
                '<tool_call>{"name":"mobile_use","arguments":{"action":"click","coordinate":[400,300]}}</tool_call>'
            ),
            tool_calls=None,
        )
    ])
    backend = _SkillTestBackend()
    validator = _RecordingValidator([True])
    runner = _AgentSubgoalRunner(
        llm=llm,
        backend=backend,
        state_validator=validator,
        model="qwen-vl-max",
        artifacts_root=tmp_path / "artifacts",
        agent_profile="qwen3vl",
    )

    result = await runner.run_subgoal("Settings screen visible", screenshot, max_steps=1)

    assert result.success is True
    assert backend.executed_actions
    action = backend.executed_actions[0]
    assert action.action_type == "tap"
    assert action.relative is True
    assert validator.calls[0]["valid_state"] == "Settings screen visible"


@pytest.mark.asyncio
async def test_agent_subgoal_runner_records_events(tmp_path: Path) -> None:
    screenshot = tmp_path / "subgoal-record.png"
    screenshot.write_bytes(b"png")
    llm = _RecordingLLM([
        LLMResponse(
            content=(
                'Thought: Move toward the target\n'
                'Action: "Tap settings"\n'
                '<tool_call>{"name":"computer_use","arguments":{"action_type":"tap","x":400,"y":300,"relative":true}}</tool_call>'
            ),
            tool_calls=[
                ToolCall(
                    id="subgoal-tool-0",
                    name="computer_use",
                    arguments={"action_type": "tap", "x": 400, "y": 300, "relative": True},
                )
            ],
        )
    ])
    backend = _SkillTestBackend()
    validator = _RecordingValidator([True])
    recorder = _make_recorder(tmp_path, "subgoal trace")
    recorder.start()
    runner = _AgentSubgoalRunner(
        llm=llm,
        backend=backend,
        state_validator=validator,
        model="test-model",
        artifacts_root=tmp_path / "artifacts",
        trajectory_recorder=recorder,
    )

    result = await runner.run_subgoal("Settings screen visible", screenshot, max_steps=1)
    trace_path = recorder.finish(success=True)
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

    assert result.success is True
    names = [event["type"] for event in events]
    assert "subgoal_start" in names
    assert "subgoal_step" in names
    assert "subgoal_result" in names
    subgoal_step = next(event for event in events if event["type"] == "subgoal_step")
    assert subgoal_step["model_output"]
    assert subgoal_step["goal_reached"] is True
    assert subgoal_step["action"]["action_type"] == "tap"


@pytest.mark.asyncio
async def test_agent_subgoal_runner_records_parse_failure(tmp_path: Path) -> None:
    screenshot = tmp_path / "subgoal-failure.png"
    screenshot.write_bytes(b"png")
    llm = _RecordingLLM([LLMResponse(content="No valid tool call", tool_calls=None)])
    recorder = _make_recorder(tmp_path, "subgoal trace failure")
    recorder.start()
    runner = _AgentSubgoalRunner(
        llm=llm,
        backend=_SkillTestBackend(),
        state_validator=_RecordingValidator([False]),
        model="test-model",
        artifacts_root=tmp_path / "artifacts-failure",
        trajectory_recorder=recorder,
    )

    result = await runner.run_subgoal("Settings screen visible", screenshot, max_steps=1)
    trace_path = recorder.finish(success=True)
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

    assert result.success is False
    subgoal_step = next(event for event in events if event["type"] == "subgoal_step")
    assert subgoal_step["error"] == "no valid action returned"
    subgoal_result = next(event for event in events if event["type"] == "subgoal_result")
    assert subgoal_result["success"] is False


@pytest.mark.asyncio
async def test_agent_runs_with_qwen3vl_content_only_profile(tmp_path: Path) -> None:
    llm = _RecordingLLM([
        LLMResponse(
            content=(
                'Thought: I should wait briefly\n'
                'Action: "Wait for the screen to settle"\n'
                '<tool_call>{"name":"mobile_use","arguments":{"action":"wait"}}</tool_call>'
            ),
            tool_calls=None,
        ),
        LLMResponse(
            content=(
                'Thought: The task is complete\n'
                'Action: "Finish successfully"\n'
                '<tool_call>{"name":"mobile_use","arguments":{"action":"terminate","status":"success"}}</tool_call>'
            ),
            tool_calls=None,
        ),
    ])
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "qwen profile"),
        artifacts_root=tmp_path / "runs",
        max_steps=2,
        include_date_context=False,
        agent_profile="qwen3vl",
    )

    result = await agent.run("Wait and finish", max_retries=1)

    assert result.success
    assert len(llm.calls) == 2
    assert "Action:" in llm.calls[0][0]["content"]


@pytest.mark.asyncio
async def test_agent_runs_with_qwen3vl_provider_computer_use_stringified_x_coordinates(
    tmp_path: Path,
) -> None:
    llm = _RecordingLLM([
        LLMResponse(
            content="Action: Tap the search bar",
            tool_calls=[
                ToolCall(
                    id="provider-tool-call-0",
                    name="computer_use",
                    arguments={"action_type": "click", "x": "[410, 125]", "relative": True},
                )
            ],
        ),
        LLMResponse(
            content="Action: Finish successfully",
            tool_calls=[
                ToolCall(
                    id="provider-tool-call-1",
                    name="computer_use",
                    arguments={"action_type": "done", "status": "success"},
                )
            ],
        ),
    ])
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "qwen provider stringified coords"),
        artifacts_root=tmp_path / "runs",
        max_steps=2,
        include_date_context=False,
        agent_profile="qwen3vl",
    )

    result = await agent.run("Tap then finish", max_retries=1)

    assert result.success is True
    assert result.summary


@pytest.mark.asyncio
async def test_agent_runs_with_qwen3vl_provider_mobile_use_tool_call(tmp_path: Path) -> None:
    llm = _RecordingLLM([
        LLMResponse(
            content="Action: Finish successfully",
            tool_calls=[
                ToolCall(
                    id="provider-tool-call-0",
                    name="mobile_use",
                    arguments={"action": "terminate", "status": "success"},
                )
            ],
        ),
    ])
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "qwen provider tool"),
        artifacts_root=tmp_path / "runs",
        max_steps=1,
        include_date_context=False,
        agent_profile="qwen3vl",
    )

    result = await agent.run("Finish", max_retries=1)

    assert result.success is True
    assert result.summary


@pytest.mark.asyncio
async def test_agent_trace_records_prompt_and_model_details(tmp_path: Path) -> None:
    llm = _RecordingLLM([
        LLMResponse(
            content="Action: wait briefly",
            tool_calls=[ToolCall(
                id="call-1",
                name="computer_use",
                arguments={"action_type": "wait", "duration_ms": 1},
            )],
        ),
        LLMResponse(
            content="Action: done",
            tool_calls=[ToolCall(
                id="call-2",
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
        max_steps=2,
        include_date_context=False,
    )

    result = await agent.run("Open Settings", max_retries=1)

    assert result.success
    assert result.trace_path is not None

    trace_path = Path(result.trace_path) / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    step_event = next(event for event in events if event["event"] == "step")

    assert step_event["prompt"]["task"] == "Open Settings"
    assert step_event["prompt"]["messages"][0]["role"] == "system"
    assert step_event["prompt"]["current_observation"]["foreground_app"] == "DryRun"
    assert step_event["model_output"]["raw_content"] == "Action: wait briefly"
    assert step_event["model_output"]["tool_calls"][0]["arguments"]["duration_ms"] == 1
    assert step_event["model_output"]["parsed_action"]["action_type"] == "wait"
    assert step_event["execution"]["tool_result"] == "[dry-run] wait 1 ms"
    image_blocks = [
        block
        for message in step_event["prompt"]["messages"]
        for block in (message.get("content") if isinstance(message.get("content"), list) else [])
        if isinstance(block, dict) and block.get("type") == "image_url"
    ]
    assert image_blocks
    assert image_blocks[0]["image_url"]["url"] == "<omitted:image-data-url>"


@pytest.mark.parametrize(
    ("error", "summary", "expected"),
    [
        ("intervention_cancelled: missing_intervention_handler", None, "intervention_cancelled"),
        ("step_timeout", "Step 3 timed out.", "step_timeout"),
        ("max_steps_exceeded", "Reached max steps (10) without completion.", "max_steps_exceeded"),
        ("Preflight failed: adb unavailable", None, "preflight_failure"),
        ("Failed to parse action after retries", None, "model_parse_failure"),
        ("Action failed: device offline", None, "backend_action_failure"),
        ("UnknownError", "unexpected", "unknown_failure"),
    ],
)
def test_agent_classifies_failure_labels(
    error: str,
    summary: str | None,
    expected: str,
) -> None:
    assert GuiAgent._classify_failure_label(error=error, summary=summary) == expected


@pytest.mark.asyncio
async def test_agent_attempt_result_trace_includes_failure_label(tmp_path: Path) -> None:
    llm = _RecordingLLM([
        LLMResponse(
            content="Action: wait briefly",
            tool_calls=[ToolCall(
                id="call-1",
                name="computer_use",
                arguments={"action_type": "wait", "duration_ms": 1},
            )],
        ),
    ])
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "max steps failure"),
        artifacts_root=tmp_path / "runs",
        max_steps=1,
        include_date_context=False,
    )

    result = await agent.run("Keep waiting", max_retries=1)

    assert result.success is False
    assert result.trace_path is not None
    trace_path = Path(result.trace_path) / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    attempt_result = next(event for event in events if event["event"] == "attempt_result")
    assert attempt_result["failure_label"] == "max_steps_exceeded"


def test_agent_thinking_mode_state_machine_is_deterministic(tmp_path: Path) -> None:
    agent = GuiAgent(
        _ScriptedLLM([]),
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "thinking mode"),
        artifacts_root=tmp_path / "runs",
        max_steps=10,
        include_date_context=False,
    )

    first = agent._select_thinking_mode(
        step_index=1,
        stagnation_signal=StagnationSignal(),
        previous_mode="fast",
        careful_mode_until_step=0,
    )
    assert first.mode == "fast"
    assert first.reason == "default_fast"
    assert first.switched is False

    second = agent._select_thinking_mode(
        step_index=2,
        stagnation_signal=StagnationSignal(detected=True, reason="consecutive_waits", repeat_count=2),
        previous_mode=first.mode,
        careful_mode_until_step=first.next_careful_mode_until_step,
    )
    assert second.mode == "careful"
    assert second.reason.startswith("stagnation:")
    assert second.switched is True
    assert second.next_careful_mode_until_step >= 3

    third = agent._select_thinking_mode(
        step_index=3,
        stagnation_signal=StagnationSignal(),
        previous_mode=second.mode,
        careful_mode_until_step=second.next_careful_mode_until_step,
    )
    assert third.mode == "careful"
    assert third.reason == "careful_cooldown"


@pytest.mark.asyncio
async def test_agent_trace_records_thinking_mode_transition_event(tmp_path: Path) -> None:
    llm = _RecordingLLM([
        LLMResponse(
            content="Action: wait",
            tool_calls=[ToolCall(id="call-1", name="computer_use", arguments={"action_type": "wait", "duration_ms": 1})],
        ),
        LLMResponse(
            content="Action: wait",
            tool_calls=[ToolCall(id="call-2", name="computer_use", arguments={"action_type": "wait", "duration_ms": 1})],
        ),
        LLMResponse(
            content="Action: wait",
            tool_calls=[ToolCall(id="call-3", name="computer_use", arguments={"action_type": "wait", "duration_ms": 1})],
        ),
        LLMResponse(
            content="Action: done",
            tool_calls=[ToolCall(id="call-4", name="computer_use", arguments={"action_type": "done", "status": "success"})],
        ),
    ])
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "thinking transition"),
        artifacts_root=tmp_path / "runs",
        max_steps=6,
        include_date_context=False,
    )

    result = await agent.run("Wait and finish", max_retries=1)

    assert result.success is True
    assert result.trace_path is not None
    events = [
        json.loads(line)
        for line in (Path(result.trace_path) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    transitions = [event for event in events if event.get("event") == "thinking_mode_transition"]
    assert transitions, "Expected at least one thinking_mode_transition event."
    assert transitions[0]["from_mode"] == "fast"
    assert transitions[0]["to_mode"] == "careful"
    assert transitions[0]["mode_reason"].startswith("stagnation:")


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
async def test_adb_backend_input_text_prefers_yadb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    run_mock = AsyncMock(return_value="")
    monkeypatch.setattr(backend, "_run", run_mock)
    ensure_yadb_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(backend, "_ensure_yadb_available", ensure_yadb_mock)
    monkeypatch.setattr(backend, "_write_local_temp_text", lambda text: Path("/tmp/opengui-yadb-input.txt"))
    monkeypatch.setattr(backend, "_make_yadb_device_text_path", lambda: "/data/local/tmp/opengui-yadb-input.txt")
    monkeypatch.setattr(backend, "_write_local_temp_yadb_script", lambda: Path("/tmp/opengui-yadb-input.sh"))
    monkeypatch.setattr(backend, "_make_yadb_device_script_path", lambda: "/data/local/tmp/opengui-yadb-input.sh")

    text = "你好，OpenGUI"
    action = parse_action({"action_type": "input_text", "text": text})
    await backend.execute(action)

    ensure_yadb_mock.assert_awaited_once_with(5.0)
    assert run_mock.await_args_list[0].args == (
        "push", "/tmp/opengui-yadb-input.txt", "/data/local/tmp/opengui-yadb-input.txt",
    )
    assert run_mock.await_args_list[1].args == (
        "push", "/tmp/opengui-yadb-input.sh", "/data/local/tmp/opengui-yadb-input.sh",
    )
    assert run_mock.await_args_list[2].args == (
        "shell", "chmod", "755", "/data/local/tmp/opengui-yadb-input.sh",
    )
    assert run_mock.await_args_list[3].args == (
        "shell", "sh", "/data/local/tmp/opengui-yadb-input.sh", "/data/local/tmp/opengui-yadb-input.txt",
    )
    assert run_mock.await_args_list[4].args == (
        "shell", "rm", "-f", "/data/local/tmp/opengui-yadb-input.txt",
    )
    assert run_mock.await_args_list[5].args == (
        "shell", "rm", "-f", "/data/local/tmp/opengui-yadb-input.sh",
    )


@pytest.mark.asyncio
async def test_adb_backend_input_text_multiline_sends_each_line_and_enter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()

    async def fake_run(*args: object, timeout: float = 5.0) -> str:
        return ""

    run_mock = AsyncMock(side_effect=fake_run)
    monkeypatch.setattr(backend, "_run", run_mock)
    ensure_yadb_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(backend, "_ensure_yadb_available", ensure_yadb_mock)
    local_paths = iter([
        Path("/tmp/opengui-yadb-input-1.txt"),
        Path("/tmp/opengui-yadb-input-2.txt"),
    ])
    device_paths = iter([
        "/data/local/tmp/opengui-yadb-input-1.txt",
        "/data/local/tmp/opengui-yadb-input-2.txt",
    ])
    script_local_paths = iter([
        Path("/tmp/opengui-yadb-input-1.sh"),
        Path("/tmp/opengui-yadb-input-2.sh"),
    ])
    script_device_paths = iter([
        "/data/local/tmp/opengui-yadb-input-1.sh",
        "/data/local/tmp/opengui-yadb-input-2.sh",
    ])
    monkeypatch.setattr(backend, "_write_local_temp_text", lambda text: next(local_paths))
    monkeypatch.setattr(backend, "_make_yadb_device_text_path", lambda: next(device_paths))
    monkeypatch.setattr(backend, "_write_local_temp_yadb_script", lambda: next(script_local_paths))
    monkeypatch.setattr(backend, "_make_yadb_device_script_path", lambda: next(script_device_paths))

    action = parse_action({"action_type": "input_text", "text": "第一行\n第二行"})
    await backend.execute(action)

    assert run_mock.await_args_list[0].args == (
        "push", "/tmp/opengui-yadb-input-1.txt", "/data/local/tmp/opengui-yadb-input-1.txt",
    )
    assert run_mock.await_args_list[1].args == (
        "push", "/tmp/opengui-yadb-input-1.sh", "/data/local/tmp/opengui-yadb-input-1.sh",
    )
    assert run_mock.await_args_list[2].args == (
        "shell", "chmod", "755", "/data/local/tmp/opengui-yadb-input-1.sh",
    )
    assert run_mock.await_args_list[3].args == (
        "shell", "sh", "/data/local/tmp/opengui-yadb-input-1.sh", "/data/local/tmp/opengui-yadb-input-1.txt",
    )
    assert run_mock.await_args_list[4].args == (
        "shell", "rm", "-f", "/data/local/tmp/opengui-yadb-input-1.txt",
    )
    assert run_mock.await_args_list[5].args == (
        "shell", "rm", "-f", "/data/local/tmp/opengui-yadb-input-1.sh",
    )
    assert run_mock.await_args_list[6].args == (
        "shell", "input", "keyevent", "KEYCODE_ENTER",
    )
    assert run_mock.await_args_list[7].args == (
        "push", "/tmp/opengui-yadb-input-2.txt", "/data/local/tmp/opengui-yadb-input-2.txt",
    )
    assert run_mock.await_args_list[8].args == (
        "push", "/tmp/opengui-yadb-input-2.sh", "/data/local/tmp/opengui-yadb-input-2.sh",
    )
    assert run_mock.await_args_list[9].args == (
        "shell", "chmod", "755", "/data/local/tmp/opengui-yadb-input-2.sh",
    )
    assert run_mock.await_args_list[10].args == (
        "shell", "sh", "/data/local/tmp/opengui-yadb-input-2.sh", "/data/local/tmp/opengui-yadb-input-2.txt",
    )
    assert run_mock.await_args_list[11].args == (
        "shell", "rm", "-f", "/data/local/tmp/opengui-yadb-input-2.txt",
    )
    assert run_mock.await_args_list[12].args == (
        "shell", "rm", "-f", "/data/local/tmp/opengui-yadb-input-2.sh",
    )


@pytest.mark.asyncio
async def test_adb_backend_input_text_falls_back_to_adb_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    run_mock = AsyncMock(side_effect=[
        "com.example.ime/.ExampleIme",
        "com.android.adbkeyboard/.AdbIME\ncom.example.ime/.ExampleIme",
        "",
        "",
    ])
    monkeypatch.setattr(backend, "_run", run_mock)
    ensure_yadb_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(backend, "_ensure_yadb_available", ensure_yadb_mock)

    text = "你好，OpenGUI"
    action = parse_action({"action_type": "input_text", "text": text})
    await backend.execute(action)

    expected_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    ensure_yadb_mock.assert_awaited_once_with(5.0)
    assert run_mock.await_args_list[0].args == (
        "shell", "settings", "get", "secure", "default_input_method",
    )
    assert run_mock.await_args_list[1].args == (
        "shell", "ime", "list", "-s",
    )
    assert run_mock.await_args_list[2].args == (
        "shell", "ime", "set", "com.android.adbkeyboard/.AdbIME",
    )
    assert run_mock.await_args_list[3].args == (
        "shell", "am", "broadcast",
        "-a", "ADB_INPUT_B64", "--es", "msg", expected_b64,
    )


@pytest.mark.asyncio
async def test_adb_backend_input_text_enables_adb_keyboard_before_switching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    run_mock = AsyncMock(side_effect=[
        "com.example.ime/.ExampleIme",
        "com.android.adbkeyboard/.AdbIME\ncom.example.ime/.ExampleIme",
        "",
        "",
        "",
    ])
    monkeypatch.setattr(backend, "_run", run_mock)
    enable_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(backend, "_needs_ime_enable_before_set", enable_mock)
    monkeypatch.setattr(backend, "_ensure_yadb_available", AsyncMock(return_value=False))

    action = parse_action({"action_type": "input_text", "text": "你好"})
    await backend.execute(action)

    enable_mock.assert_awaited_once_with(timeout=5.0)
    assert run_mock.await_args_list[2].args == (
        "shell", "ime", "enable", "com.android.adbkeyboard/.AdbIME",
    )
    assert run_mock.await_args_list[3].args == (
        "shell", "ime", "set", "com.android.adbkeyboard/.AdbIME",
    )


@pytest.mark.asyncio
async def test_adb_backend_input_text_falls_back_to_yadb_for_unicode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    run_mock = AsyncMock(return_value="")
    monkeypatch.setattr(backend, "_run", run_mock)
    ensure_yadb_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(backend, "_ensure_yadb_available", ensure_yadb_mock)
    monkeypatch.setattr(backend, "_write_local_temp_text", lambda text: Path("/tmp/opengui-yadb-input.txt"))
    monkeypatch.setattr(backend, "_make_yadb_device_text_path", lambda: "/data/local/tmp/opengui-yadb-input.txt")
    monkeypatch.setattr(backend, "_write_local_temp_yadb_script", lambda: Path("/tmp/opengui-yadb-input.sh"))
    monkeypatch.setattr(backend, "_make_yadb_device_script_path", lambda: "/data/local/tmp/opengui-yadb-input.sh")

    text = "你好，OpenGUI"
    action = parse_action({"action_type": "input_text", "text": text})
    await backend.execute(action)

    ensure_yadb_mock.assert_awaited_once_with(5.0)

    assert run_mock.await_args_list[0].args == (
        "push", "/tmp/opengui-yadb-input.txt", "/data/local/tmp/opengui-yadb-input.txt",
    )
    assert run_mock.await_args_list[1].args == (
        "push", "/tmp/opengui-yadb-input.sh", "/data/local/tmp/opengui-yadb-input.sh",
    )
    assert run_mock.await_args_list[2].args == (
        "shell", "chmod", "755", "/data/local/tmp/opengui-yadb-input.sh",
    )
    assert run_mock.await_args_list[3].args == (
        "shell", "sh", "/data/local/tmp/opengui-yadb-input.sh", "/data/local/tmp/opengui-yadb-input.txt",
    )
    assert run_mock.await_args_list[4].args == (
        "shell", "rm", "-f", "/data/local/tmp/opengui-yadb-input.txt",
    )
    assert run_mock.await_args_list[5].args == (
        "shell", "rm", "-f", "/data/local/tmp/opengui-yadb-input.sh",
    )


@pytest.mark.asyncio
async def test_adb_backend_input_text_falls_back_to_shell_input_for_ascii(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    run_mock = AsyncMock(side_effect=[
        "com.example.ime/.ExampleIme",
        "com.other.ime/.OtherIme",
        "",
    ])
    monkeypatch.setattr(backend, "_run", run_mock)
    ensure_yadb_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(backend, "_ensure_yadb_available", ensure_yadb_mock)

    text = "hello world"
    action = parse_action({"action_type": "input_text", "text": text})
    await backend.execute(action)

    ensure_yadb_mock.assert_awaited_once_with(5.0)
    assert run_mock.await_args_list[2].args == (
        "shell", "input", "text", "hello%sworld",
    )
    assert run_mock.await_args_list[2].kwargs == {"timeout": 5.0}


def test_adb_backend_text_segmentation_splits_emoji_boundaries() -> None:
    from opengui.backends.adb import _iter_text_input_segments

    assert _iter_text_input_segments("杭州✅明天☁️有雨") == [
        "杭州",
        "✅",
        "明天",
        "☁️",
        "有雨",
    ]


@pytest.mark.asyncio
async def test_adb_backend_input_text_sends_text_after_emoji_as_later_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    segments: list[str] = []
    run_mock = AsyncMock(return_value="")
    monkeypatch.setattr(backend, "_run", run_mock)

    async def fake_input_single_text(text: str, timeout: float) -> None:
        assert timeout == 5.0
        segments.append(text)

    monkeypatch.setattr(backend, "_input_single_text", fake_input_single_text)

    action = parse_action({"action_type": "input_text", "text": "已发送给苏✅请查收"})
    await backend.execute(action)

    assert segments == ["已发送给苏", "✅", "请查收"]
    run_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_adb_backend_enter_and_app_switch_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = AdbBackend()
    run_mock = AsyncMock(return_value="")
    monkeypatch.setattr(backend, "_run", run_mock)

    await backend.execute(parse_action({"action_type": "hotkey", "key": ["ENTER"]}))
    await backend.execute(Action(action_type="enter"))
    await backend.execute(Action(action_type="app_switch"))

    assert run_mock.await_args_list[0].args == (
        "shell", "input", "keyevent", "KEYCODE_ENTER",
    )
    assert run_mock.await_args_list[0].kwargs == {"timeout": 5.0}
    assert run_mock.await_args_list[1].args == (
        "shell", "input", "keyevent", "KEYCODE_ENTER",
    )
    assert run_mock.await_args_list[1].kwargs == {"timeout": 5.0}
    assert run_mock.await_args_list[2].args == (
        "shell", "input", "keyevent", "KEYCODE_APP_SWITCH",
    )
    assert run_mock.await_args_list[2].kwargs == {"timeout": 5.0}


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
async def test_agent_records_attempt_exception_and_retry_events(tmp_path: Path) -> None:
    class _FlakyLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider exploded")
            return LLMResponse(
                content="Action: done",
                tool_calls=[ToolCall(
                    id="call-2",
                    name="computer_use",
                    arguments={"action_type": "done", "status": "success"},
                )],
            )

    recorder = _make_recorder(tmp_path, "retry task")
    agent = GuiAgent(
        _FlakyLLM(),
        DryRunBackend(),
        trajectory_recorder=recorder,
        artifacts_root=tmp_path / "runs",
        max_steps=1,
    )

    result = await agent.run("retry task", max_retries=2)

    assert result.success
    assert recorder.path is not None
    events = [json.loads(line) for line in recorder.path.read_text(encoding="utf-8").splitlines()]
    types = [event["type"] for event in events]
    assert "attempt_start" in types
    assert "attempt_exception" in types
    assert "retry" in types
    attempt_exception = next(event for event in events if event["type"] == "attempt_exception")
    assert attempt_exception["error_type"] == "RuntimeError"
    assert attempt_exception["error_message"] == "provider exploded"


@pytest.mark.asyncio
async def test_agent_records_model_response_on_attempt_exception(tmp_path: Path) -> None:
    class _MalformedToolCallLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
            self.calls += 1
            if self.calls <= 3:
                return LLMResponse(
                    content="Action: Swipe up to reveal the size options.",
                    tool_calls=[ToolCall(
                        id=f"bad-call-{self.calls}",
                        name="computer_use",
                        arguments={"action_type": "swipe", "x": [500, 750], "relative": True},
                    )],
                )
            return LLMResponse(
                content="Action: done",
                tool_calls=[ToolCall(
                    id="good-call",
                    name="computer_use",
                    arguments={"action_type": "done", "status": "success"},
                )],
            )

    recorder = _make_recorder(tmp_path, "retry malformed tool call")
    agent = GuiAgent(
        _MalformedToolCallLLM(),
        DryRunBackend(),
        trajectory_recorder=recorder,
        artifacts_root=tmp_path / "runs",
        max_steps=1,
    )

    result = await agent.run("retry malformed tool call", max_retries=2)

    assert result.success
    assert recorder.path is not None
    events = [json.loads(line) for line in recorder.path.read_text(encoding="utf-8").splitlines()]
    attempt_exception = next(event for event in events if event["type"] == "attempt_exception")
    assert attempt_exception["error_type"] == "_StepExecutionError"
    assert "Failed to parse action after retries" in attempt_exception["error_message"]
    assert attempt_exception["model_response"]["raw_content"] == "Action: Swipe up to reveal the size options."
    assert attempt_exception["model_response"]["tool_calls"][0]["name"] == "computer_use"
    assert attempt_exception["model_response"]["tool_calls"][0]["arguments"] == {
        "action_type": "swipe",
        "x": [500, 750],
        "relative": True,
    }


@pytest.mark.asyncio
async def test_retry_prompt_includes_previous_attempt_summary_after_max_steps(
    tmp_path: Path,
) -> None:
    llm = _RecordingLLM([
        LLMResponse(
            content="wait briefly",
            tool_calls=[ToolCall(
                id="call-1",
                name="computer_use",
                arguments={"action_type": "wait", "duration_ms": 1},
            )],
        ),
        # Termination summary call (text-only, no tool call) after max_steps hit
        LLMResponse(content="Waited briefly but ran out of steps. Currently on home screen."),
        LLMResponse(
            content="finish task",
            tool_calls=[ToolCall(
                id="call-2",
                name="computer_use",
                arguments={"action_type": "done", "status": "success"},
            )],
        ),
    ])
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "retry summary max steps"),
        artifacts_root=tmp_path / "runs",
        max_steps=1,
        include_date_context=False,
    )

    result = await agent.run("Open Settings", max_retries=2)

    assert result.success
    # calls[0]=attempt1 step, calls[1]=termination summary, calls[2]=attempt2 step
    second_attempt = llm.calls[2]
    retry_text = "\n".join(
        block["text"]
        for block in second_attempt[1]["content"]
        if block.get("type") == "text"
    )
    assert "Previous attempt summaries:" in retry_text
    assert "Attempt 1:" in retry_text
    assert "Failure reason: max_steps_exceeded" in retry_text
    assert "Step 1: wait briefly" in retry_text
    assert "Continue from the current screen state" in retry_text


@pytest.mark.asyncio
async def test_retry_prompt_includes_previous_attempt_summary_after_exception(
    tmp_path: Path,
) -> None:
    class _MalformedThenRecoverLLM:
        def __init__(self) -> None:
            self.calls: list[list[dict]] = []
            self._call_count = 0

        async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
            del tools, tool_choice
            self.calls.append(copy.deepcopy(messages))
            self._call_count += 1
            if self._call_count <= 3:
                return LLMResponse(
                    content="Action: Swipe up to reveal the size options.",
                    tool_calls=[ToolCall(
                        id=f"bad-call-{self._call_count}",
                        name="computer_use",
                        arguments={"action_type": "swipe", "x": [500, 750], "relative": True},
                    )],
                )
            return LLMResponse(
                content="finish task",
                tool_calls=[ToolCall(
                    id="good-call",
                    name="computer_use",
                    arguments={"action_type": "done", "status": "success"},
                )],
            )

    llm = _MalformedThenRecoverLLM()
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "retry summary exception"),
        artifacts_root=tmp_path / "runs",
        max_steps=1,
        include_date_context=False,
    )

    result = await agent.run("retry malformed tool call", max_retries=2)

    assert result.success
    second_attempt = llm.calls[3]
    retry_text = "\n".join(
        block["text"]
        for block in second_attempt[1]["content"]
        if block.get("type") == "text"
    )
    assert "Previous attempt summaries:" in retry_text
    assert "Attempt 1:" in retry_text
    assert "Failure reason: _StepExecutionError: Failed to parse action after retries" in retry_text
    assert "No completed GUI actions were recorded before the failure." in retry_text
    assert "Continue from the current screen state" in retry_text


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


@pytest.mark.asyncio
async def test_agent_waits_for_ui_to_settle_before_observing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    original_sleep = asyncio.sleep

    class _SettlingBackend(DryRunBackend):
        async def execute(self, action, timeout: float = 5.0) -> str:
            events.append(f"execute:{action.action_type}")
            return await super().execute(action, timeout=timeout)

        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            events.append(f"observe:{Path(screenshot_path).name}")
            return await super().observe(screenshot_path, timeout=timeout)

    async def fake_sleep(delay: float) -> None:
        events.append(f"sleep:{delay}")
        await original_sleep(0)

    monkeypatch.setattr("opengui.agent.asyncio.sleep", fake_sleep)

    agent = GuiAgent(
        _ScriptedLLM([
            LLMResponse(
                content="tap the screen",
                tool_calls=[ToolCall(
                    id="call-1",
                    name="computer_use",
                    arguments={"action_type": "tap", "x": 10, "y": 20},
                )],
            ),
            LLMResponse(
                content="finish task",
                tool_calls=[ToolCall(
                    id="call-2",
                    name="computer_use",
                    arguments={"action_type": "done", "status": "success"},
                )],
            ),
        ]),
        _SettlingBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "settle"),
        artifacts_root=tmp_path / "runs",
        max_steps=2,
        include_date_context=False,
    )

    result = await agent.run("Tap once")

    assert result.success
    assert events[:4] == [
        "observe:step_000.png",
        "execute:tap",
        "sleep:0.25",
        "observe:step_001.png",
    ]


def test_pyproject_includes_opengui_in_build() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    include = pyproject["tool"]["hatch"]["build"]["include"]
    assert "opengui/**/*.py" in include

    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert "opengui" in wheel["packages"]

    sdist_include = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "opengui/" in sdist_include
