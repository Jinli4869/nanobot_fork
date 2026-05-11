from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from opengui.interfaces import LLMResponse
from opengui.postprocessing import (
    PostRunProcessor,
    _build_retrieval_profile,
    _load_latest_graph_terminal_node_id,
)
from opengui.skills.data import Skill, SkillStep
from opengui.skills.graph import (
    EDGE_STATUS_ACTIVE,
    NODE_KIND_AUXILIARY,
    NODE_KIND_STATE,
    NODE_STATUS_ACTIVE,
    GraphEdge,
    GraphNode,
    NodeStats,
    SkillGraphStore,
)
from opengui.skills.state_contract import normalize_state_contract


def _contract(text: str) -> dict[str, object]:
    return normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [{"selector": {"text": text}, "state": ["visible", "clickable"]}],
            "forbidden": [],
        },
        "mask_rules": [],
    }) or {}


def _skill(skill_id: str, target: str, *, contract_text: str = "Home") -> Skill:
    return Skill(
        skill_id=skill_id,
        name=f"skill_{skill_id}",
        description=f"Open {target}",
        app="com.example.app",
        platform="android",
        steps=(
            SkillStep(
                action_type="tap",
                target=target,
                valid_state="Home screen is visible",
                expected_state=f"{target} page",
                state_contract=_contract(contract_text),
                fixed=True,
                fixed_values={"x": 10.0, "y": 10.0, "relative": True},
            ),
        ),
    )


def _unanchored_launch_skill() -> Skill:
    return Skill(
        skill_id="launch-flat",
        name="launch_flat",
        description="Launch app and stop",
        app="com.example.app",
        platform="android",
        steps=(
            SkillStep(
                action_type="open_app",
                target="Example",
                valid_state="Root launcher",
                expected_state="Example app is open",
                fixed=True,
                fixed_values={"package": "com.example.app"},
            ),
        ),
    )


def _write_trace(trace_path: Path, events: list[dict[str, object]]) -> None:
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def _code_response(name: str = "open_orders") -> str:
    source = f'''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["orders"], description="Open orders page.")
async def {name}(device):
    await action(
        "tap",
        target="Orders",
        state_contract=C(app="com.example.app", required=[R(text="Home", visible=True)]),
    )
'''
    return json.dumps({
        "step_by_step_reasoning": "learn a reusable orders prefix",
        "python_code": source,
    })


class _CodeLLM:
    def __init__(self, response: str | None = None) -> None:
        self.response = response or _code_response()

    async def chat(self, messages: list[dict[str, object]]) -> LLMResponse:
        del messages
        return LLMResponse(content=self.response)


def test_retrieval_profile_discards_dynamic_feed_content() -> None:
    profile = _build_retrieval_profile({
        "app": "com.max.xiaoheihe",
        "foreground_app": "com.max.xiaoheihe",
        "platform": "android",
        "extra": {
            "visible_text": [
                "首页",
                "热点",
                "我",
                "这篇帖子详细聊聊今天版本更新后的新配队和强度变化",
                "12分钟前",
                "999评论",
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
                "com.max.xiaoheihe:id/tv_comment_count",
            ],
            "ui_tree": [
                {
                    "text": "首页",
                    "resource_id": "com.max.xiaoheihe:id/nav_home",
                    "clickable": True,
                },
                {
                    "text": "我",
                    "resource_id": "com.max.xiaoheihe:id/nav_me",
                    "clickable": True,
                },
                {
                    "text": "这篇帖子详细聊聊今天版本更新后的新配队和强度变化",
                    "resource_id": "com.max.xiaoheihe:id/tv_post_title",
                    "clickable": True,
                },
            ],
        },
    })

    assert "首页" in profile["visible_text"]
    assert "我" in profile["clickable_text"]
    assert "这篇帖子详细聊聊今天版本更新后的新配队和强度变化" not in profile.get("visible_text", [])
    assert "12分钟前" not in profile.get("visible_text", [])
    assert "999评论" not in profile.get("visible_text", [])
    assert "com.max.xiaoheihe:id/tv_post_title" not in profile.get("resource_ids", [])
    assert all(
        control.get("resource_id") != "com.max.xiaoheihe:id/tv_post_title"
        for control in profile.get("stable_controls", [])
    )


@pytest.mark.asyncio
async def test_flat_skill_migration_report_counts_replayable_paths(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    skills = [_skill("one", "Orders"), _skill("two", "Profile")]

    report = await store.migrate_flat_skills(skills)

    assert report["flat_skill_count"] == 2
    assert report["replayable_skill_count"] == 2
    assert report["graph_coverage_rate"] == 1.0
    assert report["exit_criteria"]["coverage_90_percent"] is True


def test_sanitize_canonical_graph_moves_unanchored_nodes_out_of_state_space(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    node = GraphNode(
        node_id="legacy-null-contract",
        app="com.example.app",
        platform="android",
        description="Legacy unanchored state",
        state_contract=None,
        kind=NODE_KIND_STATE,
        stats=NodeStats(reach_count=3, contract_match_count=1, contract_miss_count=2),
        fingerprint="legacy-null-contract",
    ).normalized()
    store._nodes[node.node_id] = node

    counts = store.sanitize_canonical_graph()

    assert counts == {"nodes": 1, "edges": 0}
    updated = store.get_node(node.node_id)
    assert updated is not None
    assert updated.kind == NODE_KIND_AUXILIARY
    assert updated.stats.reach_count == 3
    assert all(
        node.state_contract is not None
        for node in store.list_nodes(kind=NODE_KIND_STATE)
    )


def test_sanitize_canonical_graph_cleans_legacy_file_on_load(tmp_path: Path) -> None:
    store_dir = tmp_path / "graph"
    store = SkillGraphStore(store_dir=store_dir)
    legacy = GraphNode(
        node_id="legacy-loaded-null-contract",
        app="com.example.app",
        platform="android",
        description="Legacy loaded unanchored state",
        state_contract=None,
        kind=NODE_KIND_STATE,
        fingerprint="legacy-loaded-null-contract",
    ).normalized()
    store._nodes[legacy.node_id] = legacy
    store.save()
    assert store.get_node(legacy.node_id).kind == NODE_KIND_STATE

    loaded = SkillGraphStore(store_dir=store_dir)

    updated = loaded.get_node(legacy.node_id)
    assert updated is not None
    assert updated.kind == NODE_KIND_AUXILIARY


@pytest.mark.asyncio
async def test_ingest_skill_uses_valid_compatible_continuation_anchor(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    anchor = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile screen",
            state_contract=_contract("Profile"),
            status=NODE_STATUS_ACTIVE,
            kind=NODE_KIND_STATE,
            fingerprint="profile-screen",
        )
    )
    skill = _skill("branch", "Orders", contract_text="Profile")

    await store.ingest_skill(skill, continuation_anchor_id=anchor.node_id)

    edges = [
        edge
        for edge in store.list_edges(
            platform="android",
            app="com.example.app",
            status=EDGE_STATUS_ACTIVE,
        )
        if edge.skill_id == skill.skill_id
    ]
    assert len(edges) == 1
    assert edges[0].source_node_id == anchor.node_id


@pytest.mark.asyncio
async def test_ingest_skill_ignores_invalid_continuation_anchor(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    invalid_anchor = store.upsert_node(
        GraphNode(
            node_id="node-aux",
            app="com.example.app",
            platform="android",
            description="Auxiliary overlay",
            state_contract=None,
            status=NODE_STATUS_ACTIVE,
            kind=NODE_KIND_AUXILIARY,
            fingerprint="aux-overlay",
        )
    )
    skill = _skill("branch", "Orders", contract_text="Orders")

    await store.ingest_skill(skill, continuation_anchor_id=invalid_anchor.node_id)

    edges = [
        edge
        for edge in store.list_edges(
            platform="android",
            app="com.example.app",
            status=EDGE_STATUS_ACTIVE,
        )
        if edge.skill_id == skill.skill_id
    ]
    assert len(edges) == 1
    assert edges[0].source_node_id != invalid_anchor.node_id


@pytest.mark.asyncio
async def test_ingest_skill_ignores_incompatible_continuation_anchor(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    incompatible_anchor = store.upsert_node(
        GraphNode(
            node_id="node-settings",
            app="com.example.app",
            platform="android",
            description="Settings screen",
            state_contract=_contract("Settings"),
            status=NODE_STATUS_ACTIVE,
            kind=NODE_KIND_STATE,
            fingerprint="settings-screen",
        )
    )
    skill = _skill("branch", "Orders", contract_text="Orders")

    await store.ingest_skill(skill, continuation_anchor_id=incompatible_anchor.node_id)

    edges = [
        edge
        for edge in store.list_edges(
            platform="android",
            app="com.example.app",
            status=EDGE_STATUS_ACTIVE,
        )
        if edge.skill_id == skill.skill_id
    ]
    assert len(edges) == 1
    assert edges[0].source_node_id != incompatible_anchor.node_id


def test_load_latest_graph_terminal_node_id_uses_latest_successful_prefix(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "graph_prefix_result",
                "prefix_only": True,
                "edge_count": 1,
                "terminal_node_id": "node-prefix",
            },
            {
                "type": "graph_runtime_result",
                "state": "succeeded",
                "prefix_only": True,
                "prefix_terminal_node_id": "node-runtime",
            },
            {
                "type": "graph_runtime_result",
                "state": "succeeded",
                "prefix_only": False,
                "prefix_terminal_node_id": "node-exact",
            },
            {
                "type": "graph_runtime_result",
                "state": "failed",
                "prefix_terminal_node_id": "node-stale",
            },
            {"type": "result", "status": "succeeded"},
        ],
    )

    assert _load_latest_graph_terminal_node_id(trace_path) == "node-runtime"


def test_load_latest_graph_terminal_node_id_ignores_failed_runtime_prefix(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "graph_prefix_result",
                "prefix_only": True,
                "edge_count": 1,
                "terminal_node_id": "node-prefix",
            },
            {
                "type": "graph_runtime_result",
                "state": "failed",
                "prefix_terminal_node_id": "node-stale",
            },
            {"type": "result", "status": "succeeded"},
        ],
    )

    assert _load_latest_graph_terminal_node_id(trace_path) is None


@pytest.mark.asyncio
async def test_postrun_graph_sync_serializes_concurrent_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_path_a = tmp_path / "trace-a.jsonl"
    trace_path_b = tmp_path / "trace-b.jsonl"
    _write_trace(
        trace_path_a,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "tap", "target": "Orders"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"visible_text": ["Home", "Orders"], "clickable_text": ["Orders"]},
                },
            },
            {
                "type": "graph_runtime_result",
                "state": "succeeded",
                "prefix_only": True,
                "prefix_terminal_node_id": "node-a",
            },
            {"type": "result", "status": "succeeded"},
        ],
    )
    _write_trace(
        trace_path_b,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "tap", "target": "Orders"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {"visible_text": ["Home", "Orders"], "clickable_text": ["Orders"]},
                },
            },
            {
                "type": "graph_runtime_result",
                "state": "succeeded",
                "prefix_only": True,
                "prefix_terminal_node_id": "node-b",
            },
            {"type": "result", "status": "succeeded"},
        ],
    )

    seen_overlap = 0
    active = 0
    active_lock = asyncio.Lock()

    async def fake_sync_graph_cache(self: object) -> bool:
        nonlocal seen_overlap, active
        async with active_lock:
            active += 1
            seen_overlap = max(seen_overlap, active)
        await asyncio.sleep(0.05)
        async with active_lock:
            active -= 1
        return True

    monkeypatch.setattr(
        "opengui.skills.code_first.CodeSkillLibrary.sync_graph_cache",
        fake_sync_graph_cache,
    )

    processor = PostRunProcessor(
        llm=_CodeLLM(),
        skill_store_root=tmp_path / "skills",
        enable_skill_extraction=True,
    )

    await asyncio.gather(
        processor._extract_skill(trace_path_a, is_success=True, platform="android"),
        processor._extract_skill(trace_path_b, is_success=True, platform="android"),
    )

    assert seen_overlap == 1


@pytest.mark.asyncio
async def test_postrun_code_first_writes_code_graph_without_touching_skill_json(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            {
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "wait"},
                "observation": {
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "visible_text": ["Home", "Settings", "Profile"],
                        "clickable_text": ["Home", "Settings"],
                        "content_desc": ["Open settings"],
                        "resource_ids": ["com.example:id/home", "com.example:id/settings"],
                        "ui_tree": [
                            {
                                "text": "Settings",
                                "content_desc": "Open settings",
                                "resource_id": "com.example:id/settings",
                                "clickable": True,
                                "bounds": "[0,0][100,100]",
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
                    "app": "com.example.app",
                    "foreground_app": "com.example.app",
                    "platform": "android",
                    "extra": {
                        "visible_text": ["Orders", "All orders"],
                        "resource_ids": ["com.example:id/orders_title"],
                        "ui_tree": [
                            {
                                "text": "Orders",
                                "resource_id": "com.example:id/orders_title",
                            }
                        ],
                    },
                },
            },
            {"type": "result", "status": "succeeded"},
        ],
    )

    processor = PostRunProcessor(
        llm=_CodeLLM(),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    assert not (tmp_path / "store" / "android" / "skills.json").exists()
    assert (tmp_path / "store" / "skill_graph_code.py").exists()
    graph_payload = json.loads((tmp_path / "store" / "skill_graph.json").read_text(encoding="utf-8"))
    assert any((node.get("source_ref") or {}).get("path") == "skill_graph_code.py" for node in graph_payload["nodes"])


def test_graph_store_compacts_duplicate_nodes_after_ingest(
    tmp_path: Path,
) -> None:
    graph_dir = tmp_path / "store"
    graph = SkillGraphStore(store_dir=graph_dir)
    survivor = GraphNode(
        node_id="node-home-survivor",
        app="com.example.app",
        platform="android",
        description="Home screen is visible",
        state_contract=_contract("Home"),
        status=NODE_STATUS_ACTIVE,
        kind=NODE_KIND_STATE,
        stats=NodeStats(reach_count=5, contract_match_count=5),
        fingerprint="fp-home",
    ).normalized()
    loser = GraphNode(
        node_id="node-home-loser",
        app="com.example.app",
        platform="android",
        description="Home screen is visible",
        state_contract=_contract("Home"),
        status=NODE_STATUS_ACTIVE,
        kind=NODE_KIND_STATE,
        stats=NodeStats(reach_count=1, contract_match_count=0, contract_miss_count=4),
        fingerprint="fp-home",
    ).normalized()
    target = GraphNode(
        node_id="node-orders",
        app="com.example.app",
        platform="android",
        description="Orders page is visible",
        state_contract=_contract("Orders"),
        status=NODE_STATUS_ACTIVE,
        kind=NODE_KIND_STATE,
        fingerprint="fp-orders",
    ).normalized()
    graph._nodes[survivor.node_id] = survivor
    graph._nodes[loser.node_id] = loser
    graph._nodes[target.node_id] = target
    graph.upsert_edge(
        GraphEdge(
            edge_id="edge-home-orders",
            app="com.example.app",
            platform="android",
            source_node_id=loser.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Orders",
            precondition=loser.state_contract,
        )
    )
    graph.save()

    graph.compact_canonical_graph()

    graph_payload = json.loads((graph_dir / "skill_graph.json").read_text(encoding="utf-8"))
    node_ids = [node.get("node_id") for node in graph_payload["nodes"]]
    assert survivor.node_id in node_ids
    assert loser.node_id not in node_ids
    assert node_ids.count(survivor.node_id) == 1
    log_payload = (graph_dir / "skill_graph_compaction_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert log_payload
    record = json.loads(log_payload[-1])
    assert record["merge_kind"] == "exact_merge"
    assert record["deleted_node_id"] == loser.node_id
    assert record["canonical_node_id"] == survivor.node_id
    assert record["edge_rewrites"] >= 1
