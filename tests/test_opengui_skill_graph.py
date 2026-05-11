from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np
import pytest

from opengui.skills.data import Skill, SkillStep
from opengui.skills.graph import (
    EDGE_STATUS_ACTIVE,
    EDGE_STATUS_DISABLED,
    NODE_KIND_AUXILIARY,
    NODE_KIND_STATE,
    NODE_STATUS_DEPRECATED,
    EdgeStats,
    GoalNodeResolver,
    GraphEdge,
    GraphNode,
    NodeStats,
    PathCompiler,
    SkillGraphStore,
    StateIdentifier,
    infer_app_hint_from_task,
)
from opengui.skills.reuser import SkillReuser
from opengui.skills.state_contract import (
    evaluate_state_contract,
    infer_state_contract,
    normalize_state_contract,
    score_state_contract,
    state_contract_fingerprint,
)


class _StableEmbedder:
    DIM = 32

    async def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            for token in re.findall(r"\w+", text.lower()):
                slot = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self.DIM
                vecs[i, slot] += 1.0
            norm = float(np.linalg.norm(vecs[i]))
            if norm > 0:
                vecs[i] /= norm
        return vecs


class _NoCallLLM:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def chat(self, messages, tools=None, tool_choice=None):
        self.calls.append(messages)
        raise AssertionError("LLM judge should not be called for confirmed graph resolution")


class _RecordingEvents:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record_event(self, event_type: str, **payload: object) -> None:
        self.events.append({"type": event_type, **payload})


def _contract(
    label: str,
    *,
    app: str = "com.example.app",
    activity_class: str | None = None,
    clickable: bool = False,
    resource_id: str | None = None,
) -> dict[str, object]:
    selector: dict[str, object] = {"text": label}
    if clickable:
        selector["clickable"] = True
    if resource_id:
        selector["resource_id"] = resource_id
    anchor: dict[str, object] = {"app_package": app}
    if activity_class:
        anchor["activity_class"] = activity_class
    return normalize_state_contract({
        "anchor": anchor,
        "signature": {
            "required": [
                {"selector": selector, "state": ["visible"] + (["clickable"] if clickable else [])}
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    }) or {}


def _resource_contract(
    resource_id: str,
    *,
    app: str = "com.example.app",
    clickable: bool = True,
    mask_rules: list[str] | None = None,
) -> dict[str, object]:
    selector: dict[str, object] = {"resource_id": resource_id}
    if clickable:
        selector["clickable"] = True
    return normalize_state_contract({
        "anchor": {"app_package": app},
        "signature": {
            "required": [
                {"selector": selector, "state": ["visible"] + (["clickable"] if clickable else [])}
            ],
            "forbidden": [],
        },
        "mask_rules": mask_rules if mask_rules is not None else ["counter", "temporary_recommendation"],
    }) or {}


def _skill(
    skill_id: str,
    *,
    app: str,
    first_state: str,
    second_state: str,
    first_selector: str,
    second_selector: str,
) -> Skill:
    first_contract = _contract(first_selector, app=app, clickable=True)
    second_contract = _contract(second_selector, app=app, clickable=True)
    return Skill(
        skill_id=skill_id,
        name=f"skill_{skill_id}",
        description=second_state,
        app=app,
        platform="android",
        steps=(
            SkillStep(
                action_type="tap",
                target=first_selector,
                valid_state=first_state,
                expected_state=second_state,
                state_contract=first_contract,
                fixed=True,
                fixed_values={"x": 10.0, "y": 10.0, "relative": True},
            ),
            SkillStep(
                action_type="tap",
                target=second_selector,
                valid_state=second_state,
                expected_state=f"{second_state} done",
                state_contract=second_contract,
                fixed=True,
                fixed_values={"x": 20.0, "y": 20.0, "relative": True},
            ),
        ),
    )


def _same_screen_skill() -> Skill:
    contract = _contract("Home", clickable=True)
    return Skill(
        skill_id="same-screen",
        name="same_screen",
        description="Stay on the same screen",
        app="com.example.app",
        platform="android",
        steps=(
            SkillStep(
                action_type="tap",
                target="Refresh",
                valid_state="Home screen is visible",
                expected_state="Home screen is still visible",
                state_contract=contract,
                fixed=True,
                fixed_values={"x": 10.0, "y": 10.0, "relative": True},
            ),
            SkillStep(
                action_type="tap",
                target="Refresh",
                valid_state="Home screen is still visible",
                expected_state="Home screen is still visible",
                state_contract=contract,
                fixed=True,
                fixed_values={"x": 10.0, "y": 10.0, "relative": True},
            ),
        ),
    )


def test_state_contract_fingerprint_is_stable_for_new_schema() -> None:
    contract = {
        "anchor": {
            "app_package": "com.example.app",
            "activity_class": "MainActivity",
        },
        "signature": {
            "required": [
                {
                    "selector": {"text": "Profile", "clickable": True},
                    "state": ["visible", "clickable"],
                },
                {
                    "selector": {"resource_id": "com.example:id/title"},
                    "state": ["visible"],
                },
            ],
            "forbidden": [
                {
                    "selector": {"text": "Loading"},
                    "state": ["visible"],
                },
            ],
        },
        "mask_rules": ["badge_count", "timestamp"],
    }
    normalized = normalize_state_contract(contract)
    assert normalized is not None
    assert normalized["fingerprint"] == state_contract_fingerprint(contract)

    shuffled = {
        "signature": {
            "forbidden": [
                {
                    "state": ["visible"],
                    "selector": {"text": "Loading"},
                }
            ],
            "required": [
                {
                    "state": ["clickable", "visible"],
                    "selector": {"clickable": True, "text": "Profile"},
                },
                {
                    "selector": {"resource_id": "com.example:id/title"},
                    "state": ["visible"],
                },
            ],
        },
        "mask_rules": ["timestamp", "badge_count"],
        "anchor": {
            "activity_class": "MainActivity",
            "app_package": "com.example.app",
        },
    }
    assert state_contract_fingerprint(shuffled) == normalized["fingerprint"]


def _first_required_selector(contract: dict[str, object]) -> dict[str, object]:
    required = contract["signature"]["required"]  # type: ignore[index]
    return required[0]["selector"]  # type: ignore[index]


def _xiaoheihe_trajectory() -> dict[str, object]:
    return {
        "agent_phase": [
            {
                "observation": {
                    "screen_width": 1000,
                    "screen_height": 2000,
                    "extra": {
                        "visible_text": ["首页", "黑盒商城", "我的"],
                        "clickable_text": ["首页", "黑盒商城", "我的"],
                        "resource_ids": [
                            "com.max.xiaoheihe:id/nav_home",
                            "com.max.xiaoheihe:id/nav_mall",
                        ],
                        "ui_tree": [
                            {
                                "text": "首页",
                                "resource_id": "com.max.xiaoheihe:id/nav_home",
                                "clickable": True,
                                "bounds": "[0,1800][300,2000]",
                            },
                            {
                                "text": "黑盒商城",
                                "resource_id": "com.max.xiaoheihe:id/nav_mall",
                                "clickable": True,
                                "bounds": "[300,1800][700,2000]",
                            },
                            {
                                "text": "我的",
                                "resource_id": "com.max.xiaoheihe:id/nav_me",
                                "clickable": True,
                                "bounds": "[700,1800][1000,2000]",
                            },
                        ],
                        "ui_tree_node_count": 3,
                    },
                }
            }
        ]
    }


def _xiaoheihe_extra() -> dict[str, object]:
    trajectory = _xiaoheihe_trajectory()
    return trajectory["agent_phase"][0]["observation"]["extra"]  # type: ignore[index]


def _write_transition_evidence(store_dir: Path, record: dict[str, object]) -> None:
    path = store_dir / "skill_graph_transition_evidence.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


def test_infer_state_contract_uses_real_xiaoheihe_label_for_exact_target() -> None:
    contract = infer_state_contract(
        {
            "action_type": "tap",
            "target": "黑盒商城",
            "parameters": {"x": 500, "y": 950, "relative": True},
            "valid_state": "黑盒商城 tab is visible and clickable",
            "expected_state": "Black Box Mall page is open",
        },
        trajectory=_xiaoheihe_trajectory(),
        app="com.max.xiaoheihe",
    )

    assert contract is not None
    selector = _first_required_selector(contract)
    assert selector == {"resource_id": "com.max.xiaoheihe:id/nav_mall"}


def test_inferred_resource_id_clickable_contract_evaluates_against_source_ui_tree() -> None:
    contract = infer_state_contract(
        {
            "action_type": "tap",
            "target": "黑盒商城",
            "parameters": {"x": 500, "y": 950, "relative": True},
            "valid_state": "黑盒商城 tab is visible and clickable",
            "expected_state": "Black Box Mall page is open",
        },
        trajectory=_xiaoheihe_trajectory(),
        app="com.max.xiaoheihe",
    )

    assert contract is not None
    assert evaluate_state_contract(
        contract,
        foreground_app="com.max.xiaoheihe",
        observation_extra=_xiaoheihe_extra(),
    ) is True


def test_state_contract_does_not_match_short_partial_selector_label() -> None:
    contract = normalize_state_contract({
        "anchor": {"app_package": "com.max.xiaoheihe"},
        "signature": {
            "required": [
                {
                    "selector": {"text": "我的订单"},
                    "state": ["visible", "clickable"],
                },
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    })

    score = score_state_contract(
        contract,
        foreground_app="com.max.xiaoheihe",
        observation_extra={
            "visible_text": ["关注", "推荐", "首页", "热点", "游戏库", "我"],
            "clickable_text": ["关注", "首页", "热点", "游戏库", "我"],
            "resource_ids": ["com.max.xiaoheihe:id/rg_main"],
        },
    )

    assert score == 0.0


def test_infer_app_hint_from_task_uses_known_graph_app_aliases() -> None:
    assert infer_app_hint_from_task(
        "打开小黑盒App。点击底部我的。打开黑盒商城。",
        platform="android",
        candidate_apps=["com.max.xiaoheihe"],
    ) == "com.max.xiaoheihe"


def test_state_contract_returns_none_when_required_evidence_is_unknown() -> None:
    contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.app", "activity_class": "MainActivity"},
        "signature": {
            "required": [
                {"selector": {"text": "Profile"}, "state": ["visible"]},
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    })

    assert contract is not None
    assert evaluate_state_contract(
        contract,
        foreground_app="com.example.app",
        observation_extra={"visible_text": ["Profile"]},
    ) is None


def test_compound_selector_requires_each_field_to_match() -> None:
    contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {
                    "selector": {
                        "resource_id": "com.example:id/profile",
                        "text": "Profile",
                    },
                    "state": ["visible"],
                },
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    })

    assert contract is not None
    assert evaluate_state_contract(
        contract,
        foreground_app="com.example.app",
        observation_extra={
            "visible_text": ["Profile"],
            "resource_ids": ["com.example:id/settings"],
            "ui_tree_node_count": 2,
        },
    ) is False


def test_compound_selector_matches_same_ui_tree_node() -> None:
    contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {
                    "selector": {
                        "resource_id": "com.example:id/profile",
                        "text": "Profile",
                    },
                    "state": ["visible", "clickable"],
                },
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    })

    assert contract is not None
    assert evaluate_state_contract(
        contract,
        foreground_app="com.example.app",
        observation_extra={
            "ui_tree": [
                {
                    "text": "Profile",
                    "resource_id": "com.example:id/profile",
                    "clickable": True,
                },
            ],
            "ui_tree_node_count": 1,
        },
    ) is True


def test_infer_state_contract_bridges_semantic_target_to_coordinate_grounded_label() -> None:
    contract = infer_state_contract(
        {
            "action_type": "tap",
            "target": "Me tab in bottom navigation",
            "parameters": {"x": 500, "y": 950, "relative": True},
            "valid_state": "the bottom navigation is visible",
            "expected_state": "Black Box Mall page is open",
        },
        trajectory=_xiaoheihe_trajectory(),
        app="com.max.xiaoheihe",
    )

    assert contract is not None
    selector = _first_required_selector(contract)
    assert selector == {"resource_id": "com.max.xiaoheihe:id/nav_mall"}
    assert "Me tab in bottom navigation" not in selector.values()


def test_infer_state_contract_bridges_semantic_target_to_context_grounded_label() -> None:
    contract = infer_state_contract(
        {
            "action_type": "tap",
            "target": "My Orders button",
            "parameters": {},
            "valid_state": "我的订单 is visible and clickable on the mall page",
            "expected_state": "orders page opens",
        },
        trajectory={
            "agent_phase": [
                {
                    "observation": {
                        "extra": {
                            "visible_text": ["黑盒商城", "我的订单", "购物车"],
                            "clickable_text": ["我的订单", "购物车"],
                            "ui_tree": [
                                {
                                    "text": "我的订单",
                                    "resource_id": "com.max.xiaoheihe:id/my_orders",
                                    "clickable": True,
                                }
                            ],
                            "ui_tree_node_count": 3,
                        }
                    }
                }
            ]
        },
        app="com.max.xiaoheihe",
    )

    assert contract is not None
    selector = _first_required_selector(contract)
    assert selector == {"resource_id": "com.max.xiaoheihe:id/my_orders"}
    assert "My Orders button" not in selector.values()


def test_infer_state_contract_rejects_dynamic_feed_title_selector() -> None:
    contract = infer_state_contract(
        {
            "action_type": "tap",
            "target": "这篇帖子详细聊聊今天版本更新后的新配队和强度变化",
            "parameters": {},
            "valid_state": "the feed item is visible",
            "expected_state": "the post detail page opens",
        },
        trajectory={
            "agent_phase": [
                {
                    "observation": {
                        "extra": {
                            "visible_text": [
                                "首页",
                                "热点",
                                "我",
                                "这篇帖子详细聊聊今天版本更新后的新配队和强度变化",
                                "12分钟前",
                            ],
                            "clickable_text": [
                                "首页",
                                "热点",
                                "我",
                                "这篇帖子详细聊聊今天版本更新后的新配队和强度变化",
                            ],
                            "resource_ids": [
                                "com.max.xiaoheihe:id/nav_home",
                                "com.max.xiaoheihe:id/nav_me",
                                "com.max.xiaoheihe:id/tv_post_title",
                            ],
                            "ui_tree": [
                                {
                                    "text": "这篇帖子详细聊聊今天版本更新后的新配队和强度变化",
                                    "resource_id": "com.max.xiaoheihe:id/tv_post_title",
                                    "clickable": True,
                                }
                            ],
                            "ui_tree_node_count": 4,
                        }
                    }
                }
            ]
        },
        app="com.max.xiaoheihe",
    )

    assert contract is None


def test_infer_state_contract_does_not_promote_abstract_target_without_grounding() -> None:
    contract = infer_state_contract(
        {
            "action_type": "tap",
            "target": "Me tab in bottom navigation",
            "parameters": {},
            "valid_state": "the bottom navigation is visible",
            "expected_state": "the requested tab opens",
        },
        trajectory=_xiaoheihe_trajectory(),
        app="com.max.xiaoheihe",
    )

    assert contract is None


@pytest.mark.asyncio
async def test_ingest_xiaoheihe_skill_promotes_grounded_contracts_to_state_nodes(
    tmp_path: Path,
) -> None:
    mall_contract = infer_state_contract(
        {
            "action_type": "tap",
            "target": "Me tab in bottom navigation",
            "parameters": {"x": 500, "y": 950, "relative": True},
            "valid_state": "bottom navigation is visible",
            "expected_state": "Black Box Mall opens",
        },
        trajectory=_xiaoheihe_trajectory(),
        app="com.max.xiaoheihe",
    )
    orders_contract = infer_state_contract(
        {
            "action_type": "tap",
            "target": "My Orders button",
            "parameters": {},
            "valid_state": "我的订单 is visible and clickable on the 黑盒商城 page",
            "expected_state": "My Orders page opens",
        },
        trajectory={
            "agent_phase": [
                {
                    "observation": {
                        "extra": {
                            "visible_text": ["黑盒商城", "我的订单"],
                            "clickable_text": ["我的订单"],
                            "ui_tree": [
                                {
                                    "text": "我的订单",
                                    "resource_id": "com.max.xiaoheihe:id/my_orders",
                                    "clickable": True,
                                }
                            ],
                            "ui_tree_node_count": 2,
                        }
                    }
                }
            ]
        },
        app="com.max.xiaoheihe",
    )
    assert mall_contract is not None
    assert orders_contract is not None

    skill = Skill(
        skill_id="xhh-grounded",
        name="xhh_orders",
        description="Open XiaoHeiHe orders",
        app="com.max.xiaoheihe",
        platform="android",
        steps=(
            SkillStep(
                action_type="tap",
                target="Me tab in bottom navigation",
                valid_state="bottom navigation is visible",
                expected_state="Black Box Mall opens",
                state_contract=mall_contract,
                fixed=True,
                fixed_values={"x": 500, "y": 950, "relative": True},
            ),
            SkillStep(
                action_type="tap",
                target="My Orders button",
                valid_state="我的订单 is visible and clickable on the 黑盒商城 page",
                expected_state="My Orders page opens",
                state_contract=orders_contract,
                fixed=True,
                fixed_values={},
            ),
        ),
    )

    store = SkillGraphStore(store_dir=tmp_path / "graph")
    await store.ingest_skill(skill)

    state_selectors = [
        _first_required_selector(node.state_contract)
        for node in store.list_nodes()
        if node.state_contract
    ]
    assert {"resource_id": "com.max.xiaoheihe:id/nav_mall"} in state_selectors
    assert {"resource_id": "com.max.xiaoheihe:id/my_orders"} in state_selectors
    assert all(
        selector.get("text") not in {"Me tab in bottom navigation", "My Orders button"}
        for selector in state_selectors
    )


@pytest.mark.asyncio
async def test_ingest_xiaoheihe_skill_derives_state_nodes_from_page_profiles(
    tmp_path: Path,
) -> None:
    skill = Skill(
        skill_id="xhh-profile-derived",
        name="xhh_profile_derived",
        description="Navigate to XiaoHeiHe orders",
        app="com.max.xiaoheihe",
        platform="android",
        steps=(
            SkillStep(
                action_type="open_app",
                target="Launch com.max.xiaoheihe",
                valid_state="No need to verify",
                expected_state="App home screen is visible",
                fixed=True,
                fixed_values={"text": "com.max.xiaoheihe"},
            ),
            SkillStep(
                action_type="tap",
                target="我",
                valid_state="App home screen is visible",
                expected_state="User profile page is displayed",
                fixed=True,
                fixed_values={"x": 898.0, "y": 948.0, "relative": True},
            ),
            SkillStep(
                action_type="tap",
                target="我的订单",
                valid_state="User profile page is visible",
                expected_state="Order list page is displayed",
                fixed=True,
                fixed_values={"x": 300.0, "y": 293.0, "relative": True},
            ),
        ),
    )
    home_profile = {
        "foreground_app": "com.max.xiaoheihe",
        "app": "com.max.xiaoheihe",
        "platform": "android",
        "visible_text": ["关注", "推荐", "首页", "热点", "游戏库", "我"],
        "clickable_text": ["首页", "热点", "游戏库", "我"],
        "resource_ids": ["com.max.xiaoheihe:id/rg_main", "com.max.xiaoheihe:id/rb_5"],
    }
    profile_page = {
        "foreground_app": "com.max.xiaoheihe",
        "app": "com.max.xiaoheihe",
        "platform": "android",
        "visible_text": ["黑盒商城", "我的订单"],
        "clickable_text": ["黑盒商城", "我的订单"],
        "resource_ids": ["com.max.xiaoheihe:id/vg_menu_mall_v2"],
    }
    order_page = {
        "foreground_app": "com.max.xiaoheihe",
        "app": "com.max.xiaoheihe",
        "platform": "android",
        "visible_text": ["我的订单", "全部订单", "成功订单", "失败订单"],
        "clickable_text": ["全部订单", "成功订单", "失败订单"],
        "resource_ids": ["com.max.xiaoheihe:id/tv_appbar_title"],
    }

    store = SkillGraphStore(store_dir=tmp_path / "graph")
    await store.ingest_skill(
        skill,
        node_profiles={
            1: home_profile,
            2: profile_page,
            "terminal": order_page,
        },
    )

    nodes = store.list_nodes(platform="android", app="com.max.xiaoheihe")
    state_descriptions = {node.description for node in nodes if node.kind == "state" and node.state_contract}
    assert "App home screen is visible" in state_descriptions
    assert "User profile page is visible" in state_descriptions
    assert "Order list page is displayed" in state_descriptions
    assert {
        (edge.action_type, edge.target, edge.status)
        for edge in store.list_edges(platform="android", app="com.max.xiaoheihe")
    } >= {
        ("tap", "我", EDGE_STATUS_ACTIVE),
        ("tap", "我的订单", EDGE_STATUS_ACTIVE),
    }


@pytest.mark.asyncio
async def test_ingest_skill_skips_same_node_edges(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")

    await store.ingest_skill(_same_screen_skill())

    assert not any(
        edge.status == EDGE_STATUS_ACTIVE and edge.source_node_id == edge.target_node_id
        for edge in store.list_edges()
    )


def test_sanitize_canonical_graph_disables_same_node_active_edges(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    node = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-self",
            app="com.example.app",
            platform="android",
            source_node_id=node.node_id,
            target_node_id=node.node_id,
            action_type="tap",
            target="Refresh",
            precondition=node.state_contract,
        )
    )

    counts = store.sanitize_canonical_graph()

    assert counts == {"nodes": 0, "edges": 1}
    assert store.get_edge(edge.edge_id) is not None
    assert store.get_edge(edge.edge_id).status == EDGE_STATUS_DISABLED
    assert not any(
        active.edge_id == edge.edge_id
        for active in store.list_edges(status=EDGE_STATUS_ACTIVE)
    )


def test_sanitize_canonical_graph_disables_same_node_state_edges(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    mall = store.upsert_node(
        GraphNode(
            node_id="mall-node",
            app="com.max.xiaoheihe",
            platform="android",
            description="The Heihei Mall page is loaded.",
            state_contract=_contract("黑盒商城", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-mall",
        )
    )
    loop = store.upsert_edge(
        GraphEdge(
            edge_id="edge-loop",
            app="com.max.xiaoheihe",
            platform="android",
            source_node_id=mall.node_id,
            target_node_id=mall.node_id,
            action_type="tap",
            target="黑盒商城",
            parameters={"x": 312.0, "y": 900.0, "relative": True},
            precondition=mall.state_contract,
            status=EDGE_STATUS_DISABLED,
        )
    )

    counts = store.sanitize_canonical_graph()

    assert counts["edges"] == 0
    assert store.get_edge(loop.edge_id).status == EDGE_STATUS_DISABLED


def test_sanitize_canonical_graph_merges_duplicate_active_state_nodes(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    survivor = GraphNode(
        node_id="node-b",
        app="com.example.app",
        platform="android",
        description="Home screen duplicate with more context",
        state_contract=_contract("Home", clickable=True),
        stats=NodeStats(reach_count=8, contract_match_count=5, contract_miss_count=2),
        skill_ids=("skill-b",),
        retrieval_profile={"page_summary": "Landing page"},
        fingerprint="fp-home",
    ).normalized()
    loser = GraphNode(
        node_id="node-a",
        app="com.example.app",
        platform="android",
        description="Home screen",
        state_contract=_contract("Home", clickable=True),
        stats=NodeStats(reach_count=3, contract_match_count=1, contract_miss_count=1),
        skill_ids=("skill-a",),
        retrieval_profile={"page_title": "Home"},
        fingerprint="fp-home",
    ).normalized()
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.example.app",
            platform="android",
            description="Settings screen",
            state_contract=_contract("Settings", clickable=True),
            fingerprint="fp-settings",
        )
    )
    store._nodes[survivor.node_id] = survivor
    store._nodes[loser.node_id] = loser
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-from-loser",
            app="com.example.app",
            platform="android",
            source_node_id=loser.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Settings",
            precondition=loser.state_contract,
            stats=EdgeStats(attempt_count=4, success_count=2),
        )
    )

    counts = store.sanitize_canonical_graph()

    assert counts["nodes"] == 1
    assert counts["edges"] == 1
    assert store.get_node(survivor.node_id) is not None
    assert store.get_node(loser.node_id) is None
    assert store.get_node(survivor.node_id).skill_ids == ("skill-b", "skill-a")
    assert store.get_node(survivor.node_id).stats.reach_count == 11
    assert store.get_node(survivor.node_id).retrieval_profile == {
        "page_summary": "Landing page",
        "page_title": "Home",
    }
    rewritten = store.get_edge(edge.edge_id)
    assert rewritten is not None
    assert rewritten.source_node_id == survivor.node_id
    assert rewritten.target_node_id == target.node_id


def test_sanitize_canonical_graph_merges_duplicate_edges_during_node_compaction(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    survivor = GraphNode(
        node_id="node-b",
        app="com.example.app",
        platform="android",
        description="Home screen duplicate with more context",
        state_contract=_contract("Home", clickable=True),
        stats=NodeStats(reach_count=8, contract_match_count=5, contract_miss_count=2),
        skill_ids=("skill-b",),
        retrieval_profile={"page_summary": "Landing page"},
        fingerprint="fp-home",
    ).normalized()
    loser = GraphNode(
        node_id="node-a",
        app="com.example.app",
        platform="android",
        description="Home screen",
        state_contract=_contract("Home", clickable=True),
        stats=NodeStats(reach_count=3, contract_match_count=1, contract_miss_count=1),
        skill_ids=("skill-a",),
        retrieval_profile={"page_title": "Home"},
        fingerprint="fp-home",
    ).normalized()
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.example.app",
            platform="android",
            description="Settings screen",
            state_contract=_contract("Settings", clickable=True),
            fingerprint="fp-settings",
        )
    )
    store._nodes[survivor.node_id] = survivor
    store._nodes[loser.node_id] = loser
    survivor_edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-from-survivor",
            app="com.example.app",
            platform="android",
            source_node_id=survivor.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Settings",
            precondition=survivor.state_contract,
            stats=EdgeStats(attempt_count=6, success_count=4),
        )
    )
    loser_edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-from-loser",
            app="com.example.app",
            platform="android",
            source_node_id=loser.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Settings",
            precondition=loser.state_contract,
            stats=EdgeStats(attempt_count=4, success_count=2),
        )
    )

    counts = store.sanitize_canonical_graph()

    assert counts["nodes"] == 1
    assert counts["edges"] == 1
    active_edges = store.list_edges(platform="android", app="com.example.app", status=EDGE_STATUS_ACTIVE)
    assert len(active_edges) == 1
    assert active_edges[0].source_node_id == survivor.node_id
    assert active_edges[0].target_node_id == target.node_id
    assert store.get_edge(survivor_edge.edge_id) is not None
    assert store.get_edge(loser_edge.edge_id) is None


def test_compact_canonical_graph_hard_aliases_verified_auxiliary_node(tmp_path: Path) -> None:
    store_dir = tmp_path / "graph"
    store = SkillGraphStore(store_dir=store_dir)
    canonical = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_resource_contract("com.example:id/home"),
            stats=NodeStats(reach_count=4, contract_match_count=3, contract_miss_count=1),
            skill_ids=("skill-home",),
            retrieval_profile={
                "foreground_app": "com.example.app",
                "page_title": "Home",
                "visible_text": ["Home"],
                "clickable_text": ["Home"],
                "resource_ids": ["com.example:id/home"],
                "stable_controls": [
                    {
                        "text": "Home",
                        "resource_id": "com.example:id/home",
                        "clickable": True,
                    }
                ],
            },
            fingerprint="fp-home",
        )
    )
    alias = store.upsert_node(
        GraphNode(
            node_id="node-home-aux",
            app="com.example.app",
            platform="android",
            description="Home shell",
            kind=NODE_KIND_AUXILIARY,
            stats=NodeStats(reach_count=2, contract_match_count=1, contract_miss_count=1),
            skill_ids=("skill-alias",),
            retrieval_profile={
                "foreground_app": "com.example.app",
                "page_title": "Home",
                "visible_text": ["Home"],
                "clickable_text": ["Home"],
                "resource_ids": ["com.example:id/home"],
                "stable_controls": [
                    {
                        "text": "Home",
                        "resource_id": "com.example:id/home",
                        "clickable": True,
                    }
                ],
            },
            fingerprint="fp-home-aux",
        )
    )
    source = store.upsert_node(
        GraphNode(
            node_id="node-source",
            app="com.example.app",
            platform="android",
            description="Source screen",
            state_contract=_contract("Source", clickable=True),
            fingerprint="fp-source",
        )
    )
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.example.app",
            platform="android",
            description="Target screen",
            state_contract=_contract("Target", clickable=True),
            fingerprint="fp-target",
        )
    )
    first_edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-source-alias",
            app="com.example.app",
            platform="android",
            source_node_id=source.node_id,
            target_node_id=alias.node_id,
            action_type="tap",
            target="Home",
            precondition=source.state_contract,
        )
    )
    second_edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-alias-target",
            app="com.example.app",
            platform="android",
            source_node_id=alias.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Target",
            precondition=alias.state_contract,
        )
    )
    _write_transition_evidence(
        store_dir,
        {
            "timestamp": time.time(),
            "platform": "android",
            "app": "com.example.app",
            "source_node_id": alias.node_id,
            "action_type": "tap",
            "edge_kind": "action",
            "target_node_id": canonical.node_id,
            "reason": "verified_same_page",
            "candidate_node_ids": [canonical.node_id],
            "anchor": {"app_package": "com.example.app", "activity_class": "MainActivity"},
            "selector_signature": {
                "resource_ids": ["com.example:id/home"],
                "content_descs": ["Home"],
                "texts": ["Home"],
            },
        },
    )

    report = store.compact_canonical_graph()

    assert report["nodes"] == 1
    assert report["edges"] == 2
    assert report["exact_merges"] == 0
    assert report["hard_aliases"] == 1
    assert report["candidate_aliases"] == 0
    merged = store.get_node(canonical.node_id)
    assert merged is not None
    assert store.get_node(alias.node_id) is None
    assert merged.stats.reach_count == 6
    assert merged.skill_ids == ("skill-home", "skill-alias")
    assert merged.retrieval_profile == {
        "foreground_app": "com.example.app",
        "page_title": "Home",
        "visible_text": ["Home"],
        "clickable_text": ["Home"],
        "resource_ids": ["com.example:id/home"],
        "stable_controls": [
            {
                "text": "Home",
                "resource_id": "com.example:id/home",
            }
        ],
    }
    rewritten_source = store.get_edge(first_edge.edge_id)
    rewritten_target = store.get_edge(second_edge.edge_id)
    assert rewritten_source is not None
    assert rewritten_source.target_node_id == canonical.node_id
    assert rewritten_target is not None
    assert rewritten_target.source_node_id == canonical.node_id
    audit_path = store_dir / "skill_graph_compaction_log.jsonl"
    audit_record = json.loads(audit_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert audit_record["merge_kind"] == "hard_alias"
    assert audit_record["reason"] == "verified_same_page"
    assert audit_record["canonical_node_id"] == canonical.node_id
    assert audit_record["alias_node_id"] == alias.node_id


def test_compact_canonical_graph_preserves_ambiguous_auxiliary_candidate(tmp_path: Path) -> None:
    store_dir = tmp_path / "graph"
    store = SkillGraphStore(store_dir=store_dir)
    canonical = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_resource_contract("com.example:id/home"),
            fingerprint="fp-home",
        )
    )
    alias = store.upsert_node(
        GraphNode(
            node_id="node-home-aux",
            app="com.example.app",
            platform="android",
            description="Home shell",
            kind=NODE_KIND_AUXILIARY,
            retrieval_profile={
                "foreground_app": "com.example.app",
                "page_title": "Home",
                "visible_text": ["Home"],
                "clickable_text": ["Home"],
                "resource_ids": ["com.example:id/home"],
                "stable_controls": [
                    {
                        "text": "Home",
                        "resource_id": "com.example:id/home",
                        "clickable": True,
                    }
                ],
            },
            fingerprint="fp-home-aux",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-alias",
            app="com.example.app",
            platform="android",
            source_node_id=alias.node_id,
            target_node_id=canonical.node_id,
            action_type="tap",
            target="Home",
            precondition=None,
        )
    )
    _write_transition_evidence(
        store_dir,
        {
            "timestamp": time.time(),
            "platform": "android",
            "app": "com.example.app",
            "source_node_id": alias.node_id,
            "action_type": "tap",
            "edge_kind": "action",
            "target_node_id": canonical.node_id,
            "reason": "ambiguous_candidate",
            "candidate_node_ids": [canonical.node_id],
        },
    )

    report = store.compact_canonical_graph()

    assert report["nodes"] == 0
    assert report["edges"] == 0
    assert report["exact_merges"] == 0
    assert report["hard_aliases"] == 0
    assert report["candidate_aliases"] == 1
    assert store.get_node(alias.node_id) is not None
    assert store.get_node(canonical.node_id) is not None
    assert not (store_dir / "skill_graph_compaction_log.jsonl").exists()


def test_compact_canonical_graph_is_idempotent(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    survivor = store.upsert_node(
        GraphNode(
            node_id="node-home-a",
            app="com.example.app",
            platform="android",
            description="Home screen duplicate with more context",
            state_contract=_contract("Home", clickable=True),
            stats=NodeStats(reach_count=8, contract_match_count=5, contract_miss_count=2),
            skill_ids=("skill-a",),
            retrieval_profile={"page_summary": "Landing page"},
            fingerprint="fp-home",
        ).normalized()
    )
    loser = GraphNode(
        node_id="node-home-b",
        app="com.example.app",
        platform="android",
        description="Home screen",
        state_contract=_contract("Home", clickable=True),
        stats=NodeStats(reach_count=3, contract_match_count=1, contract_miss_count=1),
        skill_ids=("skill-b",),
        retrieval_profile={"page_title": "Home"},
        fingerprint="fp-home",
    ).normalized()
    store._nodes[loser.node_id] = loser
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.example.app",
            platform="android",
            description="Settings screen",
            state_contract=_contract("Settings", clickable=True),
            fingerprint="fp-settings",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-from-loser",
            app="com.example.app",
            platform="android",
            source_node_id=loser.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Settings",
            precondition=loser.state_contract,
            stats=EdgeStats(attempt_count=4, success_count=2),
        )
    )
    store._mark_index_dirty(platform="android", app="com.example.app")

    first = store.compact_canonical_graph()
    second = store.compact_canonical_graph()

    assert first["nodes"] == 1
    assert first["edges"] == 1
    assert first["exact_merges"] == 1
    assert second == {"nodes": 0, "edges": 0, "exact_merges": 0, "hard_aliases": 0, "candidate_aliases": 0}
    assert store.get_node(loser.node_id) is None
    assert store.get_node(survivor.node_id) is not None


def test_canonicality_report_blocks_unanchored_state_nodes(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    legacy = GraphNode(
        node_id="legacy-root",
        app="com.max.xiaoheihe",
        platform="android",
        description="Launch / root placeholder",
        state_contract=None,
        kind=NODE_KIND_STATE,
        fingerprint="legacy-root",
    ).normalized()
    store._nodes[legacy.node_id] = legacy

    report = store.canonicality_report(platform="android", app="com.max.xiaoheihe")

    assert report.ready_for_graph_only is False
    assert report.active_state_nodes == 1
    assert report.anchored_state_nodes == 0
    assert report.unanchored_state_nodes == 1
    assert "unanchored_state_nodes" in report.blocking_reasons


def test_canonicality_report_blocks_selectorless_state_contracts(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    legacy = GraphNode(
        node_id="selectorless",
        app="com.example.app",
        platform="android",
        description="Selectorless placeholder",
        state_contract=normalize_state_contract({
            "anchor": {"app_package": "com.example.app"},
            "signature": {
                "required": [{"state": ["visible"]}],
                "forbidden": [],
            },
            "mask_rules": [],
        }),
        kind=NODE_KIND_STATE,
        fingerprint="selectorless",
    ).normalized()
    store._nodes[legacy.node_id] = legacy

    report = store.canonicality_report(platform="android", app="com.example.app")

    assert report.ready_for_graph_only is False
    assert report.active_state_nodes == 1
    assert report.anchored_state_nodes == 0
    assert report.unanchored_state_nodes == 1
    assert "unanchored_state_nodes" in report.blocking_reasons


def test_upsert_node_downgrades_noncanonical_state_placeholders(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    node = store.upsert_node(
        GraphNode(
            node_id="legacy-root",
            app="com.example.app",
            platform="android",
            description="Legacy unanchored state",
            state_contract=None,
            kind=NODE_KIND_STATE,
            fingerprint="legacy-root",
        )
    )

    assert node.kind == NODE_KIND_AUXILIARY
    assert node.state_contract is None
    assert store.get_node(node.node_id).kind == NODE_KIND_AUXILIARY
    assert not store.list_nodes(kind=NODE_KIND_STATE)


def test_upsert_node_preserves_existing_canonical_state_when_placeholder_reappears(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    existing = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    updated = store.upsert_node(
        GraphNode(
            node_id=existing.node_id,
            app="com.example.app",
            platform="android",
            description="Placeholder copy",
            state_contract=None,
            kind=NODE_KIND_STATE,
            fingerprint="fp-home",
        )
    )

    assert updated.node_id == existing.node_id
    assert updated.kind == NODE_KIND_STATE
    assert updated.state_contract == existing.state_contract
    assert store.get_node(existing.node_id).kind == NODE_KIND_STATE


def test_runtime_index_excludes_active_same_node_edges(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    node = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-self-active",
            app="com.example.app",
            platform="android",
            source_node_id=node.node_id,
            target_node_id=node.node_id,
            action_type="tap",
            target="Refresh",
            precondition=node.state_contract,
            status=EDGE_STATUS_ACTIVE,
        )
    )

    assert edge.status == EDGE_STATUS_ACTIVE
    assert edge not in store.outgoing_edges(node.node_id)


def test_auxiliary_node_persists_retrieval_profile_across_save_load(tmp_path: Path) -> None:
    store_dir = tmp_path / "graph"
    store = SkillGraphStore(store_dir=store_dir)
    node = store.upsert_node(
        GraphNode(
            node_id="aux-profile",
            app="com.example.app",
            platform="android",
            description="Floating sheet",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            fingerprint="aux-profile",
            retrieval_profile={
                "page_title": "Settings",
                "visible_text": ["Settings", "Wi-Fi"],
                "stable_controls": [
                    {"text": "Wi-Fi", "resource_id": "com.example:id/wifi"},
                ],
            },
        )
    )

    loaded = SkillGraphStore(store_dir=store_dir)
    restored = loaded.get_node(node.node_id)

    assert restored is not None
    assert restored.kind == NODE_KIND_AUXILIARY
    assert restored.retrieval_profile == {
        "page_title": "Settings",
        "visible_text": ["Settings", "Wi-Fi"],
        "stable_controls": [
            {"text": "Wi-Fi", "resource_id": "com.example:id/wifi"},
        ],
    }


def test_graph_index_limits_stable_anchor_candidates_to_current_app(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    expected = store.upsert_node(
        GraphNode(
            node_id="node-xhh-home",
            app="com.max.xiaoheihe",
            platform="android",
            description="Xiaoheihe home",
            state_contract=_contract("Home", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-xhh-home",
        )
    )
    store.upsert_node(
        GraphNode(
            node_id="node-other-home",
            app="com.example.other",
            platform="android",
            description="Other app home",
            state_contract=_contract("Home", app="com.example.other", clickable=True),
            fingerprint="fp-other-home",
        )
    )
    store.upsert_node(
        GraphNode(
            node_id="node-xhh-old",
            app="com.max.xiaoheihe",
            platform="android",
            description="Deprecated XHH home",
            state_contract=_contract("Old", app="com.max.xiaoheihe", clickable=True),
            status="deprecated",
            fingerprint="fp-xhh-old",
        )
    )
    store.upsert_node(
        GraphNode(
            node_id="node-xhh-empty",
            app="com.max.xiaoheihe",
            platform="android",
            description="Auxiliary XHH node",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            fingerprint="fp-xhh-empty",
        )
    )

    candidates = store.stable_anchor_candidates(platform="android", app="com.max.xiaoheihe")

    assert [node.node_id for node in candidates] == [expected.node_id]
    assert store.index_stats()["stable_anchor_scan_count"] == 1
    cached_candidates = store.stable_anchor_candidates(platform="android", app="com.max.xiaoheihe")
    assert [node.node_id for node in cached_candidates] == [expected.node_id]
    assert store.index_stats()["stable_anchor_scan_count"] == 1


def test_graph_index_activity_bucket_falls_back_to_app_bucket(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    main = store.upsert_node(
        GraphNode(
            node_id="node-main",
            app="com.max.xiaoheihe",
            platform="android",
            description="Main activity",
            state_contract=_contract(
                "Home",
                app="com.max.xiaoheihe",
                activity_class=".MainActivity",
                clickable=True,
            ),
            fingerprint="fp-main",
        )
    )
    detail = store.upsert_node(
        GraphNode(
            node_id="node-detail",
            app="com.max.xiaoheihe",
            platform="android",
            description="Detail activity",
            state_contract=_contract(
                "Detail",
                app="com.max.xiaoheihe",
                activity_class=".DetailActivity",
                clickable=True,
            ),
            fingerprint="fp-detail",
        )
    )

    activity_candidates = store.stable_anchor_candidates(
        platform="android",
        app="com.max.xiaoheihe",
        activity_class=".MainActivity",
    )
    assert [node.node_id for node in activity_candidates] == [main.node_id]
    assert store.index_stats()["stable_anchor_scan_count"] == 1

    fallback_candidates = store.stable_anchor_candidates(
        platform="android",
        app="com.max.xiaoheihe",
        activity_class=".MissingActivity",
    )

    assert [node.node_id for node in fallback_candidates] == [detail.node_id, main.node_id]
    assert store.index_stats()["stable_anchor_scan_count"] == 2


def test_graph_index_scan_count_tracks_filtered_candidates(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    kept = store.upsert_node(
        GraphNode(
            node_id="node-kept",
            app="com.max.xiaoheihe",
            platform="android",
            description="Kept",
            state_contract=_contract("Kept", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-kept",
        )
    )
    removed = store.upsert_node(
        GraphNode(
            node_id="node-removed",
            app="com.max.xiaoheihe",
            platform="android",
            description="Removed",
            state_contract=_contract("Removed", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-removed",
        )
    )

    assert [node.node_id for node in store.stable_anchor_candidates(platform="android", app="com.max.xiaoheihe")] == [
        kept.node_id,
        removed.node_id,
    ]
    store._nodes.pop(removed.node_id)

    candidates = store.stable_anchor_candidates(platform="android", app="com.max.xiaoheihe")

    assert [node.node_id for node in candidates] == [kept.node_id]
    assert store.index_stats()["stable_anchor_scan_count"] == 1


def test_graph_index_rebuilds_after_node_and_edge_upsert(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    source = store.upsert_node(
        GraphNode(
            node_id="node-source",
            app="com.max.xiaoheihe",
            platform="android",
            description="Home",
            state_contract=_contract("Home", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-source",
        )
    )
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.max.xiaoheihe",
            platform="android",
            description="Settings",
            state_contract=_contract("Settings", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-target",
        )
    )

    assert store.outgoing_edges(source.node_id) == []

    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-source-target",
            app="com.max.xiaoheihe",
            platform="android",
            source_node_id=source.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Settings",
            precondition=source.state_contract,
        )
    )

    assert store.outgoing_edges(source.node_id) == [edge]


def test_graph_index_invalidation_after_set_node_status(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    source = store.upsert_node(
        GraphNode(
            node_id="node-source",
            app="com.example.app",
            platform="android",
            description="Source",
            state_contract=_contract("Source", app="com.example.app", clickable=True),
            fingerprint="fp-source",
        )
    )
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.example.app",
            platform="android",
            description="Target",
            state_contract=_contract("Target", app="com.example.app", clickable=True),
            fingerprint="fp-target",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-source-target",
            app="com.example.app",
            platform="android",
            source_node_id=source.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Target",
            precondition=source.state_contract,
        )
    )

    assert [node.node_id for node in store.stable_anchor_candidates(platform="android", app="com.example.app")] == [
        source.node_id,
        target.node_id,
    ]
    assert [edge.edge_id for edge in store.outgoing_edges(source.node_id)] == [edge.edge_id]

    store.set_node_status(source.node_id, status="deprecated")

    assert [node.node_id for node in store.stable_anchor_candidates(platform="android", app="com.example.app")] == [
        target.node_id,
    ]
    assert store.outgoing_edges(source.node_id) == []


@pytest.mark.parametrize("save", [False, True])
def test_sanitize_canonical_graph_keeps_index_consistent(tmp_path: Path, save: bool) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    state = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    source_state = store.upsert_node(
        GraphNode(
            node_id="node-state-shell",
            app="com.example.app",
            platform="android",
            description="State shell",
            state_contract=None,
            fingerprint="fp-state-shell",
        )
    )
    assert source_state.kind == NODE_KIND_AUXILIARY
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-launch-home",
            app="com.example.app",
            platform="android",
            source_node_id=source_state.node_id,
            target_node_id=state.node_id,
            action_type="open_app",
            target="Example",
        )
    )

    counts = store.sanitize_canonical_graph(save=save)

    assert counts == {"nodes": 0, "edges": 1}
    assert store.get_node(source_state.node_id).kind == NODE_KIND_AUXILIARY
    assert [node.node_id for node in store.stable_anchor_candidates(platform="android", app="com.example.app")] == [
        state.node_id,
    ]
    assert store.outgoing_edges(source_state.node_id) == []
    assert store.get_edge(edge.edge_id).status == EDGE_STATUS_DISABLED


def test_skill_graph_store_round_trip_preserves_lookup_semantics(tmp_path: Path) -> None:
    store_dir = tmp_path / "graph"
    store = SkillGraphStore(store_dir=store_dir)
    source = store.upsert_node(
        GraphNode(
            node_id="node-source",
            app="com.example.app",
            platform="android",
            description="Source",
            state_contract=_contract("Source", app="com.example.app", clickable=True),
            fingerprint="fp-source",
        )
    )
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.example.app",
            platform="android",
            description="Target",
            state_contract=_contract("Target", app="com.example.app", clickable=True),
            fingerprint="fp-target",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-source-target",
            app="com.example.app",
            platform="android",
            source_node_id=source.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Target",
            precondition=source.state_contract,
        )
    )

    assert [node.node_id for node in store.stable_anchor_candidates(platform="android", app="com.example.app")] == [
        source.node_id,
        target.node_id,
    ]
    assert [edge.edge_id for edge in store.outgoing_edges(source.node_id)] == [edge.edge_id]

    store.save()
    reloaded = SkillGraphStore(store_dir=store_dir)

    assert [node.node_id for node in reloaded.stable_anchor_candidates(platform="android", app="com.example.app")] == [
        source.node_id,
        target.node_id,
    ]
    assert [edge.edge_id for edge in reloaded.outgoing_edges(source.node_id)] == [edge.edge_id]


def test_sanitize_canonical_graph_disables_auxiliary_edges(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    auxiliary = store.upsert_node(
        GraphNode(
            node_id="node-launch",
            app="com.example.app",
            platform="android",
            description="Launch artifact",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            fingerprint="fp-launch",
        )
    )
    state = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-launch-home",
            app="com.example.app",
            platform="android",
            source_node_id=auxiliary.node_id,
            target_node_id=state.node_id,
            action_type="open_app",
            target="Example",
        )
    )

    counts = store.sanitize_canonical_graph()

    assert counts == {"nodes": 0, "edges": 1}
    assert [node.node_id for node in store.stable_anchor_candidates(platform="android", app="com.example.app")] == [
        state.node_id,
    ]
    assert store.outgoing_edges(auxiliary.node_id) == []
    assert store.get_edge(edge.edge_id).status == EDGE_STATUS_DISABLED


def test_sanitize_canonical_graph_repairs_profile_grounded_auxiliary_path(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    home = store.upsert_node(
        GraphNode(
            node_id="node-home-aux",
            app="com.max.xiaoheihe",
            platform="android",
            description="App home screen is visible",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            retrieval_profile={
                "foreground_app": "com.max.xiaoheihe",
                "visible_text": ["首页", "热点", "游戏库", "我"],
                "clickable_text": ["首页", "热点", "游戏库", "我"],
            },
            fingerprint="fp-home-aux",
        )
    )
    profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.max.xiaoheihe",
            platform="android",
            description="User profile page is visible",
            state_contract=_contract("我的订单", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-profile",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-profile",
            app="com.max.xiaoheihe",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=profile.node_id,
            action_type="tap",
            target="我",
            parameters={"x": 898.0, "y": 948.0, "relative": True},
            status=EDGE_STATUS_DISABLED,
        )
    )

    counts = store.sanitize_canonical_graph()

    repaired_home = store.get_node(home.node_id)
    repaired_edge = store.get_edge(edge.edge_id)
    assert counts["nodes"] == 1
    assert repaired_home is not None
    assert repaired_home.kind == "state"
    assert repaired_home.state_contract is not None
    assert repaired_edge is not None
    assert repaired_edge.status == EDGE_STATUS_ACTIVE


def test_sanitize_canonical_graph_promotes_deprecated_edges_to_active_version(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    active_profile = store.upsert_node(
        GraphNode(
            node_id="node-profile-active",
            app="com.max.xiaoheihe",
            platform="android",
            description="User profile page is visible",
            state_contract=_contract("我的订单", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-profile-active",
            retrieval_profile={
                "visible_text": ["黑盒商城", "我的订单", "我的钱包", "关注", "粉丝", "收藏"],
                "clickable_text": ["黑盒商城", "我的订单", "我的钱包", "关注", "粉丝", "收藏"],
            },
        )
    )
    legacy_profile = store.upsert_node(
        GraphNode(
            node_id="node-profile-legacy",
            app="com.max.xiaoheihe",
            platform="android",
            description="The profile page is visible with the '黑盒商城' button present.",
            state_contract=_contract("黑盒商城", app="com.max.xiaoheihe", clickable=True),
            status=NODE_STATUS_DEPRECATED,
            superseded_by=active_profile.node_id,
            fingerprint="fp-profile-legacy",
            retrieval_profile={
                "visible_text": [
                    "黑盒商城",
                    "官方服务·流程便捷·价格实惠",
                    "青铜会员",
                    "我的钱包",
                    "我的订单",
                    "领券中心",
                    "购物车",
                    "游戏厂商",
                    "销量",
                    "最高折扣",
                    "价格升序",
                    "价格降序",
                    "最新上架",
                ],
                "clickable_text": [
                    "黑盒商城",
                    "官方服务·流程便捷·价格实惠",
                    "青铜会员",
                    "我的钱包",
                    "我的订单",
                    "领券中心",
                    "购物车",
                    "游戏厂商",
                    "销量",
                    "最高折扣",
                    "价格升序",
                    "价格降序",
                    "最新上架",
                ],
            },
        )
    )
    cart = store.upsert_node(
        GraphNode(
            node_id="node-cart",
            app="com.max.xiaoheihe",
            platform="android",
            description="The cart page is loaded.",
            state_contract=_contract("Cart", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-cart",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-legacy-mall",
            app="com.max.xiaoheihe",
            platform="android",
            source_node_id=legacy_profile.node_id,
            target_node_id=cart.node_id,
            action_type="tap",
            target="Cart",
            precondition=legacy_profile.state_contract,
        )
    )

    store.sanitize_canonical_graph()

    copied_edges = [
        item
        for item in store.outgoing_edges(active_profile.node_id)
        if item.target_node_id == cart.node_id and item.action_type == "tap"
    ]
    assert copied_edges, "expected the explicit successor to inherit the deprecated cart edge"
    assert store.get_edge(edge.edge_id).status == EDGE_STATUS_ACTIVE


def test_sanitize_canonical_graph_persists_low_similarity_explicit_successor_edge_stats(tmp_path: Path) -> None:
    store_dir = tmp_path / "graph"
    store = SkillGraphStore(store_dir=store_dir)
    profile = {
        "visible_text": ["Inbox", "Messages", "Archive"],
        "clickable_text": ["Inbox", "Messages", "Archive"],
    }
    active_profile = store.upsert_node(
        GraphNode(
            node_id="node-profile-active",
            app="com.example.app",
            platform="android",
            description="Orders dashboard is visible",
            state_contract=_contract("Orders", clickable=True),
            fingerprint="fp-profile-active",
            retrieval_profile=profile,
        )
    )
    legacy_profile = store.upsert_node(
        GraphNode(
            node_id="node-profile-legacy",
            app="com.example.app",
            platform="android",
            description="Legacy inbox page is visible",
            state_contract=_contract("Archive", clickable=True),
            status=NODE_STATUS_DEPRECATED,
            superseded_by=active_profile.node_id,
            fingerprint="fp-profile-legacy",
            retrieval_profile=profile,
        )
    )
    cart = store.upsert_node(
        GraphNode(
            node_id="node-cart",
            app="com.example.app",
            platform="android",
            description="Cart page is loaded",
            state_contract=_contract("Cart", clickable=True, resource_id="com.example:id/cart"),
            fingerprint="fp-cart",
        )
    )
    stats = EdgeStats(
        attempt_count=7,
        success_count=5,
        last_attempt_at=1234.5,
        last_success_at=1235.5,
        avg_latency_ms=456.7,
        failure_reason_counts={"stale_state": 2},
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-legacy-mall",
            app="com.example.app",
            platform="android",
            source_node_id=legacy_profile.node_id,
            target_node_id=cart.node_id,
            action_type="tap",
            target="Cart",
            precondition=legacy_profile.state_contract,
            stats=stats,
        )
    )

    counts = store.sanitize_canonical_graph()

    assert counts == {"nodes": 0, "edges": 0}
    payload = json.loads((store_dir / "skill_graph.json").read_text(encoding="utf-8"))
    persisted_promoted_edges = [
        edge
        for edge in payload["edges"]
        if edge["source_node_id"] == active_profile.node_id
        and edge["target_node_id"] == cart.node_id
        and edge["action_type"] == "tap"
    ]
    assert persisted_promoted_edges

    reloaded = SkillGraphStore(store_dir=store_dir)
    reloaded_edges = [
        edge
        for edge in reloaded.outgoing_edges(active_profile.node_id)
        if edge.target_node_id == cart.node_id and edge.action_type == "tap"
    ]
    assert reloaded_edges
    reloaded_stats = reloaded_edges[0].stats
    assert reloaded_stats.attempt_count == 7
    assert reloaded_stats.success_count == 5
    assert reloaded_stats.last_attempt_at == 1234.5
    assert reloaded_stats.last_success_at == 1235.5
    assert reloaded_stats.avg_latency_ms == 456.7
    assert reloaded_stats.failure_reason_counts == {"stale_state": 2}


def test_path_compiler_rejects_zero_length_auxiliary_path(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    auxiliary = store.upsert_node(
        GraphNode(
            node_id="node-launch",
            app="com.example.app",
            platform="android",
            description="Launch artifact",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            fingerprint="fp-launch",
        )
    )

    compilation = PathCompiler(store).compile(auxiliary.node_id, auxiliary.node_id)

    assert compilation.status == "blocked"
    assert compilation.reason == "non_state_node"


def test_state_contract_matches_new_schema_against_ui_tree() -> None:
    contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {
                    "selector": {"text": "Profile", "clickable": True},
                    "state": ["visible", "clickable"],
                }
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    })
    assert contract is not None
    extra = {
        "visible_text": ["Home", "Profile"],
        "clickable_text": ["Profile"],
        "resource_ids": ["com.example:id/profile"],
        "class_names": ["android.widget.TextView"],
        "ui_tree_node_count": 3,
    }
    assert evaluate_state_contract(
        contract,
        foreground_app="com.example.app",
        observation_extra=extra,
    ) is True


@pytest.mark.asyncio
async def test_goal_node_resolver_prefers_active_version_and_returns_candidates(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    await store.ingest_skill(
        _skill(
            "skill-v1",
            app="com.example.app",
            first_state="Home screen is visible",
            second_state="Settings list is visible",
            first_selector="Settings",
            second_selector="Profile",
        )
    )
    await store.ingest_skill(
        _skill(
            "skill-v2",
            app="com.example.app",
            first_state="Home screen is visible",
            second_state="Profile page is visible",
            first_selector="Settings",
            second_selector="Profile page",
        )
    )

    resolver = GoalNodeResolver(store)
    resolution = await resolver.resolve(
        "open profile page",
        platform="android",
        app="com.example.app",
    )

    assert resolution.status == "confirmed"
    assert resolution.goal_node is not None
    assert resolution.goal_node.status == "active"
    assert "Profile page" in resolution.goal_node.description

    deprecated_nodes = [
        node for node in store.list_nodes(platform="android", app="com.example.app")
        if node.status == "deprecated"
    ]
    assert deprecated_nodes
    assert deprecated_nodes[0].superseded_by == resolution.goal_node.node_id


@pytest.mark.asyncio
async def test_goal_node_resolver_returns_candidates_for_ambiguous_intent(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    store.upsert_node(
        GraphNode(
            node_id="node-a",
            app="com.example.app",
            platform="android",
            description="Settings home page",
            state_contract=_contract("Settings", clickable=True),
            version=1,
            status="active",
            stats=NodeStats(reach_count=10, contract_match_count=8, contract_miss_count=1),
            skill_ids=("skill-a",),
            fingerprint="fp-a",
        )
    )
    store.upsert_node(
        GraphNode(
            node_id="node-b",
            app="com.example.app",
            platform="android",
            description="Settings search page",
            state_contract=_contract("Search", clickable=True),
            version=1,
            status="active",
            stats=NodeStats(reach_count=9, contract_match_count=7, contract_miss_count=1),
            skill_ids=("skill-b",),
            fingerprint="fp-b",
        )
    )

    resolver = GoalNodeResolver(store)
    resolution = await resolver.resolve(
        "settings",
        platform="android",
        app="com.example.app",
    )

    assert resolution.status == "candidates"
    assert resolution.goal_node is None
    assert len(resolution.candidates) >= 2


@pytest.mark.asyncio
async def test_goal_node_resolver_uses_retrieval_profiles_for_related_auxiliary_pages(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    profile_node = store.upsert_node(
        GraphNode(
            node_id="node-mall-profile",
            app="com.example.app",
            platform="android",
            description="Generic related page artifact",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            retrieval_profile={
                "page_title": "黑盒商城",
                "visible_text": ["黑盒商城", "我的订单"],
                "clickable_text": ["黑盒商城"],
                "content_desc": ["黑盒商城"],
                "resource_ids": ["com.example:id/orders"],
                "stable_controls": [
                    {
                        "text": "我的订单",
                        "resource_id": "com.example:id/orders",
                    }
                ],
            },
            fingerprint="fp-mall-profile",
        )
    )
    store.upsert_node(
        GraphNode(
            node_id="node-other-profile",
            app="com.other.app",
            platform="android",
            description="Other app related artifact",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            retrieval_profile={
                "page_title": "黑盒商城",
                "visible_text": ["黑盒商城"],
            },
            fingerprint="fp-other-profile",
        )
    )

    resolver = GoalNodeResolver(store)
    resolution = await resolver.resolve(
        "打开黑盒商城的我的订单",
        platform="android",
        app="com.example.app",
    )

    assert resolution.status == "candidates"
    assert resolution.goal_node is None
    assert resolution.reason == "profile_only_match"
    assert resolution.candidates
    assert resolution.candidates[0].node.node_id == profile_node.node_id
    assert resolution.candidates[0].reason == "retrieval_profile"
    assert all(candidate.node.app == "com.example.app" for candidate in resolution.candidates)


@pytest.mark.asyncio
async def test_goal_node_resolver_reports_unresolvable_when_superseded_chain_breaks(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    store.upsert_node(
        GraphNode(
            node_id="node-old",
            app="com.example.app",
            platform="android",
            description="Old settings page",
            state_contract=_contract("Settings", clickable=True),
            version=1,
            status="deprecated",
            superseded_by="missing-node",
            stats=NodeStats(reach_count=1, contract_match_count=1, contract_miss_count=0),
            skill_ids=("skill-old",),
            fingerprint="fp-old",
        )
    )
    resolver = GoalNodeResolver(store)
    resolution = await resolver.resolve(
        "settings",
        platform="android",
        app="com.example.app",
    )

    assert resolution.status == "unresolvable"
    assert resolution.goal_node is None
    assert resolution.candidates == ()


@pytest.mark.asyncio
async def test_state_identifier_and_path_compiler_use_active_graph(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    node_home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            version=1,
            status="active",
            stats=NodeStats(reach_count=5, contract_match_count=5, contract_miss_count=0),
            skill_ids=("skill-a",),
            fingerprint="fp-home",
        )
    )
    node_settings = store.upsert_node(
        GraphNode(
            node_id="node-settings",
            app="com.example.app",
            platform="android",
            description="Settings list is visible",
            state_contract=_contract("Settings", clickable=True),
            version=1,
            status="active",
            stats=NodeStats(reach_count=4, contract_match_count=4, contract_miss_count=0),
            skill_ids=("skill-b",),
            fingerprint="fp-settings",
        )
    )
    node_orders = store.upsert_node(
        GraphNode(
            node_id="node-orders",
            app="com.example.app",
            platform="android",
            description="Orders page is visible",
            state_contract=_contract("Orders", clickable=True),
            version=1,
            status="active",
            stats=NodeStats(reach_count=3, contract_match_count=3, contract_miss_count=0),
            skill_ids=("skill-c",),
            fingerprint="fp-orders",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-1",
            app="com.example.app",
            platform="android",
            source_node_id=node_home.node_id,
            target_node_id=node_settings.node_id,
            action_type="tap",
            target="Settings",
            precondition=node_home.state_contract,
            stats=EdgeStats(attempt_count=10, success_count=9, avg_latency_ms=120.0),
            skill_id="skill-a",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-2",
            app="com.example.app",
            platform="android",
            source_node_id=node_settings.node_id,
            target_node_id=node_orders.node_id,
            action_type="tap",
            target="Orders",
            precondition=node_settings.state_contract,
            stats=EdgeStats(attempt_count=10, success_count=8, avg_latency_ms=130.0),
            skill_id="skill-b",
        )
    )

    identifier = StateIdentifier(store)
    current = await identifier.identify(
        foreground_app="com.example.app",
        platform="android",
        app="com.example.app",
        observation_extra={
            "visible_text": ["Settings", "Profile"],
            "clickable_text": ["Settings"],
            "resource_ids": ["com.example:id/settings"],
            "ui_tree_node_count": 4,
        },
    )
    assert current.status == "matched"
    assert current.current_node is not None
    assert current.current_node.node_id == node_settings.node_id

    compiler = PathCompiler(store)
    path = compiler.compile(current.current_node.node_id, node_orders.node_id)

    assert path.status == "ok"
    assert [edge.edge_id for edge in path.edges] == ["edge-2"]


@pytest.mark.asyncio
async def test_state_identifier_uses_retrieval_profiles_without_promoting_auxiliary_nodes(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    profile_node = store.upsert_node(
        GraphNode(
            node_id="node-mall-profile",
            app="com.example.app",
            platform="android",
            description="Related mall artifact",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            retrieval_profile={
                "page_title": "黑盒商城",
                "visible_text": ["黑盒商城", "我的订单"],
                "clickable_text": ["黑盒商城"],
                "resource_ids": ["com.example:id/orders"],
                "stable_controls": [
                    {"text": "我的订单", "resource_id": "com.example:id/orders"}
                ],
            },
            fingerprint="fp-mall-profile",
        )
    )

    identifier = StateIdentifier(store)
    current = await identifier.identify(
        foreground_app="com.example.app",
        platform="android",
        app="com.example.app",
        observation_extra={
            "visible_text": ["黑盒商城", "我的订单"],
            "clickable_text": ["黑盒商城"],
            "content_desc": ["黑盒商城"],
            "resource_ids": ["com.example:id/orders"],
            "ui_tree_node_count": 3,
        },
    )

    assert current.status == "unknown"
    assert current.reason == "profile_only_match"
    assert current.current_node is None
    assert any(
        candidate.node.node_id == profile_node.node_id and candidate.reason == "retrieval_profile"
        for candidate in current.candidates
    )


def test_path_compiler_returns_ranked_alternatives(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    now = time.time()
    node_a = store.upsert_node(
        GraphNode(
            node_id="node-a",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            version=1,
            status="active",
            fingerprint="fp-a",
        )
    )
    node_b = store.upsert_node(
        GraphNode(
            node_id="node-b",
            app="com.example.app",
            platform="android",
            description="Settings page is visible",
            state_contract=_contract("Settings", clickable=True),
            version=1,
            status="active",
            fingerprint="fp-b",
        )
    )
    node_c = store.upsert_node(
        GraphNode(
            node_id="node-c",
            app="com.example.app",
            platform="android",
            description="Search page is visible",
            state_contract=_contract("Search", clickable=True),
            version=1,
            status="active",
            fingerprint="fp-c",
        )
    )
    node_goal = store.upsert_node(
        GraphNode(
            node_id="node-goal",
            app="com.example.app",
            platform="android",
            description="Orders page is visible",
            state_contract=_contract("Orders", clickable=True),
            version=1,
            status="active",
            fingerprint="fp-goal",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-fast-1",
            app="com.example.app",
            platform="android",
            source_node_id=node_a.node_id,
            target_node_id=node_b.node_id,
            action_type="tap",
            target="Settings",
            precondition=node_a.state_contract,
            stats=EdgeStats(attempt_count=10, success_count=9, last_success_at=now),
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-fast-2",
            app="com.example.app",
            platform="android",
            source_node_id=node_b.node_id,
            target_node_id=node_goal.node_id,
            action_type="tap",
            target="Orders",
            precondition=node_b.state_contract,
            stats=EdgeStats(attempt_count=10, success_count=9, last_success_at=now),
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-slow-1",
            app="com.example.app",
            platform="android",
            source_node_id=node_a.node_id,
            target_node_id=node_c.node_id,
            action_type="tap",
            target="Search",
            precondition=node_a.state_contract,
            stats=EdgeStats(attempt_count=10, success_count=6, last_success_at=now),
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-slow-2",
            app="com.example.app",
            platform="android",
            source_node_id=node_c.node_id,
            target_node_id=node_goal.node_id,
            action_type="tap",
            target="Orders",
            precondition=node_c.state_contract,
            stats=EdgeStats(attempt_count=10, success_count=6, last_success_at=now),
        )
    )

    compiler = PathCompiler(store)
    paths = compiler.compile_k_shortest(node_a.node_id, node_goal.node_id, k=2)

    assert len(paths) == 2
    assert [edge.edge_id for edge in paths[0].edges] == ["edge-fast-1", "edge-fast-2"]
    assert [edge.edge_id for edge in paths[1].edges] == ["edge-slow-1", "edge-slow-2"]
    assert paths[0].total_cost < paths[1].total_cost


def test_path_compiler_compiles_deepest_relevant_stable_prefix(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile mall entry stable page",
            state_contract=_contract("Profile", clickable=True),
            stats=NodeStats(reach_count=10, contract_match_count=10, contract_miss_count=0),
            fingerprint="fp-profile",
        )
    )
    mall_auxiliary = store.upsert_node(
        GraphNode(
            node_id="node-mall-aux",
            app="com.example.app",
            platform="android",
            description="Mall checkout terminal artifact",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            fingerprint="fp-mall-aux",
        )
    )
    mall_disabled = store.upsert_node(
        GraphNode(
            node_id="node-mall-disabled",
            app="com.example.app",
            platform="android",
            description="Mall disabled stable page",
            state_contract=_contract("Mall", clickable=True),
            stats=NodeStats(reach_count=10, contract_match_count=10, contract_miss_count=0),
            fingerprint="fp-mall-disabled",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-profile",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=profile.node_id,
            action_type="tap",
            target="Profile",
            precondition=home.state_contract,
            stats=EdgeStats(attempt_count=10, success_count=10),
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-profile-mall-aux",
            app="com.example.app",
            platform="android",
            source_node_id=profile.node_id,
            target_node_id=mall_auxiliary.node_id,
            action_type="tap",
            target="Mall",
            precondition=profile.state_contract,
            stats=EdgeStats(attempt_count=10, success_count=10),
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-profile-mall-disabled",
            app="com.example.app",
            platform="android",
            source_node_id=profile.node_id,
            target_node_id=mall_disabled.node_id,
            action_type="tap",
            target="Mall",
            precondition=profile.state_contract,
            status=EDGE_STATUS_DISABLED,
            stats=EdgeStats(attempt_count=10, success_count=10),
        )
    )

    compilation = PathCompiler(store).compile_deepest_prefix(
        home.node_id,
        "open mall",
        platform="android",
        app="com.example.app",
        min_relevance=0.2,
    )

    assert compilation.status == "ok"
    assert [node.node_id for node in compilation.nodes] == [home.node_id, profile.node_id]
    assert [edge.edge_id for edge in compilation.edges] == ["edge-home-profile"]


def test_path_compiler_chooses_shortest_path_to_same_prefix_target(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    settings = store.upsert_node(
        GraphNode(
            node_id="node-settings",
            app="com.example.app",
            platform="android",
            description="Settings page",
            state_contract=_contract("Settings", clickable=True),
            fingerprint="fp-settings",
        )
    )
    profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile mall entry stable page",
            state_contract=_contract("Profile", clickable=True),
            stats=NodeStats(reach_count=10, contract_match_count=10, contract_miss_count=0),
            fingerprint="fp-profile",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-profile",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=profile.node_id,
            action_type="tap",
            target="Profile",
            precondition=home.state_contract,
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-settings",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=settings.node_id,
            action_type="tap",
            target="Settings",
            precondition=home.state_contract,
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-settings-profile",
            app="com.example.app",
            platform="android",
            source_node_id=settings.node_id,
            target_node_id=profile.node_id,
            action_type="tap",
            target="Profile",
            precondition=settings.state_contract,
        )
    )

    compilation = PathCompiler(store).compile_deepest_prefix(
        home.node_id,
        "open mall",
        platform="android",
        app="com.example.app",
        min_relevance=0.2,
    )

    assert compilation.status == "ok"
    assert [node.node_id for node in compilation.nodes] == [home.node_id, profile.node_id]
    assert [edge.edge_id for edge in compilation.edges] == ["edge-home-profile"]


def test_path_compiler_never_returns_auxiliary_prefix_terminal(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    auxiliary = store.upsert_node(
        GraphNode(
            node_id="node-mall-aux",
            app="com.example.app",
            platform="android",
            description="Mall target artifact",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            fingerprint="fp-mall-aux",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-mall-aux",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=auxiliary.node_id,
            action_type="tap",
            target="Mall",
            precondition=home.state_contract,
        )
    )

    compilation = PathCompiler(store).compile_deepest_prefix(
        home.node_id,
        "open mall",
        platform="android",
        app="com.example.app",
        min_relevance=0.1,
    )

    assert compilation.status == "blocked"
    assert compilation.reason == "no_relevant_prefix"


def test_path_compiler_allows_auxiliary_launch_roots_as_entrypoints(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    launch_root = store.upsert_node(
        GraphNode(
            node_id="node-launch-root",
            app="com.example.app",
            platform="android",
            description="App launch root",
            state_contract=None,
            kind=NODE_KIND_AUXILIARY,
            fingerprint="fp-launch-root",
        )
    )
    profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile mall entry stable page",
            state_contract=_contract("Profile", clickable=True),
            stats=NodeStats(reach_count=10, contract_match_count=10, contract_miss_count=0),
            fingerprint="fp-profile",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-launch-profile",
            app="com.example.app",
            platform="android",
            source_node_id=launch_root.node_id,
            target_node_id=profile.node_id,
            action_type="tap",
            target="Profile",
            stats=EdgeStats(attempt_count=10, success_count=10),
        )
    )

    compilation = PathCompiler(store).compile_deepest_prefix(
        launch_root.node_id,
        "open mall",
        platform="android",
        app="com.example.app",
        min_relevance=0.1,
    )

    assert compilation.status == "ok"
    assert [node.node_id for node in compilation.nodes] == [launch_root.node_id, profile.node_id]
    assert [edge.edge_id for edge in compilation.edges] == ["edge-launch-profile"]


def test_path_compiler_uses_outgoing_edges_for_path_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile mall entry stable page",
            state_contract=_contract("Profile", clickable=True),
            stats=NodeStats(reach_count=10, contract_match_count=10, contract_miss_count=0),
            fingerprint="fp-profile",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-profile",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=profile.node_id,
            action_type="tap",
            target="Profile",
            precondition=home.state_contract,
        )
    )

    def fail_list_edges(*args: object, **kwargs: object) -> list[GraphEdge]:
        raise AssertionError("path compilation must use outgoing_edges")

    monkeypatch.setattr(store, "list_edges", fail_list_edges)

    compiler = PathCompiler(store)
    paths = compiler.compile_k_shortest(home.node_id, profile.node_id, k=1)
    prefix = compiler.compile_deepest_prefix(
        home.node_id,
        "open mall",
        platform="android",
        app="com.example.app",
        min_relevance=0.2,
    )

    assert [edge.edge_id for edge in paths[0].edges] == ["edge-home-profile"]
    assert [edge.edge_id for edge in prefix.edges] == ["edge-home-profile"]


def test_skill_graph_store_appends_refresh_trigger(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    store.append_refresh_trigger(
        {
            "reason": "state_identification_miss",
            "platform": "android",
            "app": "com.example.app",
            "node_id": "node-a",
            "candidate_node_ids": ["node-b", "node-c"],
        }
    )

    queue_path = store.store_dir / "skill_graph_refresh_queue.jsonl"
    assert queue_path.is_file()
    lines = queue_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["reason"] == "state_identification_miss"
    assert record["candidate_node_ids"] == ["node-b", "node-c"]
    assert record["allowed_outputs"] == ["patch_contract", "spawn_version", "add_edge"]


def test_path_compiler_ignores_navigation_edges(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    middle = store.upsert_node(
        GraphNode(
            node_id="node-middle",
            app="com.example.app",
            platform="android",
            description="Middle page",
            state_contract=_contract("Middle", clickable=True),
            fingerprint="fp-middle",
        )
    )
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.example.app",
            platform="android",
            description="Target page",
            state_contract=_contract("Target", clickable=True),
            fingerprint="fp-target",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-middle",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=middle.node_id,
            action_type="tap",
            target="Middle",
            precondition=home.state_contract,
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-middle-target",
            app="com.example.app",
            platform="android",
            source_node_id=middle.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Target",
            precondition=middle.state_contract,
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-target-nav",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=target.node_id,
            action_type="back",
            target="Back",
            kind="navigation_back",
            precondition=home.state_contract,
        )
    )

    path = PathCompiler(store).compile(home.node_id, target.node_id)

    assert [edge.edge_id for edge in path.edges] == ["edge-home-middle", "edge-middle-target"]


def test_append_transition_evidence_writes_jsonl(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    store.append_transition_evidence(
        {
            "platform": "android",
            "app": "com.example.app",
            "source_node_id": "node-home",
            "action_type": "back",
            "edge_kind": "navigation_back",
            "target_node_id": None,
            "reason": "navigation_target_unknown",
            "candidate_node_ids": [],
        }
    )

    path = tmp_path / "graph" / "skill_graph_transition_evidence.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])

    assert record["reason"] == "navigation_target_unknown"
    assert record["edge_kind"] == "navigation_back"


@pytest.mark.asyncio
async def test_skill_reuser_ignores_graph_store_without_flat_candidates(tmp_path: Path) -> None:
    store_dir = tmp_path / "skills"
    graph = SkillGraphStore(
        store_dir=store_dir,
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    skill = _skill(
        "skill-graph",
        app="com.example.app",
        first_state="Home screen is visible",
        second_state="Profile page is visible",
        first_selector="Settings",
        second_selector="Profile page",
    )
    await graph.ingest_skill(skill)

    from opengui.skills.library import SkillLibrary

    library = SkillLibrary(store_dir=store_dir, embedding_provider=_StableEmbedder())
    llm = _NoCallLLM()
    recorder = _RecordingEvents()

    reuser = SkillReuser(llm=llm, threshold=0.1, auto_accept_threshold=0.99)
    result = await reuser.find(
        "open profile page",
        library,
        platform="android",
        trajectory_recorder=recorder,
    )

    assert result is None
    assert llm.calls == []
    assert recorder.events == [
        {
            "type": "skill_search",
            "source": "reuser",
            "matched": False,
            "reason": "no_candidates",
            "threshold": 0.1,
        }
    ]
