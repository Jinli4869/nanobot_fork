import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pytest

from opengui.interfaces import LLMResponse
from opengui.postprocessing import PostRunProcessor, _load_completed_reuse
from opengui.skills.code_first import (
    CodeSkillExtractor,
    CodeSkillLibrary,
    CodeSkillRepository,
    canonicalize_code_actions_from_events,
    repair_code_contracts_from_events,
)
from opengui.skills.code_graph import compile_code_graph, compile_code_skills
from opengui.skills.code_graph_projection import project_graph_code_from_events
from opengui.skills.graph import GraphEdge, GraphNode, SkillGraphStore


class _ScriptedLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = [LLMResponse(content=response) for response in responses]
        self.messages: list[list[dict[str, Any]]] = []

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


def _write_trace(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
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


def test_code_skill_repository_removes_stale_graph_projection_for_updated_skill(tmp_path: Path) -> None:
    repository = CodeSkillRepository(tmp_path / "skills")
    repository.store_dir.mkdir(parents=True)
    repository.source_path.write_text(
        '''
from opengui.skills.code_graph import C, R, action, skill, state, transition

@skill(app="com.example.app", platform="android")
async def open_orders(device):
    await action("tap", target="Old")

@state(app="com.example.app", platform="android", node_id="stale-node", skill_ids=["code:open_orders"])
def state_open_orders_stale():
    return C(required=[R(resource_id="com.example:id/stale_order_title", visible=True)])

@transition(src=state_open_orders_stale, dst=state_open_orders_stale, skill_id="code:open_orders")
async def transition_open_orders_stale(device):
    await action(
        "tap",
        target="Old",
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


@pytest.mark.asyncio
async def test_code_skill_library_syncs_graph_cache_from_code_source(tmp_path: Path) -> None:
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


def test_action_canonicalization_synthesizes_missing_in_app_trace_gap() -> None:
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
        "input_text",
        "tap",
    ]
    assert compiled.skills[0].steps[3].parameters["text"] == "{{city}}"
    assert [step["trace_step_index"] for step in canonicalized.report["synthesized_steps"]] == [2, 3]


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
async def test_postrun_code_first_extraction_writes_code_and_graph_not_skill_json(
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
    assert result["compiled_skill_ids"] == [skill_id]
    assert "open_orders" in result["updated_functions"]
    assert (tmp_path / "store" / "skill_graph_code.py").exists()
    assert not (tmp_path / "store" / "android" / "skills.json").exists()
    graph = SkillGraphStore(store_dir=tmp_path / "store")
    assert graph.count_nodes > 0


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
    state_nodes = [
        node
        for node in graph.list_nodes(platform="android", app="com.example.app")
        if node.kind == "state"
    ]

    assert "resource_id='com.example:id/nav_orders'" in source
    assert result["contract_quality"]["quality"] == "canonical"
    assert result["contract_quality"]["canonical_node_count"] >= 1
    assert result["contract_quality"]["repaired_steps"][0]["selector"]["resource_id"] == "com.example:id/nav_orders"
    assert any(
        node.state_contract["signature"]["required"][0]["selector"].get("resource_id")
        == "com.example:id/nav_orders"
        for node in state_nodes
    )


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

    assert result["contract_quality"]["quality"] == "weak"
    assert result["contract_quality"]["canonical_node_count"] == 0
    assert result["contract_quality"]["weak_steps"][0]["reason"] == "single_text_selector"


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
        for item in required
    )


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
    assert [step["step_index"] for step in repaired.report["repaired_steps"]] == [1]


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
    assert "收货地址" in repaired.source
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
    assert selector == {"resource_id": "com.zhihu.android:id/input_text"}


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
async def test_postrun_writes_graph_projection_source_and_report(tmp_path: Path) -> None:
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

    assert "@state(" in source
    assert "@transition(" in source
    assert result["action_sequence"]["quality"] == "aligned"
    assert result["graph_projection"]["quality"] == "canonical"
    assert len(result["graph_projection"]["emitted_transitions"]) == 1
    assert result["code_graph_synced"] is True
    graph = SkillGraphStore(store_dir=tmp_path / "store")
    projected_edge_id = result["graph_projection"]["emitted_transitions"][0]["edge_id"]
    assert graph.get_edge(projected_edge_id) is not None
    assert all(node.node_id.startswith("code:") for node in graph.list_nodes())


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
