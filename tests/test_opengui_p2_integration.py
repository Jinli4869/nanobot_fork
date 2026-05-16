"""Phase 2 integration tests — OpenGUI skills, trajectory, and full flow.

Covers: AGENT-05, SKILL-08, TRAJ-03, TEST-05.
"""
from __future__ import annotations

import copy
import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest

from opengui.agent import AgentResult, GuiAgent
from opengui.backends.dry_run import DryRunBackend
from opengui.interfaces import LLMResponse, ToolCall
from opengui.observation import Observation
from opengui.memory.retrieval import MemoryRetriever
from opengui.memory.store import MemoryStore
from opengui.memory.types import MemoryEntry, MemoryType
from opengui.skills.data import Skill, SkillStep
from opengui.skills.library import SkillLibrary
from opengui.trajectory.recorder import TrajectoryRecorder
from opengui.skills.graph import EdgeStats, GraphEdge, GraphNode, SkillGraphStore
from opengui.skills.state_contract import normalize_state_contract


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    """Deterministic embedder: stable token hashing across processes."""

    DIM = 8

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


class _GraphEmbedder:
    """Stable embedder for graph runtime integration tests."""

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


_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _RecordingLLM:
    """Mock LLM that returns scripted responses and records all calls."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
        self.calls.append(copy.deepcopy(messages))
        if not self._responses:
            raise AssertionError("No scripted responses left")
        return self._responses.pop(0)


def _done_response(call_id: str = "tc_done") -> LLMResponse:
    return LLMResponse(
        content="Action: Task complete",
        tool_calls=[ToolCall(
            id=call_id, name="computer_use",
            arguments={"action_type": "done", "status": "success"},
        )],
    )


def _wait_response(call_id: str = "tc_wait") -> LLMResponse:
    return LLMResponse(
        content="Action: waiting",
        tool_calls=[ToolCall(
            id=call_id, name="computer_use",
            arguments={"action_type": "wait", "duration_ms": 1},
        )],
    )


def _make_recorder(tmp_path: Path, task: str = "test") -> TrajectoryRecorder:
    return TrajectoryRecorder(output_dir=tmp_path / "traj", task=task)


def _make_memory_entry(
    entry_id: str, content: str, memory_type: MemoryType = MemoryType.APP_GUIDE,
) -> MemoryEntry:
    return MemoryEntry(
        entry_id=entry_id, memory_type=memory_type,
        platform="android", content=content,
    )


def _graph_contract(label: str, *, app: str = "com.example.app", clickable: bool = False) -> dict[str, object]:
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


# ---------------------------------------------------------------------------
# AGENT-04 / MEM-05: Memory injected into system prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_injected_into_system_prompt(tmp_path: Path) -> None:
    """GuiAgent.run() should inject memory entries into the system prompt."""
    store = MemoryStore(tmp_path / "mem")
    store.add(_make_memory_entry("m1", "Settings is the gear icon on home screen"))
    store.add(_make_memory_entry("pol1", "Always confirm before deleting", MemoryType.POLICY))
    store.save()

    retriever = MemoryRetriever(embedding_provider=_FakeEmbedder())
    await retriever.index(store.list_all())

    llm = _RecordingLLM([
        LLMResponse(content='{"applicable": true}'),
        _done_response(),
    ])
    agent = GuiAgent(
        llm, DryRunBackend(),
        trajectory_recorder=_make_recorder(tmp_path, "Open Settings"),
        memory_retriever=retriever,
        artifacts_root=tmp_path / "runs", max_steps=1,
    )

    result = await agent.run("Open Settings", max_retries=1)
    assert result.success

    # System prompt (first message of first LLM call) should contain memory content
    system_msg = llm.calls[0][0]["content"]
    assert "Relevant Knowledge" in system_msg
    assert "Always confirm before deleting" in system_msg


# ---------------------------------------------------------------------------
# AGENT-05 / SKILL-08: Skill path chosen above threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_path_chosen_above_threshold(tmp_path: Path) -> None:
    """When a matching skill exists above threshold, GuiAgent should use SkillExecutor path."""
    embedder = _FakeEmbedder()
    lib = SkillLibrary(store_dir=tmp_path / "skills", embedding_provider=embedder)
    skill = Skill(
        skill_id="wifi-toggle", name="Toggle Wi-Fi",
        description="Toggle Wi-Fi in Settings", app="com.android.settings",
        platform="android",
        steps=(
            SkillStep(action_type="open_app", target="com.android.settings"),
            SkillStep(action_type="tap", target="Wi-Fi toggle"),
        ),
    )
    lib.add(skill)
    await lib._rebuild_index()

    # Mock executor that returns success
    mock_executor = AsyncMock()
    mock_exec_result = AsyncMock()
    mock_exec_result.state.value = "succeeded"
    mock_executor.execute = AsyncMock(return_value=mock_exec_result)

    class _AndroidDryRunBackend:
        platform = "android"

        async def preflight(self) -> None:
            return None

        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(_TINY_PNG)
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1080,
                screen_height=1920,
                foreground_app="com.android.settings",
                platform="android",
            )

        async def list_apps(self) -> list[str]:
            return []

        async def execute(self, action, timeout: float = 5.0) -> str:
            return f"[android-dry-run] {action.action_type}"

    llm = _RecordingLLM([
        LLMResponse(content='{"selected_skill_id": "wifi-toggle", "end_step": 2, "reason": "settings wifi task"}'),
        _done_response(),
    ])
    recorder = _make_recorder(tmp_path, "Turn on Wi-Fi")
    agent = GuiAgent(
        llm, _AndroidDryRunBackend(),
        trajectory_recorder=recorder,
        skill_library=lib, skill_executor=mock_executor,
        skill_threshold=0.3,  # low threshold to ensure match
        artifacts_root=tmp_path / "runs", max_steps=1,
    )

    result = await agent.run("Toggle Wi-Fi", max_retries=1)
    assert result.success

    # Check trajectory has a SKILL phase change
    traj_path = recorder.path
    assert traj_path is not None and traj_path.exists()
    events = [json.loads(line) for line in traj_path.read_text().splitlines()]
    phase_changes = [e for e in events if e.get("type") == "phase_change"]
    skill_phases = [e for e in phase_changes if e.get("to_phase") == "skill"]
    assert len(skill_phases) >= 1


@pytest.mark.asyncio
async def test_graph_runtime_path_executes_before_flat_search(tmp_path: Path) -> None:
    """When a graph path exists, GuiAgent should execute it before flat skill search."""
    graph_store_dir = tmp_path / "skills"
    graph = SkillGraphStore(
        store_dir=graph_store_dir,
        embedding_provider=_GraphEmbedder(),
        embedding_signature="sig-v1",
    )
    now = time.time()
    node_home = graph.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_graph_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )
    node_orders = graph.upsert_node(
        GraphNode(
            node_id="node-orders",
            app="com.example.app",
            platform="android",
            description="Open orders page",
            state_contract=_graph_contract("Orders", clickable=True),
            fingerprint="fp-orders",
        )
    )
    graph.upsert_edge(
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

    class _GraphBackend:
        platform = "android"

        def __init__(self) -> None:
            self.actions: list[object] = []
            self.observe_count = 0

        async def preflight(self) -> None:
            return None

        async def list_apps(self) -> list[str]:
            return ["com.example.app"]

        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(_TINY_PNG)
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
                screen_width=1080,
                screen_height=1920,
                foreground_app="com.example.app",
                platform="android",
                extra=extra,
            )

        async def execute(self, action, timeout: float = 5.0) -> str:
            self.actions.append(action)
            return f"[graph] {action.action_type}"

    backend = _GraphBackend()
    llm = _RecordingLLM([_done_response()])
    recorder = _make_recorder(tmp_path, "Open orders page")
    agent = GuiAgent(
        llm,
        backend,
        trajectory_recorder=recorder,
        skill_library=SkillLibrary(store_dir=graph_store_dir, embedding_provider=_GraphEmbedder()),
        skill_threshold=0.3,
        artifacts_root=tmp_path / "runs",
        max_steps=1,
    )

    result = await agent.run("open orders page", max_retries=1, app_hint="com.example.app")
    assert result.success
    assert backend.actions

    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    assert any(e.get("type") == "phase_change" and e.get("to_phase") == "skill" for e in events)
    assert any(e.get("type") == "graph_path_compiled" and e.get("edge_count") == 1 for e in events)
    assert any(e.get("type") == "graph_step" and e.get("edge_id") == "edge-orders" for e in events)
    assert not any(e.get("type") == "skill_search" and e.get("source") == "reuser" for e in events)


@pytest.mark.asyncio
async def test_graph_runtime_starts_from_current_home_page_without_open_app(tmp_path: Path) -> None:
    graph_store_dir = tmp_path / "skills"
    graph = SkillGraphStore(
        store_dir=graph_store_dir,
        embedding_provider=_GraphEmbedder(),
        embedding_signature="sig-v1",
    )
    now = time.time()
    home = graph.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.max.xiaoheihe",
            platform="android",
            description="XiaoHeiHe home feed",
            state_contract=_graph_contract("Home", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-home",
        )
    )
    profile = graph.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.max.xiaoheihe",
            platform="android",
            description="black box mall rewards profile page",
            state_contract=_graph_contract("Black Box Mall", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-profile",
        )
    )
    graph.upsert_node(
        GraphNode(
            node_id="node-activity",
            app="com.max.xiaoheihe",
            platform="android",
            description="black box mall rewards campaign page",
            state_contract=_graph_contract("Activity", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-activity",
        )
    )
    graph.upsert_edge(
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

    class _BackendOnHome:
        platform = "android"

        def __init__(self) -> None:
            self.actions: list[object] = []
            self.observe_count = 0

        async def preflight(self) -> None:
            return None

        async def list_apps(self) -> list[str]:
            return ["com.max.xiaoheihe"]

        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(_TINY_PNG)
            self.observe_count += 1
            label = "Home" if self.observe_count == 1 else "Black Box Mall"
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1080,
                screen_height=1920,
                foreground_app="com.max.xiaoheihe",
                platform="android",
                extra={"visible_text": [label], "clickable_text": [label], "ui_tree_node_count": 2},
            )

        async def execute(self, action, timeout: float = 5.0) -> str:
            self.actions.append(action)
            return f"[graph] {action.action_type}"

    backend = _BackendOnHome()
    llm = _RecordingLLM([_done_response()])
    recorder = _make_recorder(tmp_path, "open black box mall rewards page")
    agent = GuiAgent(
        llm,
        backend,
        trajectory_recorder=recorder,
        skill_library=SkillLibrary(store_dir=graph_store_dir, embedding_provider=_GraphEmbedder()),
        skill_threshold=0.3,
        artifacts_root=tmp_path / "runs",
        max_steps=1,
    )

    result = await agent.run(
        "open black box mall rewards page",
        max_retries=1,
        app_hint="com.max.xiaoheihe",
    )

    assert result.success
    assert [action.action_type for action in backend.actions] == ["tap"]
    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    assert any(
        event.get("type") == "graph_prefix_result"
        and event.get("prefix_only") is True
        and event.get("terminal_node_id") == profile.node_id
        and event.get("edge_count") == 1
        for event in events
    )
    assert any(
        event.get("type") == "graph_runtime_result"
        and event.get("prefix_only") is True
        and event.get("prefix_terminal_node_id") == profile.node_id
        for event in events
    )


@pytest.mark.asyncio
async def test_graph_prefix_success_does_not_suppress_flat_skill_search(tmp_path: Path) -> None:
    graph_store_dir = tmp_path / "skills"
    graph = SkillGraphStore(
        store_dir=graph_store_dir,
        embedding_provider=_GraphEmbedder(),
        embedding_signature="sig-v1",
    )
    now = time.time()
    home = graph.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.max.xiaoheihe",
            platform="android",
            description="XiaoHeiHe home feed",
            state_contract=_graph_contract("Home", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-home",
        )
    )
    profile = graph.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.max.xiaoheihe",
            platform="android",
            description="black box mall rewards profile page",
            state_contract=_graph_contract("Black Box Mall", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-profile",
        )
    )
    graph.upsert_node(
        GraphNode(
            node_id="node-activity",
            app="com.max.xiaoheihe",
            platform="android",
            description="black box mall rewards campaign page",
            state_contract=_graph_contract("Activity", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-activity",
        )
    )
    graph.upsert_edge(
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
    skill_library = SkillLibrary(store_dir=graph_store_dir, embedding_provider=_GraphEmbedder())
    skill_library.add(Skill(
        skill_id="flat-black-box-mall",
        name="Open Black Box Mall",
        description="open black box mall rewards page",
        app="com.max.xiaoheihe",
        platform="android",
        steps=(SkillStep(action_type="tap", target="Black Box Mall"),),
    ))
    await skill_library._rebuild_index()

    class _BackendOnHome:
        platform = "android"

        def __init__(self) -> None:
            self.actions: list[object] = []
            self.observe_count = 0

        async def preflight(self) -> None:
            return None

        async def list_apps(self) -> list[str]:
            return ["com.max.xiaoheihe"]

        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(_TINY_PNG)
            self.observe_count += 1
            label = "Home" if self.observe_count == 1 else "Black Box Mall"
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1080,
                screen_height=1920,
                foreground_app="com.max.xiaoheihe",
                platform="android",
                extra={"visible_text": [label], "clickable_text": [label], "ui_tree_node_count": 2},
            )

        async def execute(self, action, timeout: float = 5.0) -> str:
            self.actions.append(action)
            return f"[graph] {action.action_type}"

    backend = _BackendOnHome()
    llm = _RecordingLLM([
        LLMResponse(content='{"selected_skill_id": "flat-black-box-mall", "end_step": 1, "reason": "finish from profile page"}'),
        _done_response(),
    ])
    recorder = _make_recorder(tmp_path, "open black box mall rewards page")
    agent = GuiAgent(
        llm,
        backend,
        trajectory_recorder=recorder,
        skill_library=skill_library,
        skill_threshold=0.3,
        artifacts_root=tmp_path / "runs",
        max_steps=1,
    )

    result = await agent.run(
        "open black box mall rewards page",
        max_retries=1,
        app_hint="com.max.xiaoheihe",
    )

    assert result.success
    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    assert any(event.get("type") == "graph_runtime_result" and event.get("prefix_only") is True for event in events)
    assert any(event.get("type") == "skill_search" for event in events)


@pytest.mark.asyncio
async def test_graph_runtime_exception_falls_back_to_agent_loop(tmp_path: Path) -> None:
    graph_store_dir = tmp_path / "skills"
    graph = SkillGraphStore(
        store_dir=graph_store_dir,
        embedding_provider=_GraphEmbedder(),
        embedding_signature="sig-v1",
    )
    graph.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen is visible",
            state_contract=_graph_contract("Home", clickable=True),
            fingerprint="fp-home",
        )
    )

    class _FlakyGraphBackend:
        platform = "android"

        def __init__(self) -> None:
            self.observe_count = 0

        async def preflight(self) -> None:
            return None

        async def list_apps(self) -> list[str]:
            return ["com.example.app"]

        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            self.observe_count += 1
            if self.observe_count == 1:
                raise RuntimeError("graph observe failed")
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(_TINY_PNG)
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1080,
                screen_height=1920,
                foreground_app="com.example.app",
                platform="android",
                extra={"visible_text": ["Home"], "clickable_text": ["Home"], "ui_tree_node_count": 2},
            )

        async def execute(self, action, timeout: float = 5.0) -> str:
            return f"[fallback] {action.action_type}"

    backend = _FlakyGraphBackend()
    llm = _RecordingLLM([_done_response()])
    recorder = _make_recorder(tmp_path, "finish after graph exception")
    agent = GuiAgent(
        llm,
        backend,
        trajectory_recorder=recorder,
        skill_library=SkillLibrary(store_dir=graph_store_dir, embedding_provider=_GraphEmbedder()),
        skill_threshold=0.3,
        artifacts_root=tmp_path / "runs",
        max_steps=1,
    )

    result = await agent.run("finish after graph exception", max_retries=1, app_hint="com.example.app")

    assert result.success
    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    assert any(
        event.get("type") == "graph_runtime_result"
        and event.get("state") == "failed"
        and event.get("exception_type") == "RuntimeError"
        for event in events
    )
    assert any(event.get("type") == "skill_search" for event in events)


@pytest.mark.asyncio
async def test_graph_runtime_setup_failure_falls_back_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    graph_store_dir = tmp_path / "skills"
    skill_library = SkillLibrary(store_dir=graph_store_dir, embedding_provider=_GraphEmbedder())

    def _raise(*args, **kwargs):
        raise RuntimeError("graph store setup failed")

    monkeypatch.setattr("opengui.skills.graph.SkillGraphStore", _raise)

    class _SimpleBackend:
        platform = "android"

        def __init__(self) -> None:
            self.actions: list[object] = []

        async def preflight(self) -> None:
            return None

        async def list_apps(self) -> list[str]:
            return ["com.example.app"]

        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(_TINY_PNG)
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1080,
                screen_height=1920,
                foreground_app="com.example.app",
                platform="android",
                extra={"visible_text": ["Home"], "clickable_text": ["Home"], "ui_tree_node_count": 2},
            )

        async def execute(self, action, timeout: float = 5.0) -> str:
            self.actions.append(action)
            return f"[fallback] {action.action_type}"

    backend = _SimpleBackend()
    llm = _RecordingLLM([_done_response()])
    recorder = _make_recorder(tmp_path, "graph setup fallback")
    agent = GuiAgent(
        llm,
        backend,
        trajectory_recorder=recorder,
        skill_library=skill_library,
        skill_threshold=0.3,
        artifacts_root=tmp_path / "runs",
        max_steps=1,
    )

    result = await agent.run("graph setup fallback", max_retries=1, app_hint="com.example.app")

    assert result.success
    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    assert any(event.get("type") == "graph_runtime_result" and event.get("state") == "failed" for event in events)
    assert any(event.get("type") == "skill_search" for event in events)


# ---------------------------------------------------------------------------
# AGENT-05: Free explore when no skill match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_explore_when_no_skill_match(tmp_path: Path) -> None:
    """When no skill matches, GuiAgent should use free exploration."""
    embedder = _FakeEmbedder()
    lib = SkillLibrary(store_dir=tmp_path / "skills", embedding_provider=embedder)
    # Add an unrelated skill
    lib.add(Skill(
        skill_id="unrelated", name="Send Email",
        description="Send an email via Gmail", app="com.google.android.gm",
        platform="android",
    ))
    await lib._rebuild_index()

    llm = _RecordingLLM([_done_response()])
    recorder = _make_recorder(tmp_path, "Open calculator")
    agent = GuiAgent(
        llm, DryRunBackend(),
        trajectory_recorder=recorder,
        skill_library=lib, skill_threshold=0.9,  # high threshold — no match
        artifacts_root=tmp_path / "runs", max_steps=1,
    )

    result = await agent.run("Open calculator", max_retries=1)
    assert result.success

    # No SKILL phase in trajectory
    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    skill_phases = [
        e for e in events
        if e.get("type") == "phase_change" and e.get("to_phase") == "skill"
    ]
    assert len(skill_phases) == 0


# ---------------------------------------------------------------------------
# AGENT-06 / TRAJ-03: Trajectory recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trajectory_recorded_on_run(tmp_path: Path) -> None:
    """Every agent run should produce a JSONL trajectory with metadata/step/result."""
    llm = _RecordingLLM([_wait_response("w1"), _done_response()])
    recorder = _make_recorder(tmp_path, "Open Settings")
    agent = GuiAgent(
        llm, DryRunBackend(),
        trajectory_recorder=recorder,
        artifacts_root=tmp_path / "runs", max_steps=5,
    )

    result = await agent.run("Open Settings", max_retries=1)
    assert result.success

    assert recorder.path is not None and recorder.path.exists()
    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]

    types = [e["type"] for e in events]
    assert types[0] == "metadata"
    assert "step" in types
    assert types[-1] == "result"
    assert events[-1]["success"] is True


# ---------------------------------------------------------------------------
# TEST-05: Full flow with mock LLM + memory + skills
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_flow_with_mock_llm(tmp_path: Path) -> None:
    """Full flow: DryRunBackend + mock LLM + pre-seeded memory + skill → completion."""
    # Seed memory
    store = MemoryStore(tmp_path / "mem")
    store.add(_make_memory_entry("m1", "Settings is the gear icon"))
    store.add(_make_memory_entry("pol1", "Confirm before destructive actions", MemoryType.POLICY))
    store.save()

    retriever = MemoryRetriever(embedding_provider=_FakeEmbedder())
    await retriever.index(store.list_all())

    # Seed skill library
    embedder = _FakeEmbedder()
    lib = SkillLibrary(store_dir=tmp_path / "skills", embedding_provider=embedder)
    skill = Skill(
        skill_id="open-settings", name="Open Settings",
        description="Open the Settings app", app="com.android.settings",
        platform="android",
        steps=(SkillStep(action_type="open_app", target="com.android.settings"),),
    )
    lib.add(skill)
    await lib._rebuild_index()

    mock_executor = AsyncMock()
    mock_exec_result = AsyncMock()
    mock_exec_result.state.value = "succeeded"
    mock_executor.execute = AsyncMock(return_value=mock_exec_result)

    # GuiAgent LLM: returns done immediately (after skill execution)
    agent_llm = _RecordingLLM([_done_response()])
    recorder = _make_recorder(tmp_path, "Open Settings")

    agent = GuiAgent(
        agent_llm, DryRunBackend(),
        trajectory_recorder=recorder,
        memory_retriever=retriever, skill_library=lib,
        skill_executor=mock_executor, skill_threshold=0.3,
        artifacts_root=tmp_path / "runs", max_steps=3,
    )

    result = await agent.run("Open Settings", max_retries=1)
    assert result.success

    # Memory appeared in system prompt
    system_msg = agent_llm.calls[0][0]["content"]
    assert "Settings is the gear icon" in system_msg
    assert "Confirm before destructive actions" in system_msg

    # Trajectory file has correct events
    events = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    types = [e["type"] for e in events]
    assert "metadata" in types
    assert "result" in types
