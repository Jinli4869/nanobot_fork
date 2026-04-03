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


# ---------------------------------------------------------------------------
# Plan 02 tests — ShortcutApplicabilityRouter: named SUSE-02 behaviors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_applicability_run_when_conditions_pass() -> None:
    """ShortcutApplicabilityRouter with always-pass evaluator returns outcome='run'
    for a shortcut with 2 preconditions.
    """
    shortcut = _make_shortcut(
        "sc-run",
        "WeChat Chat",
        "com.tencent.mm",
        "android",
        preconditions=(
            StateDescriptor(kind="app_visible", value="wechat"),
            StateDescriptor(kind="screen_contains", value="chat_list"),
        ),
    )
    router = ShortcutApplicabilityRouter()  # default always-pass evaluator
    decision = await router.evaluate(shortcut, Path("/tmp/fake.png"))
    assert decision.outcome == "run"
    assert decision.shortcut_id == "sc-run"
    assert decision.reason == "all_preconditions_satisfied"


@pytest.mark.asyncio
async def test_applicability_skip_when_condition_fails() -> None:
    """Router with evaluator returning True for first, False for second gives 'skip'."""
    shortcut = _make_shortcut(
        "sc-skip",
        "WeChat Chat",
        "com.tencent.mm",
        "android",
        preconditions=(
            StateDescriptor(kind="app_visible", value="wechat"),
            StateDescriptor(kind="screen_contains", value="chat_list"),
        ),
    )
    call_count = 0

    class _SecondCallFailEvaluator:
        async def evaluate(self, cond: StateDescriptor, screenshot: Path) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count < 2  # True on first, False on second

    router = ShortcutApplicabilityRouter(condition_evaluator=_SecondCallFailEvaluator())
    decision = await router.evaluate(shortcut, Path("/tmp/fake.png"))
    assert decision.outcome == "skip"
    assert decision.shortcut_id == "sc-skip"
    assert decision.failed_condition is not None
    assert decision.failed_condition.value == "chat_list"


@pytest.mark.asyncio
async def test_applicability_exception_produces_fallback() -> None:
    """Router with evaluator that raises RuntimeError returns outcome='fallback' with
    'evaluation_error' in reason.
    """
    shortcut = _make_shortcut(
        "sc-fallback",
        "Some Action",
        "com.tencent.mm",
        "android",
        preconditions=(StateDescriptor(kind="app_visible", value="wechat"),),
    )

    class _RaisingEvaluator:
        async def evaluate(self, cond: StateDescriptor, screenshot: Path) -> bool:
            raise RuntimeError("LLM timeout")

    router = ShortcutApplicabilityRouter(condition_evaluator=_RaisingEvaluator())
    decision = await router.evaluate(shortcut, Path("/tmp/fake.png"))
    assert decision.outcome == "fallback"
    assert "evaluation_error" in decision.reason


# ---------------------------------------------------------------------------
# Plan 02 tests — _evaluate_shortcut_applicability in GuiAgent context
# ---------------------------------------------------------------------------


def _make_minimal_agent(
    router: ShortcutApplicabilityRouter | None = None,
) -> tuple:
    """Build a minimal GuiAgent with mocked backend/LLM/recorder.

    Returns (agent, recorder) so callers can inspect recorded events.
    """
    import tempfile

    from opengui.agent import GuiAgent
    from opengui.trajectory.recorder import TrajectoryRecorder

    tmpdir = tempfile.mkdtemp()
    mock_backend = MagicMock()
    mock_backend.platform = "android"
    mock_llm = MagicMock()
    recorder = TrajectoryRecorder(
        output_dir=tmpdir,
        task="test task",
        platform="android",
    )
    recorder.start()
    agent = GuiAgent(
        llm=mock_llm,
        backend=mock_backend,
        trajectory_recorder=recorder,
        shortcut_applicability_router=router,
    )
    return agent, recorder


@pytest.mark.asyncio
async def test_fallback_when_no_candidates() -> None:
    """_evaluate_shortcut_applicability with empty candidate list returns
    ApplicabilityDecision(outcome='fallback', reason='no_candidates') and
    emits a shortcut_applicability trajectory event.
    """
    import json

    agent, recorder = _make_minimal_agent()
    decision = await agent._evaluate_shortcut_applicability(
        [], screenshot_path=Path("/tmp/test.png"), task="test"
    )
    assert decision.outcome == "fallback"
    assert decision.reason == "no_candidates"

    # Check trajectory event was written
    trace_path = recorder.path
    assert trace_path is not None and trace_path.exists()
    events = [
        json.loads(line)
        for line in trace_path.read_text().splitlines()
        if line.strip()
    ]
    applicability_events = [e for e in events if e.get("type") == "shortcut_applicability"]
    assert len(applicability_events) == 1
    assert applicability_events[0]["outcome"] == "fallback"
    assert applicability_events[0]["reason"] == "no_candidates"


@pytest.mark.asyncio
async def test_applicability_emits_trajectory_event() -> None:
    """After _evaluate_shortcut_applicability with one passing candidate, trajectory
    recorder has a 'shortcut_applicability' event with outcome='run' and correct shortcut_id.
    """
    import json

    shortcut = _make_shortcut(
        "sc-traj",
        "WeChat Action",
        "com.tencent.mm",
        "android",
        preconditions=(),
    )
    candidate = _make_result(shortcut, 0.85)

    router = ShortcutApplicabilityRouter()  # always-pass
    agent, recorder = _make_minimal_agent(router=router)
    decision = await agent._evaluate_shortcut_applicability(
        [candidate], screenshot_path=Path("/tmp/test.png"), task="open wechat"
    )
    assert decision.outcome == "run"

    trace_path = recorder.path
    assert trace_path is not None and trace_path.exists()
    events = [
        json.loads(line)
        for line in trace_path.read_text().splitlines()
        if line.strip()
    ]
    applicability_events = [e for e in events if e.get("type") == "shortcut_applicability"]
    assert len(applicability_events) == 1
    evt = applicability_events[0]
    assert evt["outcome"] == "run"
    assert evt["shortcut_id"] == "sc-traj"


@pytest.mark.asyncio
async def test_applicability_selects_first_passing_candidate() -> None:
    """Given 2 candidates, first fails precondition, second passes — decision returns
    outcome='run' with shortcut_id matching the second candidate.
    """
    sc_fail = _make_shortcut(
        "sc-fail",
        "Failing Action",
        "com.tencent.mm",
        "android",
        preconditions=(StateDescriptor(kind="app_visible", value="wechat"),),
    )
    sc_pass = _make_shortcut(
        "sc-pass",
        "Passing Action",
        "com.tencent.mm",
        "android",
        preconditions=(StateDescriptor(kind="app_visible", value="wechat"),),
    )
    candidates = [_make_result(sc_fail, 0.9), _make_result(sc_pass, 0.8)]

    evaluated_ids: list[str] = []

    class _FailFirstEvaluator:
        async def evaluate(self, cond: StateDescriptor, screenshot: Path) -> bool:
            return cond.value != "wechat" or len(evaluated_ids) >= 1

    # Track which shortcut is being evaluated by the router
    original_evaluate = ShortcutApplicabilityRouter.evaluate

    call_shortcut_ids: list[str] = []

    async def patched_evaluate(
        self_router: ShortcutApplicabilityRouter,
        candidate: ShortcutSkill,
        screenshot_path: Path,
    ) -> ApplicabilityDecision:
        call_shortcut_ids.append(candidate.skill_id)
        if candidate.skill_id == "sc-fail":
            return ApplicabilityDecision(
                outcome="skip",
                shortcut_id=candidate.skill_id,
                reason="precondition_failed:app_visible:wechat",
                failed_condition=StateDescriptor(kind="app_visible", value="wechat"),
            )
        return ApplicabilityDecision(
            outcome="run",
            shortcut_id=candidate.skill_id,
            reason="all_preconditions_satisfied",
        )

    router = ShortcutApplicabilityRouter()
    agent, _ = _make_minimal_agent(router=router)

    with patch.object(ShortcutApplicabilityRouter, "evaluate", patched_evaluate):
        decision = await agent._evaluate_shortcut_applicability(
            candidates, screenshot_path=Path("/tmp/test.png"), task="test"
        )

    assert decision.outcome == "run"
    assert decision.shortcut_id == "sc-pass"
    assert "sc-fail" in call_shortcut_ids
    assert "sc-pass" in call_shortcut_ids


@pytest.mark.asyncio
async def test_failed_shortcut_clears_for_retry() -> None:
    """After a shortcut-assisted first attempt fails, the agent's run() clears
    matched_skill before subsequent retries so retries use free exploration.

    We verify this by checking that _run_once is called twice and the second
    call receives skill_context=None (indicating no shortcut context injected).
    """
    import tempfile

    from opengui.agent import AgentResult, GuiAgent
    from opengui.trajectory.recorder import TrajectoryRecorder

    tmpdir = tempfile.mkdtemp()
    mock_backend = MagicMock()
    mock_backend.platform = "android"
    mock_backend.observe = AsyncMock(return_value=MagicMock(screenshot_path="/tmp/shot.png"))
    mock_backend.preflight = AsyncMock()
    mock_llm = MagicMock()
    recorder = TrajectoryRecorder(
        output_dir=tmpdir, task="test", platform="android"
    )

    # Shortcut that will be found
    shortcut = _make_shortcut(
        "sc-clear-test",
        "Test Shortcut",
        "com.tencent.mm",
        "android",
        preconditions=(),
    )
    candidate = _make_result(shortcut, 0.9)

    mock_search = MagicMock()
    mock_search.search = AsyncMock(return_value=[candidate])

    # Router that always approves
    router = ShortcutApplicabilityRouter()

    run_once_calls: list[dict] = []
    fail_count = [0]

    async def mock_run_once(
        task: str,
        *,
        app_hint: object,
        run_dir: object,
        memory_context: object,
        skill_context: object,
    ) -> AgentResult:
        run_once_calls.append({"skill_context": skill_context})
        fail_count[0] += 1
        if fail_count[0] == 1:
            return AgentResult(success=False, summary="shortcut failed", error="failed")
        return AgentResult(success=True, summary="done")

    agent = GuiAgent(
        llm=mock_llm,
        backend=mock_backend,
        trajectory_recorder=recorder,
        unified_skill_search=mock_search,
        shortcut_applicability_router=router,
        skill_threshold=0.5,
    )

    with patch.object(agent, "_run_once", mock_run_once):
        result = await agent.run("test task", max_retries=2)

    assert result.success is True
    assert len(run_once_calls) == 2
    # First call should have skill_context (shortcut was run)
    # Second call should have NO skill context (shortcut was cleared)
    assert run_once_calls[1]["skill_context"] is None


@pytest.mark.asyncio
async def test_normal_path_unchanged_when_no_shortcut() -> None:
    """When no unified_skill_search is set, run() proceeds through the normal
    retry loop without error.
    """
    import tempfile

    from opengui.agent import AgentResult, GuiAgent
    from opengui.trajectory.recorder import TrajectoryRecorder

    tmpdir = tempfile.mkdtemp()
    mock_backend = MagicMock()
    mock_backend.platform = "android"
    mock_llm = MagicMock()
    recorder = TrajectoryRecorder(
        output_dir=tmpdir, task="test", platform="android"
    )

    agent = GuiAgent(
        llm=mock_llm,
        backend=mock_backend,
        trajectory_recorder=recorder,
        # No unified_skill_search — no shortcuts at all
    )

    with patch.object(
        agent, "_run_once", AsyncMock(return_value=AgentResult(success=True, summary="done"))
    ):
        result = await agent.run("test task")

    assert result.success is True


# ---------------------------------------------------------------------------
# Task 2 tests — nanobot wiring of ShortcutApplicabilityRouter
# ---------------------------------------------------------------------------


def test_nanobot_wires_applicability_router(tmp_path: Path) -> None:
    """When enable_skill_execution=True, the constructed GuiAgent receives a
    non-None _shortcut_applicability_router wired with the real LLMStateValidator.
    """
    from typing import Any
    from unittest.mock import MagicMock

    from nanobot.config.schema import Config
    from nanobot.providers.base import LLMProvider as NanobotLLMProvider
    from opengui.agent import GuiAgent

    class _StubNanobotProvider(NanobotLLMProvider):
        def __init__(self) -> None:
            super().__init__(api_key="test-key")

        async def chat(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Should not be called")

        async def chat_with_retry(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Should not be called")

        def get_default_model(self) -> str:
            return "test-model"

    (tmp_path / "gui_runs").mkdir()
    (tmp_path / "gui_skills").mkdir()

    from nanobot.agent.tools.gui import GuiSubagentTool

    provider = _StubNanobotProvider()
    tool = GuiSubagentTool(
        gui_config=Config(gui={"backend": "dry-run", "enable_skill_execution": True}).gui,
        provider=provider,
        model=provider.get_default_model(),
        workspace=tmp_path,
    )

    # Capture the shortcut_applicability_router argument passed to GuiAgent.__init__
    captured_router: list[Any] = []
    original_init = GuiAgent.__init__

    def capturing_init(self_agent: Any, **kwargs: Any) -> None:
        captured_router.append(kwargs.get("shortcut_applicability_router"))
        original_init(self_agent, **kwargs)

    from opengui.agent import AgentResult

    with patch.object(GuiAgent, "__init__", capturing_init):
        # Mock _run_task's backend operations so nothing real runs
        mock_backend = MagicMock()
        mock_backend.platform = "desktop"
        mock_backend.observe = MagicMock()
        mock_backend.preflight = MagicMock()
        # Patch agent.run to avoid actually running the agent loop
        with patch.object(
            GuiAgent,
            "run",
            AsyncMock(return_value=AgentResult(success=True, summary="done")),
        ):
            import asyncio
            asyncio.run(tool._run_task(mock_backend, "test"))

    assert len(captured_router) == 1, "GuiAgent.__init__ should have been called once"
    assert captured_router[0] is not None, (
        "shortcut_applicability_router must be non-None when enable_skill_execution=True"
    )
