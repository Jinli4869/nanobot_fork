from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from opengui.skills.data import Skill, SkillStep
from opengui.skills.graph import (
    EDGE_STATUS_ACTIVE,
    GraphNode,
    NODE_KIND_AUXILIARY,
    NODE_KIND_STATE,
    NODE_STATUS_ACTIVE,
    NodeStats,
    SkillGraphStore,
)
from opengui.postprocessing import PostRunProcessor, _build_retrieval_profile
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


@pytest.mark.asyncio
async def test_postrun_graph_sync_passes_latest_successful_terminal_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    expected_skill = _skill("branch", "Orders", contract_text="Orders")

    class FakeSkillExtractor:
        def __init__(self, *, llm: object) -> None:
            self.total_usage = {}

        async def extract_from_file(self, trace_path: Path, is_success: bool) -> Skill | None:
            return expected_skill

    class FakeSkillLibrary:
        def __init__(self, **kwargs: object) -> None:
            self._skill = expected_skill

        async def add_or_merge(self, skill: Skill) -> tuple[str, str]:
            return ("added", skill.skill_id)

        def get(self, skill_id: str) -> Skill | None:
            return self._skill if skill_id == self._skill.skill_id else None

    captured: list[str | None] = []

    async def fake_sync(
        self: PostRunProcessor,
        skill: object,
        *,
        continuation_anchor_id: str | None = None,
        node_profiles: dict[int | str, dict[str, object] | None] | None = None,
    ) -> bool:
        captured.append(continuation_anchor_id)
        return True

    monkeypatch.setattr("opengui.skills.extractor.SkillExtractor", FakeSkillExtractor)
    monkeypatch.setattr("opengui.skills.library.SkillLibrary", FakeSkillLibrary)
    monkeypatch.setattr(PostRunProcessor, "_sync_skill_graph", fake_sync)

    processor = PostRunProcessor(
        llm=object(),
        skill_store_root=tmp_path / "skills",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    assert captured == ["node-runtime"]


@pytest.mark.asyncio
async def test_postrun_graph_sync_ignores_prefix_when_runtime_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    expected_skill = _skill("branch", "Orders", contract_text="Orders")

    class FakeSkillExtractor:
        def __init__(self, *, llm: object) -> None:
            self.total_usage = {}

        async def extract_from_file(self, trace_path: Path, is_success: bool) -> Skill | None:
            return expected_skill

    class FakeSkillLibrary:
        def __init__(self, **kwargs: object) -> None:
            self._skill = expected_skill

        async def add_or_merge(self, skill: Skill) -> tuple[str, str]:
            return ("added", skill.skill_id)

        def get(self, skill_id: str) -> Skill | None:
            return self._skill if skill_id == self._skill.skill_id else None

    captured: list[str | None] = []

    async def fake_sync(
        self: PostRunProcessor,
        skill: object,
        *,
        continuation_anchor_id: str | None = None,
        node_profiles: dict[int | str, dict[str, object] | None] | None = None,
    ) -> bool:
        captured.append(continuation_anchor_id)
        return True

    monkeypatch.setattr("opengui.skills.extractor.SkillExtractor", FakeSkillExtractor)
    monkeypatch.setattr("opengui.skills.library.SkillLibrary", FakeSkillLibrary)
    monkeypatch.setattr(PostRunProcessor, "_sync_skill_graph", fake_sync)

    processor = PostRunProcessor(
        llm=object(),
        skill_store_root=tmp_path / "skills",
        enable_skill_extraction=True,
    )

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    assert captured == [None]


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
                "type": "graph_runtime_result",
                "state": "succeeded",
                "prefix_only": True,
                "prefix_terminal_node_id": "node-b",
            },
            {"type": "result", "status": "succeeded"},
        ],
    )

    expected_skill = _skill("branch", "Orders", contract_text="Orders")
    seen_overlap = 0
    active = 0
    active_lock = asyncio.Lock()

    class FakeSkillExtractor:
        def __init__(self, *, llm: object) -> None:
            self.total_usage = {}

        async def extract_from_file(self, trace_path: Path, is_success: bool) -> Skill | None:
            return expected_skill

    class FakeSkillLibrary:
        def __init__(self, **kwargs: object) -> None:
            self._skill = expected_skill

        async def add_or_merge(self, skill: Skill) -> tuple[str, str]:
            return ("added", skill.skill_id)

        def get(self, skill_id: str) -> Skill | None:
            return self._skill if skill_id == self._skill.skill_id else None

    class FakeGraphStore:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def ingest_skill(
            self,
            skill: Skill,
            continuation_anchor_id: str | None = None,
            node_profiles: dict[int | str, dict[str, object] | None] | None = None,
        ) -> None:
            nonlocal seen_overlap, active
            async with active_lock:
                active += 1
                seen_overlap = max(seen_overlap, active)
            await asyncio.sleep(0.05)
            async with active_lock:
                active -= 1

    monkeypatch.setattr("opengui.skills.extractor.SkillExtractor", FakeSkillExtractor)
    monkeypatch.setattr("opengui.skills.library.SkillLibrary", FakeSkillLibrary)
    monkeypatch.setattr("opengui.skills.graph.SkillGraphStore", FakeGraphStore)

    processor = PostRunProcessor(
        llm=object(),
        skill_store_root=tmp_path / "skills",
        enable_skill_extraction=True,
    )

    await asyncio.gather(
        processor._extract_skill(trace_path_a, is_success=True, platform="android"),
        processor._extract_skill(trace_path_b, is_success=True, platform="android"),
    )

    assert seen_overlap == 1


@pytest.mark.asyncio
async def test_postrun_graph_sync_persists_retrieval_profiles_without_touching_skill_json(
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
            {"type": "result", "status": "succeeded"},
        ],
    )

    expected_skill = _skill("branch", "Orders", contract_text="Orders")

    class FakeSkillExtractor:
        def __init__(self, *, llm: object) -> None:
            self.total_usage = {}

        async def extract_from_file(self, trace_path: Path, is_success: bool) -> Skill | None:
            return expected_skill

    processor = PostRunProcessor(
        llm=object(),
        skill_store_root=tmp_path / "store",
        enable_skill_extraction=True,
    )

    monkeypatch.setattr("opengui.skills.extractor.SkillExtractor", FakeSkillExtractor)

    await processor._extract_skill(trace_path, is_success=True, platform="android")

    skills_payload = json.loads((tmp_path / "store" / "android" / "skills.json").read_text(encoding="utf-8"))
    stored_skill = skills_payload["apps"]["com.example.app"][0]
    assert "retrieval_profile" not in stored_skill

    graph_payload = json.loads((tmp_path / "store" / "skill_graph.json").read_text(encoding="utf-8"))
    assert any(node.get("retrieval_profile") for node in graph_payload["nodes"])
    assert any(
        node.get("retrieval_profile", {}).get("stable_controls")
        for node in graph_payload["nodes"]
    )
