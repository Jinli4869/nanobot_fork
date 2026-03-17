"""Phase 2 memory tests — MEM-05 POLICY always-include behavior."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from opengui.agent import GuiAgent
from opengui.backends.dry_run import DryRunBackend
from opengui.interfaces import LLMResponse, ToolCall
from opengui.memory.retrieval import MemoryRetriever
from opengui.memory.store import MemoryStore
from opengui.memory.types import MemoryEntry, MemoryType
from opengui.trajectory.recorder import TrajectoryRecorder


class _FakeEmbedder:
    DIM = 8

    async def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            slot = hash(text) % self.DIM
            vecs[i, slot] = 1.0
        return vecs


class _RecordingLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
        self.calls.append(copy.deepcopy(messages))
        if not self._responses:
            raise AssertionError("No scripted responses left")
        return self._responses.pop(0)


def _done_response() -> LLMResponse:
    return LLMResponse(
        content="Action: done",
        tool_calls=[ToolCall(
            id="tc_done", name="computer_use",
            arguments={"action_type": "done", "status": "success"},
        )],
    )


def _make_entry(
    entry_id: str, content: str, memory_type: MemoryType = MemoryType.APP_GUIDE,
) -> MemoryEntry:
    return MemoryEntry(
        entry_id=entry_id, memory_type=memory_type,
        platform="android", content=content,
    )


# ---------------------------------------------------------------------------
# MEM-05: POLICY entries always included regardless of relevance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_always_included(tmp_path: Path) -> None:
    """POLICY memory entries should appear in system prompt regardless of relevance score."""
    store = MemoryStore(tmp_path / "mem")
    # Add many non-POLICY entries
    for i in range(6):
        store.add(_make_entry(f"app{i}", f"App guide entry {i}"))
    # Add 1 POLICY entry
    store.add(_make_entry("policy1", "Never delete user data without confirmation", MemoryType.POLICY))
    store.save()

    retriever = MemoryRetriever(embedding_provider=_FakeEmbedder())
    await retriever.index(store.list_all())

    llm = _RecordingLLM([_done_response()])
    recorder = TrajectoryRecorder(output_dir=tmp_path / "traj", task="unrelated query")
    agent = GuiAgent(
        llm, DryRunBackend(),
        trajectory_recorder=recorder,
        memory_retriever=retriever, memory_top_k=3,
        artifacts_root=tmp_path / "runs", max_steps=1,
    )

    result = await agent.run("unrelated query", max_retries=1)
    assert result.success

    system_msg = llm.calls[0][0]["content"]
    # POLICY always appears
    assert "Never delete user data without confirmation" in system_msg


# ---------------------------------------------------------------------------
# MEM-05: Memory context formatted in system prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_context_formatted_in_system_prompt(tmp_path: Path) -> None:
    """Memory context should be formatted and passed to build_system_prompt()."""
    store = MemoryStore(tmp_path / "mem")
    store.add(_make_entry("g1", "Swipe up from bottom to go home"))
    store.add(_make_entry("g2", "Long press for app info", MemoryType.OS_GUIDE))
    store.save()

    retriever = MemoryRetriever(embedding_provider=_FakeEmbedder())
    await retriever.index(store.list_all())

    llm = _RecordingLLM([_done_response()])
    recorder = TrajectoryRecorder(output_dir=tmp_path / "traj", task="go home")
    agent = GuiAgent(
        llm, DryRunBackend(),
        trajectory_recorder=recorder,
        memory_retriever=retriever,
        artifacts_root=tmp_path / "runs", max_steps=1,
    )

    result = await agent.run("go home", max_retries=1)
    assert result.success

    system_msg = llm.calls[0][0]["content"]
    # System prompt should contain the "Relevant Knowledge" section
    assert "Relevant Knowledge" in system_msg
    # At least one of our entries should appear
    assert "Swipe up from bottom to go home" in system_msg or "Long press for app info" in system_msg
