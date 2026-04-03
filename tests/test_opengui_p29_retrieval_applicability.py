"""Phase 29 — multi-candidate shortcut retrieval and applicability routing tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opengui.skills.shortcut import ShortcutSkill, StateDescriptor
from opengui.skills.shortcut_router import (
    ApplicabilityDecision,
    ShortcutApplicabilityRouter,
    filter_candidates_by_context,
)
from opengui.skills.shortcut_store import SkillSearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_shortcut(
    skill_id: str,
    name: str,
    app: str,
    platform: str,
    preconditions: tuple[StateDescriptor, ...] = (),
) -> ShortcutSkill:
    return ShortcutSkill(
        skill_id=skill_id,
        name=name,
        description=f"Test shortcut: {name}",
        app=app,
        platform=platform,
        preconditions=preconditions,
    )


def _make_result(
    shortcut: ShortcutSkill,
    score: float,
    layer: str = "shortcut",
) -> SkillSearchResult:
    return SkillSearchResult(skill=shortcut, layer=layer, score=score, raw_score=score)


# ---------------------------------------------------------------------------
# Task 1 tests — ApplicabilityDecision and ShortcutApplicabilityRouter
# ---------------------------------------------------------------------------


def test_applicability_decision_frozen() -> None:
    """ApplicabilityDecision is a frozen dataclass with the expected fields."""
    decision = ApplicabilityDecision(outcome="run", shortcut_id="sc-1", reason="ok")
    assert decision.outcome == "run"
    assert decision.shortcut_id == "sc-1"
    assert decision.reason == "ok"
    assert decision.score is None
    assert decision.failed_condition is None

    # Must be frozen — writing to a field should raise
    with pytest.raises((AttributeError, TypeError)):
        decision.outcome = "skip"  # type: ignore[misc]


def test_applicability_router_init_default_evaluator() -> None:
    """ShortcutApplicabilityRouter() without an evaluator uses _AlwaysPassEvaluator."""
    from opengui.skills.shortcut_router import _AlwaysPassEvaluator

    router = ShortcutApplicabilityRouter()
    assert isinstance(router._evaluator, _AlwaysPassEvaluator)


@pytest.mark.asyncio
async def test_router_all_preconditions_pass() -> None:
    """When all preconditions pass, outcome is 'run'."""
    condition = StateDescriptor(kind="app_open", value="com.tencent.mm")
    shortcut = _make_shortcut(
        "sc-1", "Open WeChat", "com.tencent.mm", "android",
        preconditions=(condition,),
    )
    router = ShortcutApplicabilityRouter()
    screenshot = Path("/tmp/fake_screenshot.png")
    decision = await router.evaluate(shortcut, screenshot)
    assert decision.outcome == "run"
    assert decision.shortcut_id == "sc-1"


@pytest.mark.asyncio
async def test_router_precondition_fails_gives_skip() -> None:
    """When a precondition evaluator returns False, outcome is 'skip'."""
    condition = StateDescriptor(kind="app_open", value="com.tencent.mm")
    shortcut = _make_shortcut(
        "sc-2", "Open WeChat", "com.tencent.mm", "android",
        preconditions=(condition,),
    )

    class _AlwaysFailEvaluator:
        async def evaluate(self, cond: StateDescriptor, screenshot: Path) -> bool:
            return False

    router = ShortcutApplicabilityRouter(condition_evaluator=_AlwaysFailEvaluator())
    decision = await router.evaluate(shortcut, Path("/tmp/fake.png"))
    assert decision.outcome == "skip"
    assert decision.shortcut_id == "sc-2"
    assert "precondition_failed" in decision.reason
    assert decision.failed_condition == condition


@pytest.mark.asyncio
async def test_router_evaluator_exception_gives_fallback() -> None:
    """When evaluator raises, outcome is 'fallback'."""
    condition = StateDescriptor(kind="app_open", value="com.example.app")
    shortcut = _make_shortcut("sc-3", "Some Action", "com.example.app", "android",
                               preconditions=(condition,))

    class _RaisingEvaluator:
        async def evaluate(self, cond: StateDescriptor, screenshot: Path) -> bool:
            raise RuntimeError("VLM crashed")

    router = ShortcutApplicabilityRouter(condition_evaluator=_RaisingEvaluator())
    decision = await router.evaluate(shortcut, Path("/tmp/fake.png"))
    assert decision.outcome == "fallback"
    assert "RuntimeError" in decision.reason


# ---------------------------------------------------------------------------
# Task 1 tests — filter_candidates_by_context
# ---------------------------------------------------------------------------


def test_retrieval_filters_by_platform() -> None:
    """Given 3 results (2 android, 1 ios), filtering by platform='android' returns 2."""
    android_sc1 = _make_shortcut("sc-a1", "Action A", "com.tencent.mm", "android")
    android_sc2 = _make_shortcut("sc-a2", "Action B", "com.eg.android.AlipayGphone", "android")
    ios_sc1 = _make_shortcut("sc-i1", "Action iOS", "com.tencent.xin", "ios")

    candidates = [
        _make_result(android_sc1, 0.9),
        _make_result(android_sc2, 0.8),
        _make_result(ios_sc1, 0.85),
    ]

    filtered = filter_candidates_by_context(candidates, platform="android", app_hint=None)
    assert len(filtered) == 2
    skill_ids = {r.skill.skill_id for r in filtered}
    assert skill_ids == {"sc-a1", "sc-a2"}


def test_retrieval_permissive_without_foreground_app() -> None:
    """When app_hint is None or empty, only platform filter applies (no app filter)."""
    sc1 = _make_shortcut("sc-1", "Action A", "com.tencent.mm", "android")
    sc2 = _make_shortcut("sc-2", "Action B", "com.eg.android.AlipayGphone", "android")

    candidates = [_make_result(sc1, 0.9), _make_result(sc2, 0.8)]

    # app_hint=None — both should pass
    filtered_none = filter_candidates_by_context(candidates, platform="android", app_hint=None)
    assert len(filtered_none) == 2

    # app_hint="" — should also return all platform-matching
    filtered_empty = filter_candidates_by_context(candidates, platform="android", app_hint="")
    assert len(filtered_empty) == 2


def test_retrieval_normalizes_app_before_filter() -> None:
    """app_hint='WeChat' on android normalizes to 'com.tencent.mm' and matches stored shortcut."""
    wechat_sc = _make_shortcut("sc-wc", "WeChat Action", "com.tencent.mm", "android")
    other_sc = _make_shortcut("sc-other", "Other Action", "com.eg.android.AlipayGphone", "android")

    candidates = [_make_result(wechat_sc, 0.9), _make_result(other_sc, 0.8)]

    filtered = filter_candidates_by_context(candidates, platform="android", app_hint="WeChat")
    assert len(filtered) == 1
    assert filtered[0].skill.skill_id == "sc-wc"


def test_retrieval_app_filter_fallback_to_platform_when_empty() -> None:
    """When app filter produces empty result, fall back to platform-only filtered list."""
    sc1 = _make_shortcut("sc-1", "Action A", "com.tencent.mm", "android")
    sc2 = _make_shortcut("sc-2", "Action B", "com.eg.android.AlipayGphone", "android")
    candidates = [_make_result(sc1, 0.9), _make_result(sc2, 0.8)]

    # "nonexistent-app" won't match anything, so should fall back to platform-only (2 results)
    filtered = filter_candidates_by_context(
        candidates, platform="android", app_hint="some-completely-unknown-app-xyz"
    )
    assert len(filtered) == 2


def test_retrieval_emits_trajectory_event() -> None:
    """
    Placeholder for trajectory event test — the actual emission is tested
    in test_retrieval_in_agent_run below once Task 2 wires it into GuiAgent.
    This test verifies filter_candidates_by_context itself doesn't mutate scores.
    """
    sc1 = _make_shortcut("sc-1", "WeChat Chat", "com.tencent.mm", "android")
    result = _make_result(sc1, 0.75)
    filtered = filter_candidates_by_context([result], platform="android", app_hint=None)
    assert len(filtered) == 1
    assert filtered[0].score == 0.75


# ---------------------------------------------------------------------------
# Task 2 tests — _retrieve_shortcut_candidates in GuiAgent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieval_in_agent_run() -> None:
    """
    GuiAgent._retrieve_shortcut_candidates returns platform-filtered candidates
    and emits a 'shortcut_retrieval' trajectory event with candidate_count=2.
    """
    import json
    import tempfile

    from opengui.agent import GuiAgent
    from opengui.trajectory.recorder import TrajectoryRecorder

    # Build mock shortcuts: 2 android (score=0.8) and 1 ios (score=0.9)
    android_sc1 = _make_shortcut("sc-a1", "Android Action A", "com.tencent.mm", "android")
    android_sc2 = _make_shortcut("sc-a2", "Android Action B", "com.eg.android.AlipayGphone", "android")
    ios_sc1 = _make_shortcut("sc-i1", "iOS Action", "com.tencent.xin", "ios")

    mock_search_results = [
        _make_result(android_sc1, 0.8),
        _make_result(android_sc2, 0.8),
        _make_result(ios_sc1, 0.9),
    ]

    # Mock UnifiedSkillSearch
    mock_search = MagicMock()
    mock_search.search = AsyncMock(return_value=mock_search_results)

    # Mock DeviceBackend
    mock_backend = MagicMock()
    mock_backend.platform = "android"

    # Mock LLMProvider
    mock_llm = MagicMock()

    # Real TrajectoryRecorder — keep tmpdir alive for the duration of the test
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = TrajectoryRecorder(
            output_dir=tmpdir,
            task="open wechat",
            platform="android",
        )
        recorder.start()

        agent = GuiAgent(
            llm=mock_llm,
            backend=mock_backend,
            trajectory_recorder=recorder,
            unified_skill_search=mock_search,
            skill_threshold=0.5,
        )

        result = await agent._retrieve_shortcut_candidates(
            "open wechat", platform="android", app_hint=None
        )

        # Assertions inside the context so the tmpdir is still alive
        # Should return only the 2 android candidates (ios filtered out)
        assert len(result) == 2
        skill_ids = {r.skill.skill_id for r in result}
        assert skill_ids == {"sc-a1", "sc-a2"}

        # Verify mock was called with top_k=5
        mock_search.search.assert_called_once_with("open wechat", top_k=5)

        # Verify trajectory recorder received the shortcut_retrieval event
        trace_path = recorder.path
        assert trace_path is not None and trace_path.exists()

        events = [
            json.loads(line)
            for line in trace_path.read_text().splitlines()
            if line.strip()
        ]
        retrieval_events = [e for e in events if e.get("type") == "shortcut_retrieval"]
        assert len(retrieval_events) == 1

        event = retrieval_events[0]
        assert event["candidate_count"] == 2
        assert event["task"] == "open wechat"
        assert event["platform"] == "android"
