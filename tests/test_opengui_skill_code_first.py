import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pytest

from opengui.action import Action
from opengui.interfaces import LLMResponse
from opengui.observation import Observation
from opengui.postprocessing import EvaluationConfig, PostRunProcessor, _load_completed_reuse
from opengui.skills.code_first import (
    CodeSkillExtraction,
    CodeSkillExtractor,
    CodeSkillLibrary,
    CodeSkillRepository,
    TraceSegmenter,
    canonicalize_code_actions_from_events,
    filter_code_to_contract_complete,
    normalize_code_skill_entrypoints,
    repair_code_contracts_from_events,
)
from opengui.skills.code_graph import compile_code_graph, compile_code_skills
from opengui.skills.code_graph_projection import project_graph_code_from_events
from opengui.skills.deeplink import (
    DeeplinkCandidate,
    CapturedIntentSpec,
    _build_candidates,
    _capture_current_intent_specs,
    _candidate_for_probe_record,
    _candidate_is_probeable,
    _candidate_probe_key,
    _contract_from_observation,
    _code_for_verified_candidates,
    _dedupe_candidates,
    _normalize_candidate_uri,
    _parse_intent_at,
    _parse_intent_extras,
    _probe_candidate,
    _raw_capture_for_spec,
    discover_deeplink_skills_from_trace,
)
from opengui.skills.evolution import SkillEvolutionEngine, _task_skill_conflict
from opengui.skills.graph import GraphEdge, GraphNode, SkillGraphStore


class _ScriptedLLM:
    def __init__(self, responses: list[str], *, model: str | None = None) -> None:
        self._responses = [LLMResponse(content=response) for response in responses]
        self.messages: list[list[dict[str, Any]]] = []
        if model is not None:
            self._model = model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        del tools, tool_choice
        self.messages.append(messages)
        if not self._responses:
            raise AssertionError("no scripted LLM responses remain")
        return self._responses.pop(0)


class _SemanticEmbedder:
    async def embed(self, texts: list[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for text in texts:
            lowered = text.casefold()
            if any(token in lowered for token in ("purchase history", "订单", "order total")):
                rows.append([1.0, 0.0])
            else:
                rows.append([0.0, 1.0])
        return np.array(rows, dtype=np.float32)


class _SlowLLM:
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        del messages, tools, tool_choice
        await asyncio.sleep(10.0)
        return LLMResponse(content="")


class _FakeDeeplinkBackend:
    platform = "android"

    def __init__(
        self,
        *,
        app: str = "com.example.app",
        package_output: str = "Activity Resolver Table:\n  scheme=demo\n",
        activity_outputs: dict[str, str] | None = None,
        verified_uris: set[str] | None = None,
        launch_errors: dict[str, Exception] | None = None,
        component_launch_errors: set[str] | None = None,
        resolve_outputs: dict[str, str] | None = None,
        verified_intents: set[str] | None = None,
        launch_outputs: dict[str, str] | None = None,
    ) -> None:
        self.app = app
        self.package_output = package_output
        self.activity_outputs = activity_outputs or {}
        self.verified_uris = verified_uris or {"demo://order"}
        self.launch_errors = launch_errors or {}
        self.component_launch_errors = component_launch_errors or set()
        self.resolve_outputs = resolve_outputs or {}
        self.verified_intents = verified_intents or set()
        self.launch_outputs = launch_outputs or {}
        self.launched_uri: str | None = None
        self.launched_intent_action: str | None = None
        self.launched_package: str | None = None
        self.actions: list[Action] = []
        self.run_calls: list[tuple[str, ...]] = []

    async def _run(self, *args: str, timeout: float = 10.0) -> str:
        del timeout
        self.run_calls.append(args)
        command = " ".join(args)
        if "dumpsys activity activities" in command:
            for marker, output in self.activity_outputs.items():
                if marker in command:
                    return output
            return self.activity_outputs.get("*", "")
        if "cmd package resolve-activity" in command:
            for marker, output in self.resolve_outputs.items():
                if marker in command:
                    return output
            return self.resolve_outputs.get("*", "")
        if "dumpsys package" in command:
            return self.package_output
        return ""

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        del timeout
        self.actions.append(action)
        if action.action_type == "open_deeplink":
            if action.component and action.text in self.component_launch_errors:
                raise RuntimeError("SecurityException: Permission Denial")
            if action.text in self.launch_errors:
                raise self.launch_errors[action.text]
            self.launched_uri = action.text
            self.launched_intent_action = None
            self.launched_package = action.package
        if action.action_type == "open_intent":
            self.launched_uri = action.text
            self.launched_intent_action = action.intent_action
            self.launched_package = action.package
        if action.action_type == "close_app":
            self.launched_uri = None
            self.launched_intent_action = None
            self.launched_package = None
        return self.launch_outputs.get(action.text or action.intent_action or "", "ok")

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        del timeout
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        _write_png(screenshot_path)
        if (
            self.launched_uri in self.verified_uris
            or self.launched_intent_action in self.verified_intents
        ):
            if self.app == "com.google.android.documentsui":
                return Observation(
                    screenshot_path=str(screenshot_path),
                    screen_width=1080,
                    screen_height=1920,
                    foreground_app=self.app,
                    platform="android",
                    extra={
                        "visible_text": ["Downloads"],
                        "content_desc": ["Downloads"],
                        "resource_ids": ["com.google.android.documentsui:id/dir_list"],
                    },
                )
            if (self.launched_package or self.app) == "com.google.android.contacts":
                return Observation(
                    screenshot_path=str(screenshot_path),
                    screen_width=1080,
                    screen_height=1920,
                    foreground_app="com.google.android.contacts",
                    platform="android",
                    extra={
                        "visible_text": ["Create contact", "Save", "First name"],
                        "content_desc": ["Cancel", "More options"],
                        "resource_ids": [
                            "com.google.android.contacts:id/contact_editor_fragment",
                            "com.google.android.contacts:id/toolbar_button",
                        ],
                    },
                )
            if self.app == "com.google.android.deskclock":
                return Observation(
                    screenshot_path=str(screenshot_path),
                    screen_width=1080,
                    screen_height=1920,
                    foreground_app=self.app,
                    platform="android",
                    extra={
                        "visible_text": ["Timer", "00h 00m 00s", "1", "2", "3"],
                        "content_desc": ["Timer"],
                        "resource_ids": ["com.google.android.deskclock:id/timer_setup_digit_1"],
                    },
                )
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1080,
                screen_height=1920,
                foreground_app=self.app,
                platform="android",
                extra={
                    "visible_text": ["My Orders", "Recent purchases"],
                    "content_desc": ["My Orders"],
                    "resource_ids": ["com.example.app:id/orders_title"],
                },
            )
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1080,
            screen_height=1920,
            foreground_app=self.app,
            platform="android",
            extra={"visible_text": ["Home"], "content_desc": [], "resource_ids": []},
        )


class _ScriptedProbeBackend(_FakeDeeplinkBackend):
    def __init__(
        self,
        *,
        package: str = "com.example.app",
        execute_plan: list[BaseException | None] | None = None,
        verified_attempts: set[int] | None = None,
        activity_state: str | list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(app=package, **kwargs)
        self.execute_plan = list(execute_plan or [])
        self.verified_attempts = set(verified_attempts or {1})
        self.activity_state = activity_state
        self._open_attempt = 0
        self._observe_attempt = 0
        self._run_calls = 0

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        if action.action_type.startswith("open_"):
            self._open_attempt += 1
            if self._open_attempt <= len(self.execute_plan):
                planned = self.execute_plan[self._open_attempt - 1]
                if planned is not None:
                    raise planned
        return await super().execute(action, timeout=timeout)

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        del timeout
        self._observe_attempt = self._open_attempt
        _write_png(screenshot_path)
        if self._observe_attempt in self.verified_attempts:
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1080,
                screen_height=1920,
                foreground_app=self.app,
                platform="android",
                extra={
                    "visible_text": ["My Orders", "Recent purchases"],
                    "content_desc": ["My Orders"],
                    "resource_ids": ["com.example.app:id/orders_title"],
                },
            )
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1080,
            screen_height=1920,
            foreground_app=self.app,
            platform="android",
            extra={"visible_text": ["Home"], "content_desc": [], "resource_ids": []},
        )

    async def _run(self, *args: str, timeout: float = 10.0) -> str:
        self._run_calls += 1
        command = " ".join(args)
        if "dumpsys activity activities" in command:
            if self.activity_state is None:
                return await super()._run(*args, timeout=timeout)
            if isinstance(self.activity_state, list):
                index = min(self._run_calls - 1, len(self.activity_state) - 1)
                return self.activity_state[index]
            return self.activity_state
        return await super()._run(*args, timeout=timeout)


def _write_trace(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def _write_png(path: Path) -> None:
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
            "0000000c49444154789c6360f8ffff3f0005fe02fea7ee26db0000000049454e44ae426082"
        )
    )


def _skill_source(name: str = "open_orders") -> str:
    return f'''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["orders"])
async def {name}(device):
    await action(
        "tap",
        target="Orders",
        text="Orders",
        state_contract=C(required=[R(text="Orders", visible=True)]),
    )
'''


def _text_only_skill_source(name: str = "open_orders") -> str:
    return f'''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["orders"])
async def {name}(device):
    await action("open_app", target="com.example.app")
    await action(
        "tap",
        target="Orders",
        state_contract=C(app="com.example.app", required=[R(text="Orders", clickable=True)]),
    )
'''


def _single_tap_skill_source(name: str, target: str = "Button") -> str:
    return f'''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.app", platform="android", tags=["long"])
async def {name}(device):
    await action("tap", target="{target}")
'''


def _wrapped_code(source: str) -> str:
    return json.dumps({
        "step_by_step_reasoning": "learn an orders shortcut",
        "python_code": source,
    })


def _xiaoheihe_orders_source() -> str:
    return '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.max.xiaoheihe", platform="android", tags=["orders"])
async def navigate_to_my_orders(device):
    await action("open_app", target="com.max.xiaoheihe")
    await action(
        "tap",
        target="我",
        state_contract=C(app="com.max.xiaoheihe", required=[R(text="我", clickable=True)]),
    )
    await action(
        "tap",
        target="我的订单",
        state_contract=C(app="com.max.xiaoheihe", required=[R(text="我的订单", clickable=True)]),
    )
    await action(
        "tap",
        target="我的订单",
        state_contract=C(app="com.max.xiaoheihe", required=[R(text="我的订单", clickable=True)]),
    )
'''


def _xiaoheihe_repeated_orders_events() -> list[dict[str, Any]]:
    return [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "com.max.xiaoheihe"},
            "observation": {
                "foreground_app": "com.android.permissioncontroller",
                "platform": "android",
                "extra": {"visible_text": ["权限管理"]},
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "wait"},
            "observation": {
                "foreground_app": "com.max.xiaoheihe",
                "platform": "android",
                "extra": {
                    "visible_text": ["首页", "社区", "我"],
                    "clickable_text": ["我"],
                    "ui_tree": [
                        {
                            "text": "我",
                            "resource_id": "com.max.xiaoheihe:id/rb_5",
                            "clickable": True,
                            "bounds": "[880,2100][1080,2240]",
                        }
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 2,
            "action": {"action_type": "tap", "target": "我"},
            "action_summary": '点击底部导航 "我"',
            "observation": {
                "foreground_app": "com.max.xiaoheihe",
                "platform": "android",
                "extra": {"visible_text": [], "clickable_text": [], "ui_tree": []},
            },
        },
        {
            "type": "step",
            "step_index": 3,
            "action": {"action_type": "tap", "target": "我的订单"},
            "action_summary": '点击 "我的订单"',
            "observation": {
                "foreground_app": "com.max.xiaoheihe",
                "platform": "android",
                "extra": {
                    "visible_text": ["黑盒商城", "我的订单", "收货地址", "优惠券"],
                    "clickable_text": ["我的订单"],
                    "ui_tree": [
                        {"text": "黑盒商城", "resource_id": "com.max.xiaoheihe:id/tv_title"},
                        {
                            "text": "我的订单",
                            "resource_id": "com.max.xiaoheihe:id/tv_desc",
                            "clickable": False,
                        },
                        {"text": "收货地址"},
                        {"text": "优惠券"},
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 4,
            "action": {"action_type": "tap", "target": "我的订单"},
            "action_summary": '再次点击 "我的订单"',
            "observation": {
                "foreground_app": "com.max.xiaoheihe",
                "platform": "android",
                "extra": {
                    "visible_text": ["我的订单", "全部订单", "成功订单", "购买成功"],
                    "clickable_text": ["全部订单", "成功订单"],
                    "ui_tree": [
                        {
                            "text": "我的订单",
                            "resource_id": "com.max.xiaoheihe:id/tv_appbar_title",
                            "clickable": False,
                        },
                        {"text": "全部订单"},
                        {"text": "成功订单"},
                        {"text": "购买成功"},
                    ],
                },
            },
        },
        {"type": "result", "success": True},
    ]


def _zhihu_search_source() -> str:
    return '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.zhihu.android", platform="android", tags=["search", "zhihu"])
async def search_zhihu_and_open_top_post(device, query="强化学习"):
    await action(
        "tap",
        target="com.zhihu.android:id/input_text",
        state_contract=C(app="com.zhihu.android", required=[R(text="com.zhihu.android:id/input_text", visible=True)]),
    )
    await action(
        "input_text",
        target="com.zhihu.android:id/input_text",
        text=query,
        auto_enter=True,
        state_contract=C(app="com.zhihu.android", required=[R(resource_id="com.zhihu.android:id/input_text", focused=True)]),
    )
    await action(
        "tap",
        target=query,
        state_contract=C(app="com.zhihu.android", required=[R(text=query, clickable=True)]),
    )
'''


def _zhihu_search_events() -> list[dict[str, Any]]:
    return [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "x": 417.0, "y": 65.0},
            "observation": {
                "foreground_app": "com.zhihu.android",
                "platform": "android",
                "extra": {
                    "visible_text": ["AI 搜索", "搜索", "热榜"],
                    "ui_tree": [
                        {
                            "text": "强化学习",
                            "resource_id": "com.zhihu.android:id/input_text",
                            "class": "android.widget.EditText",
                            "clickable": True,
                            "enabled": True,
                            "focused": True,
                        },
                        {
                            "text": "搜索",
                            "resource_id": "com.zhihu.android:id/search_button",
                            "clickable": True,
                            "enabled": True,
                        },
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "input_text", "text": "强化学习", "auto_enter": True},
            "observation": {
                "foreground_app": "com.zhihu.android",
                "platform": "android",
                "extra": {"visible_text": [], "ui_tree": []},
            },
        },
        {
            "type": "step",
            "step_index": 2,
            "action": {"action_type": "input_text", "text": "强化学习", "auto_enter": True},
            "observation": {
                "foreground_app": "com.zhihu.android",
                "platform": "android",
                "extra": {
                    "visible_text": ["强化学习", "综合", "AI", "搜索"],
                    "clickable_text": ["强化学习", "综合", "AI", "搜索"],
                    "ui_tree": [
                        {"text": "强化学习"},
                        {"text": "综合"},
                        {"text": "AI"},
                        {"text": "搜索"},
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 3,
            "action": {"action_type": "tap", "x": 496.0, "y": 327.0},
            "observation": {
                "foreground_app": "com.zhihu.android",
                "platform": "android",
                "extra": {"visible_text": [], "ui_tree": []},
            },
        },
        {
            "type": "step",
            "step_index": 4,
            "action": {"action_type": "wait", "duration_ms": 2000},
            "observation": {
                "foreground_app": "com.zhihu.android",
                "platform": "android",
                "extra": {
                    "visible_text": ["浮生梦晓", "关注", "全文", "欢迎参与讨论"],
                    "content_desc": ["赞同535", "收藏1215"],
                    "resource_ids": [
                        "com.zhihu.android:id/follow_btn",
                        "com.zhihu.android:id/btn_people_follow",
                        "com.zhihu.android:id/bottom_layout",
                    ],
                    "ui_tree": [
                        {
                            "resource_id": "com.zhihu.android:id/follow_btn",
                            "clickable": True,
                            "enabled": True,
                        },
                        {
                            "text": "关注",
                            "resource_id": "com.zhihu.android:id/btn_people_follow",
                            "enabled": True,
                        },
                        {
                            "resource_id": "com.zhihu.android:id/bottom_layout",
                            "clickable": True,
                            "enabled": True,
                        },
                    ],
                },
            },
        },
        {"type": "result", "success": True},
    ]


@pytest.mark.asyncio
async def test_code_skill_extractor_returns_python_code_from_json_wrapper(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [{"type": "step", "action": {"action_type": "tap"}}])
    extractor = CodeSkillExtractor(llm=_ScriptedLLM([_wrapped_code(_skill_source())]))

    result = await extractor.extract_from_file(trace_path, is_success=True)

    assert result is not None
    assert result.python_code.strip().startswith("from opengui.skills.code_graph import")
    assert result.attempts[0]["violations"] == []


@pytest.mark.asyncio
async def test_code_skill_extractor_attaches_segment_screenshots(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    _write_png(screenshot)
    llm = _ScriptedLLM([_wrapped_code(_skill_source())])
    extractor = CodeSkillExtractor(llm=llm, max_screenshots_per_segment=1)

    result = await extractor.extract_from_events(
        [{
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Orders"},
            "screenshot_path": str(screenshot),
            "observation": {"foreground_app": "com.example.app", "extra": {"visible_text": ["Orders"]}},
        }],
        is_success=True,
        platform="android",
        task="open orders",
        segment_id="seg-000",
    )

    assert result is not None
    assert result.screenshots_used == (str(screenshot),)
    content = llm.messages[0][0]["content"]
    assert isinstance(content, list)
    assert any(block.get("type") == "image_url" for block in content)


@pytest.mark.asyncio
async def test_code_skill_extractor_can_disable_screenshots(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    _write_png(screenshot)
    llm = _ScriptedLLM([_wrapped_code(_skill_source())])
    extractor = CodeSkillExtractor(llm=llm, include_screenshots=False)

    result = await extractor.extract_from_events(
        [{
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Orders"},
            "screenshot_path": str(screenshot),
        }],
        is_success=True,
    )

    assert result is not None
    assert result.screenshots_used == ()
    assert isinstance(llm.messages[0][0]["content"], str)


@pytest.mark.asyncio
async def test_code_skill_extractor_skips_screenshots_for_text_model(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    _write_png(screenshot)
    llm = _ScriptedLLM([_wrapped_code(_skill_source())], model="qwen3.5-plus")
    extractor = CodeSkillExtractor(llm=llm)

    result = await extractor.extract_from_events(
        [{
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Orders"},
            "screenshot_path": str(screenshot),
        }],
        is_success=True,
    )

    assert result is not None
    assert result.screenshots_used == ()
    assert isinstance(llm.messages[0][0]["content"], str)


@pytest.mark.asyncio
async def test_code_skill_extractor_accepts_cli_event_step_key() -> None:
    llm = _ScriptedLLM([_wrapped_code('''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.app", platform="android")
async def open_home(device):
    await action("tap", target="Home")
''')])
    extractor = CodeSkillExtractor(llm=llm, include_screenshots=False)

    result = await extractor.extract_from_events(
        [{"event": "step", "step_index": 0, "action": {"action_type": "tap", "target": "Home"}}],
        is_success=True,
        platform="android",
        task="Open home",
    )

    assert result is not None
    assert "open_home" in result.python_code
    assert llm.messages


@pytest.mark.asyncio
async def test_code_skill_extractor_falls_back_when_screenshot_missing(tmp_path: Path) -> None:
    llm = _ScriptedLLM([_wrapped_code(_skill_source())])
    extractor = CodeSkillExtractor(llm=llm)

    result = await extractor.extract_from_events(
        [{
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Orders"},
            "screenshot_path": str(tmp_path / "missing.png"),
        }],
        is_success=True,
    )

    assert result is not None
    assert result.screenshots_used == ()
    assert isinstance(llm.messages[0][0]["content"], str)


@pytest.mark.asyncio
async def test_code_skill_extractor_times_out_text_only_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from opengui.skills import code_first

    monkeypatch.setattr(code_first, "_TEXT_EXTRACTION_TIMEOUT_S", 0.01)
    extractor = CodeSkillExtractor(llm=_SlowLLM())

    with pytest.raises(asyncio.TimeoutError):
        await extractor.extract_from_events(
            [{"type": "step", "step_index": 0, "action": {"action_type": "tap", "target": "Orders"}}],
            is_success=True,
        )


def test_code_skill_repository_merges_and_compiles_code(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")

    result = repository.add_code(_skill_source())

    assert not result.errors
    assert result.source_path == tmp_path / "skills" / "skill_graph_code.py"
    assert result.updated_functions == ("open_orders",)
    assert result.skills[0].name == "open_orders"
    assert result.source_path.read_text(encoding="utf-8").count("async def open_orders") == 1


def test_code_skill_repository_rejects_invalid_code_without_mutating_source(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")
    first = repository.add_code(_skill_source())
    before = first.source_path.read_text(encoding="utf-8")

    result = repository.add_code("import os\n")

    assert result.errors
    assert first.source_path.read_text(encoding="utf-8") == before


def test_code_skill_repository_rejects_app_selector_in_r(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")

    result = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["orders"])
async def open_orders(device):
    await action("tap", target="Orders", state_contract=C(required=[R(app="com.example.app")]))
''')

    assert result.errors
    assert any("unsupported R() field: app" in error for error in result.errors)
    assert not repository.source_path.exists()


def test_code_skill_repository_normalizes_target_selector_calls(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")

    result = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.max.xiaoheihe", platform="android", tags=["orders"])
async def open_orders(device):
    await action("open_app", target="com.max.xiaoheihe")
    await action(
        "tap",
        target=R(text="我", clickable=True),
        state_contract=C(app="com.max.xiaoheihe", required=[R(text="我", clickable=True)]),
    )
    await action(
        "tap",
        target=R(resource_id="com.max.xiaoheihe:id/rb_5", clickable=True),
        state_contract=C(app="com.max.xiaoheihe", required=[]),
    )
''')

    assert not result.errors
    assert result.skills[0].steps[1].target == "我"
    assert result.skills[0].steps[2].target == "com.max.xiaoheihe:id/rb_5"
    source = repository.source_path.read_text(encoding="utf-8")
    assert "target=R(" not in source
    assert "resource_id='com.max.xiaoheihe:id/rb_5'" in source


def test_code_skill_repository_literalizes_safe_generated_expressions(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")

    result = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.dimowner.audiorecorder", platform="android", tags=["audio"])
async def record_audio_clip(device, duration_seconds: int = 10):
    await action(
        "wait",
        target=f"{duration_seconds} seconds",
        duration_ms=duration_seconds * 1000,
        state_contract=C(app="com.dimowner.audiorecorder", required=[R(text="Recording", visible=True)]),
    )
''')

    assert not result.errors
    assert result.skills[0].steps[0].target == "10 seconds"
    assert result.skills[0].steps[0].parameters["duration_ms"] == 10000


def test_code_skill_repository_literalizes_safe_string_method_chain(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")

    result = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.apps.nexuslauncher", platform="android", tags=["launch"])
async def open_audio_recorder(device, app_name: str = "Audio Recorder"):
    await action("open_app", target=app_name.lower().replace(" ", "-"))
    await action(
        "tap",
        target=app_name,
        state_contract=C(app="com.google.android.apps.nexuslauncher", required=[R(text=app_name, clickable=True)]),
    )
''')

    assert not result.errors
    assert result.skills[0].steps[0].target == "audio-recorder"
    assert result.skills[0].steps[1].target == "{{app_name}}"


def test_code_skill_repository_literalizes_safe_selector_expressions(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")

    result = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.contacts", platform="android", tags=["contacts"])
async def enter_contact_phone(device, phone_label: str):
    await action(
        "tap",
        target="Phone",
        state_contract=C(
            app="com.google.android.contacts",
            required=[R(text=f"{phone_label} Phone", visible=True)],
        ),
    )
''')

    assert not result.errors
    required = result.skills[0].steps[0].state_contract["signature"]["required"]
    assert required[0]["selector"]["text"] == "{{phone_label}} Phone"


def test_code_skill_repository_removes_stale_graph_projection_for_updated_skill(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")
    repository.store_dir.mkdir(parents=True)
    repository.source_path.write_text(
        '''
from opengui.skills.code_graph import C, R, action, skill, state, transition

@skill(app="com.example.app", platform="android")
async def open_orders(device):
    await action("tap", target="Orders")

@state(app="com.example.app", platform="android", node_id="stale-node", skill_ids=["code:open_orders"])
def state_open_orders_stale():
    return C(required=[R(resource_id="com.example:id/stale_order_title", visible=True)])

@transition(src=state_open_orders_stale, dst=state_open_orders_stale, skill_id="code:open_orders")
async def transition_open_orders_stale(device):
    await action(
        "tap",
        target="Orders",
        state_contract=C(required=[R(resource_id="com.example:id/stale_order_title", visible=True)]),
    )
''',
        encoding="utf-8",
    )

    result = repository.add_code(_skill_source("open_orders"))

    assert not result.errors
    source = repository.source_path.read_text(encoding="utf-8")
    assert "stale_order_title" not in source
    assert "state_open_orders_stale" not in source
    assert source.count("async def open_orders") == 1


def test_trace_segmenter_splits_long_traces_with_overlap() -> None:
    events = [
        {
            "type": "step",
            "step_index": index,
            "action": {"action_type": "tap", "target": f"Button {index}"},
            "observation": {
                "foreground_app": "com.example.app",
                "extra": {"visible_text": ["Stable page"], "resource_ids": ["com.example:id/root"]},
            },
        }
        for index in range(25)
    ]

    segments = TraceSegmenter(max_reusable_actions=10, overlap_reusable_actions=2).segment(events)

    assert len(segments) == 3
    assert segments[0].start_step_index == 0
    assert segments[1].start_step_index == 8
    assert segments[2].start_step_index == 16
    assert all(segment.reusable_action_count <= 10 for segment in segments)


@pytest.mark.asyncio
async def test_code_skill_library_sync_graph_cache_compiles_graph_declarations(tmp_path: Path) -> None:
    store_dir = tmp_path / "skills"
    store_dir.mkdir()
    (store_dir / "skill_graph_code.py").write_text(
        '''
from opengui.skills.code_graph import C, R, action, state, transition

@state(app="com.example.app", platform="android", node_id="node-home")
def home():
    return C(required=[R(text="Home", visible=True)])

@state(app="com.example.app", platform="android", node_id="node-orders")
def orders():
    return C(required=[R(text="Orders", visible=True)])

@transition(src=home, dst=orders, edge_id="edge-orders")
async def open_orders(device):
    await action(
        "tap",
        target="Orders",
        state_contract=C(required=[R(text="Home", visible=True)]),
    )
''',
        encoding="utf-8",
    )
    library = CodeSkillLibrary(store_dir=store_dir, legacy_fallback=False)

    synced = await library.sync_graph_cache()

    graph = SkillGraphStore(store_dir=store_dir)
    assert synced is True
    assert graph.get_node("node-home") is not None
    assert graph.get_edge("edge-orders") is not None


@pytest.mark.asyncio
async def test_code_skill_library_sync_graph_cache_skips_state_only_code_source(tmp_path: Path) -> None:
    store_dir = tmp_path / "skills"
    stale_graph = SkillGraphStore(store_dir=store_dir)
    source_node = stale_graph.upsert_node(
        GraphNode(
            node_id="flat-source",
            app="com.example.app",
            platform="android",
            description="flat source node",
            state_contract={
                "anchor": {"app_package": "com.example.app"},
                "signature": {
                    "required": [{"selector": {"text": "Home"}, "state": ["visible"]}],
                    "forbidden": [],
                },
            },
        )
    )
    target_node = stale_graph.upsert_node(
        GraphNode(
            node_id="flat-target",
            app="com.example.app",
            platform="android",
            description="flat target node",
            state_contract={
                "anchor": {"app_package": "com.example.app"},
                "signature": {
                    "required": [{"selector": {"text": "Orders"}, "state": ["visible"]}],
                    "forbidden": [],
                },
            },
        )
    )
    stale_graph.upsert_edge(
        GraphEdge(
            edge_id="flat-edge",
            app="com.example.app",
            platform="android",
            source_node_id=source_node.node_id,
            target_node_id=target_node.node_id,
            action_type="tap",
            target="Orders",
            precondition=source_node.state_contract,
        )
    )
    (store_dir / "skill_graph_code.py").write_text(
        '''
from opengui.skills.code_graph import C, R, state

@state(app="com.example.app", platform="android", node_id="node-home")
def home():
    return C(required=[R(text="Home", visible=True)])
''',
        encoding="utf-8",
    )
    library = CodeSkillLibrary(store_dir=store_dir, legacy_fallback=False)

    synced = await library.sync_graph_cache()

    graph = SkillGraphStore(store_dir=store_dir)
    assert synced is False
    assert graph.get_node("node-home") is None
    assert graph.get_edge("flat-edge") is not None


@pytest.mark.asyncio
async def test_code_skill_library_search_uses_natural_language_description(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")
    result = repository.add_code('''
from opengui.skills.code_graph import action, skill

@skill(app="com.max.xiaoheihe", platform="android", tags=["orders"])
async def xiaoheihe_navigate_to_orders(device):
    """Open XiaoHeiHe and show the orders page."""
    await action("open_app", target="com.max.xiaoheihe")
    await action("tap", target="我")
    await action("tap", target="我的订单")
''', description_hint="打开 小黑盒 展示 订单列表 页面")
    library = CodeSkillLibrary(store_dir=tmp_path / "skills", legacy_fallback=False)

    matches = await library.search(
        "打开 小黑盒 展示 订单列表 页面",
        platform="android",
        app="com.max.xiaoheihe",
    )

    assert not result.errors
    assert "description='打开 小黑盒 展示 订单列表 页面" in repository.source_path.read_text(encoding="utf-8")
    assert matches
    assert matches[0][0].name == "xiaoheihe_navigate_to_orders"
    assert matches[0][1] >= 0.8


def test_action_canonicalization_rewrites_skill_steps_to_trace_actions() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="com.zhihu.android", platform="android", tags=["search"], description="在知乎搜索并打开热门帖子")
async def open_zhihu_hot_post(device, query="强化学习"):
    await action("tap", target="搜索")
    await action("input_text", target="搜索框", text=query)
    await action("tap", target="最多赞同")
    await action("tap", target="第一条结果")
'''
    home = {
        "foreground_app": "com.zhihu.android",
        "screen_width": 1080,
        "screen_height": 2400,
        "platform": "android",
        "extra": {
            "ui_tree": [
                {
                    "resource_id": "com.zhihu.android:id/query_container",
                    "text": "搜索",
                    "clickable": True,
                    "bounds": "[180,70][900,150]",
                }
            ],
        },
    }
    history = {
        "foreground_app": "com.zhihu.android",
        "screen_width": 1080,
        "screen_height": 2400,
        "platform": "android",
        "extra": {
            "ui_tree": [
                {
                    "text": "强化学习",
                    "resource_id": "com.zhihu.android:id/titleTv",
                    "bounds": "[40,250][1040,340]",
                }
            ],
        },
    }
    results = {
        "foreground_app": "com.zhihu.android",
        "screen_width": 1080,
        "screen_height": 2400,
        "platform": "android",
        "extra": {
            "ui_tree": [
                {
                    "resource_id": "com.zhihu.android:id/bottom_layout",
                    "clickable": True,
                    "bounds": "[0,420][1080,900]",
                }
            ],
        },
    }
    events = [
        {"type": "step", "step_index": 0, "action": {"action_type": "wait"}, "observation": home},
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 420, "y": 100},
            "observation": history,
        },
        {
            "type": "step",
            "step_index": 2,
            "action": {"action_type": "tap", "x": 500, "y": 300},
            "observation": {"foreground_app": "com.zhihu.android", "extra": {"ui_tree": []}},
        },
        {"type": "step", "step_index": 3, "action": {"action_type": "wait"}, "observation": results},
        {
            "type": "step",
            "step_index": 4,
            "action": {"action_type": "tap", "x": 540, "y": 640},
            "observation": {"foreground_app": "com.zhihu.android", "extra": {"ui_tree": []}},
        },
        {"type": "result", "success": True},
    ]

    canonicalized = canonicalize_code_actions_from_events(source, events)
    compiled = compile_code_skills(canonicalized.source)

    assert compiled.errors == []
    assert [step.action_type for step in compiled.skills[0].steps] == ["tap", "tap", "tap"]
    assert [step.target for step in compiled.skills[0].steps] == [
        "搜索",
        "强化学习",
        "com.zhihu.android:id/bottom_layout",
    ]
    assert "input_text" not in canonicalized.source
    assert "最多赞同" not in canonicalized.source
    assert canonicalized.report["quality"] == "partial"
    assert canonicalized.report["removed_steps"][0]["action_type"] == "input_text"
    assert canonicalized.report["aligned_steps"][-1]["trace_step_index"] == 4


def test_action_canonicalization_skips_cross_app_trace_detour() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="tv.danmaku.bili", platform="android", tags=["search"])
async def search_bilibili(device):
    await action("open_app", target="tv.danmaku.bili")
    await action("tap", target="tv.danmaku.bili:id/ad_banner_item_container", x=663, y=242, relative=True)
    await action("input_text", target="Search query", text="舌尖上的中国", auto_enter=True)
'''
    home = {
        "foreground_app": "tv.danmaku.bili",
        "platform": "android",
        "screen_width": 1000,
        "screen_height": 1000,
        "extra": {
            "ui_tree": [
                {
                    "content_desc": "Search bar, button",
                    "resource_id": "tv.danmaku.bili:id/expand_search",
                    "clickable": True,
                    "enabled": True,
                    "bounds": "[400,0][700,160]",
                },
                {
                    "resource_id": "tv.danmaku.bili:id/ad_banner_item_container",
                    "clickable": True,
                    "enabled": True,
                    "bounds": "[600,200][900,500]",
                },
            ]
        },
    }
    search = {
        "foreground_app": "tv.danmaku.bili",
        "platform": "android",
        "extra": {
            "ui_tree": [
                {
                    "content_desc": "Search query",
                    "resource_id": "tv.danmaku.bili:id/search_src_text",
                    "focused": True,
                    "enabled": True,
                }
            ]
        },
    }
    events = [
        {"type": "step", "step_index": 0, "action": {"action_type": "open_app", "text": "tv.danmaku.bili"}, "observation": home},
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 663, "y": 242, "relative": True},
            "observation": {
                "foreground_app": "com.taobao.taobao",
                "platform": "android",
                "extra": {"ui_tree": [{"text": "Agree", "resource_id": "com.taobao:id/agree"}]},
            },
        },
        {"type": "step", "step_index": 2, "action": {"action_type": "open_app", "text": "tv.danmaku.bili"}, "observation": home},
        {"type": "step", "step_index": 3, "action": {"action_type": "tap", "x": 459, "y": 76, "relative": True}, "observation": search},
        {
            "type": "step",
            "step_index": 4,
            "action": {"action_type": "input_text", "text": "舌尖上的中国", "auto_enter": True},
            "observation": {
                "foreground_app": "tv.danmaku.bili",
                "platform": "android",
                "extra": {"ui_tree": [{"text": "舌尖上的中国", "resource_id": "tv.danmaku.bili:id/search_fake_text"}]},
            },
        },
    ]

    canonicalized = canonicalize_code_actions_from_events(source, events)
    compiled = compile_code_skills(canonicalized.source)

    assert compiled.errors == []
    assert [step.action_type for step in compiled.skills[0].steps] == ["open_app", "tap", "input_text"]
    assert compiled.skills[0].steps[1].target == "Search bar, button"
    assert compiled.skills[0].steps[1].parameters["x"] == 459
    assert "ad_banner_item_container" not in canonicalized.source


def test_action_canonicalization_does_not_synthesize_unrelated_in_app_trace_gap() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.app", platform="android", tags=["search"])
async def search_city(device, city: str):
    await action("open_app", target="com.example.app")
    await action("tap", target="Close promo", x=900, y=120, relative=True)
    await action("tap", target="Search", x=120, y=200, relative=True)
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "com.example.app"},
            "observation": {"foreground_app": "com.example.app", "platform": "android", "extra": {"ui_tree": []}},
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 900, "y": 120, "relative": True},
            "observation": None,
        },
        {
            "type": "step",
            "step_index": 2,
            "action": {"action_type": "tap", "x": 500, "y": 100, "relative": True},
            "model_output": "点击搜索栏",
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "resource_id": "com.example:id/search_src_text",
                            "focused": True,
                            "enabled": True,
                            "bounds": "[0,0][800,180]",
                        }
                    ]
                },
            },
        },
        {
            "type": "step",
            "step_index": 3,
            "action": {"action_type": "input_text", "text": "广州", "auto_enter": True},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {"ui_tree": [{"resource_id": "com.example:id/result_list", "enabled": True}]},
            },
        },
        {
            "type": "step",
            "step_index": 4,
            "action": {"action_type": "tap", "x": 120, "y": 200, "relative": True},
            "model_output": "进入搜索结果",
            "observation": {"foreground_app": "com.example.app", "platform": "android", "extra": {"ui_tree": []}},
        },
    ]

    canonicalized = canonicalize_code_actions_from_events(source, events)
    compiled = compile_code_skills(canonicalized.source)

    assert compiled.errors == []
    assert [step.action_type for step in compiled.skills[0].steps] == [
        "open_app",
        "tap",
        "tap",
    ]
    assert all(step["reason"] != "trace_gap" for step in canonicalized.report["synthesized_steps"])


@pytest.mark.asyncio
async def test_code_skill_library_search_uses_embedding_when_tokens_do_not_overlap(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")
    result = repository.add_code('''
from opengui.skills.code_graph import action, skill

@skill(app="com.max.xiaoheihe", platform="android", tags=["orders"], description="Show purchase history.")
async def xiaoheihe_navigate_to_orders(device):
    await action("open_app", target="com.max.xiaoheihe")
    await action("tap", target="我")
    await action("tap", target="我的订单")

@skill(app="com.max.xiaoheihe", platform="android", tags=["settings"], description="Open account preferences.")
async def xiaoheihe_open_preferences(device):
    await action("open_app", target="com.max.xiaoheihe")
    await action("tap", target="设置")
''')
    library = CodeSkillLibrary(
        store_dir=tmp_path / "skills",
        embedding_provider=_SemanticEmbedder(),
        legacy_fallback=False,
    )

    matches = await library.search(
        "最近两个订单总额",
        platform="android",
        app="com.max.xiaoheihe",
    )

    assert not result.errors
    assert matches
    assert matches[0][0].name == "xiaoheihe_navigate_to_orders"


@pytest.mark.asyncio
async def test_postrun_code_first_extraction_writes_code_not_graph_or_skill_json(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "tap", "target": "Orders"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"visible_text": ["Home", "Orders"]},
                },
            },
            {
                "type": "result",
                "success": False,
                "error": "stagnation_detected",
                "total_steps": 3,
            },
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([_wrapped_code(_skill_source())]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    skill_id = await processor._extract_skill(trace_path, is_success=False, platform="android")

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert result["status"] == "processed_code"
    assert result["learning_mode"] == "failure_prefix"
    assert result["compiled_skill_ids"] == [skill_id]
    assert "open_orders" in result["updated_functions"]
    assert (tmp_path / "store" / "skill_graph_code.py").exists()
    assert not (tmp_path / "store" / "android" / "skills.json").exists()
    graph = SkillGraphStore(store_dir=tmp_path / "store")
    assert graph.count_nodes == 0


@pytest.mark.asyncio
async def test_postrun_runs_deeplink_before_code_extraction_after_evaluation(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [{"type": "result", "success": True}])
    processor = PostRunProcessor(llm=_ScriptedLLM([]))
    order: list[str] = []

    async def summarize(path: Path) -> str:
        assert path == trace_path
        order.append("summary")
        return "state"

    async def evaluate(*, trace_path: Path, is_success: bool, task: str) -> dict[str, Any]:
        assert is_success is True
        assert task == "open profile"
        order.append("evaluation")
        return {"success": True}

    async def deeplink(
        path: Path,
        is_success: bool,
        platform: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        assert path == trace_path
        assert is_success is True
        assert platform == "android"
        assert kwargs["evaluation_result"] == {"success": True}
        order.append("deeplink")
        return {"status": "no_candidate"}

    async def extract(
        path: Path,
        is_success: bool,
        platform: str,
        **kwargs: Any,
    ) -> None:
        assert path == trace_path
        assert is_success is True
        assert platform == "android"
        assert kwargs["evaluation_result"] == {"success": True}
        order.append("skill")

    processor._summarize_trajectory = summarize  # type: ignore[method-assign]
    processor._run_evaluation = evaluate  # type: ignore[method-assign]
    processor._extract_deeplink_skill = deeplink  # type: ignore[method-assign]
    processor._extract_skill = extract  # type: ignore[method-assign]

    await processor._run_all(trace_path, is_success=True, platform="android", task="open profile")

    assert order.index("evaluation") < order.index("deeplink")
    assert order.index("deeplink") < order.index("skill")


@pytest.mark.asyncio
async def test_postrun_extracts_flat_prefix_when_agent_did_not_succeed(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [{"type": "result", "success": False, "error": "max_steps"}])
    processor = PostRunProcessor(
        llm=_ScriptedLLM([]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
        enable_deeplink_skill_extraction=True,
    )
    order: list[str] = []

    async def summarize(path: Path) -> str:
        assert path == trace_path
        return "state"

    async def evaluate(*, trace_path: Path, is_success: bool, task: str) -> None:
        assert is_success is False
        return None

    async def deeplink(
        path: Path,
        is_success: bool,
        platform: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        assert path == trace_path
        assert is_success is False
        assert platform == "android"
        order.append("deeplink")
        return {"status": "skipped", "reason": "task_not_successful"}

    async def extract(
        path: Path,
        is_success: bool,
        platform: str,
        **kwargs: Any,
    ) -> None:
        assert path == trace_path
        assert is_success is False
        assert platform == "android"
        assert kwargs["agent_success"] is False
        order.append("skill")

    processor._summarize_trajectory = summarize  # type: ignore[method-assign]
    processor._run_evaluation = evaluate  # type: ignore[method-assign]
    processor._extract_deeplink_skill = deeplink  # type: ignore[method-assign]
    processor._extract_skill = extract  # type: ignore[method-assign]

    await processor._run_all(trace_path, is_success=False, platform="android", task="open profile")

    assert order == ["deeplink", "skill"]


@pytest.mark.asyncio
async def test_postrun_continues_after_segment_extraction_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "open_app", "target": "launcher"},
                "observation": {
                    "foreground_app": "com.google.android.apps.nexuslauncher",
                    "platform": "android",
                    "extra": {"visible_text": ["Home"]},
                },
            },
            {
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "swipe", "target": "up"},
                "observation": {
                    "foreground_app": "com.google.android.apps.nexuslauncher",
                    "platform": "android",
                    "extra": {"visible_text": ["Home", "Orders"]},
                },
            },
            {
                "type": "step",
                "step_index": 2,
                "action": {"action_type": "tap", "target": "Orders"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"visible_text": ["Home", "Orders"]},
                },
            },
            {"type": "result", "success": True, "error": None, "total_steps": 3},
        ],
    )

    async def fake_extract(
        self: CodeSkillExtractor,
        events: list[dict[str, Any]],
        *,
        is_success: bool,
        platform: str | None = None,
        task: str | None = None,
        evaluation_result: dict[str, Any] | None = None,
        feedback: str | None = None,
        segment_id: str | None = None,
        segment_summary: str | None = None,
    ) -> CodeSkillExtraction:
        del self, events, is_success, platform, task, evaluation_result, feedback, segment_summary
        if segment_id == "seg-000":
            raise asyncio.TimeoutError()
        return CodeSkillExtraction(
            python_code=_skill_source(),
            attempts=({"segment_id": segment_id, "violations": []},),
        )

    monkeypatch.setattr(CodeSkillExtractor, "extract_from_events", fake_extract)
    processor = PostRunProcessor(
        llm=_ScriptedLLM([]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    skill_id = await processor._extract_skill(trace_path, is_success=True, platform="android")

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert skill_id == "code:open_orders"
    assert result["status"] == "processed_code"
    assert result["segments"][0]["status"] == "error"
    assert result["segments"][0]["rejected_reason"] == "extraction_error"
    assert result["segments"][1]["status"] == "processed_code"


def test_postrun_code_result_preserves_existing_deeplink_result(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [{"type": "result", "success": True}])
    (tmp_path / "extraction_result.json").write_text(
        json.dumps({
            "status": "processed_deeplink_code",
            "trace": str(trace_path),
            "updated_functions": ["open_deeplink_orders"],
            "compiled_skill_ids": ["deeplink:orders"],
            "code_graph_synced": True,
            "deeplink": {
                "status": "processed_deeplink_code",
                "updated_functions": ["open_deeplink_orders"],
                "compiled_skill_ids": ["deeplink:orders"],
            },
            "deeplink_skill_extraction_enabled": True,
        }),
        encoding="utf-8",
    )

    PostRunProcessor._write_extraction_result(trace_path, {
        "status": "processed_code",
        "trace": str(trace_path),
        "updated_functions": ["navigate_to_profile"],
        "compiled_skill_ids": ["code:navigate_to_profile"],
        "code_graph_synced": False,
    })

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert result["status"] == "processed_code"
    assert result["deeplink"]["status"] == "processed_deeplink_code"
    assert result["deeplink_skill_extraction_enabled"] is True
    assert result["updated_functions"] == ["open_deeplink_orders", "navigate_to_profile"]
    assert result["compiled_skill_ids"] == ["deeplink:orders", "code:navigate_to_profile"]
    assert result["code_graph_synced"] is True


def test_postrun_code_no_candidate_does_not_downgrade_existing_deeplink(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [{"type": "result", "success": True}])
    (tmp_path / "extraction_result.json").write_text(
        json.dumps({
            "status": "processed_deeplink_code",
            "trace": str(trace_path),
            "updated_functions": ["open_deeplink_orders"],
            "compiled_skill_ids": ["deeplink:orders"],
            "deeplink": {"status": "processed_deeplink_code"},
            "deeplink_skill_extraction_enabled": True,
        }),
        encoding="utf-8",
    )

    PostRunProcessor._write_extraction_result(trace_path, {
        "status": "no_candidate",
        "trace": str(trace_path),
        "updated_functions": [],
        "compiled_skill_ids": [],
    })

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert result["status"] == "processed_deeplink_code"
    assert result["deeplink"]["status"] == "processed_deeplink_code"
    assert result["updated_functions"] == ["open_deeplink_orders"]
    assert result["compiled_skill_ids"] == ["deeplink:orders"]


@pytest.mark.asyncio
async def test_postrun_deeplink_missing_backend_writes_audit_file(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [{"type": "result", "success": True, "error": None}])
    processor = PostRunProcessor(
        llm=_ScriptedLLM([]),
        enable_deeplink_skill_extraction=True,
        deeplink_probe_backend=None,
    )

    result = await processor._extract_deeplink_skill(
        trace_path,
        is_success=True,
        platform="android",
        task="open profile",
    )

    audit = json.loads((tmp_path / "deeplink_result.json").read_text(encoding="utf-8"))
    extraction = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert result == {"status": "skipped", "reason": "missing_probe_backend"}
    assert audit == {"status": "skipped", "reason": "missing_probe_backend"}
    assert extraction["deeplink"] == audit
    assert extraction["deeplink_skill_extraction_enabled"] is True


@pytest.mark.asyncio
async def test_deeplink_discovery_writes_verified_code_skill(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "visible_text": ["My Orders", "Recent purchases"],
                        "content_desc": ["My Orders"],
                        "resource_ids": ["com.example.app:id/orders_title"],
                    },
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=_FakeDeeplinkBackend(),
        task="open my orders",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    compiled = compile_code_skills(source)
    assert result.status == "processed_deeplink_code"
    assert not result.errors
    assert result.compiled_skill_ids
    assert "open_deeplink" in source
    assert "demo://order" in source
    assert not compiled.errors
    assert compiled.skills[0].steps[0].action_type == "open_deeplink"


@pytest.mark.asyncio
async def test_deeplink_discovery_writes_result_for_weak_contract(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "tap"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {},
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=_FakeDeeplinkBackend(),
        task="open profile",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    saved = json.loads((tmp_path / "deeplink_result.json").read_text(encoding="utf-8"))
    assert result.status == "no_candidate"
    assert result.reason == "weak_final_state_contract"
    assert saved["status"] == "no_candidate"
    assert saved["reason"] == "weak_final_state_contract"
    assert saved["app"] == "com.example.app"


@pytest.mark.asyncio
async def test_deeplink_discovery_prefers_captured_activity_intent(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.max.xiaoheihe",
                    "foreground_app": "com.max.xiaoheihe",
                    "platform": "android",
                    "activity_class": "com.max.xiaoheihe.RouterActivity",
                    "extra": {
                        "visible_text": ["My Orders", "Recent purchases"],
                        "content_desc": ["My Orders"],
                    },
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    activity_dump = """
    Hist #0: ActivityRecord{123 u0 com.max.xiaoheihe/.RouterActivity t42}
      Intent { act=android.intent.action.VIEW dat=heybox://mall/order cmp=com.max.xiaoheihe/.RouterActivity }
    """
    backend = _FakeDeeplinkBackend(
        app="com.max.xiaoheihe",
        package_output='Activity Resolver Table:\n  Scheme: "xiaoheihe"\n',
        activity_outputs={"RouterActivity": activity_dump},
        verified_uris={"heybox://mall/order"},
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=backend,
        task="open my orders",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    open_actions = [action for action in backend.actions if action.action_type == "open_deeplink"]
    assert result.status == "processed_deeplink_code"
    assert open_actions[0].text == "heybox://mall/order"
    assert open_actions[0].component is None
    assert result.candidates[0].source == "dumpsys_activity_activity_grep"
    assert result.candidates[0].kind == "captured_intent"
    assert "heybox://mall/order" in source
    assert "'text': 'heybox://mall/order'" in source
    assert "'package': 'com.max.xiaoheihe'" in source
    assert "dumpsys_activity_activity_grep" in source


@pytest.mark.asyncio
async def test_deeplink_candidate_builder_uses_full_activity_dump_fallback() -> None:
    activity_dump = """
    Hist #0: ActivityRecord{123 u0 com.example.app/.DeepLinkActivity t42}
      Intent { act=android.intent.action.VIEW dat=demo://order cmp=com.example.app/.DeepLinkActivity }
    """
    backend = _FakeDeeplinkBackend(
        activity_outputs={
            "DeepLinkActivity": "",
            "com.example.app": "",
            "*": activity_dump,
        },
    )

    candidates = await _build_candidates(
        backend,
        app="com.example.app",
        task="open my orders",
        final_observation={"activity_class": "com.example.app.DeepLinkActivity"},
        limit=4,
    )

    assert candidates[0].uri == "demo://order"
    assert candidates[0].component == "com.example.app/.DeepLinkActivity"
    assert candidates[0].kind == "captured_intent"
    assert candidates[0].source == "dumpsys_activity_full"


def test_parse_intent_extras_splits_nested_bundle_values() -> None:
    lines = [
        "    Intent { act=android.intent.action.VIEW dat=demo://order cmp=com.example.app/.Main cat=[android.intent.category.DEFAULT,android.intent.category.BROWSABLE] flg=0x10000000 (has extras)}",
        "      Extras: Bundle[{a=1, b=[one,two], c={n=[x,y], m={k=v,u:[1,2,3]}}, d=(String)=true}]",
        "    }",
    ]
    spec = _parse_intent_at(lines, 0, source="dumpsys_activity_activity_grep")
    assert spec is not None
    assert spec.action == "android.intent.action.VIEW"
    assert spec.data_uri == "demo://order"
    assert spec.flags == "0x10000000"
    assert spec.categories == ("android.intent.category.DEFAULT", "android.intent.category.BROWSABLE")
    assert spec.extras == (
        ("a", 1),
        ("b", "[one,two]"),
        ("c", "{n=[x,y], m={k=v,u:[1,2,3]}}"),
        ("d", "(String)=true"),
    )
    assert spec.has_extras_marker is True


def test_parse_intent_extras_preserves_typed_values_and_reconstructs_command() -> None:
    lines = [
        "    Intent { act=android.intent.action.VIEW dat=https://example.com/order cmp=com.example.app/.RouterActivity cat=[android.intent.category.DEFAULT] (has extras) }",
        "      Extras: Bundle[{flag=true, count=123, ratio=1.5, id=1234567890123, name=abc}]",
        "    }",
    ]
    spec = _parse_intent_at(lines, 0, source="dumpsys_activity_full")

    assert spec is not None
    assert spec.extras == (
        ("flag", True),
        ("count", 123),
        ("ratio", 1.5),
        ("id", 1234567890123),
        ("name", "abc"),
    )
    raw_capture = dict(_raw_capture_for_spec(spec))
    assert raw_capture["extras_typed_count"] == 4
    assert raw_capture["sample_count"] == 1
    assert "--ez flag true" in raw_capture["am_start_command"]
    assert "--ei count 123" in raw_capture["am_start_command"]
    assert "--ef ratio 1.5" in raw_capture["am_start_command"]
    assert "--el id 1234567890123" in raw_capture["am_start_command"]
    assert "--es name abc" in raw_capture["am_start_command"]
    assert "-n com.example.app/.RouterActivity" in raw_capture["am_start_command"]
    assert "-n com.example.app/.RouterActivity" not in raw_capture["am_start_command_without_component"]


def test_component_only_capture_is_privileged_audit_not_probeable_uri() -> None:
    line = "    Intent { act=android.intent.action.MAIN cmp=com.example.app/.SecretActivity }"
    spec = _parse_intent_at([line], 0, source="dumpsys_activity_full")

    assert spec is not None
    raw_capture = dict(_raw_capture_for_spec(spec))
    assert raw_capture["requires_privileged_activity_start"] is True
    assert "-n com.example.app/.SecretActivity" in raw_capture["am_start_command"]


def test_parse_intent_at_restores_full_fields_with_extras_marker() -> None:
    line = "    Intent { act=android.intent.action.VIEW dat=content://contacts/people/1 flg=0x10000000 cmp=com.example.app/.RouterActivity (has extras) cat=[android.intent.category.DEFAULT,android.intent.category.BROWSABLE]}"
    spec = _parse_intent_at([line], 0, source="dumpsys_activity_full")
    assert spec is not None
    assert spec.flags == "0x10000000"
    assert spec.component == "com.example.app/.RouterActivity"
    assert spec.categories == (
        "android.intent.category.DEFAULT",
        "android.intent.category.BROWSABLE",
    )
    assert spec.raw_capture_source == "dumpsys_activity_full"
    assert spec.has_extras_marker is True


@pytest.mark.asyncio
async def test_capture_current_intent_specs_collects_three_activity_sources() -> None:
    backend = _FakeDeeplinkBackend(
        app="com.example.app",
        activity_outputs={
            "DeepLinkActivity": """
Hist #0: ActivityRecord{123 u0 com.example.app/.DeepLinkActivity t42}
  Intent { act=android.intent.action.VIEW dat=demo://from_activity cmp=com.example.app/.DeepLinkActivity }
""",
            "com.example.app": """
Hist #0: ActivityRecord{124 u0 com.example.app/.MainActivity t42}
  Intent { act=android.intent.action.VIEW dat=demo://from_package cmp=com.example.app/.MainActivity }
""",
            "*": """
Hist #0: ActivityRecord{125 u0 com.example.app/.FallbackActivity t42}
  Intent { act=android.intent.action.VIEW dat=demo://from_full cmp=com.example.app/.FallbackActivity }
""",
        },
    )

    specs = await _capture_current_intent_specs(
        backend,
        app="com.example.app",
        activity="com.example.app.DeepLinkActivity",
    )

    assert len(specs) == 3
    assert [spec.source for spec in specs] == [
        "dumpsys_activity_activity_grep",
        "dumpsys_activity_package_grep",
        "dumpsys_activity_full",
    ]
    assert {spec.data_uri for spec in specs} == {
        "demo://from_activity",
        "demo://from_package",
        "demo://from_full",
    }


def test_candidate_dedupe_normalizes_querystring_and_keeps_highest_confidence() -> None:
    candidates = _dedupe_candidates(
        [
            DeeplinkCandidate(
                uri="demo://order?a=1&b=2",
                kind="custom_scheme",
                package="com.example.app",
                action="android.intent.action.VIEW",
                confidence=0.5,
            ),
            DeeplinkCandidate(
                uri="demo://order?b=2&a=1",
                kind="custom_scheme",
                package="com.example.app",
                action="android.intent.action.VIEW",
                confidence=0.9,
                categories=("android.intent.category.DEFAULT",),
            ),
        ],
        limit=4,
    )

    assert len(candidates) == 1
    assert candidates[0].confidence == 0.9
    assert candidates[0].uri == "demo://order?a=1&b=2"


def test_weak_web_and_internal_candidates_need_resolution() -> None:
    assert not _candidate_is_probeable(DeeplinkCandidate(
        uri="https://example.com/orders",
        kind="web_link",
        package="com.example.app",
        confidence=0.5,
    ))
    assert not _candidate_is_probeable(DeeplinkCandidate(
        uri="content://com.example.app/orders",
        kind="internal_uri_intent",
        package="com.example.app",
        source="package_manifest_internal_uri",
        confidence=0.5,
    ))
    assert _candidate_is_probeable(DeeplinkCandidate(
        uri="content://com.example.app/orders",
        kind="internal_uri_intent",
        package="com.example.app",
        source="dumpsys_activity_full",
        confidence=0.5,
    ))
    assert _candidate_is_probeable(DeeplinkCandidate(
        uri="content://com.example.app/orders",
        kind="internal_uri_intent",
        package="com.example.app",
        source="package_manifest_internal_uri_resolved",
        confidence=0.5,
    ))


@pytest.mark.asyncio
async def test_deeplink_candidate_builder_falls_back_to_manifest_guess_when_no_capture_uri() -> None:
    backend = _FakeDeeplinkBackend(
        app="com.autonavi.minimap",
        package_output='Activity Resolver Table:\n  Scheme: "amapuri"\n',
    )

    candidates = await _build_candidates(
        backend,
        app="com.autonavi.minimap",
        task="open my orders",
        final_observation=None,
        limit=2,
    )

    assert candidates
    manifest_candidates = [
        candidate
        for candidate in candidates
        if candidate.source.startswith("package_manifest_")
    ]
    assert manifest_candidates
    assert any(
        candidate.kind == "manifest_scheme_host_path_guess"
        for candidate in manifest_candidates
    )
    manifest_candidate = next(candidate for candidate in candidates if candidate.source.startswith("package_manifest_"))
    raw_capture = dict(manifest_candidate.raw_capture)
    assert raw_capture["manifest_source"] == "package_dumpsys"
    assert raw_capture["generation_method"] in {"scheme_host_path", "guess_scheme"}


@pytest.mark.asyncio
async def test_deeplink_candidate_builder_falls_back_when_only_non_probeable_uri_candidates_exist(monkeypatch: Any) -> None:
    async def _fake_capture(
        _backend: Any,
        *,
        app: str,
        activity: str | None = None,
    ) -> tuple[CapturedIntentSpec, ...]:
        del app, activity
        return (
            CapturedIntentSpec(
                action="android.intent.action.VIEW",
                data_uri="content://example.app/internal",
                component=None,
                source="manifest_internal",
                raw_intent_line='Intent { act=android.intent.action.VIEW dat=content://example.app/internal }',
            ),
        )

    monkeypatch.setattr(
        "opengui.skills.deeplink._capture_current_intent_specs",
        _fake_capture,
    )
    monkeypatch.setattr(
        "opengui.skills.deeplink._candidate_is_probeable",
        lambda candidate: False if candidate.source == "manifest_internal" else _candidate_is_probeable(candidate),
    )

    backend = _FakeDeeplinkBackend(
        app="com.example.app",
        package_output="""
        Activity Resolver Table:
          Schemes:
              example:
                1234567 com.example.app/.Main filter 89abcde
                  Action: "android.intent.action.VIEW"
                  Category: "android.intent.category.DEFAULT"
                  Scheme: "example"
                  Authority: "example.app": -1
        """,
    )

    candidates = await _build_candidates(
        backend,
        app="com.example.app",
        task="open settings",
        final_observation=None,
        limit=6,
    )

    assert candidates
    assert any(candidate.source.startswith("package_manifest_") for candidate in candidates)


@pytest.mark.asyncio
async def test_deeplink_candidate_builder_falls_back_to_manifest_uri_candidates_by_priority() -> None:
    package_output = """
    Activity Resolver Table:
      Schemes:
          amapuri:
            1234567 com.autonavi.minimap/.RouterActivity filter 89abcde
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "amapuri"
          amapuri:
            2234567 com.autonavi.minimap/.RouterActivity filter 89abcde
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "amapuri"
          clock-app:
            3333333 com.google.android.deskclock/.DeskClock filter 89abcde
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "clock-app"
              Authority: "com.google.android.deskclock": -1
              Path: "PatternMatcher{LITERAL: /timer}"
    """
    backend = _FakeDeeplinkBackend(
        app="com.autonavi.minimap",
        package_output=package_output,
    )

    candidates = await _build_candidates(
        backend,
        app="com.autonavi.minimap",
        task="open timer",
        final_observation=None,
        limit=60,
    )

    assert candidates[0].source == "package_manifest_manifest_router"
    first_non_router = next(
        candidate for candidate in candidates if candidate.source != "package_manifest_manifest_router"
    )
    assert first_non_router.source == "package_manifest_manifest_exact_scheme_host_path"
    assert candidates[0].kind == "manifest_router"
    assert candidates[0].confidence == 0.65
    assert any(candidate.source == "package_manifest_manifest_exact_scheme_host_path" and candidate.confidence == 0.60 for candidate in candidates)
    assert candidates[-1].confidence <= 0.65
    assert any(candidate.source == "package_manifest_manifest_scheme_host_path_guess" for candidate in candidates)
    assert any(candidate.source == "package_manifest_manifest_guess_scheme_path" for candidate in candidates)


@pytest.mark.asyncio
async def test_deeplink_candidate_builder_falls_back_when_capture_has_only_component_only_intent() -> None:
    activity_dump = """
    Hist #0: ActivityRecord{123 u0 com.example.app/.SplashActivity t42}
      Intent { act=android.intent.action.MAIN cmp=com.example.app/.SplashActivity }
    """
    package_output = """
    Activity Resolver Table:
      Schemes:
          example:
            4567890 com.example.app/.Main filter 89abcde
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "example"
              Authority: "com.example.app": -1
              Path: "/orders"
    """
    backend = _FakeDeeplinkBackend(
        app="com.example.app",
        package_output=package_output,
        activity_outputs={"SplashActivity": activity_dump},
    )

    candidates = await _build_candidates(
        backend,
        app="com.example.app",
        task="open stopwatch",
        final_observation=None,
        limit=4,
    )

    assert candidates
    assert all(candidate.uri for candidate in candidates)
    assert all(candidate.kind != "captured_privileged_activity" for candidate in candidates)
    assert any("manifest_source" in dict(candidate.raw_capture) for candidate in candidates)


@pytest.mark.asyncio
async def test_deeplink_candidate_builder_does_not_resolve_manifest_guess() -> None:
    activity_dump = """
    Hist #0: ActivityRecord{123 u0 com.max.xiaoheihe/.RouterActivity t42}
      Intent { act=android.intent.action.VIEW dat=heybox://order cmp=com.max.xiaoheihe/.RouterActivity }
    """
    backend = _FakeDeeplinkBackend(
        app="com.max.xiaoheihe",
        package_output='Activity Resolver Table:\n  Scheme: "heybox"\n',
        activity_outputs={"max.xiaoheihe": activity_dump},
        resolve_outputs={
            "heybox://order": "com.max.xiaoheihe/.RouterActivity\n",
        },
    )

    candidates = await _build_candidates(
        backend,
        app="com.max.xiaoheihe",
        task="open my orders",
        final_observation=None,
        limit=4,
    )

    assert all(candidate.kind == "captured_intent" for candidate in candidates)
    assert not any("cmd package resolve-activity" in " ".join(call) for call in backend.run_calls)


def test_deeplink_contract_rejects_more_options_only_anchor() -> None:
    contract = _contract_from_observation(
        {
            "foreground_app": "com.google.android.deskclock",
            "extra": {
                "content_desc": ["More options"],
                "visible_text": [],
                "resource_ids": [],
                "ui_tree": [{"content_desc": "More options", "clickable": True}],
            },
        },
        app="com.google.android.deskclock",
        task="open stopwatch",
    )

    assert contract is None


@pytest.mark.asyncio
async def test_shortcut_intent_discovery_writes_open_intent_skill(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.google.android.documentsui",
                    "foreground_app": "com.google.android.documentsui",
                    "platform": "android",
                    "extra": {
                        "visible_text": ["Downloads"],
                        "content_desc": ["Downloads"],
                        "resource_ids": ["com.google.android.documentsui:id/dir_list"],
                    },
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    backend = _FakeDeeplinkBackend(
        app="com.google.android.documentsui",
        package_output="",
        verified_uris=set(),
        verified_intents={"android.provider.action.VIEW_DOWNLOADS"},
        resolve_outputs={
            "android.provider.action.VIEW_DOWNLOADS": "com.google.android.documentsui/.files.FilesActivity\n",
        },
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=backend,
        task="open downloads",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    compiled = compile_code_skills(source)
    open_actions = [action for action in backend.actions if action.action_type == "open_intent"]
    assert result.status == "processed_deeplink_code"
    assert open_actions
    assert open_actions[0].intent_action == "android.provider.action.VIEW_DOWNLOADS"
    assert compiled.skills[0].steps[0].action_type == "open_intent"
    assert "android.provider.action.VIEW_DOWNLOADS" in source


def test_code_for_verified_open_intent_candidate_includes_full_fixed_values() -> None:
    source = _code_for_verified_candidates(
        [
            DeeplinkCandidate(
                uri="",
                kind="shortcut_intent",
                package="com.example.app",
                action="android.intent.action.INSERT",
                mime_type="vnd.example.contact",
                categories=(
                    "android.intent.category.DEFAULT",
                    "android.intent.category.BROWSABLE",
                ),
                extras=(("source", "contacts"), ("mode", "quick")),
                source="shortcut_profile_contact_insert",
                confidence=0.9,
                component="com.example.app/.ContactInsertActivity",
                verified_package="com.google.android.contacts",
                verified_component="com.google.android.contacts/.ContactInsertActivity",
                verified_action_type="open_intent",
            ),
        ],
        app="com.example.app",
        task="open contact insert",
        contract={
            "anchor": {"app_package": "com.google.android.contacts"},
            "signature": {
                "required": [{"selector": {"text": "Contacts"}, "state": ["visible"]}],
                "forbidden": [],
            },
        },
    )

    assert "'intent_action': 'android.intent.action.INSERT'" in source
    assert "'categories': ['android.intent.category.DEFAULT', 'android.intent.category.BROWSABLE']" in source
    assert "'mime_type': 'vnd.example.contact'" in source
    assert "'extras': {'source': 'contacts', 'mode': 'quick'}" in source
    assert "'component': 'com.google.android.contacts/.ContactInsertActivity'" in source
    assert "'package': 'com.google.android.contacts'" in source


@pytest.mark.asyncio
async def test_clock_timer_shortcut_intent_writes_open_intent_skill(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.google.android.deskclock",
                    "foreground_app": "com.google.android.deskclock",
                    "platform": "android",
                    "extra": {
                        "visible_text": ["Timer", "00h 00m 00s"],
                        "content_desc": ["Timer"],
                        "resource_ids": ["com.google.android.deskclock:id/timer_setup_digit_1"],
                    },
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    backend = _FakeDeeplinkBackend(
        app="com.google.android.deskclock",
        package_output="",
        verified_uris=set(),
        verified_intents={"android.intent.action.SHOW_TIMERS"},
        resolve_outputs={
            "android.intent.action.SHOW_TIMERS": (
                "com.google.android.deskclock/com.android.deskclock.HandleApiCalls\n"
            ),
        },
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=backend,
        task="open timer",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    compiled = compile_code_skills(source)
    open_actions = [action for action in backend.actions if action.action_type == "open_intent"]
    assert result.status == "processed_deeplink_code"
    assert result.candidates[0].kind == "shortcut_intent"
    assert result.candidates[0].source == "shortcut_profile_clock_show_timers_resolved"
    assert result.compiled_skill_ids[0].startswith("intent:com.google.android.deskclock:")
    assert open_actions[0].intent_action == "android.intent.action.SHOW_TIMERS"
    assert compiled.skills[0].steps[0].action_type == "open_intent"
    assert "android.intent.action.SHOW_TIMERS" in source
    assert "shortcut_profile_clock_show_timers_resolved" in source


@pytest.mark.asyncio
async def test_contact_shortcut_intent_maps_dialer_entry_to_contacts_insert(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.google.android.dialer",
                    "foreground_app": "com.google.android.dialer",
                    "platform": "android",
                    "extra": {
                        "visible_text": ["Hugo Pereira", "saved"],
                        "content_desc": ["Contacts"],
                        "resource_ids": ["com.google.android.dialer:id/contact_name"],
                    },
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    backend = _FakeDeeplinkBackend(
        app="com.google.android.dialer",
        package_output="",
        verified_uris=set(),
        verified_intents={"android.intent.action.INSERT"},
        resolve_outputs={
            "android.intent.action.INSERT": (
                "com.google.android.contacts/"
                "com.google.android.apps.contacts.editor.ContactEditorActivity\n"
            ),
        },
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=backend,
        task="Create a new contact for Hugo Pereira.",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    compiled = compile_code_skills(source)
    open_actions = [action for action in backend.actions if action.action_type == "open_intent"]
    assert result.status == "processed_deeplink_code"
    assert result.app == "com.google.android.dialer"
    assert result.contract["anchor"]["app_package"] == "com.google.android.contacts"
    assert result.candidates[0].component == (
        "com.google.android.contacts/"
        "com.google.android.apps.contacts.editor.ContactEditorActivity"
    )
    assert open_actions[0].package == "com.google.android.contacts"
    assert compiled.skills[0].app == "com.google.android.contacts"
    assert compiled.skills[0].steps[0].action_type == "open_intent"


@pytest.mark.asyncio
async def test_internal_uri_intent_discovery_writes_open_intent_skill(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.example.clock",
                    "foreground_app": "com.example.clock",
                    "platform": "android",
                    "extra": {
                        "visible_text": ["My Orders", "Recent purchases"],
                        "content_desc": ["My Orders"],
                        "resource_ids": ["com.example.app:id/orders_title"],
                    },
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    package_output = """
    Activity Resolver Table:
      Schemes:
          internal:
            1234567 com.example.clock/.HandleUris filter 89abcde
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Scheme: "internal"
              Authority: "example": -1
    """
    backend = _FakeDeeplinkBackend(
        app="com.example.clock",
        package_output=package_output,
        verified_uris={"internal://example"},
        resolve_outputs={
            "internal://example": "com.example.clock/.HandleUris\n",
        },
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=backend,
        task="open internal page",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    compiled = compile_code_skills(source)
    open_actions = [action for action in backend.actions if action.action_type == "open_intent"]
    assert result.status == "processed_deeplink_code"
    assert result.candidates[0].kind == "internal_uri_intent"
    assert result.compiled_skill_ids[0].startswith("internal_uri_intent:com.example.clock:")
    assert open_actions[0].intent_action == "android.intent.action.VIEW"
    assert open_actions[0].text == "internal://example"
    assert compiled.skills[0].skill_id.startswith("internal_uri_intent:com.example.clock:")
    assert compiled.skills[0].steps[0].action_type == "open_intent"
    assert "open_internal_uri_intent_com_example_clock" in source
    assert "'text': 'internal://example'" in source
    assert "'intent_action': 'android.intent.action.VIEW'" in source


@pytest.mark.asyncio
async def test_shortcut_intent_candidates_drop_manifest_uri_noise() -> None:
    package_output = """
    Activity Resolver Table:
      Schemes:
          content:
            1111111 com.google.android.contacts/.PeopleActivity filter 2222222
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "content"
              Authority: "com.android.contacts": -1
              Path: "PatternMatcher{LITERAL: /contacts}"
          contacts:
            3333333 com.google.android.contacts/.PeopleActivity filter 4444444
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "contacts"
              Authority: "people": -1
              Path: "PatternMatcher{LITERAL: /list}"
    """
    backend = _FakeDeeplinkBackend(
        app="com.google.android.contacts",
        package_output=package_output,
    )

    candidates = await _build_candidates(
        backend,
        app="com.google.android.contacts",
        task="Create a new contact for Hugo Pereira",
        final_observation=None,
        limit=3,
    )

    assert candidates[0].kind == "shortcut_intent"
    assert candidates[0].package == "com.google.android.contacts"
    assert candidates[0].action == "android.intent.action.INSERT"
    assert candidates[0].mime_type == "vnd.android.cursor.dir/contact"
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_deeplink_candidate_builder_uses_only_captured_page_intent() -> None:
    activity_dump = """
    Hist #0: ActivityRecord{123 u0 com.max.xiaoheihe/.RouterActivity t42}
      Intent { act=android.intent.action.VIEW dat=hblink://universal/mall/order cmp=com.max.xiaoheihe/.RouterActivity }
    """
    package_output = """
    Activity Resolver Table:
      Schemes:
          heybox:
            1111111 com.max.xiaoheihe/.getui.GeTuiPushActivity filter 2222222
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "heybox"
              Authority: "c.xiaoheihe.cn": -1
              Path: "PatternMatcher{LITERAL: /getuipush}"
            3333333 com.max.xiaoheihe/.RouterActivity filter 4444444
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "heybox"
    """
    backend = _FakeDeeplinkBackend(
        app="com.max.xiaoheihe",
        package_output=package_output,
        activity_outputs={"RouterActivity": activity_dump},
    )

    candidates = await _build_candidates(
        backend,
        app="com.max.xiaoheihe",
        task="open my orders",
        final_observation={"activity_class": "com.max.xiaoheihe.RouterActivity"},
        limit=3,
    )

    assert len(candidates) == 1
    assert candidates[0].uri == "hblink://universal/mall/order"
    assert candidates[0].kind == "captured_intent"
    assert candidates[0].component == "com.max.xiaoheihe/.RouterActivity"
    assert candidates[0].source == "dumpsys_activity_activity_grep"


@pytest.mark.asyncio
async def test_deeplink_discovery_verifies_captured_page_intent_only(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.max.xiaoheihe",
                    "foreground_app": "com.max.xiaoheihe",
                    "platform": "android",
                    "activity_class": "com.max.xiaoheihe.RouterActivity",
                    "extra": {
                        "visible_text": ["My Orders", "Recent purchases"],
                        "content_desc": ["My Orders"],
                    },
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    activity_dump = """
    Hist #0: ActivityRecord{123 u0 com.max.xiaoheihe/.RouterActivity t42}
      Intent { act=android.intent.action.VIEW dat=hblink://universal/mall/order cmp=com.max.xiaoheihe/.RouterActivity }
    """
    package_output = """
    Activity Resolver Table:
      Schemes:
          heybox:
            3333333 com.max.xiaoheihe/.RouterActivity filter 4444444
              Action: "android.intent.action.VIEW"
              Category: "android.intent.category.DEFAULT"
              Category: "android.intent.category.BROWSABLE"
              Scheme: "heybox"
    """
    expected = "hblink://universal/mall/order"
    backend = _FakeDeeplinkBackend(
        app="com.max.xiaoheihe",
        package_output=package_output,
        activity_outputs={"RouterActivity": activity_dump},
        verified_uris={expected},
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=backend,
        task="open my orders",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    open_actions = [action for action in backend.actions if action.action_type == "open_deeplink"]
    assert result.status == "processed_deeplink_code"
    assert any(candidate.uri == expected and candidate.matched for candidate in result.candidates)
    assert any(action.text == expected and action.component is None for action in open_actions)
    assert f"'text': '{expected}'" in source
    assert "'package': 'com.max.xiaoheihe'" in source
    assert "'component': 'com.max.xiaoheihe/.RouterActivity'" not in source


@pytest.mark.asyncio
async def test_deeplink_candidate_builder_does_not_publish_component_only_intent() -> None:
    activity_dump = """
    Hist #0: ActivityRecord{123 u0 com.example.app/.RouterActivity t42}
      Intent { act=android.intent.action.MAIN cmp=com.example.app/.RouterActivity }
    """
    backend = _FakeDeeplinkBackend(
        package_output="",
        activity_outputs={"RouterActivity": activity_dump, "*": activity_dump},
    )

    candidates = await _build_candidates(
        backend,
        app="com.example.app",
        task="open my orders",
        final_observation={"activity_class": "com.example.app.RouterActivity"},
        limit=6,
    )

    assert candidates
    assert any(candidate.kind == "captured_privileged_activity" for candidate in candidates)
    assert any(candidate.source.startswith("package_manifest_") for candidate in candidates)


@pytest.mark.asyncio
async def test_deeplink_discovery_classifies_security_launch_errors(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"visible_text": ["My Orders"]},
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    backend = _FakeDeeplinkBackend(
        launch_errors={
            "demo://order": RuntimeError("SecurityException: Permission Denial"),
            "demo://order?tab=all": RuntimeError("SecurityException: Permission Denial"),
        },
    )

    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=backend,
        task="open my orders",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    assert result.status == "no_candidate"
    assert result.reason == "no_verified_deeplink"
    assert any(candidate.status == "launch_error_security" for candidate in result.candidates)
    assert any(candidate.launch_error_type == "launch_error_security" for candidate in result.candidates)


@pytest.mark.asyncio
async def test_deeplink_discovery_does_not_emit_code_for_unverified_candidates(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "visible_text": ["My Orders", "Recent purchases"],
                        "content_desc": ["My Orders"],
                        "resource_ids": ["com.example.app:id/orders_title"],
                    },
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=_FakeDeeplinkBackend(
            verified_uris=set(),
            package_output='Activity Resolver Table:\n  Scheme: "hello"\n',
        ),
        task="open my orders",
        platform="android",
        is_success=True,
        store_root=tmp_path / "store",
    )

    assert result.status == "no_candidate"
    assert result.reason == "no_verified_deeplink"
    assert not (tmp_path / "store" / "skill_graph_code.py").exists()


@pytest.mark.asyncio
async def test_deeplink_probe_retries_security_failure_without_component(tmp_path: Path) -> None:
    backend = _ScriptedProbeBackend(
        execute_plan=[
            RuntimeError("SecurityException: Permission Denial"),
            RuntimeError("SecurityException: Permission Denial"),
            None,
        ],
        verified_attempts={3},
    )
    contract = {
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [{"selector": {"text": "My Orders"}, "state": ["visible"]}],
            "forbidden": [],
        },
    }

    record = await _probe_candidate(
        backend,
        DeeplinkCandidate(
            uri="demo://order",
            kind="captured_intent",
            package="com.example.app",
            component="com.example.app/.UnexportedActivity",
            source="test",
            confidence=0.9,
        ),
        contract=contract,
        screenshot_path=tmp_path / "probe.png",
        settle_seconds=0.0,
    )

    open_actions = [action for action in backend.actions if action.action_type == "open_deeplink"]
    assert record.status == "target_verified"
    assert record.component is None
    assert [entry["component"] for entry in record.probe_plan] == [
        None,
        "com.example.app/.UnexportedActivity",
        None,
    ]
    assert [entry["status"] for entry in record.probe_plan] == [
        "launch_error_security",
        "launch_error_security",
        "target_verified",
    ]


@pytest.mark.asyncio
async def test_deeplink_probe_retries_activity_not_found_with_implicit_package(tmp_path: Path) -> None:
    backend = _ScriptedProbeBackend(
        execute_plan=[
            RuntimeError("ActivityNotFoundException: No activity found to handle Intent"),
            None,
        ],
        verified_attempts={2},
    )
    contract = {
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [{"selector": {"text": "My Orders"}, "state": ["visible"]}],
            "forbidden": [],
        },
    }

    record = await _probe_candidate(
        backend,
        DeeplinkCandidate(
            uri="demo://order",
            kind="captured_intent",
            package="com.example.app",
            source="test",
            confidence=0.9,
        ),
        contract=contract,
        screenshot_path=tmp_path / "probe.png",
        settle_seconds=0.0,
    )

    assert record.status == "target_verified"
    assert record.launch_error_type is None
    assert record.probe_plan[0]["status"] == "launch_error_activity_not_found"
    assert record.probe_plan[1]["status"] == "target_verified"
    assert record.probe_plan[1]["package"] is None


@pytest.mark.asyncio
async def test_deeplink_probe_records_verified_browser_redirect_variant(tmp_path: Path) -> None:
    backend = _FakeDeeplinkBackend(
        verified_uris={"https://example.com/order"},
        launch_outputs={
            "https://example.com/order": "Starting: Intent {}\n[opengui_launch_variant=browser_redirect]",
        },
    )
    contract = {
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [{"selector": {"text": "My Orders"}, "state": ["visible"]}],
            "forbidden": [],
        },
    }
    candidate = DeeplinkCandidate(
        uri="https://example.com/order",
        kind="captured_intent",
        package="com.example.app",
        source="test",
        confidence=0.9,
    )

    record = await _probe_candidate(
        backend,
        candidate,
        contract=contract,
        screenshot_path=tmp_path / "probe_redirect.png",
        settle_seconds=0.0,
    )
    verified_candidate = _candidate_for_probe_record(candidate, record)
    source = _code_for_verified_candidates(
        [verified_candidate],
        app="com.example.app",
        task="open my orders",
        contract=contract,
    )

    assert record.status == "target_verified"
    assert record.launch_variant == "browser_redirect"
    assert record.probe_plan[0]["launch_variant"] == "browser_redirect"
    assert verified_candidate.verified_package is None
    assert "verified_launch_variant" in source
    assert "fixed_values={'text': 'https://example.com/order'}" in source


@pytest.mark.asyncio
async def test_deeplink_probe_keeps_unverified_browser_redirect_out_of_codegen(tmp_path: Path) -> None:
    backend = _FakeDeeplinkBackend(
        verified_uris=set(),
        launch_outputs={
            "https://example.com/order": "Starting: Intent {}\n[opengui_launch_variant=browser_redirect]",
        },
    )
    contract = {
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [{"selector": {"text": "My Orders"}, "state": ["visible"]}],
            "forbidden": [],
        },
    }

    record = await _probe_candidate(
        backend,
        DeeplinkCandidate(
            uri="https://example.com/order",
            kind="captured_intent",
            package="com.example.app",
            source="test",
            confidence=0.9,
        ),
        contract=contract,
        screenshot_path=tmp_path / "probe_redirect_unverified.png",
        settle_seconds=0.0,
    )

    assert record.matched is False
    assert record.launch_variant == "browser_redirect"
    assert record.probe_plan[0]["launch_variant"] == "browser_redirect"
    assert record.status in {"contract_mismatch", "redirect_unverified"}


@pytest.mark.asyncio
async def test_deeplink_probe_detects_wrong_app_navigation_state(tmp_path: Path) -> None:
    activity_state = """
    ACTIVITY MANAGER ACTIVITIES (dumpsys activity activities)
    TASK com.example.app id=1
      Hist #0: ActivityRecord{111 u0 com.other/.WrongApp t1}
        Intent { flg=0x10800000 }
    """
    backend = _ScriptedProbeBackend(
        execute_plan=[None, None],
        verified_attempts={1, 2},
        activity_state=activity_state,
    )
    contract = {
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [{"selector": {"text": "My Orders"}, "state": ["visible"]}],
            "forbidden": [],
        },
    }

    record = await _probe_candidate(
        backend,
        DeeplinkCandidate(
            uri="demo://order",
            kind="captured_intent",
            package="com.example.app",
            source="test",
            confidence=0.9,
        ),
        contract=contract,
        screenshot_path=tmp_path / "probe_wrong_app.png",
        settle_seconds=0.0,
    )

    assert record.status == "wrong_app"
    assert all(entry["status"] == "wrong_app" for entry in record.probe_plan)
    assert record.launch_error_type is None
    assert [entry["package"] for entry in record.probe_plan] == ["com.example.app", None]


@pytest.mark.asyncio
async def test_deeplink_probe_distinguishes_launch_error_and_contract_mismatch(tmp_path: Path) -> None:
    backend = _ScriptedProbeBackend(
        execute_plan=[
            RuntimeError("SecurityException: Permission Denial"),
            None,
        ],
        verified_attempts=set(),
    )
    contract = {
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [{"selector": {"text": "My Orders"}, "state": ["visible"]}],
            "forbidden": [],
        },
    }

    record = await _probe_candidate(
        backend,
        DeeplinkCandidate(
            uri="demo://order",
            kind="captured_intent",
            package="com.example.app",
            source="test",
            confidence=0.9,
        ),
        contract=contract,
        screenshot_path=tmp_path / "probe_mismatch.png",
        settle_seconds=0.0,
    )

    assert record.status == "contract_mismatch"
    assert record.probe_plan[0]["status"] == "launch_error_security"
    assert record.probe_plan[1]["status"] == "contract_mismatch"


@pytest.mark.asyncio
async def test_postrun_deeplink_switch_can_run_without_linear_extraction(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "done"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"visible_text": ["My Orders"]},
                },
            },
            {"type": "result", "success": True, "total_steps": 1, "error": None},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=False,
        enable_deeplink_skill_extraction=True,
        deeplink_probe_backend=_FakeDeeplinkBackend(),
    )

    result = await processor._extract_deeplink_skill(
        trace_path,
        is_success=True,
        platform="android",
        task="open my orders",
    )

    extraction_result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert result is not None
    assert result["status"] == "processed_deeplink_code"
    assert extraction_result["status"] == "processed_deeplink_code"
    assert extraction_result["deeplink"]["status"] == "processed_deeplink_code"
    assert extraction_result["compiled_skill_ids"]


@pytest.mark.asyncio
async def test_postrun_code_first_reports_compile_error(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [{"type": "step", "action": {"action_type": "tap"}}])
    processor = PostRunProcessor(
        llm=_ScriptedLLM([_wrapped_code("import os\n")]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    skill_id = await processor._extract_skill(trace_path, is_success=True, platform="android")

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert skill_id is None
    assert result["status"] == "code_compile_error"
    assert result["attempts"][0]["errors"]


@pytest.mark.asyncio
async def test_postrun_repairs_text_contract_from_ui_tree_resource_id(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "ui_tree": [
                            {
                                "text": "Orders",
                                "resource_id": "com.example:id/nav_orders",
                                "clickable": True,
                                "bounds": "[0,0][120,120]",
                            }
                        ],
                    },
                },
            },
            {
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "tap", "target": "Orders"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"visible_text": ["All orders", "Success orders"]},
                },
            },
            {"type": "result", "success": True},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([_wrapped_code(_text_only_skill_source())]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    graph = SkillGraphStore(store_dir=tmp_path / "store")

    assert "resource_id='com.example:id/nav_orders'" in source
    assert result["contract_quality"]["quality"] == "canonical"
    assert result["contract_quality"]["canonical_node_count"] >= 1
    assert result["contract_quality"]["repaired_steps"][0]["selector"]["resource_id"] == "com.example:id/nav_orders"
    assert result["contract_quality"]["graph_projection"]["quality"] == "canonical"
    assert graph.count_nodes >= 1
    assert graph.count_edges >= 1


def test_contract_repair_replaces_screenshot_guessed_resource_id_with_ui_tree_evidence() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["orders"])
async def open_orders(device):
    await action(
        "tap",
        target="Orders",
        state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/from_screenshot", clickable=True)]),
    )
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Orders"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Orders",
                            "resource_id": "com.example:id/nav_orders",
                            "clickable": True,
                        }
                    ],
                },
            },
        }
    ]

    repaired = repair_code_contracts_from_events(source, events)

    assert "from_screenshot" not in repaired.source
    assert "com.example:id/nav_orders" in repaired.source


def test_contract_repair_uses_coordinate_static_selector_without_clickable_flag() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.travel", platform="android", tags=["hotel"])
async def open_hotels(device):
    await action("tap", target="Hotel")
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "wait"},
            "observation": {
                "foreground_app": "com.example.travel",
                "platform": "android",
                "screen_width": 488,
                "screen_height": 1080,
                "extra": {
                    "ui_tree": [
                        {
                            "content_desc": "Hotel",
                            "resource_id": "com.example.travel:id/home_grid_hotel_widget",
                            "enabled": True,
                            "bounds": "[36,274][225,440]",
                        }
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 126.0, "y": 152.0, "relative": True},
            "model_output": '点击 "Hotel"',
            "observation": {
                "foreground_app": "com.example.travel",
                "platform": "android",
                "extra": {"ui_tree": []},
            },
        },
    ]

    repaired = repair_code_contracts_from_events(source, events)

    assert "home_grid_hotel_widget" in repaired.source
    assert "enabled=True" in repaired.source
    assert "clickable=True" not in repaired.source
    assert repaired.report["quality"] == "canonical"


def test_contract_repair_reads_cli_prompt_observation_for_precondition() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.travel", platform="android", tags=["hotel"])
async def open_hotels(device):
    await action("tap", target="酒店")
'''
    events = [
        {
            "event": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 123.0, "y": 137.0, "relative": True},
            "prompt": {
                "current_observation": {
                    "foreground_app": "com.example.travel",
                    "platform": "android",
                    "screen_width": 496,
                    "screen_height": 1080,
                    "extra": {
                        "ui_tree": [
                            {
                                "content_desc": "酒店",
                                "resource_id": "com.example.travel:id/home_grid_hotel_widget",
                                "clickable": True,
                                "enabled": True,
                                "bounds": "[42,324][296,547]",
                            }
                        ],
                    },
                },
            },
            "execution": {
                "next_observation": {
                    "foreground_app": "com.example.travel",
                    "platform": "android",
                    "extra": {"ui_tree": []},
                },
            },
        },
    ]

    repaired = repair_code_contracts_from_events(source, events)

    assert "home_grid_hotel_widget" in repaired.source
    assert repaired.report["quality"] == "canonical"


def test_contract_repair_treats_focused_text_edit_as_canonical_input_identity() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.travel", platform="android", tags=["hotel"])
async def enter_destination(device, destination: str):
    await action("input_text", target="位置/品牌/酒店", text=destination, auto_enter=True)
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "input_text", "text": "深圳北站", "auto_enter": True},
            "pre_observation": {
                "foreground_app": "com.example.travel",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "位置/品牌/酒店",
                            "class": "android.widget.EditText",
                            "clickable": True,
                            "focused": True,
                            "enabled": True,
                        }
                    ],
                },
            },
            "observation": {
                "foreground_app": "com.example.travel",
                "platform": "android",
                "extra": {"ui_tree": []},
            },
        },
    ]

    repaired = repair_code_contracts_from_events(source, events)

    assert "class_='android.widget.EditText'" in repaired.source
    assert "focused=True" not in repaired.source
    assert repaired.report["quality"] == "canonical"


def test_contract_repair_targets_timer_digit_instead_of_page_anchor() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.deskclock", platform="android", tags=["timer"])
async def tap_timer_digit_one(device):
    await action(
        "tap",
        target="1",
        state_contract=C(
            app="com.google.android.deskclock",
            required=[
                R(text="1", visible=True),
                R(text="2", visible=True),
                R(content_desc="More options", visible=True),
            ],
        ),
    )
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "1", "x": 260, "y": 810},
            "pre_observation": {
                "foreground_app": "com.google.android.deskclock",
                "platform": "android",
                "screen_width": 1080,
                "screen_height": 1920,
                "extra": {
                    "ui_tree": [
                        {
                            "text": "1",
                            "resource_id": "com.google.android.deskclock:id/timer_setup_digit_1",
                            "class": "android.widget.Button",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[120,680][400,960]",
                        },
                        {"text": "2", "bounds": "[420,680][700,960]"},
                        {"content_desc": "More options", "clickable": True},
                    ],
                },
            },
            "observation": {
                "foreground_app": "com.google.android.deskclock",
                "platform": "android",
                "extra": {"ui_tree": []},
            },
        }
    ]

    repaired = repair_code_contracts_from_events(source, events)
    compiled = compile_code_skills(repaired.source)
    required = compiled.skills[0].steps[0].state_contract["signature"]["required"]

    assert required[0]["selector"] == {
        "resource_id": "com.google.android.deskclock:id/timer_setup_digit_1"
    }
    assert set(required[0]["state"]) == {"visible", "enabled", "clickable"}
    assert "More options" not in repaired.source
    assert repaired.report["target_selector_repaired_steps"][0]["step_index"] == 0
    assert repaired.report["page_anchor_downgraded_steps"][0]["step_index"] == 0
    assert repaired.report["multi_required_action_contract_reduced_steps"][0]["step_index"] == 0


def test_contract_repair_reduces_page_text_anchors_to_action_target_text() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.deskclock", platform="android", tags=["stopwatch"])
async def run_stopwatch(device):
    await action(
        "tap",
        target="Start",
        state_contract=C(
            app="com.google.android.deskclock",
            required=[
                R(text="Alarm", visible=True),
                R(text="More options", visible=True),
                R(text="Start", visible=True),
            ],
        ),
    )
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Start"},
            "pre_observation": {
                "foreground_app": "com.google.android.deskclock",
                "platform": "android",
                "extra": {"visible_text": ["Alarm", "More options", "Start"]},
            },
            "observation": {
                "foreground_app": "com.google.android.deskclock",
                "platform": "android",
                "extra": {"ui_tree": []},
            },
        }
    ]

    repaired = repair_code_contracts_from_events(source, events)
    compiled = compile_code_skills(repaired.source)
    required = compiled.skills[0].steps[0].state_contract["signature"]["required"]

    assert required == [{"selector": {"text": "Start"}, "state": ["visible"]}]
    assert "Alarm" not in repaired.source
    assert "More options" not in repaired.source
    assert repaired.report["background_anchor_dropped_steps"][0]["step_index"] == 0


def test_contract_repair_reduces_contact_field_contract_to_target_element() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.contacts", platform="android", tags=["contact"])
async def create_contact(device):
    await action(
        "tap",
        target="First name",
        state_contract=C(
            app="com.google.android.contacts",
            required=[
                R(text="Cancel", visible=True),
                R(text="First name", visible=True),
                R(text="Save", visible=True),
            ],
        ),
    )
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "First name"},
            "pre_observation": {
                "foreground_app": "com.google.android.contacts",
                "platform": "android",
                "extra": {"visible_text": ["Cancel", "First name", "Save"]},
            },
            "observation": {
                "foreground_app": "com.google.android.contacts",
                "platform": "android",
                "extra": {"ui_tree": []},
            },
        }
    ]

    repaired = repair_code_contracts_from_events(source, events)
    compiled = compile_code_skills(repaired.source)
    required = compiled.skills[0].steps[0].state_contract["signature"]["required"]

    assert required == [{"selector": {"text": "First name"}, "state": ["visible"]}]
    assert "Cancel" not in repaired.source
    assert "Save" not in repaired.source


def test_contract_repair_does_not_generate_page_contract_when_target_selector_missing() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.app", platform="android", tags=["example"])
async def tap_unknown(device):
    await action("tap", target="Missing")
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Missing"},
            "pre_observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {"visible_text": ["Alarm", "More options", "Save"]},
            },
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {"ui_tree": []},
            },
        }
    ]

    repaired = repair_code_contracts_from_events(source, events)

    assert "Alarm" not in repaired.source
    assert "More options" not in repaired.source
    assert "Save" not in repaired.source
    assert repaired.report["no_target_selector_steps"][0]["step_index"] == 0


def test_contract_repair_strips_dynamic_input_text_when_field_has_resource_id() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.search", platform="android", tags=["search"])
async def search_example(device, query: str):
    await action(
        "input_text",
        target="Search",
        text=query,
        state_contract=C(
            app="com.example.search",
            required=[
                R(
                    resource_id="com.example.search:id/search_src_text",
                    text="old query",
                    class_="android.widget.EditText",
                    visible=True,
                    focused=True,
                )
            ],
        ),
    )
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "input_text", "text": "new query"},
            "pre_observation": {
                "foreground_app": "com.example.search",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "old query",
                            "resource_id": "com.example.search:id/search_src_text",
                            "class": "android.widget.EditText",
                            "focused": True,
                            "enabled": True,
                        }
                    ],
                },
            },
            "observation": {
                "foreground_app": "com.example.search",
                "platform": "android",
                "extra": {"ui_tree": []},
            },
        }
    ]

    repaired = repair_code_contracts_from_events(source, events)
    compiled = compile_code_skills(repaired.source)
    selector = compiled.skills[0].steps[0].state_contract["signature"]["required"][0]["selector"]

    assert selector == {
        "resource_id": "com.example.search:id/search_src_text",
        "class": "android.widget.EditText",
    }
    assert "old query" not in repaired.source
    assert repaired.report["dynamic_target_text_stripped_steps"][0]["step_index"] == 0


def test_contract_repair_does_not_anchor_parameter_target_text() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.search", platform="android", tags=["search"])
async def open_search_result(device, query: str):
    await action(
        "tap",
        target="{{query}}",
        state_contract=C(
            app="com.example.search",
            required=[
                R(text="{{query}}", visible=True, clickable=True),
                R(content_desc="More options", visible=True),
            ],
        ),
    )
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "weather", "x": 100, "y": 120},
            "pre_observation": {
                "foreground_app": "com.example.search",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "weather",
                            "resource_id": "com.example.search:id/search_result_button",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[20,80][260,180]",
                        },
                        {"content_desc": "More options"},
                    ],
                },
            },
            "observation": {
                "foreground_app": "com.example.search",
                "platform": "android",
                "extra": {"ui_tree": []},
            },
        }
    ]

    repaired = repair_code_contracts_from_events(source, events)
    compiled = compile_code_skills(repaired.source)
    selector = compiled.skills[0].steps[0].state_contract["signature"]["required"][0]["selector"]

    assert selector == {"resource_id": "com.example.search:id/search_result_button"}
    assert "text='{{query}}'" not in repaired.source


def test_contract_filter_drops_functions_with_weak_steps() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def strong(device):
    await action("tap", target="Orders", state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/orders", visible=True, enabled=True)]))

@skill(app="com.example.app", platform="android")
async def weak(device):
    await action("tap", target="Orders")
'''

    filtered = filter_code_to_contract_complete(source)
    compiled = compile_code_skills(filtered.source)

    assert compiled.errors == []
    assert [skill.name for skill in compiled.skills] == ["strong"]
    assert filtered.removed_functions == ("weak",)
    assert filtered.report["quality"] == "canonical"


def test_contract_filter_trims_weak_suffix_instead_of_dropping_prefix() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def open_orders_prefix(device):
    await action("open_app", target="com.example.app")
    await action("tap", target="Orders", state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/orders", visible=True, enabled=True)]))
    await action("swipe", target="page", state_contract=C(app="com.example.app", required=[R(text="More")]))
    await action("tap", target="AfterWeak", state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/after", visible=True, enabled=True)]))
'''

    filtered = filter_code_to_contract_complete(source)
    compiled = compile_code_skills(filtered.source)

    assert compiled.errors == []
    assert [skill.name for skill in compiled.skills] == ["open_orders_prefix"]
    assert [step.action_type for step in compiled.skills[0].steps] == ["open_app", "tap"]
    assert filtered.removed_functions == ()
    assert filtered.report["quality"] == "canonical"
    assert filtered.report["trimmed_functions"] == ["open_orders_prefix"]
    assert "AfterWeak" not in filtered.source


def test_entrypoint_normalization_adds_open_app_after_app_change_segment() -> None:
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Files"},
            "observation": {
                "foreground_app": "com.google.android.apps.nexuslauncher",
                "extra": {"visible_text": ["Files"]},
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "target": "Downloads"},
            "observation": {
                "foreground_app": "com.google.android.documentsui",
                "extra": {"visible_text": ["Downloads"]},
            },
        },
    ]
    segments = TraceSegmenter(max_reusable_actions=10).segment(events)
    assert len(segments) == 2
    assert segments[1].reason == "app_changed"

    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.documentsui", platform="android")
async def open_downloads(device):
    await action("tap", target="Downloads", state_contract=C(app="com.google.android.documentsui", required=[R(content_desc="Downloads", visible=True, clickable=True)]))
'''

    filtered = filter_code_to_contract_complete(source)
    normalized = normalize_code_skill_entrypoints(filtered.source)
    compiled = compile_code_skills(normalized.source)

    assert compiled.errors == []
    skill = compiled.skills[0]
    assert [step.action_type for step in skill.steps] == ["open_app", "tap"]
    assert skill.steps[0].target == "com.google.android.documentsui"
    assert normalized.report["entrypoint_normalized_functions"] == ["open_downloads"]


def test_entrypoint_normalization_keeps_deeplink_as_entrypoint() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def open_orders(device):
    await action("open_deeplink", target="example://orders", fixed=True, fixed_values={"text": "example://orders"}, state_contract=C(app="com.example.app", required=[R(text="Orders", visible=True)]))
    await action("tap", target="Orders", state_contract=C(app="com.example.app", required=[R(text="Orders", visible=True, clickable=True)]))
'''

    normalized = normalize_code_skill_entrypoints(source)
    compiled = compile_code_skills(normalized.source)

    assert compiled.errors == []
    assert [step.action_type for step in compiled.skills[0].steps] == ["open_deeplink", "tap"]
    assert normalized.report["entrypoint_normalized_functions"] == []
    assert normalized.source.count("open_app") == 0


def test_entrypoint_normalization_does_not_open_launcher_package() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.apps.nexuslauncher", platform="android")
async def open_app_drawer_for_clock(device):
    await action("swipe", target="screen", state_contract=C(app="com.google.android.apps.nexuslauncher", required=[R(visible=True)]))
'''

    normalized = normalize_code_skill_entrypoints(source)
    compiled = compile_code_skills(normalized.source)

    assert compiled.errors == []
    assert [step.action_type for step in compiled.skills[0].steps] == ["swipe"]
    assert normalized.report["entrypoint_normalized_functions"] == []
    assert "await action('open_app'" not in normalized.source


def test_code_skill_repository_does_not_index_launcher_package_skills(tmp_path: Path) -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.apps.nexuslauncher", platform="android")
async def open_app_drawer_for_clock(device):
    await action("swipe", target="screen", state_contract=C(app="com.google.android.apps.nexuslauncher", required=[R(visible=True)]))
'''

    repository = CodeSkillRepository(tmp_path)
    update = repository.add_code(source)

    assert update.errors == ()
    assert update.skills == ()
    assert repository.list_all(platform="android") == []


def test_entrypoint_normalization_strips_open_app_state_contract() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def open_orders(device):
    await action("open_app", target="com.example.app", state_contract=C(app="com.example.app", required=[R(text="Orders", visible=True)]))
    await action("tap", target="Orders", state_contract=C(app="com.example.app", required=[R(text="Orders", visible=True, clickable=True)]))
'''

    normalized = normalize_code_skill_entrypoints(source)
    compiled = compile_code_skills(normalized.source)

    assert compiled.errors == []
    assert compiled.skills[0].steps[0].state_contract is None
    assert normalized.report["open_app_contract_stripped_functions"] == ["open_orders"]
    assert "open_app', target='com.example.app', state_contract" not in normalized.source


def test_code_skill_repository_preserves_existing_entrypoint_on_same_name_update(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")
    first = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.contacts", platform="android")
async def create_contact(device):
    await action("open_app", target="com.google.android.contacts", state_contract=C(app="com.google.android.contacts", required=[R(text="Create contact", visible=True)]))
    await action("tap", target="Create contact", state_contract=C(app="com.google.android.contacts", required=[R(text="Create contact", visible=True, clickable=True)]))
''')
    assert not first.errors

    second = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.google.android.contacts", platform="android")
async def create_contact(device):
    await action("tap", target="Create contact", state_contract=C(app="com.google.android.contacts", required=[R(text="Create contact", visible=True, clickable=True)]))
    await action("tap", target="First name", state_contract=C(app="com.google.android.contacts", required=[R(text="First name", visible=True, clickable=True)]))
''')

    assert not second.errors
    skill = next(skill for skill in second.skills if skill.name == "create_contact")
    assert [step.action_type for step in skill.steps] == ["open_app", "tap", "tap"]
    assert skill.steps[0].state_contract is None
    source = repository.source_path.read_text(encoding="utf-8")
    assert source.count("async def create_contact") == 1
    assert source.index("open_app") < source.index("First name")


def test_code_skill_repository_preserves_existing_optional_interrupt_prelude(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")
    first = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def open_search(device):
    await action("open_app", target="com.example.app")
    await action(
        "tap",
        target="Close",
        optional=True,
        state_contract=C(app="com.example.app", required=[R(content_desc="Close", visible=True, clickable=True)]),
    )
    await action("tap", target="Search", state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/search", visible=True, clickable=True)]))
''')
    assert not first.errors

    second = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def open_search(device):
    await action("open_app", target="com.example.app")
    await action("tap", target="Search", state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/search", visible=True, clickable=True)]))
    await action("tap", target="Result", state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/result", visible=True, clickable=True)]))
''')

    assert not second.errors
    source = repository.source_path.read_text(encoding="utf-8")
    assert source.count("target='Close'") == 1
    assert "optional=True" in source
    assert source.index("target='Close'") < source.index("target='Search'")


def test_code_skill_repository_writes_variant_for_incompatible_same_name_update(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")
    first = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def open_orders(device):
    await action("tap", target="Orders", state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/orders", visible=True, clickable=True)]))
''')
    assert not first.errors

    second = repository.add_code('''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def open_orders(device):
    await action("tap", target="Profile", state_contract=C(app="com.example.app", required=[R(resource_id="com.example:id/profile", visible=True, clickable=True)]))
''')

    assert not second.errors
    source = repository.source_path.read_text(encoding="utf-8")
    assert "async def open_orders(device)" in source
    assert "async def open_orders_variant(device)" in source
    assert "target='Orders'" in source
    assert "target='Profile'" in source
    assert second.updated_functions == ("open_orders_variant",)


@pytest.mark.asyncio
async def test_postrun_repairs_contract_when_generated_skill_omits_recovery_step(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"ui_tree": [{"text": "Comments"}]},
                },
            },
            {
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "back"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "ui_tree": [
                            {
                                "text": "Orders",
                                "resource_id": "com.example:id/nav_orders",
                                "clickable": True,
                                "bounds": "[0,0][120,120]",
                            }
                        ],
                    },
                },
            },
            {
                "type": "step",
                "step_index": 2,
                "action": {"action_type": "tap", "target": "Orders"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"ui_tree": [{"text": "Order list"}]},
                },
            },
            {"type": "result", "success": True},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([_wrapped_code(_text_only_skill_source())]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))

    assert "resource_id='com.example:id/nav_orders'" in source
    assert result["contract_quality"]["repaired_steps"][0]["step_index"] == 1


@pytest.mark.asyncio
async def test_postrun_reports_weak_contract_when_ui_tree_has_only_text(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "ui_tree": [
                            {
                                "text": "Orders",
                                "clickable": True,
                                "bounds": "[0,0][120,120]",
                            }
                        ],
                    },
                },
            },
            {
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "tap", "target": "Orders"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"ui_tree": [{"text": "Order list"}]},
                },
            },
            {"type": "result", "success": True},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([_wrapped_code(_text_only_skill_source())]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))

    assert result["status"] == "processed_code"
    assert result["processed_segment_count"] == 1
    assert result["segments"][0]["status"] == "processed_code"
    assert result["segments"][0]["contract_quality"]["quality"] == "canonical"
    assert result["segments"][0]["contract_quality"]["canonical_node_count"] == 1
    assert result["segments"][0]["contract_quality"]["target_contract_steps"][0]["reason"] == (
        "target_text_contract_from_observation"
    )


@pytest.mark.asyncio
async def test_postrun_visual_guarded_fallback_writes_ui_skill_for_screenshot_only_trace(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir()
    for name in ("step_000.png", "step_001.png", "step_002.png"):
        _write_png(screenshot_dir / name)
    weak_source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.tencent.mm", platform="android", tags=["wechat"], description="open WeChat profile")
async def navigate_to_wechat_profile(device):
    await action("open_app", target="com.tencent.mm")
    await action("tap", target="Me tab", state_contract=C(app="com.tencent.mm", required=[R(text="Me", clickable=True)]))
    await action("tap", target="profile area")
'''
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "screenshot_path": str(screenshot_dir / "step_000.png"),
                "model_output": "Open WeChat",
                "action": {"action_type": "open_app", "text": "com.tencent.mm"},
                "observation": {
                    "foreground_app": "com.tencent.mm",
                    "platform": "android",
                    "screenshot_path": str(screenshot_dir / "step_000.png"),
                    "extra": {"ui_tree_node_count": 1},
                },
            },
            {
                "type": "step",
                "step_index": 1,
                "screenshot_path": str(screenshot_dir / "step_001.png"),
                "model_output": "Tap the bottom Me tab to enter the personal center page",
                "action": {"action_type": "tap", "x": 873, "y": 942, "relative": True},
                "observation": {
                    "foreground_app": "com.tencent.mm",
                    "platform": "android",
                    "screenshot_path": str(screenshot_dir / "step_001.png"),
                    "extra": {"ui_tree_node_count": 1},
                },
            },
            {
                "type": "step",
                "step_index": 2,
                "screenshot_path": str(screenshot_dir / "step_002.png"),
                "model_output": "Tap the top profile area to enter the personal information page",
                "action": {"action_type": "tap", "x": 131, "y": 149, "relative": True},
                "observation": {
                    "foreground_app": "com.tencent.mm",
                    "platform": "android",
                    "screenshot_path": str(screenshot_dir / "step_002.png"),
                    "extra": {"ui_tree_node_count": 1},
                },
            },
            {"type": "result", "success": True},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([_wrapped_code(weak_source)]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    compiled = compile_code_skills(source)

    assert result["status"] == "processed_code"
    assert result["processed_segment_count"] == 1
    assert result["visual_guarded_segment_count"] == 1
    assert result["segments"][0]["status"] == "processed_visual_guarded_code"
    assert result["segments"][0]["contract_quality"]["quality"] == "visual_guarded"
    assert result["segments"][0]["visual_guarded_fallback"]["enabled"] is True
    assert "visual_guarded" in source
    assert "valid_state=" in source
    assert "state_contract=" not in source
    assert not compiled.errors
    assert compiled.skills[0].tags == ("wechat", "visual_guarded", "ui")
    assert compiled.skills[0].steps[1].state_contract is None
    assert compiled.skills[0].steps[1].valid_state
    assert "bottom Me tab" in compiled.skills[0].steps[1].valid_state


@pytest.mark.asyncio
async def test_graph_projection_emits_state_for_repaired_contract(tmp_path: Path) -> None:
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "com.example.app"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Orders",
                            "resource_id": "com.example:id/nav_orders",
                            "clickable": True,
                            "bounds": "[0,0][120,120]",
                        }
                    ],
                },
            },
        },
        {"type": "result", "success": True},
    ]
    repaired = repair_code_contracts_from_events(_text_only_skill_source(), events)

    projection = project_graph_code_from_events(repaired.source, events)

    assert projection.emitted_states
    assert "@state(" in projection.source
    assert "com.example:id/nav_orders" in projection.source
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    result = await compile_code_graph(projection.source, store)
    assert result.errors == []
    assert any(node.kind == "state" for node in result.nodes)


@pytest.mark.asyncio
async def test_graph_projection_emits_transition_for_canonical_source_and_target(tmp_path: Path) -> None:
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "com.example.app"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Orders",
                            "resource_id": "com.example:id/nav_orders",
                            "clickable": True,
                        }
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "target": "Orders"},
            "action_summary": "Tap Orders",
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Order list",
                            "resource_id": "com.example:id/order_page_title",
                        }
                    ],
                },
            },
        },
        {"type": "result", "success": True},
    ]
    repaired = repair_code_contracts_from_events(_text_only_skill_source(), events)

    projection = project_graph_code_from_events(repaired.source, events)

    assert projection.emitted_transitions
    assert "@transition(" in projection.source
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    result = await compile_code_graph(projection.source, store)
    assert result.errors == []
    assert len(result.edges) == 1
    assert result.edges[0].target == "Orders"


@pytest.mark.asyncio
async def test_graph_projection_preserves_transition_parameters(tmp_path: Path) -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["search"])
async def search_example(device, query: str):
    await action(
        "input_text",
        target="com.example:id/search",
        text=query,
        auto_enter=True,
        state_contract=C(
            app="com.example.app",
            required=[R(resource_id="com.example:id/search", visible=True, focused=True)],
        ),
    )
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "input_text", "text": "MacBook Pro测评"},
            "pre_observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "resource_id": "com.example:id/search",
                            "focused": True,
                            "bounds": "[0,0][300,80]",
                        }
                    ],
                },
            },
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "resource_id": "com.example:id/search_results",
                            "text": "MacBook Pro测评",
                        },
                        {"content_desc": "MacBook Pro测评"},
                        {"resource_id": "com.example:id/result_list"},
                    ],
                },
            },
        },
    ]

    projection = project_graph_code_from_events(source, events)

    assert "parameters={'auto_enter': True, 'text': '{{query}}'}" in projection.source
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    result = await compile_code_graph(projection.source, store)
    assert result.errors == []
    assert len(result.edges) == 1
    assert result.edges[0].parameters["text"] == "{{query}}"
    assert result.edges[0].parameters["auto_enter"] is True
    target_node = store.get_node(result.edges[0].target_node_id)
    assert target_node is not None
    required = target_node.state_contract["signature"]["required"]
    assert not any(
        item["selector"].get("text") == "MacBook Pro测评"
        or item["selector"].get("content_desc") == "MacBook Pro测评"
        for item in required
    )


def test_graph_projection_strips_stale_text_before_parameterized_input() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["search"])
async def search_example(device, query: str):
    await action("tap", target="Search", state_contract=C(app="com.example.app", required=[R(text="Search", visible=True)]))
    await action("input_text", target="com.example:id/search", text=query, auto_enter=True)
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "target": "Search"},
            "pre_observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {"visible_text": ["Search"]},
            },
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "resource_id": "com.example:id/search",
                            "text": "old query",
                            "focused": True,
                            "enabled": True,
                        }
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "input_text", "text": "new query", "auto_enter": True},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {"ui_tree": [{"resource_id": "com.example:id/result_list"}]},
            },
        },
    ]

    projection = project_graph_code_from_events(source, events)

    assert "old query" not in projection.source
    assert "parameters={'auto_enter': True, 'text': '{{query}}'}" in projection.source


@pytest.mark.asyncio
async def test_graph_projection_uses_coordinate_hit_selector_as_source_evidence(tmp_path: Path) -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.app", platform="android", tags=["orders"])
async def open_orders(device):
    await action("tap", target="Orders", x=700, y=90)
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "com.example.app"},
            "observation": {
                "foreground_app": "com.example.app",
                "screen_width": 1000,
                "screen_height": 1000,
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Orders",
                            "resource_id": "com.example:id/nav_orders_decoy",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[0,0][250,180]",
                        },
                        {
                            "text": "Profile",
                            "resource_id": "com.example:id/nav_profile",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[260,0][500,180]",
                        },
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 100, "y": 90},
            "action_summary": "Tap Orders decoy",
            "observation": {
                "foreground_app": "com.example.app",
                "screen_width": 1000,
                "screen_height": 1000,
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Orders",
                            "resource_id": "com.example:id/nav_orders_target",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[600,0][850,180]",
                        }
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 2,
            "action": {"action_type": "tap", "x": 700, "y": 90},
            "observation": {
                "foreground_app": "com.example.app",
                "screen_width": 1000,
                "screen_height": 1000,
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Order list",
                            "resource_id": "com.example:id/order_page_title",
                            "enabled": True,
                            "bounds": "[0,0][600,120]",
                        }
                    ],
                },
            },
        },
        {"type": "result", "success": True},
    ]

    projection = project_graph_code_from_events(source, events)

    assert projection.emitted_transitions
    assert "com.example:id/nav_orders_target" in projection.source
    assert "com.example:id/nav_orders_decoy" not in projection.source
    assert "com.example:id/nav_profile" not in projection.source
    precondition = projection.emitted_transitions[0]["precondition"]
    required = precondition["signature"]["required"]
    assert required == [
        {
            "selector": {"resource_id": "com.example:id/nav_orders_target"},
            "state": ["visible", "clickable", "enabled"],
        }
    ]
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    result = await compile_code_graph(projection.source, store)
    assert result.errors == []
    assert len(result.edges) == 1


def test_graph_projection_skips_cross_app_target_state() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="tv.danmaku.bili", platform="android", tags=["search"])
async def search_bilibili(device):
    await action("tap", target="Search", x=500, y=100, relative=True)
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "tv.danmaku.bili"},
            "observation": {
                "foreground_app": "tv.danmaku.bili",
                "screen_width": 1000,
                "screen_height": 1000,
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Search",
                            "resource_id": "tv.danmaku.bili:id/search_text",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[400,0][700,180]",
                        }
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 500, "y": 100, "relative": True},
            "observation": {
                "foreground_app": "com.taobao.taobao",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Agree",
                            "resource_id": "com.taobao.taobao:id/provision_positive_button",
                            "clickable": True,
                            "enabled": True,
                        },
                        {
                            "text": "Disagree",
                            "resource_id": "com.taobao.taobao:id/provision_negative_button",
                            "clickable": True,
                            "enabled": True,
                        },
                    ],
                },
            },
        },
        {"type": "result", "success": True},
    ]

    projection = project_graph_code_from_events(source, events)

    assert not projection.emitted_transitions
    assert projection.skipped_transitions[0]["reason"] == "cross_app_target_state"
    assert "com.taobao.taobao:id/provision_positive_button" not in projection.source


@pytest.mark.asyncio
async def test_graph_projection_links_missing_post_state_to_next_source(tmp_path: Path) -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["search"])
async def search_items(device):
    await action("tap", target="Close", state_contract=C(app="com.example.app", required=[R(text="Close", clickable=True)]))
    await action("tap", target="Search", state_contract=C(app="com.example.app", required=[R(text="Search", clickable=True)]))
'''
    popup = {
        "foreground_app": "com.example.app",
        "platform": "android",
        "extra": {
            "ui_tree": [
                {"text": "Close", "clickable": True, "enabled": True, "bounds": "[800,0][1000,180]"}
            ]
        },
    }
    search_entry = {
        "foreground_app": "com.example.app",
        "platform": "android",
        "extra": {
            "ui_tree": [
                {"text": "Search", "clickable": True, "enabled": True, "bounds": "[0,0][600,180]"}
            ]
        },
    }
    results = {
        "foreground_app": "com.example.app",
        "platform": "android",
        "extra": {
            "ui_tree": [
                {"resource_id": "com.example:id/result_list", "enabled": True},
                {"text": "Search", "clickable": True, "enabled": True},
            ]
        },
    }
    events = [
        {"type": "step", "step_index": 0, "action": {"action_type": "wait"}, "observation": popup},
        {"type": "step", "step_index": 1, "action": {"action_type": "tap", "x": 900, "y": 90}, "observation": None},
        {"type": "step", "step_index": 2, "action": {"action_type": "wait"}, "observation": search_entry},
        {"type": "step", "step_index": 3, "action": {"action_type": "tap", "x": 300, "y": 90}, "observation": results},
    ]

    projection = project_graph_code_from_events(source, events)

    assert projection.quality == "canonical"
    assert [transition["step_index"] for transition in projection.emitted_transitions] == [0, 1]
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    result = await compile_code_graph(projection.source, store)
    assert result.errors == []
    assert len(result.edges) == 2


def test_graph_projection_skips_transition_when_target_state_is_weak() -> None:
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "com.example.app"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Orders",
                            "resource_id": "com.example:id/nav_orders",
                            "clickable": True,
                        }
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "target": "Orders"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {"ui_tree": [{"text": "Orders"}]},
            },
        },
        {"type": "result", "success": True},
    ]
    repaired = repair_code_contracts_from_events(_text_only_skill_source(), events)

    projection = project_graph_code_from_events(repaired.source, events)

    assert projection.emitted_states
    assert not projection.emitted_transitions
    assert projection.skipped_transitions[0]["reason"] == "weak_target_state"


def test_graph_projection_prefers_text_signature_over_unmatched_identity_selector() -> None:
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "com.example.app"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {
                            "text": "Orders",
                            "resource_id": "com.example:id/nav_orders",
                            "clickable": True,
                        }
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "target": "Orders"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {"text": "Sign in", "resource_id": "com.example:id/home_login_panel"},
                        {"text": "All orders"},
                        {"text": "Success orders"},
                    ],
                },
            },
        },
        {"type": "result", "success": True},
    ]
    repaired = repair_code_contracts_from_events(_text_only_skill_source(), events)

    projection = project_graph_code_from_events(repaired.source, events)

    assert "home_login_panel" not in projection.source
    assert "All orders" in projection.source
    assert "Success orders" in projection.source


@pytest.mark.asyncio
async def test_graph_projection_keeps_target_text_in_page_signature(tmp_path: Path) -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["orders"])
async def open_my_orders(device):
    await action("open_app", text="com.example.app")
    await action(
        "tap",
        target="Your Orders",
        state_contract=C(app="com.example.app", required=[R(text="Your Orders", clickable=True)]),
    )
'''
    events = [
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "open_app", "text": "com.example.app"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "ui_tree": [
                        {"text": "Sign in", "resource_id": "com.example:id/home_login_panel"},
                        {"text": "Home"},
                        {"text": "Profile"},
                        {"text": "Settings"},
                        {"text": "Search"},
                        {"text": "Your Orders"},
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "target": "Your Orders"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {"ui_tree": [{"text": "All orders"}]},
            },
        },
    ]

    projection = project_graph_code_from_events(source, events)

    store = SkillGraphStore(store_dir=tmp_path / "graph")
    result = await compile_code_graph(projection.source, store)
    source_node = next(
        node
        for node in result.nodes
        if node.description == "open_my_orders step 1 source"
    )
    required = source_node.state_contract["signature"]["required"]

    assert {"selector": {"text": "Your Orders"}, "state": ["visible"]} in required
    assert not any(
        item["selector"].get("resource_id") == "com.example:id/home_login_panel"
        for item in required
    )


def test_contract_repair_does_not_use_future_order_title_as_tap_precondition() -> None:
    repaired = repair_code_contracts_from_events(
        _xiaoheihe_orders_source(),
        _xiaoheihe_repeated_orders_events(),
    )

    assert "com.max.xiaoheihe:id/rb_5" in repaired.source
    assert "com.max.xiaoheihe:id/tv_appbar_title" not in repaired.source
    assert [step["step_index"] for step in repaired.report["repaired_steps"]] == [1, 2, 3]
    assert repaired.report["repaired_steps"][1]["reason"] == "target_text_contract_from_observation"


def test_contract_repair_replaces_unsupported_stable_precondition() -> None:
    source = _xiaoheihe_orders_source().replace(
        'R(text="我的订单", clickable=True)',
        'R(resource_id="com.max.xiaoheihe:id/tv_appbar_title", visible=True, clickable=True)',
    )

    repaired = repair_code_contracts_from_events(
        source,
        _xiaoheihe_repeated_orders_events(),
    )

    assert "com.max.xiaoheihe:id/tv_appbar_title" not in repaired.source
    assert "收货地址" not in repaired.source
    assert "text': '我的订单'" in repaired.source
    assert "购买成功" not in repaired.source
    assert {step["step_index"] for step in repaired.report["repaired_steps"]} >= {2, 3}


def test_contract_repair_normalizes_target_selector_calls_before_compile() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.max.xiaoheihe", platform="android", tags=["orders"])
async def navigate_to_my_orders(device):
    await action("open_app", target="com.max.xiaoheihe")
    await action(
        "tap",
        target=R(text="我", clickable=True),
        state_contract=C(app="com.max.xiaoheihe", required=[R(text="我", clickable=True)]),
    )
'''

    repaired = repair_code_contracts_from_events(source, _xiaoheihe_repeated_orders_events())

    assert "target=R(" not in repaired.source
    assert "target='我'" in repaired.source
    assert "com.max.xiaoheihe:id/rb_5" in repaired.source
    assert repaired.report["quality"] == "canonical"


def test_contract_repair_uses_post_ui_tree_when_first_pre_observation_is_missing() -> None:
    repaired = repair_code_contracts_from_events(
        _zhihu_search_source(),
        _zhihu_search_events(),
    )

    assert "text='com.zhihu.android:id/input_text'" not in repaired.source
    assert "resource_id='com.zhihu.android:id/input_text'" in repaired.source
    assert repaired.report["repaired_steps"][0]["step_index"] == 0


def test_action_canonicalization_does_not_synthesize_unverifiable_trailing_trace_actions() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.max.xiaoheihe", platform="android", tags=["orders"])
async def navigate_to_my_orders(device):
    await action("open_app", target="com.max.xiaoheihe")
    await action(
        "tap",
        target="我",
        state_contract=C(app="com.max.xiaoheihe", required=[R(text="我", clickable=True)]),
    )
    await action(
        "tap",
        target="我的订单",
        state_contract=C(app="com.max.xiaoheihe", required=[R(text="我的订单", clickable=True)]),
    )
'''

    canonicalized = canonicalize_code_actions_from_events(
        source,
        _xiaoheihe_repeated_orders_events(),
    )
    compiled = compile_code_skills(canonicalized.source)

    assert compiled.errors == []
    assert [step.target for step in compiled.skills[0].steps] == [
        "com.max.xiaoheihe",
        "我",
        "我的订单",
    ]
    assert canonicalized.report["quality"] == "aligned"
    assert canonicalized.report["synthesized_steps"] == []


def test_action_canonicalization_removes_unmatched_parameterized_tap() -> None:
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="ctrip.android.view", platform="android", tags=["hotel"])
async def search_hotel_by_city(device, city_name: str = "杭州"):
    await action("open_app", target="ctrip.android.view")
    await action("tap", target="酒店")
    await action("tap", target="{{city_name}}")
'''
    events = [
        {
            "event": "step",
            "step_index": 1,
            "action": {"action_type": "open_app", "text": "ctrip.android.view"},
            "execution": {
                "next_observation": {
                    "foreground_app": "ctrip.android.view",
                    "platform": "android",
                    "extra": {"ui_tree": []},
                },
            },
        },
        {
            "event": "step",
            "step_index": 3,
            "action": {"action_type": "tap", "x": 121.0, "y": 156.0, "relative": True},
            "model_output": '点击 "酒店"',
            "prompt": {
                "current_observation": {
                    "foreground_app": "ctrip.android.view",
                    "platform": "android",
                    "screen_width": 496,
                    "screen_height": 1080,
                    "extra": {
                        "ui_tree": [
                            {
                                "content_desc": "酒店",
                                "resource_id": "ctrip.android.view:id/home_grid_hotel_widget",
                                "clickable": True,
                                "enabled": True,
                                "bounds": "[42,324][296,547]",
                            }
                        ],
                    },
                },
            },
            "execution": {
                "next_observation": {
                    "foreground_app": "ctrip.android.view",
                    "platform": "android",
                    "extra": {"ui_tree": []},
                },
            },
        },
    ]

    canonicalized = canonicalize_code_actions_from_events(source, events)
    compiled = compile_code_skills(canonicalized.source)

    assert compiled.errors == []
    assert [step.target for step in compiled.skills[0].steps] == ["ctrip.android.view", "酒店"]
    assert canonicalized.report["removed_steps"][0]["target"] == "{{city_name}}"


def test_contract_repair_strips_parameterized_input_text_from_precondition() -> None:
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.zhihu.android", platform="android", tags=["search"])
async def search_zhihu(device, query: str):
    await action(
        "input_text",
        target="com.zhihu.android:id/input_text",
        text=query,
        state_contract=C(
            app="com.zhihu.android",
            required=[
                R(
                    resource_id="com.zhihu.android:id/input_text",
                    text="强化学习基本概念",
                    visible=True,
                    focused=True,
                )
            ],
        ),
    )
'''

    repaired = repair_code_contracts_from_events(source, _zhihu_search_events())

    assert "'text': '强化学习基本概念'" not in repaired.source
    assert "resource_id" in repaired.source
    assert repaired.report["repaired_steps"][0]["reason"] == "parameterized_input_text_removed"
    compiled = compile_code_skills(repaired.source)
    selector = compiled.skills[0].steps[0].state_contract["signature"]["required"][0]["selector"]
    assert selector == {
        "resource_id": "com.zhihu.android:id/input_text",
        "class": "android.widget.EditText",
    }
    state = compiled.skills[0].steps[0].state_contract["signature"]["required"][0]["state"]
    assert "focused" not in state


def test_graph_projection_uses_monotonic_trace_alignment_for_repeated_targets() -> None:
    projection = project_graph_code_from_events(
        _xiaoheihe_orders_source(),
        _xiaoheihe_repeated_orders_events(),
    )

    assert [transition["step_index"] for transition in projection.emitted_transitions] == [1, 2, 3]
    transition = projection.emitted_transitions[-1]
    source_state = next(
        state
        for state in projection.emitted_states
        if state["function"] == transition["src"]
    )
    target_state = next(
        state
        for state in projection.emitted_states
        if state["function"] == transition["dst"]
    )
    assert "收货地址" in projection.source
    assert "购买成功" in projection.source
    assert "com.max.xiaoheihe:id/tv_appbar_title" not in projection.source
    assert source_state["description"] == "navigate_to_my_orders step 2 target"
    assert target_state["description"] == "navigate_to_my_orders step 3 target"


@pytest.mark.asyncio
async def test_graph_projection_uses_trace_pre_post_ui_tree_with_lookahead(tmp_path: Path) -> None:
    repaired = repair_code_contracts_from_events(
        _zhihu_search_source(),
        _zhihu_search_events(),
    )

    projection = project_graph_code_from_events(repaired.source, _zhihu_search_events())

    assert [transition["step_index"] for transition in projection.emitted_transitions] == [1, 2]
    assert "com.zhihu.android:id/input_text" in projection.source
    assert "com.zhihu.android:id/bottom_layout" in projection.source
    assert "'text': '关注'" in projection.source
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    result = await compile_code_graph(projection.source, store)
    assert result.errors == []
    assert len(result.edges) == 2


def test_graph_projection_drops_stale_graph_declarations_for_updated_skill() -> None:
    source = _xiaoheihe_orders_source() + '''

@state(app="com.max.xiaoheihe", platform="android", node_id="stale-node", skill_ids=["code:navigate_to_my_orders"])
def state_navigate_to_my_orders_stale():
    return C(required=[R(resource_id="com.max.xiaoheihe:id/tv_appbar_title", visible=True)])
'''

    projection = project_graph_code_from_events(source, _xiaoheihe_repeated_orders_events())

    assert "state_navigate_to_my_orders_stale" not in projection.source
    assert "com.max.xiaoheihe:id/tv_appbar_title" not in projection.source


@pytest.mark.asyncio
async def test_postrun_writes_code_with_graph_projection_when_trace_is_grounded(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "ui_tree": [
                            {
                                "text": "Orders",
                                "resource_id": "com.example:id/nav_orders",
                                "clickable": True,
                            }
                        ],
                    },
                },
            },
            {
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "tap", "target": "Orders"},
                "action_summary": "Tap Orders",
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "ui_tree": [
                            {
                                "text": "Order list",
                                "resource_id": "com.example:id/order_page_title",
                            }
                        ],
                    },
                },
            },
            {"type": "result", "success": True},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([_wrapped_code(_text_only_skill_source())]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    graph = SkillGraphStore(store_dir=tmp_path / "store")

    assert "@skill(" in source
    assert "@state(" in source
    assert "@transition(" in source
    assert result["action_sequence"]["quality"] == "aligned"
    assert result["contract_quality"]["graph_projection"]["quality"] == "canonical"
    assert result["graph_synced"] is False
    assert result["code_graph_synced"] is True
    assert graph.list_nodes()
    assert graph.list_edges()


@pytest.mark.asyncio
async def test_postrun_extracts_long_trace_as_multiple_segments(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    events = [
        {
            "type": "step",
            "step_index": index,
            "action": {"action_type": "tap", "target": f"Button {index}"},
            "observation": {
                "foreground_app": "com.example.app",
                "platform": "android",
                "extra": {
                    "visible_text": [f"Stable page {stable}" for stable in range(8)],
                    "resource_ids": ["com.example:id/root"],
                    "ui_tree": [
                        {
                            "text": f"Button {index}",
                            "resource_id": f"com.example:id/button_{index}",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[0,0][120,120]",
                        }
                    ],
                },
            },
        }
        for index in range(25)
    ]
    events.append({"type": "result", "success": True})
    _write_trace(trace_path, events)
    processor = PostRunProcessor(
        llm=_ScriptedLLM([
            _wrapped_code(_single_tap_skill_source("early_prefix", "Button 0")),
            _wrapped_code(_single_tap_skill_source("middle_prefix", "Button 8")),
            _wrapped_code(_single_tap_skill_source("late_prefix", "Button 16")),
        ]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    source = (tmp_path / "store" / "skill_graph_code.py").read_text(encoding="utf-8")
    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))

    assert result["status"] == "processed_code"
    assert result["segment_count"] == 3
    assert result["processed_segment_count"] == 3
    assert result["segments"][0]["start_step_index"] == 0
    assert result["segments"][1]["start_step_index"] == 8
    assert result["segments"][2]["start_step_index"] == 16
    assert set(result["updated_functions"]) == {"early_prefix", "middle_prefix", "late_prefix"}
    assert "async def early_prefix" in source
    assert "async def middle_prefix" in source
    assert "async def late_prefix" in source


@pytest.mark.asyncio
async def test_postrun_returns_updated_skill_id_when_repository_has_existing_skills(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "ui_tree": [
                            {
                                "text": "Orders",
                                "resource_id": "com.example:id/nav_orders",
                                "clickable": True,
                            }
                        ],
                    },
                },
            },
            {
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "tap", "target": "Orders"},
                "action_summary": "Tap Orders",
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "ui_tree": [
                            {
                                "text": "Order list",
                                "resource_id": "com.example:id/order_page_title",
                            }
                        ],
                    },
                },
            },
            {"type": "result", "success": True},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([
            _wrapped_code(_text_only_skill_source("first_skill")),
            _wrapped_code(_text_only_skill_source("second_skill")),
        ]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    first_id = await processor._extract_skill(trace_path, is_success=True, platform="android")
    second_id = await processor._extract_skill(trace_path, is_success=True, platform="android")

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert first_id == "code:first_skill"
    assert second_id == "code:second_skill"
    assert "second_skill" in result["updated_functions"]
    assert result["compiled_skill_ids"] == ["code:first_skill", "code:second_skill"]


@pytest.mark.asyncio
async def test_postrun_rejects_trace_aligned_but_degenerate_skill(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"ui_tree": [{"text": "Already there"}]},
                },
            },
            {
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "wait", "duration_ms": 1000},
                "observation": {
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"ui_tree": [{"text": "Already there"}]},
                },
            },
            {"type": "result", "success": True},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([_wrapped_code('''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.app", platform="android", tags=["degenerate"])
async def open_existing_page(device):
    await action("open_app", target="com.example.app")
    await action("wait", duration_ms=1000)
''')]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    skill_id = await processor._extract_skill(trace_path, is_success=True, platform="android")

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert skill_id is None
    assert result["status"] == "no_candidate"
    assert result["reason"] == "no_trace_aligned_reusable_actions"
    assert result["action_sequence"]["reusable_action_count"] == 0
    assert not (tmp_path / "store" / "skill_graph_code.py").exists()


@pytest.mark.asyncio
async def test_postrun_uses_prefix_extraction_when_evaluation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [{"type": "step", "action": {"action_type": "tap"}}])
    captured: dict[str, Any] = {}

    async def fake_extract(
        self: PostRunProcessor,
        trace_path: Path,
        is_success: bool,
        platform: str,
        *,
        task: str | None = None,
        evaluation_result: dict[str, Any] | None = None,
        agent_success: bool | None = None,
    ) -> None:
        captured.update({
            "trace_path": trace_path,
            "is_success": is_success,
            "platform": platform,
            "task": task,
            "evaluation_result": evaluation_result,
            "agent_success": agent_success,
        })

    async def fake_evaluation(
        self: PostRunProcessor,
        *,
        trace_path: Path,
        is_success: bool,
        task: str,
    ) -> dict[str, Any]:
        del self, trace_path, is_success, task
        return {"success": False, "reason": "no evidence for final answer"}

    monkeypatch.setattr(PostRunProcessor, "_summarize_trajectory", AsyncMock(return_value=""))
    monkeypatch.setattr(PostRunProcessor, "_run_evaluation", fake_evaluation)
    monkeypatch.setattr(PostRunProcessor, "_extract_skill", fake_extract)
    processor = PostRunProcessor(
        llm=object(),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    await processor._run_all(
        trace_path,
        is_success=True,
        platform="android",
        task="tell me the order total",
    )

    assert captured["is_success"] is False
    assert captured["agent_success"] is True
    assert captured["task"] == "tell me the order total"
    assert captured["evaluation_result"]["success"] is False


@pytest.mark.asyncio
async def test_postrun_skips_extraction_after_complete_graph_reuse_even_if_evaluation_fails(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "graph_runtime_result",
                "state": "succeeded",
                "prefix_only": False,
                "prefix_terminal_node_id": "node-target",
            },
            {"type": "result", "success": True},
        ],
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([]),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    skill_id = await processor._extract_skill(
        trace_path,
        is_success=False,
        platform="android",
        evaluation_result={"success": False, "reason": "no screenshot"},
        agent_success=True,
    )

    result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert skill_id is None
    assert result["status"] == "skipped_reused_skill_complete"
    assert result["reuse_source"] == "graph"
    assert result["evaluation_success"] is False
    assert not (tmp_path / "store" / "skill_graph_code.py").exists()


@pytest.mark.asyncio
async def test_postrun_evolution_skips_ordinary_extraction_for_reuse_failure(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "skill_graph_code.py").write_text(
        """
from opengui.skills.code_graph import action, skill

@skill(app="com.google.android.deskclock", platform="android", description="Pause stopwatch")
async def pause_stopwatch(device):
    await action("open_app", target="com.google.android.deskclock")
    await action("tap", target="Pause")
""".lstrip(),
        encoding="utf-8",
    )
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [
        {"type": "metadata", "task": "Run the stopwatch", "platform": "android"},
        {
            "type": "skill_step",
            "skill_id": "code:pause_stopwatch",
            "skill_name": "pause_stopwatch",
            "step_index": 1,
            "target": "Pause",
            "action": {"action_type": "tap", "target": "Pause"},
            "error": "wrong page",
        },
        {
            "type": "skill_execution_result",
            "state": "failed",
            "skill_id": "code:pause_stopwatch",
            "skill_name": "pause_stopwatch",
        },
        {
            "type": "step",
            "action": {"action_type": "tap", "target": "Start"},
            "observation": {"foreground_app": "com.google.android.deskclock"},
        },
        {"type": "result", "success": True},
    ])
    processor = PostRunProcessor(
        llm=_ScriptedLLM([]),
        skill_store_root=store,
        enable_skill_extraction=True,
        evaluation=EvaluationConfig(enabled=False),
    )

    await processor._run_all(
        trace_path,
        is_success=True,
        platform="android",
        task="Run the stopwatch",
    )

    evolution = json.loads((tmp_path / "evolution_result.json").read_text(encoding="utf-8"))
    extraction = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert evolution["status"] == "processed_evolution"
    assert extraction["status"] == "processed_evolution"
    assert extraction["ordinary_code_extraction_skipped"] is True
    assert "Run the stopwatch" in json.loads(
        (store / "skill_feedback.json").read_text(encoding="utf-8")
    )["skills"]["code:pause_stopwatch"]["negative_tasks"]


def test_completed_reuse_does_not_skip_when_agent_continues_with_actions(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "graph_runtime_result",
                "state": "succeeded",
                "prefix_only": False,
                "prefix_terminal_node_id": "node-search-result",
            },
            {
                "type": "step",
                "phase": "agent",
                "action": {"action_type": "open_app", "text": "com.zhihu.android"},
            },
            {
                "type": "step",
                "phase": "agent",
                "action": {"action_type": "tap", "x": 450, "y": 75, "relative": True},
            },
            {"type": "result", "success": True},
        ],
    )

    assert _load_completed_reuse(trace_path) is None


def test_evolution_downgrades_over_strong_contract_without_variant(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    app = "com.google.android.deskclock"
    (store / "skill_graph_code.py").write_text(
        f"""
from opengui.skills.code_graph import C, R, action, skill

@skill(app="{app}", platform="android", description="Pause stopwatch")
async def pause_stopwatch(device):
    await action("open_app", target="{app}")
    await action("tap", target="Pause", state_contract=C(app="{app}", required=[
        R(text="Alarm", visible=True),
        R(content_desc="More options", visible=True),
        R(content_desc="Pause", visible=True, enabled=True, clickable=True),
    ]))
""".lstrip(),
        encoding="utf-8",
    )
    contract = {
        "anchor": {"app_package": app},
        "signature": {
            "required": [
                {"selector": {"text": "Alarm"}, "state": ["visible"]},
                {"selector": {"content_desc": "More options"}, "state": ["visible"]},
                {
                    "selector": {"content_desc": "Pause"},
                    "state": ["visible", "enabled", "clickable"],
                },
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    }
    observation = {
        "foreground_app": app,
        "extra": {
            "content_desc": ["Pause"],
            "ui_tree": [{"content_desc": "Pause", "clickable": True, "enabled": True}],
        },
    }
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [
        {"type": "metadata", "task": "Pause the stopwatch", "platform": "android"},
        {
            "type": "skill_step",
            "skill_id": "code:pause_stopwatch",
            "skill_name": "pause_stopwatch",
            "step_index": 1,
            "target": "Pause",
            "action": {"action_type": "tap", "target": "Pause"},
            "state_contract": contract,
            "observation": observation,
            "screenshot_path": str(tmp_path / "screen.png"),
            "contract_eval_detail": {
                "passed": False,
                "reason": "failed_required",
                "matched_required": [
                    {"anchor": {"app_package": app}},
                    {
                        "element": {
                            "selector": {"content_desc": "Pause"},
                            "state": ["visible", "enabled", "clickable"],
                        },
                        "score": 1.0,
                    },
                ],
                "failed_required": [
                    {"element": {"selector": {"text": "Alarm"}, "state": ["visible"]}},
                    {
                        "element": {
                            "selector": {"content_desc": "More options"},
                            "state": ["visible"],
                        }
                    },
                ],
            },
            "error": "Valid state check failed before action",
        },
        {
            "type": "skill_execution_result",
            "state": "failed",
            "skill_id": "code:pause_stopwatch",
            "skill_name": "pause_stopwatch",
        },
    ])

    result = SkillEvolutionEngine(store).evolve_trace(
        trace_path,
        task="Pause the stopwatch",
        platform="android",
    )

    assert result["status"] == "processed_evolution"
    assert result["decisions"][0]["decision_type"] == "contract_downgrade"
    assert result["decisions"][0]["promoted"] is True
    source = (store / "skill_graph_code.py").read_text(encoding="utf-8")
    assert "pause_stopwatch_variant" not in source
    assert "More options" not in source
    assert "Alarm" not in source
    assert "Pause" in source


def test_evolution_inserts_missing_gap_action_from_fallback(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    app = "com.google.android.deskclock"
    (store / "skill_graph_code.py").write_text(
        f"""
from opengui.skills.code_graph import C, R, action, skill

@skill(app="{app}", platform="android", description="Navigate to timer setup")
async def navigate_to_timer_setup(device):
    await action("open_app", target="{app}")
    await action("tap", target="Timer")
    await action("tap", target="1", state_contract=C(app="{app}", required=[
        R(resource_id="timer_setup_digit_1", visible=True),
    ]))
""".lstrip(),
        encoding="utf-8",
    )
    digit_contract = {
        "anchor": {"app_package": app},
        "signature": {
            "required": [
                {"selector": {"resource_id": "timer_setup_digit_1"}, "state": ["visible"]}
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    }
    before_plus = {
        "foreground_app": app,
        "extra": {
            "content_desc": ["Add timer"],
            "ui_tree": [
                {
                    "content_desc": "Add timer",
                    "resource_id": "com.google.android.deskclock:id/timer_setup_fab",
                    "clickable": True,
                    "enabled": True,
                    "bounds": "[400,900][600,1100]",
                }
            ],
        },
    }
    after_plus = {
        "foreground_app": app,
        "extra": {
            "resource_ids": ["timer_setup_digit_1"],
            "ui_tree": [{"resource_id": "timer_setup_digit_1", "text": "1"}],
        },
    }
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(trace_path, [
        {"type": "metadata", "task": "Set a timer for 1 second", "platform": "android"},
        {
            "type": "skill_step",
            "skill_id": "code:navigate_to_timer_setup",
            "skill_name": "navigate_to_timer_setup",
            "step_index": 2,
            "target": "1",
            "action": {"action_type": "tap", "target": "1"},
            "state_contract": digit_contract,
            "observation": before_plus,
            "contract_eval_detail": {
                "passed": False,
                "reason": "failed_required",
                "failed_required": [{"element": digit_contract["signature"]["required"][0]}],
            },
            "error": "Valid state check failed before action",
        },
        {
            "type": "skill_execution_result",
            "state": "failed",
            "skill_id": "code:navigate_to_timer_setup",
            "skill_name": "navigate_to_timer_setup",
        },
        {
            "type": "step",
            "action": {"action_type": "tap", "target": "Add timer", "x": 500, "y": 1000},
            "observation": after_plus,
        },
    ])

    result = SkillEvolutionEngine(store).evolve_trace(
        trace_path,
        task="Set a timer for 1 second",
        platform="android",
    )

    assert result["status"] == "processed_evolution"
    assert result["decisions"][0]["decision_type"] == "insert_missing_action_gap"
    compiled = compile_code_skills((store / "skill_graph_code.py").read_text(encoding="utf-8"))
    assert not compiled.errors
    skill = compiled.skills[0]
    assert [(step.action_type, step.target) for step in skill.steps] == [
        ("open_app", app),
        ("tap", "Timer"),
        ("tap", "Add timer"),
        ("tap", "1"),
    ]


def test_evolution_records_negative_and_preferred_feedback(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "skill_graph_code.py").write_text(
        """
from opengui.skills.code_graph import action, skill

@skill(app="com.google.android.deskclock", platform="android", description="Pause stopwatch")
async def pause_stopwatch(device):
    await action("open_app", target="com.google.android.deskclock")
    await action("tap", target="Pause")
""".lstrip(),
        encoding="utf-8",
    )
    trace_path = tmp_path / "trace.jsonl"
    (tmp_path / "deeplink_result.json").write_text(
        json.dumps({
            "status": "processed_deeplink_code",
            "compiled_skill_ids": ["intent:show_timers"],
        }),
        encoding="utf-8",
    )
    _write_trace(trace_path, [
        {"type": "metadata", "task": "Run the stopwatch", "platform": "android"},
        {
            "type": "skill_step",
            "skill_id": "code:pause_stopwatch",
            "skill_name": "pause_stopwatch",
            "step_index": 1,
            "target": "Pause",
            "action": {"action_type": "tap", "target": "Pause"},
            "error": "wrong page",
        },
        {
            "type": "skill_execution_result",
            "state": "failed",
            "skill_id": "code:pause_stopwatch",
            "skill_name": "pause_stopwatch",
        },
    ])

    result = SkillEvolutionEngine(store).evolve_trace(
        trace_path,
        task="Run the stopwatch",
        platform="android",
    )

    decisions = {decision["decision_type"] for decision in result["decisions"]}
    assert "negative_selection_feedback" in decisions
    assert "prefer_verified_intent" in decisions
    feedback = json.loads((store / "skill_feedback.json").read_text(encoding="utf-8"))
    assert "Run the stopwatch" in feedback["skills"]["code:pause_stopwatch"]["negative_tasks"]
    assert "Run the stopwatch" in feedback["skills"]["intent:show_timers"]["preferred_for_tasks"]


def test_evolution_prefers_only_updated_verified_intent_from_legacy_deeplink_result(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "skill_graph_code.py").write_text(
        """
from opengui.skills.code_graph import action, skill

@skill(app="com.google.android.deskclock", platform="android", skill_id="intent:show_timers")
async def open_show_timers(device):
    await action("open_intent", intent_action="android.intent.action.SHOW_TIMERS")

@skill(app="com.google.android.deskclock", platform="android", skill_id="intent:unrelated")
async def open_unrelated_intent(device):
    await action("open_intent", intent_action="android.intent.action.SET_ALARM")

@skill(app="com.google.android.deskclock", platform="android")
async def pause_stopwatch(device):
    await action("open_app", target="com.google.android.deskclock")
    await action("tap", target="Pause")
""".lstrip(),
        encoding="utf-8",
    )
    trace_path = tmp_path / "trace.jsonl"
    (tmp_path / "deeplink_result.json").write_text(
        json.dumps({
            "status": "processed_deeplink_code",
            "candidates": [{"kind": "shortcut_intent"}],
            "updated_functions": ["open_show_timers"],
            "compiled_skill_ids": ["intent:show_timers", "intent:unrelated"],
        }),
        encoding="utf-8",
    )
    _write_trace(trace_path, [
        {"type": "metadata", "task": "Run the stopwatch", "platform": "android"},
        {
            "type": "skill_step",
            "skill_id": "code:pause_stopwatch",
            "skill_name": "pause_stopwatch",
            "step_index": 1,
            "target": "Pause",
            "action": {"action_type": "tap", "target": "Pause"},
            "error": "wrong page",
        },
        {
            "type": "skill_execution_result",
            "state": "failed",
            "skill_id": "code:pause_stopwatch",
            "skill_name": "pause_stopwatch",
        },
    ])

    result = SkillEvolutionEngine(store).evolve_trace(
        trace_path,
        task="Run the stopwatch",
        platform="android",
    )

    decision = next(
        item for item in result["decisions"] if item["decision_type"] == "prefer_verified_intent"
    )
    assert decision["preferred_skill_ids"] == ["intent:show_timers"]
    feedback = json.loads((store / "skill_feedback.json").read_text(encoding="utf-8"))
    assert "Run the stopwatch" in feedback["skills"]["intent:show_timers"]["preferred_for_tasks"]
    assert "intent:unrelated" not in feedback["skills"]


@pytest.mark.asyncio
async def test_evolution_task_skill_conflict_tokenizes_stopwatch() -> None:
    assert not _task_skill_conflict("Run the stopwatch.", "run_stopwatch")
    assert _task_skill_conflict("Run the stopwatch.", "pause_stopwatch")
    assert _task_skill_conflict("Pause the stopwatch.", "run_stopwatch")


@pytest.mark.asyncio
async def test_code_skill_search_downweights_negative_feedback(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "skill_graph_code.py").write_text(
        """
from opengui.skills.code_graph import action, skill

@skill(app="com.google.android.deskclock", platform="android", description="Pause stopwatch")
async def pause_stopwatch(device):
    await action("open_app", target="com.google.android.deskclock")
    await action("tap", target="Pause")
""".lstrip(),
        encoding="utf-8",
    )
    (store / "skill_feedback.json").write_text(
        json.dumps({
            "version": 1,
            "skills": {
                "code:pause_stopwatch": {
                    "negative_tasks": ["Run the stopwatch"],
                    "failure_counts": {"wrong_skill_selected": 1},
                }
            },
        }),
        encoding="utf-8",
    )
    library = CodeSkillLibrary(store_dir=store, legacy_fallback=False)

    matches = await library.search("Run the stopwatch", platform="android", top_k=5)

    assert matches
    assert matches[0][0].skill_id == "code:pause_stopwatch"
    assert matches[0][1] < 0.35
