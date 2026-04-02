"""
Phase 26 - Quality-gated extraction building-block tests.

Covers:
  - StepCritic and TrajectoryCritic runtime-checkable protocol contracts
  - StepVerdict and TrajectoryVerdict frozen dataclasses
  - ExtractionSuccess and ExtractionRejected result dataclasses
  - ShortcutSkillProducer transformation from trajectory step events to ShortcutSkill
  - Module compile smoke for the new shortcut_extractor module

All tests use fake critics and concrete trajectory-step dictionaries so no live
LLM, screenshots, or device backend are required.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path
from typing import Any

import pytest

from opengui.skills.shortcut import ShortcutSkill, StateDescriptor
from opengui.skills.shortcut_extractor import (
    ExtractionPipeline,
    ExtractionRejected,
    ExtractionSuccess,
    ShortcutSkillProducer,
    StepCritic,
    StepVerdict,
    TrajectoryCritic,
    TrajectoryVerdict,
)


class _FakeStepCritic:
    async def evaluate(self, step: dict[str, Any], step_index: int) -> StepVerdict:
        action_type = str(step.get("action", {}).get("action_type", "")).strip()
        target = str(step.get("model_output", "")).strip()
        if not action_type or not target:
            return StepVerdict(step_index=step_index, passed=False, reason="missing action or target")
        return StepVerdict(step_index=step_index, passed=True, reason="ok")


class _FakeTrajectoryCritic:
    async def evaluate(self, steps: list[dict[str, Any]], metadata: dict[str, Any]) -> TrajectoryVerdict:
        if not metadata.get("success", False):
            return TrajectoryVerdict(
                passed=False,
                reason="task failed",
                failed_step_index=len(steps) - 1 if steps else None,
            )
        return TrajectoryVerdict(passed=True, reason="all steps valid")


class _CountingStepCritic:
    def __init__(self, verdicts: list[StepVerdict] | None = None) -> None:
        self.calls: list[tuple[dict[str, Any], int]] = []
        self._verdicts = verdicts or []

    async def evaluate(self, step: dict[str, Any], step_index: int) -> StepVerdict:
        self.calls.append((step, step_index))
        if step_index < len(self._verdicts):
            return self._verdicts[step_index]
        return StepVerdict(step_index=step_index, passed=True, reason="ok")


class _CountingTrajectoryCritic:
    def __init__(self, verdict: TrajectoryVerdict | None = None) -> None:
        self.calls: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
        self._verdict = verdict or TrajectoryVerdict(passed=True, reason="all steps valid")

    async def evaluate(self, steps: list[dict[str, Any]], metadata: dict[str, Any]) -> TrajectoryVerdict:
        self.calls.append((steps, metadata))
        return self._verdict


class _CountingProducer(ShortcutSkillProducer):
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, Any]], str, str]] = []

    def produce(self, steps: list[dict[str, Any]], *, app: str, platform: str) -> ShortcutSkill:
        self.calls.append((steps, app, platform))
        return super().produce(steps, app=app, platform=platform)


def _make_step(
    *,
    step_index: int,
    action_type: str = "tap",
    model_output: str = "Tap the search bar",
    valid_state: str | None = None,
    expected_state: str | None = None,
) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "screen_width": 1080,
        "screen_height": 1920,
    }
    if valid_state is not None:
        observation["valid_state"] = valid_state
    if expected_state is not None:
        observation["expected_state"] = expected_state

    return {
        "type": "step",
        "step_index": step_index,
        "phase": "agent",
        "timestamp": 1234567890.0 + step_index,
        "action": {
            "action_type": action_type,
            "x": 540,
            "y": 120,
        },
        "model_output": model_output,
        "screenshot_path": f"/tmp/trace/step_{step_index:03d}.png",
        "observation": observation,
    }


@pytest.mark.asyncio
async def test_step_verdict_is_frozen_dataclass() -> None:
    verdict = StepVerdict(step_index=0, passed=True, reason="ok")

    assert dataclasses.is_dataclass(verdict)
    assert verdict.step_index == 0
    assert verdict.passed is True
    assert verdict.reason == "ok"
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.reason = "mutated"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_step_verdict_carries_failure_details() -> None:
    verdict = StepVerdict(step_index=1, passed=False, reason="empty target")

    assert verdict.step_index == 1
    assert verdict.passed is False
    assert verdict.reason == "empty target"


@pytest.mark.asyncio
async def test_trajectory_verdict_is_frozen_dataclass() -> None:
    verdict = TrajectoryVerdict(passed=True, reason="all steps valid")

    assert dataclasses.is_dataclass(verdict)
    assert verdict.passed is True
    assert verdict.reason == "all steps valid"
    assert verdict.failed_step_index is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.failed_step_index = 3  # type: ignore[misc]


@pytest.mark.asyncio
async def test_trajectory_verdict_carries_failed_step_index() -> None:
    verdict = TrajectoryVerdict(passed=False, reason="task failed", failed_step_index=3)

    assert verdict.passed is False
    assert verdict.reason == "task failed"
    assert verdict.failed_step_index == 3


@pytest.mark.asyncio
async def test_extraction_success_holds_candidate_and_verdicts() -> None:
    candidate = ShortcutSkill(
        skill_id="skill-1",
        name="tap_search_bar",
        description="Extracted from trajectory",
        app="com.example.app",
        platform="android",
    )
    result = ExtractionSuccess(
        candidate=candidate,
        step_verdicts=(StepVerdict(step_index=0, passed=True, reason="ok"),),
        trajectory_verdict=TrajectoryVerdict(passed=True, reason="all steps valid"),
    )

    assert result.candidate == candidate
    assert result.step_verdicts[0].passed is True
    assert result.trajectory_verdict.passed is True


@pytest.mark.asyncio
async def test_extraction_rejected_holds_failure_context() -> None:
    step_verdict = StepVerdict(step_index=1, passed=False, reason="empty target")
    trajectory_verdict = TrajectoryVerdict(passed=False, reason="task failed", failed_step_index=1)
    result = ExtractionRejected(
        reason="step_critic",
        failed_step_verdict=step_verdict,
        failed_trajectory_verdict=trajectory_verdict,
    )

    assert result.reason == "step_critic"
    assert result.failed_step_verdict == step_verdict
    assert result.failed_trajectory_verdict == trajectory_verdict


@pytest.mark.asyncio
async def test_step_critic_protocol_runtime_check_and_valid_step() -> None:
    critic = _FakeStepCritic()
    step = _make_step(step_index=0)

    assert isinstance(critic, StepCritic)
    verdict = await critic.evaluate(step, 0)
    assert verdict == StepVerdict(step_index=0, passed=True, reason="ok")


@pytest.mark.asyncio
async def test_step_critic_rejects_empty_target() -> None:
    critic = _FakeStepCritic()
    step = _make_step(step_index=1, model_output="")

    verdict = await critic.evaluate(step, 1)
    assert verdict.passed is False
    assert verdict.step_index == 1


@pytest.mark.asyncio
async def test_trajectory_critic_protocol_runtime_check_and_success() -> None:
    critic = _FakeTrajectoryCritic()
    steps = [_make_step(step_index=0), _make_step(step_index=1)]

    assert isinstance(critic, TrajectoryCritic)
    verdict = await critic.evaluate(steps, {"success": True})
    assert verdict == TrajectoryVerdict(passed=True, reason="all steps valid")


@pytest.mark.asyncio
async def test_trajectory_critic_rejects_failed_trajectory() -> None:
    critic = _FakeTrajectoryCritic()
    steps = [_make_step(step_index=0), _make_step(step_index=1)]

    verdict = await critic.evaluate(steps, {"success": False})
    assert verdict.passed is False
    assert verdict.reason == "task failed"
    assert verdict.failed_step_index == 1


@pytest.mark.asyncio
async def test_shortcut_skill_producer_infers_parameter_slots_and_conditions() -> None:
    producer = ShortcutSkillProducer()
    steps = [
        _make_step(
            step_index=0,
            action_type="tap",
            model_output="Tap {{search_term}} in {{search_box}}",
            valid_state="search field is visible",
            expected_state="search results are visible",
        ),
        _make_step(
            step_index=1,
            action_type="input_text",
            model_output="Type {{search_term}}",
            valid_state="No need to verify",
            expected_state="",
        ),
    ]

    skill = producer.produce(steps, app="com.Example.App", platform="android")

    assert skill.app == "com.example.app"
    assert tuple(slot.name for slot in skill.parameter_slots) == ("search_term", "search_box")
    assert skill.preconditions == (
        StateDescriptor(kind="screen_state", value="search field is visible"),
    )
    assert skill.postconditions == (
        StateDescriptor(kind="screen_state", value="search results are visible"),
    )


@pytest.mark.asyncio
async def test_shortcut_skill_producer_returns_empty_slots_without_placeholders() -> None:
    producer = ShortcutSkillProducer()
    steps = [
        _make_step(
            step_index=0,
            action_type="tap",
            model_output="Tap the settings button",
            valid_state="",
            expected_state="settings screen is visible",
        )
    ]

    skill = producer.produce(steps, app="Settings", platform="android")

    assert skill.parameter_slots == ()
    assert skill.steps[0].action_type == "tap"
    assert skill.steps[0].target == "Tap the settings button"


@pytest.mark.asyncio
async def test_shortcut_extractor_module_compiles() -> None:
    process = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        sys.executable,
        "-m",
        "py_compile",
        "opengui/skills/shortcut_extractor.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "steps",
    [
        [],
        [_make_step(step_index=0)],
    ],
)
async def test_pipeline_rejects_too_few_steps_without_running_critics(
    steps: list[dict[str, Any]],
) -> None:
    step_critic = _CountingStepCritic()
    trajectory_critic = _CountingTrajectoryCritic()
    producer = _CountingProducer()
    pipeline = ExtractionPipeline(
        step_critic=step_critic,
        trajectory_critic=trajectory_critic,
        producer=producer,
    )

    result = await pipeline.run(
        steps,
        {"app": "com.example.app", "platform": "android", "success": True, "task": "Open settings"},
    )

    assert result == ExtractionRejected(
        reason="too_few_steps",
        failed_step_verdict=None,
        failed_trajectory_verdict=None,
    )
    assert step_critic.calls == []
    assert trajectory_critic.calls == []
    assert producer.calls == []


@pytest.mark.asyncio
async def test_pipeline_returns_success_after_both_critics_pass() -> None:
    step_critic = _CountingStepCritic()
    trajectory_critic = _CountingTrajectoryCritic()
    producer = _CountingProducer()
    pipeline = ExtractionPipeline(
        step_critic=step_critic,
        trajectory_critic=trajectory_critic,
        producer=producer,
    )
    steps = [_make_step(step_index=0), _make_step(step_index=1)]

    result = await pipeline.run(
        steps,
        {"app": "com.example.app", "platform": "android", "success": True, "task": "Open settings"},
    )

    assert isinstance(result, ExtractionSuccess)
    assert len(result.step_verdicts) == 2
    assert all(verdict.passed for verdict in result.step_verdicts)
    assert result.trajectory_verdict.passed is True
    assert isinstance(result.candidate, ShortcutSkill)
    assert len(step_critic.calls) == 2
    assert len(trajectory_critic.calls) == 1
    assert len(producer.calls) == 1


@pytest.mark.asyncio
async def test_pipeline_stops_after_step_critic_failure() -> None:
    failed_step = StepVerdict(step_index=1, passed=False, reason="missing target")
    step_critic = _CountingStepCritic(
        verdicts=[
            StepVerdict(step_index=0, passed=True, reason="ok"),
            failed_step,
        ]
    )
    trajectory_critic = _CountingTrajectoryCritic()
    producer = _CountingProducer()
    pipeline = ExtractionPipeline(
        step_critic=step_critic,
        trajectory_critic=trajectory_critic,
        producer=producer,
    )
    steps = [_make_step(step_index=0), _make_step(step_index=1, model_output="")]

    result = await pipeline.run(
        steps,
        {"app": "com.example.app", "platform": "android", "success": True, "task": "Open settings"},
    )

    assert result == ExtractionRejected(
        reason="step_critic",
        failed_step_verdict=failed_step,
        failed_trajectory_verdict=None,
    )
    assert len(step_critic.calls) == 2
    assert trajectory_critic.calls == []
    assert producer.calls == []


@pytest.mark.asyncio
async def test_pipeline_stops_after_trajectory_critic_failure() -> None:
    trajectory_verdict = TrajectoryVerdict(
        passed=False,
        reason="contradictory steps",
        failed_step_index=1,
    )
    step_critic = _CountingStepCritic()
    trajectory_critic = _CountingTrajectoryCritic(verdict=trajectory_verdict)
    producer = _CountingProducer()
    pipeline = ExtractionPipeline(
        step_critic=step_critic,
        trajectory_critic=trajectory_critic,
        producer=producer,
    )
    steps = [_make_step(step_index=0), _make_step(step_index=1)]

    result = await pipeline.run(
        steps,
        {"app": "com.example.app", "platform": "android", "success": True, "task": "Open settings"},
    )

    assert result == ExtractionRejected(
        reason="trajectory_critic",
        failed_step_verdict=None,
        failed_trajectory_verdict=trajectory_verdict,
    )
    assert len(step_critic.calls) == 2
    assert len(trajectory_critic.calls) == 1
    assert producer.calls == []


@pytest.mark.asyncio
async def test_pipeline_defaults_to_always_pass_critics() -> None:
    pipeline = ExtractionPipeline()
    steps = [_make_step(step_index=0), _make_step(step_index=1)]

    result = await pipeline.run(
        steps,
        {"app": "com.example.app", "platform": "android", "success": True, "task": "Open settings"},
    )

    assert isinstance(result, ExtractionSuccess)
    assert len(result.step_verdicts) == 2
    assert result.trajectory_verdict.passed is True


def test_pipeline_symbols_are_exported_from_package() -> None:
    from opengui import skills

    assert skills.ExtractionPipeline is ExtractionPipeline
    assert skills.ExtractionRejected is ExtractionRejected
    assert skills.ExtractionSuccess is ExtractionSuccess
    assert skills.ShortcutSkillProducer is ShortcutSkillProducer
    assert skills.StepCritic is StepCritic
    assert skills.StepVerdict is StepVerdict
    assert skills.TrajectoryCritic is TrajectoryCritic
    assert skills.TrajectoryVerdict is TrajectoryVerdict
