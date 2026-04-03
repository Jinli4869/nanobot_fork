"""Phase 30 - Stable shortcut execution: live binding, settle timing, and fallback."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opengui.action import Action, parse_action
from opengui.agent import AgentResult, GuiAgent
from opengui.grounding.protocol import GroundingResult
from opengui.observation import Observation
from opengui.skills.data import SkillStep
from opengui.skills.multi_layer_executor import (
    ContractViolationReport,
    LLMConditionEvaluator,
    ShortcutExecutionSuccess,
    ShortcutStepResult,
    ShortcutExecutor,
)
from opengui.skills.shortcut import ShortcutSkill, StateDescriptor
from opengui.skills.shortcut_router import ApplicabilityDecision
from opengui.skills.shortcut_store import SkillSearchResult
from opengui.trajectory.recorder import TrajectoryRecorder


class _FakeBackend:
    def __init__(self) -> None:
        self.executed_actions: list[Action] = []

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.touch()
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=1080,
            screen_height=1920,
            foreground_app="com.example.app",
            platform="android",
        )

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        self.executed_actions.append(action)
        return f"ok:{action.action_type}"

    async def preflight(self) -> None:
        pass

    async def list_apps(self) -> list[str]:
        return []

    @property
    def platform(self) -> str:
        return "android"


class _NeverCalledGrounder:
    async def ground(self, target: str, context: object) -> GroundingResult:
        raise AssertionError(f"Grounder should not be called for fixed step {target!r}")


class _FakeValidator:
    def __init__(self, result: bool) -> None:
        self._result = result
        self.calls: list[tuple[str, Path]] = []

    async def validate(self, valid_state: str, screenshot: Path) -> bool:
        self.calls.append((valid_state, screenshot))
        return self._result


class _CapturingRecorder:
    """Minimal trajectory recorder fake for fallback event assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def start(self, **kwargs: object) -> None:
        pass

    def finish(self, **kwargs: object) -> None:
        pass

    def set_phase(self, *args: object, **kwargs: object) -> None:
        pass

    def record_event(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))

    def record_step(self, *args: object, **kwargs: object) -> None:
        pass

    @property
    def path(self) -> Path | None:
        return None


def _make_shortcut(*, action_type: str = "tap") -> ShortcutSkill:
    fixed_values: dict[str, object] = {"action_type": action_type}
    if action_type == "tap":
        fixed_values.update({"x": 100, "y": 200})
    if action_type == "request_intervention":
        fixed_values["text"] = "Need help"

    return ShortcutSkill(
        skill_id=f"sc-{action_type}",
        name=f"Shortcut {action_type}",
        description="Phase 30 shortcut",
        app="com.example.app",
        platform="android",
        steps=(
            SkillStep(
                action_type=action_type,
                target=f"{action_type} target",
                fixed=True,
                fixed_values=fixed_values,
            ),
        ),
    )


def _make_result(shortcut: ShortcutSkill, score: float = 0.9) -> SkillSearchResult:
    return SkillSearchResult(skill=shortcut, layer="shortcut", score=score, raw_score=score)


def _make_shortcut_success(skill_id: str) -> ShortcutExecutionSuccess:
    return ShortcutExecutionSuccess(
        skill_id=skill_id,
        step_results=(
            ShortcutStepResult(
                step_index=0,
                action=parse_action({"action_type": "tap", "x": 10, "y": 20}),
                backend_result="ok:tap",
                grounding=None,
                screenshot_path="/tmp/pre.png",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_llm_condition_evaluator() -> None:
    validator = _FakeValidator(result=True)
    evaluator = LLMConditionEvaluator(validator)
    screenshot = Path("/tmp/screenshot.png")

    result = await evaluator.evaluate(
        StateDescriptor(kind="app_open", value="com.example.app"),
        screenshot,
    )
    negated = await evaluator.evaluate(
        StateDescriptor(kind="app_open", value="com.example.app", negated=True),
        screenshot,
    )

    assert result is True
    assert negated is False
    assert validator.calls == [
        ("com.example.app", screenshot),
        ("com.example.app", screenshot),
    ]


@pytest.mark.asyncio
async def test_shortcut_executor_settle_applied(tmp_path: Path) -> None:
    executor = ShortcutExecutor(
        backend=_FakeBackend(),
        grounder=_NeverCalledGrounder(),
        screenshot_dir=tmp_path,
        post_action_settle_seconds=0.1,
    )

    with patch("opengui.skills.multi_layer_executor.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        result = await executor.execute(_make_shortcut(action_type="tap"))

    assert isinstance(result, ShortcutExecutionSuccess)
    sleep_mock.assert_awaited_once_with(0.1)


@pytest.mark.asyncio
@pytest.mark.parametrize("action_type", ["done", "wait", "request_intervention"])
async def test_shortcut_executor_no_settle_for_exempt_actions(
    tmp_path: Path, action_type: str
) -> None:
    executor = ShortcutExecutor(
        backend=_FakeBackend(),
        grounder=_NeverCalledGrounder(),
        screenshot_dir=tmp_path,
        post_action_settle_seconds=0.1,
    )

    with patch("opengui.skills.multi_layer_executor.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        result = await executor.execute(_make_shortcut(action_type=action_type))

    assert isinstance(result, ShortcutExecutionSuccess)
    sleep_mock.assert_not_awaited()


def test_shortcut_executor_exports_llm_condition_evaluator() -> None:
    from opengui.skills import multi_layer_executor

    assert "LLMConditionEvaluator" in multi_layer_executor.__all__


@pytest.mark.asyncio
async def test_shortcut_executor_wiring(tmp_path: Path) -> None:
    recorder = TrajectoryRecorder(output_dir=tmp_path / "trace", task="open app", platform="android")
    backend = _FakeBackend()
    approved = _make_shortcut(action_type="tap")
    shortcut_executor = MagicMock()
    shortcut_executor.execute = AsyncMock(return_value=_make_shortcut_success(approved.skill_id))
    skill_executor = MagicMock()
    skill_executor.execute = AsyncMock()

    agent = GuiAgent(
        llm=MagicMock(),
        backend=backend,
        trajectory_recorder=recorder,
        skill_executor=skill_executor,
        shortcut_executor=shortcut_executor,
    )
    agent._retrieve_memory = AsyncMock(return_value=None)
    agent._search_skill = AsyncMock(return_value=None)
    agent._retrieve_shortcut_candidates = AsyncMock(return_value=[_make_result(approved)])
    agent._evaluate_shortcut_applicability = AsyncMock(
        return_value=ApplicabilityDecision(
            outcome="run",
            shortcut_id=approved.skill_id,
            score=0.9,
            reason="ok",
        )
    )
    agent._inject_skill_memory_context = AsyncMock(side_effect=lambda skill, context: context)
    agent._make_run_dir = lambda task, attempt: tmp_path / f"attempt-{attempt}"
    agent._log_attempt_event = AsyncMock()
    agent._skill_maintenance = AsyncMock()
    agent._run_once = AsyncMock(
        return_value=AgentResult(success=True, summary="done", trace_path=str(tmp_path / "attempt-0"))
    )

    await agent.run("open app", max_retries=1)

    shortcut_executor.execute.assert_awaited_once_with(approved)
    skill_executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_binding_uses_shortcut_execution_success(tmp_path: Path) -> None:
    recorder = TrajectoryRecorder(output_dir=tmp_path / "trace", task="open app", platform="android")
    backend = _FakeBackend()
    approved = _make_shortcut(action_type="tap")
    shortcut_executor = MagicMock()
    shortcut_executor.execute = AsyncMock(return_value=_make_shortcut_success(approved.skill_id))

    agent = GuiAgent(
        llm=MagicMock(),
        backend=backend,
        trajectory_recorder=recorder,
        shortcut_executor=shortcut_executor,
    )
    agent._retrieve_memory = AsyncMock(return_value=None)
    agent._search_skill = AsyncMock(return_value=None)
    agent._retrieve_shortcut_candidates = AsyncMock(return_value=[_make_result(approved)])
    agent._evaluate_shortcut_applicability = AsyncMock(
        return_value=ApplicabilityDecision(
            outcome="run",
            shortcut_id=approved.skill_id,
            score=0.9,
            reason="ok",
        )
    )
    agent._inject_skill_memory_context = AsyncMock(side_effect=lambda skill, context: context)
    agent._make_run_dir = lambda task, attempt: tmp_path / f"attempt-{attempt}"
    agent._log_attempt_event = AsyncMock()
    agent._skill_maintenance = AsyncMock()
    agent._run_once = AsyncMock(
        return_value=AgentResult(success=True, summary="done", trace_path=str(tmp_path / "attempt-0"))
    )

    await agent.run("open app", max_retries=1)

    skill_context = agent._run_once.await_args.kwargs["skill_context"]
    assert "Shortcut 'sc-tap' executed 1 step(s):" in skill_context
    assert "Step 0: tap" in skill_context

    assert recorder.path is not None
    events = [json.loads(line) for line in recorder.path.read_text().splitlines() if line.strip()]
    shortcut_events = [event for event in events if event.get("type") == "shortcut_execution"]
    assert shortcut_events
    assert shortcut_events[-1]["outcome"] == "success"
    assert shortcut_events[-1]["skill_id"] == approved.skill_id


@pytest.mark.asyncio
async def test_nanobot_wires_shortcut_executor(tmp_path: Path) -> None:
    from nanobot.agent.tools.gui import GuiSubagentTool

    captured_gui_agent_kwargs: dict[str, object] = {}
    constructed: dict[str, object] = {}

    class _FakeGuiAgent:
        def __init__(self, **kwargs: object) -> None:
            captured_gui_agent_kwargs.update(kwargs)

        async def run(self, task: str) -> AgentResult:
            return AgentResult(success=True, summary=task, trace_path=str(tmp_path / "agent-trace"))

    class _FakeStateValidator:
        def __init__(self, llm: object) -> None:
            self.llm = llm

    class _FakeSkillExecutor:
        def __init__(self, **kwargs: object) -> None:
            constructed["skill_executor"] = kwargs

    class _FakeConditionEvaluator:
        def __init__(self, validator: object) -> None:
            constructed["condition_evaluator"] = validator

    class _FakeGrounder:
        def __init__(self, llm: object) -> None:
            constructed["grounder_llm"] = llm

    class _FakeShortcutExecutor:
        def __init__(self, **kwargs: object) -> None:
            constructed["shortcut_executor"] = kwargs

    class _FakeRouter:
        def __init__(self, **kwargs: object) -> None:
            constructed["router"] = kwargs

    tool = GuiSubagentTool.__new__(GuiSubagentTool)
    tool._gui_config = SimpleNamespace(enable_skill_execution=True, max_steps=3, skill_threshold=0.5)
    tool._llm_adapter = object()
    tool._model = "test-model"
    tool._load_policy_context_and_memory_store = lambda: (None, None)
    tool._get_skill_library = lambda platform: None
    tool._get_unified_skill_search = lambda platform: None
    tool._make_run_dir = lambda: tmp_path / "run"
    tool._build_intervention_handler = lambda active_backend, task: None
    tool._resolve_trace_path = lambda recorder_path, agent_trace_path: Path(agent_trace_path)
    tool._schedule_trajectory_postprocessing = lambda *args, **kwargs: None

    active_backend = SimpleNamespace(platform="android")

    with patch("nanobot.agent.tools.gui.GuiAgent", _FakeGuiAgent), \
        patch("opengui.skills.executor.LLMStateValidator", _FakeStateValidator), \
        patch("opengui.skills.executor.SkillExecutor", _FakeSkillExecutor), \
        patch("opengui.skills.multi_layer_executor.LLMConditionEvaluator", _FakeConditionEvaluator), \
        patch("opengui.skills.multi_layer_executor.ShortcutExecutor", _FakeShortcutExecutor), \
        patch("opengui.grounding.llm.LLMGrounder", _FakeGrounder), \
        patch("opengui.skills.shortcut_router.ShortcutApplicabilityRouter", _FakeRouter):
        payload = await GuiSubagentTool._run_task(tool, active_backend, "open app")

    parsed = json.loads(payload)
    assert parsed["success"] is True
    assert captured_gui_agent_kwargs["shortcut_executor"] is not None
    assert captured_gui_agent_kwargs["shortcut_applicability_router"] is not None
    assert constructed["shortcut_executor"]["condition_evaluator"] is constructed["router"]["condition_evaluator"]


@pytest.mark.asyncio
async def test_settle_timing(tmp_path: Path) -> None:
    executor = ShortcutExecutor(
        backend=_FakeBackend(),
        grounder=_NeverCalledGrounder(),
        screenshot_dir=tmp_path / "settle_test",
        post_action_settle_seconds=0.2,
    )

    with patch("opengui.skills.multi_layer_executor.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        result = await executor.execute(_make_shortcut(action_type="tap"))

    assert isinstance(result, ShortcutExecutionSuccess)
    sleep_mock.assert_awaited_once_with(0.2)


@pytest.mark.asyncio
async def test_post_step_observation(tmp_path: Path) -> None:
    call_log: list[str] = []

    class _LoggingBackend:
        async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.touch()
            boundary = "pre" if "pre" in screenshot_path.name else "post"
            call_log.append(f"observe_{boundary}")
            return Observation(
                screenshot_path=str(screenshot_path),
                screen_width=1080,
                screen_height=1920,
                foreground_app="com.example.app",
                platform="android",
            )

        async def execute(self, action: Action, timeout: float = 5.0) -> str:
            call_log.append("execute")
            return "ok"

        @property
        def platform(self) -> str:
            return "android"

    executor = ShortcutExecutor(
        backend=_LoggingBackend(),
        grounder=_NeverCalledGrounder(),
        screenshot_dir=tmp_path / "order_test",
        post_action_settle_seconds=0.0,
    )

    result = await executor.execute(_make_shortcut(action_type="tap"))

    assert isinstance(result, ShortcutExecutionSuccess)
    assert call_log == ["observe_pre", "execute", "observe_post"]


@pytest.mark.asyncio
async def test_post_step_validation(tmp_path: Path) -> None:
    captured_screenshots: list[Path] = []
    postcondition = StateDescriptor(kind="screen_state", value="confirm_screen_visible")

    class _CapturingEvaluator:
        async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool:
            captured_screenshots.append(screenshot)
            return False

    shortcut = ShortcutSkill(
        skill_id="sc-post-validate",
        name="PostVal",
        description="tests post validation",
        app="com.example.app",
        platform="android",
        steps=(
            SkillStep(
                action_type="tap",
                target="tap target",
                fixed=True,
                fixed_values={"action_type": "tap", "x": 10, "y": 20},
            ),
        ),
        postconditions=(postcondition,),
    )

    executor = ShortcutExecutor(
        backend=_FakeBackend(),
        grounder=_NeverCalledGrounder(),
        condition_evaluator=_CapturingEvaluator(),
        screenshot_dir=tmp_path / "post_val",
        post_action_settle_seconds=0.0,
    )

    result = await executor.execute(shortcut)

    assert isinstance(result, ContractViolationReport)
    assert result.boundary == "post"
    assert result.step_index == 0
    assert result.failed_condition == postcondition
    assert len(captured_screenshots) == 1
    assert "post" in captured_screenshots[0].name


@pytest.mark.asyncio
async def test_contract_violation_fallback(tmp_path: Path) -> None:
    """SUSE-04: Contract violations fall back into the normal agent loop."""

    violation = ContractViolationReport(
        skill_id="sc-fallback-01",
        step_index=1,
        failed_condition=StateDescriptor(kind="screen_state", value="target_visible"),
        boundary="post",
    )
    shortcut_executor = MagicMock()
    shortcut_executor.execute = AsyncMock(return_value=violation)
    recorder = _CapturingRecorder()

    agent = GuiAgent(
        llm=MagicMock(),
        backend=_FakeBackend(),
        trajectory_recorder=recorder,
        shortcut_executor=shortcut_executor,
        artifacts_root=tmp_path,
    )
    agent._retrieve_memory = AsyncMock(return_value=None)
    agent._search_skill = AsyncMock(return_value=None)
    agent._retrieve_shortcut_candidates = AsyncMock(return_value=[_make_result(_make_shortcut())])
    agent._evaluate_shortcut_applicability = AsyncMock(
        return_value=ApplicabilityDecision(
            outcome="run",
            shortcut_id="sc-tap",
            reason="ok",
            score=0.9,
        )
    )
    agent._inject_skill_memory_context = AsyncMock(side_effect=lambda skill, context: context)
    agent._make_run_dir = lambda task, attempt: tmp_path / f"attempt-{attempt}"
    agent._log_attempt_event = AsyncMock()
    agent._skill_maintenance = AsyncMock()

    run_once_calls: list[dict[str, object]] = []

    async def fake_run_once(
        task: str,
        *,
        app_hint: str | None,
        run_dir: Path,
        memory_context: str | None = None,
        skill_context: str | None = None,
    ) -> AgentResult:
        run_once_calls.append(
            {
                "task": task,
                "app_hint": app_hint,
                "run_dir": run_dir,
                "memory_context": memory_context,
                "skill_context": skill_context,
            }
        )
        return AgentResult(success=True, summary="done", trace_path=str(run_dir))

    agent._run_once = fake_run_once

    result = await agent.run("open settings", max_retries=1)

    assert result.success is True
    assert shortcut_executor.execute.await_count == 1
    assert len(run_once_calls) == 1
    assert run_once_calls[0]["skill_context"] is None
    assert not isinstance(result.error, str) or "sc-fallback-01" not in result.error


@pytest.mark.asyncio
async def test_fallback_no_worse(tmp_path: Path) -> None:
    """SUSE-04: A crashing shortcut executor is no worse than skipping shortcuts."""

    crashing_executor = MagicMock()
    crashing_executor.execute = AsyncMock(side_effect=RuntimeError("backend io failure"))
    normal_outcome = AgentResult(success=True, summary="done via normal path")

    async def fake_run_once(
        task: str,
        *,
        app_hint: str | None,
        run_dir: Path,
        memory_context: str | None = None,
        skill_context: str | None = None,
    ) -> AgentResult:
        return normal_outcome

    def make_agent(shortcut_executor: object | None) -> GuiAgent:
        agent = GuiAgent(
            llm=MagicMock(),
            backend=_FakeBackend(),
            trajectory_recorder=_CapturingRecorder(),
            shortcut_executor=shortcut_executor,
            artifacts_root=tmp_path / f"agent-{id(shortcut_executor)}",
        )
        agent._retrieve_memory = AsyncMock(return_value=None)
        agent._search_skill = AsyncMock(return_value=None)
        agent._inject_skill_memory_context = AsyncMock(side_effect=lambda skill, context: context)
        agent._make_run_dir = lambda task, attempt: tmp_path / f"agent-{id(shortcut_executor)}" / f"attempt-{attempt}"
        agent._log_attempt_event = AsyncMock()
        agent._skill_maintenance = AsyncMock()
        agent._run_once = fake_run_once
        return agent

    approved = _make_shortcut()
    candidate = _make_result(approved)
    decision = ApplicabilityDecision(
        outcome="run",
        shortcut_id=approved.skill_id,
        reason="ok",
        score=0.9,
    )

    agent_with_crash = make_agent(crashing_executor)
    agent_with_crash._retrieve_shortcut_candidates = AsyncMock(return_value=[candidate])
    agent_with_crash._evaluate_shortcut_applicability = AsyncMock(return_value=decision)

    result_with_crash = await agent_with_crash.run("open app", max_retries=1)

    agent_no_shortcut = make_agent(None)
    agent_no_shortcut._retrieve_shortcut_candidates = AsyncMock(return_value=[])
    agent_no_shortcut._evaluate_shortcut_applicability = AsyncMock()

    result_no_shortcut = await agent_no_shortcut.run("open app", max_retries=1)

    crashing_executor.execute.assert_awaited_once()
    assert result_with_crash.success == result_no_shortcut.success
    assert result_with_crash.summary == result_no_shortcut.summary
    assert "RuntimeError" not in (result_with_crash.error or "")


@pytest.mark.asyncio
async def test_shortcut_trajectory_event(tmp_path: Path) -> None:
    """SSTA-02: Violation telemetry includes the structured contract fields."""

    violation = ContractViolationReport(
        skill_id="sc-drift-001",
        step_index=2,
        failed_condition=StateDescriptor(kind="screen_state", value="confirm_visible"),
        boundary="post",
    )
    shortcut_executor = MagicMock()
    shortcut_executor.execute = AsyncMock(return_value=violation)
    recorder = _CapturingRecorder()

    agent = GuiAgent(
        llm=MagicMock(),
        backend=_FakeBackend(),
        trajectory_recorder=recorder,
        shortcut_executor=shortcut_executor,
        artifacts_root=tmp_path,
    )
    approved = ShortcutSkill(
        skill_id="sc-drift-001",
        name="Drift",
        description="trajectory event test",
        app="com.example.app",
        platform="android",
    )
    agent._retrieve_memory = AsyncMock(return_value=None)
    agent._search_skill = AsyncMock(return_value=None)
    agent._retrieve_shortcut_candidates = AsyncMock(return_value=[_make_result(approved, score=0.85)])
    agent._evaluate_shortcut_applicability = AsyncMock(
        return_value=ApplicabilityDecision(
            outcome="run",
            shortcut_id=approved.skill_id,
            reason="ok",
            score=0.85,
        )
    )
    agent._inject_skill_memory_context = AsyncMock(side_effect=lambda skill, context: context)
    agent._make_run_dir = lambda task, attempt: tmp_path / f"attempt-{attempt}"
    agent._log_attempt_event = AsyncMock()
    agent._skill_maintenance = AsyncMock()
    agent._run_once = AsyncMock(
        return_value=AgentResult(success=True, summary="ok", trace_path=str(tmp_path / "attempt-0"))
    )

    await agent.run("open settings", max_retries=1)

    violation_events = [
        payload
        for event, payload in recorder.events
        if event == "shortcut_execution" and payload.get("outcome") == "violation"
    ]
    assert len(violation_events) == 1
    assert violation_events[0]["skill_id"] == "sc-drift-001"
    assert violation_events[0]["step_index"] == 2
    assert violation_events[0]["boundary"] == "post"
    assert violation_events[0]["failed_condition"] == "confirm_visible"


@pytest.mark.asyncio
async def test_gui_agent_injects_live_trajectory_recorder_into_shortcut_executor(
    tmp_path: Path,
) -> None:
    """SSTA-03 wiring regression: GuiAgent must assign self._trajectory_recorder onto
    the shortcut_executor instance before execute() is awaited, so executor-emitted
    events land in the same JSONL trace artifact.

    Uses a MagicMock shortcut_executor and a real TrajectoryRecorder.  The test
    captures the recorder that was assigned onto the executor at the moment execute()
    was awaited, then asserts it is the same object as the agent's live recorder.
    """
    recorder = TrajectoryRecorder(output_dir=tmp_path / "trace", task="open app", platform="android")
    backend = _FakeBackend()
    approved = _make_shortcut(action_type="tap")

    captured: dict[str, object] = {}

    async def _capturing_execute(shortcut: object) -> ShortcutExecutionSuccess:
        # Capture the recorder that was set on the mock before execute() is called.
        captured["recorder"] = shortcut_executor.trajectory_recorder
        return _make_shortcut_success(approved.skill_id)

    shortcut_executor = MagicMock()
    shortcut_executor.execute = _capturing_execute

    agent = GuiAgent(
        llm=MagicMock(),
        backend=backend,
        trajectory_recorder=recorder,
        shortcut_executor=shortcut_executor,
    )
    agent._retrieve_memory = AsyncMock(return_value=None)
    agent._search_skill = AsyncMock(return_value=None)
    agent._retrieve_shortcut_candidates = AsyncMock(return_value=[_make_result(approved)])
    agent._evaluate_shortcut_applicability = AsyncMock(
        return_value=ApplicabilityDecision(
            outcome="run",
            shortcut_id=approved.skill_id,
            score=0.9,
            reason="ok",
        )
    )
    agent._inject_skill_memory_context = AsyncMock(side_effect=lambda skill, context: context)
    agent._make_run_dir = lambda task, attempt: tmp_path / f"attempt-{attempt}"
    agent._log_attempt_event = AsyncMock()
    agent._skill_maintenance = AsyncMock()
    agent._run_once = AsyncMock(
        return_value=AgentResult(success=True, summary="done", trace_path=str(tmp_path / "attempt-0"))
    )

    await agent.run("open app", max_retries=1)

    # The recorder injected onto the executor must be the agent's live recorder.
    assert "recorder" in captured, "execute() was never awaited"
    assert captured["recorder"] is recorder, (
        "GuiAgent must assign self._trajectory_recorder onto the shortcut executor "
        "before execute() is called"
    )
