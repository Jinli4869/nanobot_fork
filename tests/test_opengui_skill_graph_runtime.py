from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np
import pytest

from opengui.action import Action
from opengui.observation import Observation
from opengui.skills.graph import (
    EdgeStats,
    GraphEdge,
    GraphNode,
    GraphSessionCursor,
    NodeStats,
    SkillGraphStore,
    StateIdentifier,
    infer_explicit_app_hint_from_task,
)
from opengui.skills.graph_runtime import GraphRuntimeExecutor
from opengui.skills.state_contract import normalize_state_contract


def test_infer_explicit_app_hint_from_task_without_existing_graph_bucket() -> None:
    assert (
        infer_explicit_app_hint_from_task(
            "请在知乎搜索强化学习，停留在搜索结果页",
            platform="android",
        )
        == "com.zhihu.android"
    )


def test_infer_explicit_app_hint_from_task_handles_bilibili_short_alias() -> None:
    assert (
        infer_explicit_app_hint_from_task(
            "去B站搜“AI绘画教程”，然后按最多播放排序查看。",
            platform="android",
        )
        == "tv.danmaku.bili"
    )


def test_infer_explicit_app_hint_from_task_ignores_unknown_slug_fragments() -> None:
    assert (
        infer_explicit_app_hint_from_task(
            "去不存在的App搜AI绘画教程",
            platform="android",
        )
        is None
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


class _SpyEmbedder:
    DIM = 32

    def __init__(self) -> None:
        self.call_count = 0

    async def embed(self, texts: list[str]) -> np.ndarray:
        self.call_count += 1
        vecs = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            for token in re.findall(r"\w+", text.lower()):
                slot = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self.DIM
                vecs[i, slot] += 1.0
            norm = float(np.linalg.norm(vecs[i]))
            if norm > 0:
                vecs[i] /= norm
        return vecs


def _contract(label: str, *, app: str = "com.example.app", clickable: bool = False) -> dict[str, object]:
    selector: dict[str, object] = {"text": label}
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
        "mask_rules": [],
    }) or {}


class _Backend:
    platform = "android"

    def __init__(self, *, precondition_visible: bool = True) -> None:
        self.actions: list[Action] = []
        self.observe_count = 0
        self.precondition_visible = precondition_visible

    async def preflight(self) -> None:
        return None

    async def list_apps(self) -> list[str]:
        return ["com.example.app"]

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        self.observe_count += 1
        if self.observe_count == 1:
            extra = {
                "visible_text": ["Home"],
                "clickable_text": ["Home"],
                "resource_ids": ["com.example:id/home"],
                "ui_tree_node_count": 2,
            }
        else:
            extra = {
                "visible_text": ["Orders"],
                "clickable_text": ["Orders"],
                "resource_ids": ["com.example:id/orders"],
                "ui_tree_node_count": 2,
            }
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1000,
            screen_height=2000,
            foreground_app="com.example.app",
            platform="android",
            extra=extra,
        )

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        self.actions.append(action)
        return "ok"


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record_event(self, event_type: str, **payload: object) -> None:
        self.events.append({"type": event_type, **payload})


class _InterruptBackend(_Backend):
    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        self.observe_count += 1
        if self.observe_count == 1:
            extra = {
                "visible_text": ["Allow", "Permission"],
                "clickable_text": ["Allow"],
                "ui_tree_node_count": 2,
            }
        elif self.observe_count == 2:
            extra = {
                "visible_text": ["Home"],
                "clickable_text": ["Home"],
                "resource_ids": ["com.example:id/home"],
                "ui_tree_node_count": 2,
            }
        else:
            extra = {
                "visible_text": ["Orders"],
                "clickable_text": ["Orders"],
                "resource_ids": ["com.example:id/orders"],
                "ui_tree_node_count": 2,
            }
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1000,
            screen_height=2000,
            foreground_app="com.example.app",
            platform="android",
            extra=extra,
        )


class _AlwaysUnknownBackend(_Backend):
    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        self.observe_count += 1
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1000,
            screen_height=2000,
            foreground_app="com.example.app",
            platform="android",
            extra={
                "visible_text": ["Unexpected"],
                "clickable_text": [],
                "ui_tree_node_count": 1,
            },
        )


class _ProfileOnlyBackend(_Backend):
    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        self.observe_count += 1
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1000,
            screen_height=2000,
            foreground_app="com.example.app",
            platform="android",
            extra={
                "visible_text": ["黑盒商城", "我的订单"],
                "clickable_text": ["黑盒商城"],
                "content_desc": ["黑盒商城"],
                "resource_ids": ["com.example:id/orders"],
                "ui_tree_node_count": 3,
            },
        )


class _NavigationProbeBackend(_Backend):
    def __init__(self) -> None:
        super().__init__()
        self.mode = "forward"

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        self.observe_count += 1
        if self.observe_count == 1:
            extra = {
                "visible_text": ["Home"],
                "clickable_text": ["Home"],
                "resource_ids": ["com.example:id/home"],
                "ui_tree_node_count": 2,
            }
        elif self.observe_count == 2:
            extra = {
                "visible_text": ["Middle"],
                "clickable_text": ["Middle"],
                "resource_ids": ["com.example:id/middle"],
                "ui_tree_node_count": 2,
            }
        elif self.observe_count == 3:
            extra = {
                "visible_text": ["Target"],
                "clickable_text": ["Target"],
                "resource_ids": ["com.example:id/target"],
                "ui_tree_node_count": 2,
            }
        elif self.mode == "probe":
            extra = {
                "visible_text": ["Middle"],
                "clickable_text": ["Middle"],
                "resource_ids": ["com.example:id/middle"],
                "ui_tree_node_count": 2,
            }
        else:
            extra = {
                "visible_text": ["Target"],
                "clickable_text": ["Target"],
                "resource_ids": ["com.example:id/target"],
                "ui_tree_node_count": 2,
            }
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1000,
            screen_height=2000,
            foreground_app="com.example.app",
            platform="android",
            extra=extra,
        )

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        self.actions.append(action)
        if action.action_type == "back":
            self.mode = "probe"
        elif action.action_type == "tap" and self.mode == "probe":
            self.mode = "restored"
        return "ok"


class _UnknownReturnBackend(_Backend):
    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        self.observe_count += 1
        if self.observe_count == 1:
            extra = {
                "visible_text": ["Home"],
                "clickable_text": ["Home"],
                "resource_ids": ["com.example:id/home"],
                "ui_tree_node_count": 2,
            }
        elif self.observe_count == 2:
            extra = {
                "visible_text": ["Target"],
                "clickable_text": ["Target"],
                "resource_ids": ["com.example:id/target"],
                "ui_tree_node_count": 2,
            }
        else:
            extra = {
                "visible_text": ["Unexpected"],
                "clickable_text": [],
                "ui_tree_node_count": 1,
            }
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1000,
            screen_height=2000,
            foreground_app="com.example.app",
            platform="android",
            extra=extra,
        )


class _LaunchThenHomeBackend(_Backend):
    def __init__(self) -> None:
        super().__init__()
        self.launched = False
        self.mall_open = False

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        self.observe_count += 1
        if not self.launched:
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1000,
                screen_height=2000,
                foreground_app="com.android.launcher",
                platform="android",
                extra={"visible_text": ["Launcher"], "ui_tree_node_count": 1},
            )
        if self.mall_open:
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1000,
                screen_height=2000,
                foreground_app="com.max.xiaoheihe",
                platform="android",
                extra={
                    "visible_text": ["黑盒商城", "我的订单"],
                    "clickable_text": ["黑盒商城", "我的订单"],
                    "ui_tree_node_count": 2,
                },
            )
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1000,
            screen_height=2000,
            foreground_app="com.max.xiaoheihe",
            platform="android",
            extra={
                "visible_text": ["关注", "推荐", "首页", "热点", "游戏库", "我"],
                "clickable_text": ["首页", "热点", "游戏库", "我"],
                "resource_ids": ["com.max.xiaoheihe:id/rg_main"],
                "ui_tree_node_count": 6,
            },
        )

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        self.actions.append(action)
        if action.action_type == "open_app" and action.text == "com.max.xiaoheihe":
            self.launched = True
        if action.action_type == "tap" and action.x == 900.0:
            self.mall_open = True
        return "ok"


@pytest.mark.asyncio
async def test_entry_alignment_reuses_session_cursor_when_contract_matches(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    cursor = GraphSessionCursor()
    cursor.set(home)

    backend = _Backend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = await backend.observe(tmp_path / "screen.png")

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.example.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == home.node_id
    assert cursor.current_node_id == home.node_id
    assert store.index_stats()["stable_anchor_scan_count"] == 0


@pytest.mark.asyncio
async def test_entry_alignment_clears_session_cursor_on_first_contract_miss(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile screen is visible",
            state_contract=_contract("Profile", clickable=True),
            fingerprint="fp-profile",
        )
    )
    cursor = GraphSessionCursor()
    cursor.set(profile)

    backend = _Backend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = await backend.observe(tmp_path / "screen.png")

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.example.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == home.node_id
    assert cursor.current_node_id == home.node_id
    assert store.index_stats()["stable_anchor_scan_count"] > 0


@pytest.mark.asyncio
async def test_entry_alignment_clears_session_cursor_on_compatibility_miss(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    other = store.upsert_node(
        GraphNode(
            node_id="node-other",
            app="com.other.app",
            platform="android",
            description="Other app screen",
            state_contract=_contract("Other", app="com.other.app", clickable=True),
            fingerprint="fp-other",
        )
    )
    cursor = GraphSessionCursor()
    cursor.set(other)

    backend = _Backend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = await backend.observe(tmp_path / "screen.png")

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.example.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == home.node_id
    assert cursor.current_node_id == home.node_id
    assert cursor.clear_reason is None
    assert store.index_stats()["stable_anchor_scan_count"] > 0


@pytest.mark.asyncio
async def test_entry_alignment_does_not_reuse_deprecated_cached_node(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    old_home = store.upsert_node(
        GraphNode(
            node_id="node-home-v1",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home-v1",
        )
    )
    new_home = store.upsert_node(
        GraphNode(
            node_id="node-home-v2",
            app="com.example.app",
            platform="android",
            description="Home screen with id is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home-v2",
        )
    )
    assert store.resolve_active_node(old_home.node_id) is not None
    assert store.get_node(old_home.node_id) is not None
    assert store.get_node(old_home.node_id).status == "deprecated"

    cursor = GraphSessionCursor()
    cursor.set(old_home)

    runtime = GraphRuntimeExecutor(
        store=store,
        backend=_Backend(),
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = Observation(
        screenshot_path=str(tmp_path / "screen.png"),
        screen_width=1000,
        screen_height=2000,
        foreground_app="com.example.app",
        platform="android",
        extra={
            "visible_text": ["Home"],
            "clickable_text": ["Home"],
            "resource_ids": ["com.example:id/home"],
            "ui_tree_node_count": 2,
        },
    )

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.example.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == new_home.node_id
    assert cursor.current_node_id == new_home.node_id
    assert cursor.clear_reason is None


@pytest.mark.asyncio
async def test_entry_alignment_uses_observation_app_to_block_cross_app_cursor_reuse(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    app_a_home = store.upsert_node(
        GraphNode(
            node_id="node-app-a-home",
            app="com.example.app",
            platform="android",
            description="App A home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-app-a-home",
        )
    )
    app_b_home = store.upsert_node(
        GraphNode(
            node_id="node-app-b-home",
            app="com.other.app",
            platform="android",
            description="App B home screen",
            state_contract=_contract("Other Home", app="com.other.app", clickable=True),
            fingerprint="fp-app-b-home",
        )
    )
    cursor = GraphSessionCursor()
    cursor.set(app_a_home)

    runtime = GraphRuntimeExecutor(
        store=store,
        backend=_Backend(),
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = Observation(
        screenshot_path=str(tmp_path / "screen.png"),
        screen_width=1000,
        screen_height=2000,
        foreground_app="com.other.app",
        platform="android",
        extra={
            "visible_text": ["Other Home"],
            "clickable_text": ["Other Home"],
            "resource_ids": ["com.other:id/home"],
            "ui_tree_node_count": 2,
        },
    )

    identified = await runtime.align_entry(observation, platform="android", app_hint=None)

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == app_b_home.node_id
    assert cursor.current_node_id == app_b_home.node_id
    assert cursor.clear_reason is None


@pytest.mark.asyncio
async def test_entry_alignment_uses_app_hint_to_block_cross_app_cursor_reuse(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    app_a_home = store.upsert_node(
        GraphNode(
            node_id="node-app-a-home",
            app="com.example.app",
            platform="android",
            description="App A home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-app-a-home",
        )
    )
    app_b_home = store.upsert_node(
        GraphNode(
            node_id="node-app-b-home",
            app="com.other.app",
            platform="android",
            description="App B home screen",
            state_contract=_contract("Other Home", app="com.other.app", clickable=True),
            fingerprint="fp-app-b-home",
        )
    )
    cursor = GraphSessionCursor()
    cursor.set(app_a_home)

    runtime = GraphRuntimeExecutor(
        store=store,
        backend=_Backend(),
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = Observation(
        screenshot_path=str(tmp_path / "screen.png"),
        screen_width=1000,
        screen_height=2000,
        foreground_app=None,
        platform="android",
        extra={
            "visible_text": ["Other Home"],
            "clickable_text": ["Other Home"],
            "resource_ids": ["com.other:id/home"],
            "ui_tree_node_count": 2,
        },
    )

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.other.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == app_b_home.node_id
    assert cursor.current_node_id == app_b_home.node_id
    assert cursor.clear_reason is None


@pytest.mark.asyncio
async def test_entry_alignment_prefers_observation_app_over_app_hint_for_cursor_reuse(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    app_a_home = store.upsert_node(
        GraphNode(
            node_id="node-app-a-home",
            app="com.example.app",
            platform="android",
            description="App A home screen",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-app-a-home",
        )
    )
    cursor = GraphSessionCursor()
    cursor.set(app_a_home)

    runtime = GraphRuntimeExecutor(
        store=store,
        backend=_Backend(),
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = Observation(
        screenshot_path=str(tmp_path / "screen.png"),
        screen_width=1000,
        screen_height=2000,
        foreground_app="com.example.app",
        platform="android",
        extra={
            "visible_text": ["Home"],
            "clickable_text": ["Home"],
            "resource_ids": ["com.example:id/home"],
            "ui_tree_node_count": 2,
        },
    )

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.other.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == app_a_home.node_id
    assert cursor.current_node_id == app_a_home.node_id
    assert cursor.clear_reason is None
    assert store.index_stats()["stable_anchor_scan_count"] == 0


@pytest.mark.asyncio
async def test_entry_alignment_sets_cursor_from_stable_anchor_bucket(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )

    backend = _Backend()
    cursor = GraphSessionCursor()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = await backend.observe(tmp_path / "screen.png")

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.example.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == home.node_id
    assert cursor.current_node_id == home.node_id
    assert cursor.clear_reason is None
    assert store.index_stats()["stable_anchor_scan_count"] > 0


@pytest.mark.asyncio
async def test_entry_alignment_matches_stable_node_without_embeddings(tmp_path: Path) -> None:
    embedder = _SpyEmbedder()
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=embedder,
        embedding_signature="sig-spy",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )

    backend = _Backend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )
    observation = await backend.observe(tmp_path / "screen.png")

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.example.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == home.node_id
    assert embedder.call_count == 0


@pytest.mark.asyncio
async def test_entry_alignment_scan_count_limited_to_current_app_bucket(tmp_path: Path) -> None:
    embedder = _SpyEmbedder()
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=embedder,
        embedding_signature="sig-spy",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-current-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-current-home",
        )
    )
    for index in range(50):
        store.upsert_node(
            GraphNode(
                node_id=f"node-other-{index}",
                app="com.other.app",
                platform="android",
                description=f"Other app screen {index}",
                state_contract=_contract(f"Other {index}", app="com.other.app", clickable=True),
                fingerprint=f"fp-other-{index}",
            )
        )

    backend = _Backend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )
    observation = await backend.observe(tmp_path / "screen.png")

    identified = await runtime.align_entry(observation, platform="android", app_hint="com.example.app")

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == home.node_id
    assert store.index_stats()["stable_anchor_scan_count"] == 1
    assert embedder.call_count == 0


@pytest.mark.asyncio
async def test_state_identifier_resolves_survivor_after_duplicate_compaction(
    tmp_path: Path,
) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    survivor = store.upsert_node(
        GraphNode(
            node_id="node-home-survivor",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            stats=NodeStats(reach_count=5, contract_match_count=5),
            fingerprint="fp-home",
        )
    )
    loser = GraphNode(
        node_id="node-home-loser",
        app="com.example.app",
        platform="android",
        description="Home screen is visible",
        state_contract=_contract("Home", clickable=True),
        stats=NodeStats(reach_count=1, contract_match_count=0, contract_miss_count=4),
        fingerprint="fp-home",
    )
    store._nodes[loser.node_id] = loser.normalized()

    store.compact_canonical_graph()

    identifier = StateIdentifier(store)
    observation = Observation(
        screenshot_path=str(tmp_path / "screen.png"),
        screen_width=1000,
        screen_height=2000,
        foreground_app="com.example.app",
        platform="android",
        extra={
            "visible_text": ["Home"],
            "clickable_text": ["Home"],
            "resource_ids": ["com.example:id/home"],
            "ui_tree_node_count": 2,
        },
    )

    identified = await identifier.identify(
        observation,
        foreground_app="com.example.app",
        platform="android",
        app="com.example.app",
    )

    assert identified.status == "matched"
    assert identified.current_node is not None
    assert identified.current_node.node_id == survivor.node_id
    assert store.resolve_active_node(loser.node_id) is None
    assert store.index_stats()["stable_anchor_scan_count"] == 1


@pytest.mark.asyncio
async def test_graph_session_cursor_is_session_local_and_not_persisted_to_disk(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    cursor = GraphSessionCursor()
    cursor.set(home)

    runtime = GraphRuntimeExecutor(
        store=store,
        backend=_Backend(),
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )
    observation = await runtime.backend.observe(tmp_path / "screen.png")
    await runtime.align_entry(observation, platform="android", app_hint="com.example.app")
    store.save()

    graph_payload = json.loads((store.store_dir / "skill_graph.json").read_text(encoding="utf-8"))
    assert "current_node_id" not in graph_payload
    assert "clear_reason" not in graph_payload
    assert cursor.current_node_id == home.node_id


@pytest.mark.asyncio
async def test_graph_runtime_executes_fixed_edge(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    now = time.time()
    node_home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    node_orders = store.upsert_node(
        GraphNode(
            node_id="node-orders",
            app="com.example.app",
            platform="android",
            description="Open orders page",
            state_contract=_contract("Orders", clickable=True),
            fingerprint="fp-orders",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-orders",
            app="com.example.app",
            platform="android",
            source_node_id=node_home.node_id,
            target_node_id=node_orders.node_id,
            action_type="tap",
            target="Orders",
            parameters={"x": 500.0, "y": 600.0, "relative": True},
            precondition=node_home.state_contract,
            stats=EdgeStats(attempt_count=5, success_count=5, last_success_at=now),
        )
    )

    backend = _Backend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute("open orders page", platform="android", app_hint="com.example.app")

    assert result.state.value == "succeeded", (
        result.error,
        result.state_identification.status if result.state_identification else None,
        result.goal_resolution.status if result.goal_resolution else None,
        result.path.status if result.path else None,
        result.path.reason if result.path else None,
    )
    assert result.path is not None
    assert [item.edge_id for item in result.path.edges] == ["edge-orders"]
    assert backend.actions and backend.actions[0].action_type == "tap"
    assert backend.actions[0].x == 500.0
    assert backend.actions[0].y == 600.0
    assert backend.actions[0].relative is True
    updated_edge = store.get_edge(edge.edge_id)
    assert updated_edge is not None
    assert updated_edge.stats.attempt_count == 6
    assert updated_edge.stats.success_count == 6


@pytest.mark.asyncio
async def test_graph_runtime_launches_target_app_before_entry_alignment(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-xhh-home",
            app="com.max.xiaoheihe",
            platform="android",
            description="XiaoHeiHe home screen is visible",
            state_contract=_contract("我", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-xhh-home",
        )
    )
    mall = store.upsert_node(
        GraphNode(
            node_id="node-xhh-mall",
            app="com.max.xiaoheihe",
            platform="android",
            description="Black Box Mall page is visible",
            state_contract=_contract("黑盒商城", app="com.max.xiaoheihe", clickable=True),
            stats=NodeStats(reach_count=10, contract_match_count=10),
            fingerprint="fp-xhh-mall",
            retrieval_profile={
                "visible_text": ["黑盒商城", "我的订单"],
                "clickable_text": ["黑盒商城", "我的订单"],
            },
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-mall",
            app="com.max.xiaoheihe",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=mall.node_id,
            action_type="tap",
            target="我",
            parameters={"x": 900.0, "y": 950.0, "relative": True},
            precondition=home.state_contract,
            stats=EdgeStats(attempt_count=5, success_count=5),
        )
    )
    backend = _LaunchThenHomeBackend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute(
        "打开小黑盒App。点击底部我。打开黑盒商城。",
        platform="android",
        app_hint="com.max.xiaoheihe",
    )

    assert result.state.value == "succeeded", (
        result.error,
        result.state_identification.status if result.state_identification else None,
        result.goal_resolution.status if result.goal_resolution else None,
        result.path.status if result.path else None,
        result.path.reason if result.path else None,
    )
    assert [action.action_type for action in backend.actions] == ["open_app", "tap", "back"]
    assert backend.actions[0].text == "com.max.xiaoheihe"
    assert result.path is not None
    assert [path_edge.edge_id for path_edge in result.path.edges] == [edge.edge_id]


@pytest.mark.asyncio
async def test_graph_runtime_substitutes_parameterized_edge_text(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    home = store.upsert_node(
        GraphNode(
            node_id="node-bili-home",
            app="tv.danmaku.bili",
            platform="android",
            description="Bilibili home search bar",
            state_contract=normalize_state_contract({
                "anchor": {"app_package": "tv.danmaku.bili"},
                "signature": {
                    "required": [
                        {
                            "selector": {"resource_id": "tv.danmaku.bili:id/expand_search"},
                            "state": ["visible"],
                        }
                    ],
                    "forbidden": [],
                },
            }),
            fingerprint="fp-bili-home",
        )
    )
    query = store.upsert_node(
        GraphNode(
            node_id="node-bili-query",
            app="tv.danmaku.bili",
            platform="android",
            description="Bilibili search query input",
            state_contract=normalize_state_contract({
                "anchor": {"app_package": "tv.danmaku.bili"},
                "signature": {
                    "required": [
                        {
                            "selector": {"resource_id": "tv.danmaku.bili:id/search_src_text"},
                            "state": ["visible"],
                        }
                    ],
                    "forbidden": [],
                },
            }),
            fingerprint="fp-bili-query",
        )
    )
    results = store.upsert_node(
        GraphNode(
            node_id="node-bili-results",
            app="tv.danmaku.bili",
            platform="android",
            description="Bilibili search results page",
            state_contract=normalize_state_contract({
                "anchor": {"app_package": "tv.danmaku.bili"},
                "signature": {
                    "required": [
                        {"selector": {"resource_id": "tv.danmaku.bili:id/search_fake_text"}, "state": ["visible"]},
                        {"selector": {"resource_id": "tv.danmaku.bili:id/search_close_btn"}, "state": ["visible"]},
                    ],
                    "forbidden": [],
                },
            }),
            fingerprint="fp-bili-results",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-bili-open-search",
            app="tv.danmaku.bili",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=query.node_id,
            action_type="tap",
            target="Search bar",
            parameters={"x": 459.0, "y": 76.0, "relative": True},
            precondition=home.state_contract,
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-bili-input-query",
            app="tv.danmaku.bili",
            platform="android",
            source_node_id=query.node_id,
            target_node_id=results.node_id,
            action_type="input_text",
            target="Search query",
            parameters={"text": "{{query}}", "auto_enter": True},
            precondition=query.state_contract,
        )
    )

    class _BiliSearchBackend(_Backend):
        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            self.observe_count += 1
            if self.observe_count == 1:
                extra = {
                    "resource_ids": ["tv.danmaku.bili:id/expand_search"],
                    "ui_tree_node_count": 1,
                }
            elif self.observe_count == 2:
                extra = {
                    "resource_ids": ["tv.danmaku.bili:id/search_src_text"],
                    "ui_tree_node_count": 1,
                }
            else:
                extra = {
                    "resource_ids": [
                        "tv.danmaku.bili:id/search_fake_text",
                        "tv.danmaku.bili:id/search_close_btn",
                    ],
                    "ui_tree_node_count": 2,
                }
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1000,
                screen_height=2000,
                foreground_app="tv.danmaku.bili",
                platform="android",
                extra=extra,
            )

    backend = _BiliSearchBackend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute(
        "去B站搜“AI绘画教程”，然后按最多播放排序查看。",
        platform="android",
        app_hint="tv.danmaku.bili",
    )

    assert result.state.value == "succeeded", (
        result.error,
        result.state_identification.status if result.state_identification else None,
        result.goal_resolution.status if result.goal_resolution else None,
        result.path.status if result.path else None,
        result.path.reason if result.path else None,
    )
    input_actions = [action for action in backend.actions if action.action_type == "input_text"]
    assert input_actions
    assert input_actions[0].text == "AI绘画教程"


@pytest.mark.asyncio
async def test_graph_runtime_executes_prefix_when_goal_is_unconfirmed(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    now = time.time()
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.max.xiaoheihe",
            platform="android",
            description="XiaoHeiHe home feed",
            state_contract=_contract("Home", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-home",
        )
    )
    profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.max.xiaoheihe",
            platform="android",
            description="black box mall rewards profile page",
            state_contract=_contract("Black Box Mall", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-profile",
        )
    )
    store.upsert_node(
        GraphNode(
            node_id="node-activity",
            app="com.max.xiaoheihe",
            platform="android",
            description="black box mall rewards campaign page",
            state_contract=_contract("Activity", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-activity",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-profile",
            app="com.max.xiaoheihe",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=profile.node_id,
            action_type="tap",
            target="Me",
            parameters={"x": 800.0, "y": 950.0, "relative": True},
            precondition=home.state_contract,
            stats=EdgeStats(attempt_count=5, success_count=5, last_success_at=now),
        )
    )

    class _XhhBackend(_Backend):
        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            self.observe_count += 1
            label = "Home" if self.observe_count == 1 else "Black Box Mall"
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1000,
                screen_height=2000,
                foreground_app="com.max.xiaoheihe",
                platform="android",
                extra={"visible_text": [label], "clickable_text": [label], "ui_tree_node_count": 2},
            )

    recorder = _EventRecorder()
    backend = _XhhBackend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
        trajectory_recorder=recorder,
    )

    result = await runtime.execute(
        "open black box mall rewards page",
        platform="android",
        app_hint="com.max.xiaoheihe",
    )

    assert result.state.value == "succeeded"
    assert result.goal_resolution is not None
    assert result.goal_resolution.status == "candidates"
    assert result.prefix_only is True
    assert result.prefix_terminal_node_id == profile.node_id
    assert runtime.session_cursor.current_node_id == profile.node_id
    assert [step.edge_id for step in result.step_results] == ["edge-profile"]
    assert result.execution_summary == "Graph prefix executed: edge-profile:succeeded"
    prefix_events = [event for event in recorder.events if event.get("type") == "graph_prefix_result"]
    assert prefix_events
    assert prefix_events[-1]["prefix_only"] is True
    assert prefix_events[-1]["terminal_node_id"] == profile.node_id
    assert prefix_events[-1]["edge_count"] == 1


@pytest.mark.asyncio
async def test_graph_runtime_target_contract_miss_does_not_advance_cursor(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    now = time.time()
    node_home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    node_profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Open profile page",
            state_contract=_contract("Profile", clickable=True),
            fingerprint="fp-profile",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-profile",
            app="com.example.app",
            platform="android",
            source_node_id=node_home.node_id,
            target_node_id=node_profile.node_id,
            action_type="tap",
            target="Profile",
            parameters={"x": 500.0, "y": 600.0, "relative": True},
            precondition=node_home.state_contract,
            stats=EdgeStats(attempt_count=5, success_count=5, last_success_at=now),
        )
    )
    cursor = GraphSessionCursor()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=_Backend(),
        artifacts_root=tmp_path / "runs",
        session_cursor=cursor,
    )

    result = await runtime.execute("open profile page", platform="android", app_hint="com.example.app")

    assert result.state.value == "failed"
    assert result.step_results
    assert result.step_results[0].failure_reason == "target_contract_miss"
    assert result.error == "target_contract_miss"
    assert cursor.current_node_id == node_home.node_id
    assert cursor.current_node_id != node_profile.node_id
    updated_edge = store.get_edge(edge.edge_id)
    assert updated_edge is not None
    assert updated_edge.stats.failure_reason_counts["target_contract_miss"] == 1


@pytest.mark.asyncio
async def test_graph_runtime_persists_node_and_edge_stats_after_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            fingerprint="fp-home",
            stats=NodeStats(reach_count=2, contract_match_count=1),
        )
    )
    node_orders = store.upsert_node(
        GraphNode(
            node_id="node-orders",
            app="com.example.app",
            platform="android",
            description="Open orders page",
            state_contract=_contract("Orders", clickable=True),
            fingerprint="fp-orders",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-orders",
            app="com.example.app",
            platform="android",
            source_node_id=node_home.node_id,
            target_node_id=node_orders.node_id,
            action_type="tap",
            target="Orders",
            parameters={"x": 500.0, "y": 600.0, "relative": True},
            precondition=node_home.state_contract,
            stats=EdgeStats(attempt_count=7, success_count=3),
        )
    )
    previous_reach_count = node_home.stats.reach_count
    previous_match_count = node_home.stats.contract_match_count
    previous_attempt_count = edge.stats.attempt_count
    previous_success_count = edge.stats.success_count

    original_record_node_match = store.record_node_match
    original_record_edge_attempt = store.record_edge_attempt

    def record_node_match_without_autosave(
        node_id: str,
        *,
        matched: bool,
        save: bool = True,
    ) -> None:
        original_record_node_match(node_id, matched=matched, save=False)

    def record_edge_attempt_without_autosave(
        edge_id: str,
        *,
        success: bool,
        latency_ms: float | None = None,
        failure_reason: str | None = None,
        save: bool = True,
    ) -> None:
        original_record_edge_attempt(
            edge_id,
            success=success,
            latency_ms=latency_ms,
            failure_reason=failure_reason,
            save=False,
        )

    monkeypatch.setattr(store, "record_node_match", record_node_match_without_autosave)
    monkeypatch.setattr(store, "record_edge_attempt", record_edge_attempt_without_autosave)

    backend = _Backend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute("open orders page", platform="android", app_hint="com.example.app")

    assert result.state.value == "succeeded"
    reloaded = SkillGraphStore(
        store_dir=store.store_dir,
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    reloaded_home = reloaded.get_node(node_home.node_id)
    assert reloaded_home is not None
    assert reloaded_home.stats.reach_count > previous_reach_count
    assert reloaded_home.stats.contract_match_count > previous_match_count
    reloaded_edge = reloaded.get_edge(edge.edge_id)
    assert reloaded_edge is not None
    assert reloaded_edge.stats.attempt_count > previous_attempt_count
    assert reloaded_edge.stats.success_count > previous_success_count


@pytest.mark.asyncio
async def test_graph_runtime_blocks_on_precondition_miss(tmp_path: Path) -> None:
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
            fingerprint="fp-home",
        )
    )
    node_orders = store.upsert_node(
        GraphNode(
            node_id="node-orders",
            app="com.example.app",
            platform="android",
            description="Open orders page",
            state_contract=_contract("Orders", clickable=True),
            fingerprint="fp-orders",
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-orders",
            app="com.example.app",
            platform="android",
            source_node_id=node_home.node_id,
            target_node_id=node_orders.node_id,
            action_type="tap",
            target="Orders",
            parameters={"x": 500.0, "y": 600.0, "relative": True},
            precondition=_contract("Missing", clickable=True),
            stats=EdgeStats(attempt_count=5, success_count=5, last_success_at=time.time()),
        )
    )

    backend = _Backend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute("open orders page", platform="android", app_hint="com.example.app")

    assert result.state.value == "failed"
    assert result.step_results
    assert result.step_results[0].failure_reason == "precondition_miss"
    assert backend.actions == []
    updated_edge = store.get_edge(edge.edge_id)
    assert updated_edge is not None
    assert updated_edge.stats.failure_reason_counts["precondition_miss"] == 1
    reloaded = SkillGraphStore(
        store_dir=store.store_dir,
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    reloaded_edge = reloaded.get_edge(edge.edge_id)
    assert reloaded_edge is not None
    assert reloaded_edge.stats.failure_reason_counts["precondition_miss"] == 1


@pytest.mark.asyncio
async def test_graph_runtime_dismisses_interrupt_before_path(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    store.upsert_node(
        GraphNode(
            node_id="interrupt-permission",
            app="com.example.app",
            platform="android",
            description="Permission dialog",
            state_contract=_contract("Allow", clickable=True),
            fingerprint="fp-interrupt",
            kind="interrupt",
            dismiss_action={"action_type": "tap", "x": 100.0, "y": 100.0, "relative": True},
            resume_policy="reidentify",
        )
    )
    node_home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    node_orders = store.upsert_node(
        GraphNode(
            node_id="node-orders",
            app="com.example.app",
            platform="android",
            description="Open orders page",
            state_contract=_contract("Orders", clickable=True),
            fingerprint="fp-orders",
        )
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-orders",
            app="com.example.app",
            platform="android",
            source_node_id=node_home.node_id,
            target_node_id=node_orders.node_id,
            action_type="tap",
            target="Orders",
            parameters={"x": 500.0, "y": 600.0, "relative": True},
            precondition=node_home.state_contract,
            stats=EdgeStats(attempt_count=5, success_count=5),
        )
    )

    backend = _InterruptBackend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute("open orders page", platform="android", app_hint="com.example.app")

    assert result.state.value == "succeeded"
    assert [action.action_type for action in backend.actions] == ["tap", "tap", "back"]
    assert backend.actions[0].x == 100.0
    assert backend.actions[1].x == 500.0


@pytest.mark.asyncio
async def test_graph_runtime_resamples_unknown_before_blocking(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    store.upsert_node(
        GraphNode(
            node_id="node-orders",
            app="com.example.app",
            platform="android",
            description="Open orders page",
            state_contract=_contract("Orders", clickable=True),
            fingerprint="fp-orders",
        )
    )

    backend = _AlwaysUnknownBackend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute("open orders page", platform="android", app_hint="com.example.app")

    assert result.state.value == "failed"
    assert backend.observe_count >= 2


@pytest.mark.asyncio
async def test_graph_runtime_enqueues_refresh_trigger_on_persistent_unknown(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    store.upsert_node(
        GraphNode(
            node_id="node-orders",
            app="com.example.app",
            platform="android",
            description="Open orders page",
            state_contract=_contract("Orders", clickable=True),
            fingerprint="fp-orders",
        )
    )

    backend = _AlwaysUnknownBackend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute("open orders page", platform="android", app_hint="com.example.app")

    assert result.state.value == "failed"
    queue_path = store.store_dir / "skill_graph_refresh_queue.jsonl"
    assert queue_path.exists()
    record = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["reason"] == "state_identification_miss"
    assert record["allowed_outputs"] == ["patch_contract", "spawn_version", "add_edge"]


@pytest.mark.asyncio
async def test_graph_runtime_enqueues_profile_only_refresh_trigger(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
    store.upsert_node(
        GraphNode(
            node_id="node-mall-profile",
            app="com.example.app",
            platform="android",
            description="Graph artifact for mall page",
            state_contract=None,
            kind="auxiliary",
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

    backend = _ProfileOnlyBackend()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
    )

    result = await runtime.execute("打开黑盒商城的我的订单", platform="android", app_hint="com.example.app")

    assert result.state.value == "failed"
    assert result.error == "profile_only_match"
    assert any(candidate.node.node_id == "node-mall-profile" for candidate in result.candidates)
    queue_path = store.store_dir / "skill_graph_refresh_queue.jsonl"
    assert queue_path.exists()
    record = json.loads(queue_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["reason"] == "profile_only_match"
    assert record["candidate_node_ids"] == ["node-mall-profile"]


@pytest.mark.asyncio
async def test_graph_runtime_records_navigation_back_and_restores_terminal(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
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
            parameters={"x": 100.0, "y": 100.0, "relative": True},
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
            parameters={"x": 500.0, "y": 500.0, "relative": True},
            precondition=middle.state_contract,
        )
    )

    backend = _NavigationProbeBackend()
    recorder = _EventRecorder()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
        trajectory_recorder=recorder,
    )

    result = await runtime.execute("open target page", platform="android", app_hint="com.example.app")

    assert result.state.value == "succeeded"
    assert [action.action_type for action in backend.actions] == ["tap", "tap", "back", "tap"]
    nav_edges = [edge for edge in store.list_edges(platform="android", app="com.example.app") if edge.kind == "navigation_back"]
    assert len(nav_edges) == 1
    assert nav_edges[0].source_node_id == target.node_id
    assert nav_edges[0].target_node_id == middle.node_id
    assert nav_edges[0].stats.success_count == 1
    assert any(event["type"] == "graph_navigation_probe" for event in recorder.events)
    assert any(event["type"] == "graph_navigation_restore" for event in recorder.events)


@pytest.mark.asyncio
async def test_graph_runtime_records_unknown_navigation_transition_without_fake_target(tmp_path: Path) -> None:
    store = SkillGraphStore(
        store_dir=tmp_path / "graph",
        embedding_provider=_StableEmbedder(),
        embedding_signature="sig-v1",
    )
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
            edge_id="edge-home-target",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Target",
            parameters={"x": 500.0, "y": 500.0, "relative": True},
            precondition=home.state_contract,
        )
    )

    backend = _UnknownReturnBackend()
    recorder = _EventRecorder()
    runtime = GraphRuntimeExecutor(
        store=store,
        backend=backend,
        artifacts_root=tmp_path / "runs",
        trajectory_recorder=recorder,
    )

    result = await runtime.execute("open target page", platform="android", app_hint="com.example.app")

    assert result.state.value == "succeeded"
    assert [action.action_type for action in backend.actions] == ["tap", "back"]
    evidence_path = tmp_path / "graph" / "skill_graph_transition_evidence.jsonl"
    assert evidence_path.is_file()
    record = json.loads(evidence_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["reason"] == "navigation_target_unknown"
    assert record["edge_kind"] == "navigation_back"
    assert record["source_node_id"] == target.node_id
    assert all(edge.kind == "action" for edge in store.list_edges(platform="android", app="com.example.app"))
    assert any(event["type"] == "graph_transition_evidence" for event in recorder.events)
