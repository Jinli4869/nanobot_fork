"""
Phase 27 — Storage and unified skill search contract tests.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from opengui.agent import GuiAgent
from opengui.memory.types import MemoryEntry, MemoryType
from opengui.skills import (
    ShortcutSkillStore,
    ShortcutSkill,
    TaskSkill,
    TaskSkillStore,
    UnifiedSkillSearch,
)
from opengui.skills.data import Skill, SkillStep
from opengui.skills.shortcut import ParameterSlot, StateDescriptor
from opengui.skills.shortcut_store import SkillSearchResult
from opengui.skills.task_skill import ShortcutRefNode


def _make_shortcut_skill(
    *,
    skill_id: str,
    name: str,
    description: str,
    app: str = "com.example.mail",
    platform: str = "android",
    tags: tuple[str, ...] = (),
    parameter_slots: tuple[ParameterSlot, ...] = (),
    preconditions: tuple[StateDescriptor, ...] = (),
    postconditions: tuple[StateDescriptor, ...] = (),
    source_task: str | None = None,
    source_trace_path: str | None = None,
    source_run_id: str | None = None,
    source_step_indices: tuple[int, ...] = (),
    promotion_version: int = 1,
    shortcut_version: int = 1,
    merged_from_ids: tuple[str, ...] = (),
    promoted_at: float | None = None,
) -> ShortcutSkill:
    return ShortcutSkill(
        skill_id=skill_id,
        name=name,
        description=description,
        app=app,
        platform=platform,
        steps=(SkillStep(action_type="tap", target="compose"),),
        parameter_slots=parameter_slots,
        preconditions=preconditions,
        postconditions=postconditions,
        tags=tags,
        source_task=source_task,
        source_trace_path=source_trace_path,
        source_run_id=source_run_id,
        source_step_indices=source_step_indices,
        promotion_version=promotion_version,
        shortcut_version=shortcut_version,
        merged_from_ids=merged_from_ids,
        promoted_at=promoted_at,
        created_at=1700000000.0,
    )


def _make_task_skill(
    *,
    skill_id: str,
    name: str,
    description: str,
    app: str = "com.example.mail",
    platform: str = "android",
    memory_context_id: str | None = None,
    tags: tuple[str, ...] = (),
) -> TaskSkill:
    return TaskSkill(
        skill_id=skill_id,
        name=name,
        description=description,
        app=app,
        platform=platform,
        steps=(ShortcutRefNode(shortcut_id="shortcut-compose"),),
        memory_context_id=memory_context_id,
        tags=tags,
        created_at=1700000001.0,
    )


def _make_agent(**kwargs: object) -> GuiAgent:
    return GuiAgent(
        llm=Mock(),
        backend=Mock(),
        trajectory_recorder=Mock(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_shortcut_store_round_trip(tmp_path: Path) -> None:
    skill = _make_shortcut_skill(
        skill_id="shortcut-compose-email",
        name="Compose Email",
        description="Open compose flow and focus the recipient field",
        tags=("email", "compose"),
        parameter_slots=(
            ParameterSlot(
                name="recipient",
                type="text",
                description="Email recipient",
            ),
        ),
        preconditions=(StateDescriptor(kind="app_open", value="mail"),),
        postconditions=(StateDescriptor(kind="screen_visible", value="compose"),),
        source_task="Send a project update",
        source_trace_path="/tmp/gui_runs/run-123/trace.jsonl",
        source_run_id="run-123",
        source_step_indices=(2, 4),
        promotion_version=1,
        shortcut_version=3,
        merged_from_ids=("shortcut-compose-email-v2",),
        promoted_at=1700000002.5,
    )

    store = ShortcutSkillStore(tmp_path)
    store.add(skill)

    reloaded = ShortcutSkillStore(tmp_path)
    assert reloaded.get(skill.skill_id) == skill
    reloaded_skill = reloaded.get(skill.skill_id)
    assert reloaded_skill is not None
    assert reloaded_skill.source_trace_path == "/tmp/gui_runs/run-123/trace.jsonl"
    assert reloaded_skill.source_step_indices == (2, 4)
    assert reloaded_skill.shortcut_version == 3
    assert reloaded_skill.merged_from_ids == ("shortcut-compose-email-v2",)


@pytest.mark.asyncio
async def test_task_store_round_trip(tmp_path: Path) -> None:
    skill = _make_task_skill(
        skill_id="task-send-status",
        name="Send Status Update",
        description="Compose and send the routine project update",
        memory_context_id="mem-status-template",
        tags=("email", "status"),
    )

    store = TaskSkillStore(tmp_path)
    store.add(skill)

    reloaded = TaskSkillStore(tmp_path)
    assert reloaded.get(skill.skill_id) == skill


def test_version_field(tmp_path: Path) -> None:
    shortcut_store = ShortcutSkillStore(tmp_path)
    shortcut_store.add(
        _make_shortcut_skill(
            skill_id="shortcut-version",
            name="Version Shortcut",
            description="Persist shortcut version envelope",
        )
    )
    shortcut_payload = json.loads(
        (tmp_path / "android" / "shortcut_skills.json").read_text(encoding="utf-8")
    )
    assert shortcut_payload["version"] == 1

    task_store = TaskSkillStore(tmp_path)
    task_store.add(
        _make_task_skill(
            skill_id="task-version",
            name="Version Task",
            description="Persist task version envelope",
        )
    )
    task_payload = json.loads(
        (tmp_path / "android" / "task_skills.json").read_text(encoding="utf-8")
    )
    assert task_payload["version"] == 1


@pytest.mark.asyncio
async def test_shortcut_store_search(tmp_path: Path) -> None:
    store = ShortcutSkillStore(tmp_path)
    store.add(
        _make_shortcut_skill(
            skill_id="shortcut-compose",
            name="Compose Email",
            description="Create a brand new draft message",
        )
    )
    store.add(
        _make_shortcut_skill(
            skill_id="shortcut-archive",
            name="Archive Thread",
            description="Archive the currently selected conversation",
        )
    )
    store.add(
        _make_shortcut_skill(
            skill_id="shortcut-calendar",
            name="Open Calendar",
            description="Switch to the calendar tab",
        )
    )

    results = await store.search("compose a new message", top_k=3)

    assert results
    assert isinstance(results[0][0], ShortcutSkill)
    assert isinstance(results[0][1], float)
    assert results[0][0].skill_id == "shortcut-compose"
    assert results[0][1] >= results[-1][1]


@pytest.mark.asyncio
async def test_shortcut_store_search_returns_canonical_skill_id_after_merge(tmp_path: Path) -> None:
    store = ShortcutSkillStore(tmp_path)
    old = _make_shortcut_skill(
        skill_id="shortcut-compose-v1",
        name="Compose Email",
        description="Create a brand new draft message",
        source_trace_path="/tmp/gui_runs/run-123/trace.jsonl",
        source_step_indices=(2, 4),
    )
    new = _make_shortcut_skill(
        skill_id="shortcut-compose-v2",
        name="Compose Message",
        description="Create a brand new draft message and focus the editor",
        source_trace_path="/tmp/gui_runs/run-456/trace.jsonl",
        source_step_indices=(3, 5),
    )

    first_decision, first_id = await store.add_or_merge(old)
    second_decision, second_id = await store.add_or_merge(new)

    assert first_decision == "ADD"
    assert first_id == "shortcut-compose-v1"
    assert second_decision == "MERGE"
    assert second_id == "shortcut-compose-v1"

    merged = store.get("shortcut-compose-v1")
    assert merged is not None
    assert merged.shortcut_version == 2

    results = await store.search("compose a new message", top_k=3)

    assert results
    assert results[0][0].skill_id == "shortcut-compose-v1"


@pytest.mark.asyncio
async def test_task_store_search(tmp_path: Path) -> None:
    store = TaskSkillStore(tmp_path)
    store.add(
        _make_task_skill(
            skill_id="task-send-update",
            name="Send Weekly Update",
            description="Draft and send a weekly project update email",
        )
    )
    store.add(
        _make_task_skill(
            skill_id="task-open-calendar",
            name="Review Calendar",
            description="Open the calendar and scan upcoming events",
        )
    )

    results = await store.search("send project update email", top_k=2)

    assert results
    assert isinstance(results[0][0], TaskSkill)
    assert isinstance(results[0][1], float)
    assert results[0][0].skill_id == "task-send-update"


@pytest.mark.asyncio
async def test_unified_search(tmp_path: Path) -> None:
    shortcut_store = ShortcutSkillStore(tmp_path)
    shortcut_store.add(
        _make_shortcut_skill(
            skill_id="shortcut-compose",
            name="Compose Email",
            description="Start a new email draft",
        )
    )

    task_store = TaskSkillStore(tmp_path)
    task_store.add(
        _make_task_skill(
            skill_id="task-send-update",
            name="Send Weekly Update",
            description="Compose an email and send the weekly update",
        )
    )

    unified = UnifiedSkillSearch(shortcut_store, task_store)
    results = await unified.search("compose email", top_k=5)

    assert results
    assert all(isinstance(result, SkillSearchResult) for result in results)
    assert {"shortcut", "task"} <= {result.layer for result in results}
    assert results == sorted(results, key=lambda result: result.score, reverse=True)


@pytest.mark.asyncio
async def test_unified_search_layer_weight(tmp_path: Path) -> None:
    shortcut_store = ShortcutSkillStore(tmp_path)
    shortcut_store.add(
        _make_shortcut_skill(
            skill_id="shortcut-compose",
            name="Compose Email",
            description="Create a new message draft",
        )
    )

    task_store = TaskSkillStore(tmp_path)
    task_store.add(
        _make_task_skill(
            skill_id="task-send-update",
            name="Send Update",
            description="Compose a new message draft and send it",
        )
    )

    unified = UnifiedSkillSearch(shortcut_store, task_store)
    unweighted = await unified.search("compose draft", top_k=5)
    weighted = await unified.search("compose draft", top_k=5, shortcut_layer_weight=2.0)

    unweighted_shortcut = next(result for result in unweighted if result.layer == "shortcut")
    weighted_shortcut = next(result for result in weighted if result.layer == "shortcut")
    assert weighted_shortcut.score > unweighted_shortcut.score
    assert weighted_shortcut.raw_score == unweighted_shortcut.raw_score


@pytest.mark.asyncio
async def test_shortcut_store_empty(tmp_path: Path) -> None:
    store = ShortcutSkillStore(tmp_path)
    assert await store.search("anything", top_k=3) == []


@pytest.mark.asyncio
async def test_shortcut_store_remove(tmp_path: Path) -> None:
    store = ShortcutSkillStore(tmp_path)
    skill = _make_shortcut_skill(
        skill_id="shortcut-remove",
        name="Remove Me",
        description="Temporary shortcut skill",
    )
    store.add(skill)

    assert store.remove(skill.skill_id) is True
    assert await store.search("temporary shortcut", top_k=3) == []


@pytest.mark.asyncio
async def test_agent_skill_lookup() -> None:
    skill = _make_shortcut_skill(
        skill_id="shortcut-compose",
        name="Compose Email",
        description="Compose a new email",
    )
    unified_search = Mock()
    unified_search.search = AsyncMock(
        return_value=[
            SkillSearchResult(skill=skill, layer="shortcut", score=0.82, raw_score=0.82),
        ]
    )
    agent = _make_agent(unified_skill_search=unified_search, skill_threshold=0.6)

    result = await agent._search_skill("compose email")

    assert isinstance(result, SkillSearchResult)
    assert result.skill == skill
    assert result.layer == "shortcut"
    assert result.score >= 0.6


@pytest.mark.asyncio
async def test_agent_skill_lookup_below_threshold() -> None:
    skill = _make_shortcut_skill(
        skill_id="shortcut-compose-low",
        name="Compose Email",
        description="Compose a new email",
    )
    unified_search = Mock()
    unified_search.search = AsyncMock(
        return_value=[
            SkillSearchResult(skill=skill, layer="shortcut", score=0.32, raw_score=0.32),
        ]
    )
    agent = _make_agent(unified_skill_search=unified_search, skill_threshold=0.6)

    result = await agent._search_skill("compose email")

    assert result is None


@pytest.mark.asyncio
async def test_agent_skill_lookup_logs_layer(caplog: pytest.LogCaptureFixture) -> None:
    skill = _make_task_skill(
        skill_id="task-send-update",
        name="Send Weekly Update",
        description="Send weekly update",
    )
    unified_search = Mock()
    unified_search.search = AsyncMock(
        return_value=[SkillSearchResult(skill=skill, layer="task", score=0.91, raw_score=0.91)]
    )
    agent = _make_agent(unified_skill_search=unified_search, skill_threshold=0.6)
    caplog.set_level(logging.INFO, logger="opengui.agent")

    result = await agent._search_skill("send weekly update")

    assert result is not None
    assert "layer=task" in caplog.text


@pytest.mark.asyncio
async def test_memory_context_injection() -> None:
    skill = _make_task_skill(
        skill_id="task-with-memory",
        name="Task With Memory",
        description="Uses app context",
        memory_context_id="mem-123",
    )
    memory_store = Mock()
    memory_store.get.return_value = MemoryEntry(
        entry_id="mem-123",
        memory_type=MemoryType.APP_GUIDE,
        platform="android",
        content="app context",
    )
    agent = _make_agent(memory_store=memory_store)

    result = await agent._inject_skill_memory_context(skill, "existing")

    assert result is not None
    assert result.startswith("[Skill memory context]\napp context")
    assert result.endswith("\n\nexisting")


@pytest.mark.asyncio
async def test_missing_memory_context(caplog: pytest.LogCaptureFixture) -> None:
    skill = _make_task_skill(
        skill_id="task-missing-memory",
        name="Task Missing Memory",
        description="Missing app context",
        memory_context_id="missing-id",
    )
    memory_store = Mock()
    memory_store.get.return_value = None
    agent = _make_agent(memory_store=memory_store)
    caplog.set_level(logging.WARNING, logger="opengui.agent")

    result = await agent._inject_skill_memory_context(skill, "existing")

    assert result == "existing"
    assert "missing memory context missing-id" in caplog.text


@pytest.mark.asyncio
async def test_inject_shortcut_skill_noop() -> None:
    agent = _make_agent(memory_store=Mock())

    result = await agent._inject_skill_memory_context(
        _make_shortcut_skill(
            skill_id="shortcut-noop",
            name="Shortcut Noop",
            description="No memory injection",
        ),
        "existing",
    )

    assert result == "existing"


@pytest.mark.asyncio
async def test_inject_no_memory_store() -> None:
    skill = _make_task_skill(
        skill_id="task-no-store",
        name="Task Without Store",
        description="No memory store",
        memory_context_id="mem-123",
    )
    agent = _make_agent()

    result = await agent._inject_skill_memory_context(skill, "existing")

    assert result == "existing"


@pytest.mark.asyncio
async def test_legacy_skill_library_fallback() -> None:
    legacy_skill = Skill(
        skill_id="legacy-compose",
        name="Compose Email",
        description="Legacy skill",
        app="com.example.mail",
        platform="android",
        steps=(SkillStep(action_type="tap", target="compose"),),
        success_count=1,
        failure_count=0,
    )
    legacy_library = Mock()
    legacy_library.search = AsyncMock(return_value=[(legacy_skill, 0.9)])
    agent = _make_agent(skill_library=legacy_library, skill_threshold=0.6)

    result = await agent._search_skill("compose email")

    assert result is not None
    assert result[0] == legacy_skill
    assert result[1] == pytest.approx(0.9)
    legacy_library.search.assert_awaited_once_with("compose email", top_k=1)


def test_import_safety() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", "opengui/skills/shortcut_store.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
