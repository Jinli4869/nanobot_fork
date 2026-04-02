"""
Phase 27 — Storage and unified skill search contract tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from opengui.skills import (
    ShortcutSkillStore,
    ShortcutSkill,
    TaskSkill,
    TaskSkillStore,
    UnifiedSkillSearch,
)
from opengui.skills.data import SkillStep
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
    )

    store = ShortcutSkillStore(tmp_path)
    store.add(skill)

    reloaded = ShortcutSkillStore(tmp_path)
    assert reloaded.get(skill.skill_id) == skill


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


def test_import_safety() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", "opengui/skills/shortcut_store.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
