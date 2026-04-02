"""
Phase 25 — Multi-layer execution contract tests.

Covers:
  - ShortcutExecutor pre-condition contract: violation report returned before step runs
  - ShortcutExecutor post-condition contract: violation report returned after step runs
  - Grounding seam: unbound parameter slots routed through GrounderProtocol + parse_action()
  - Fixed-value bypass: fixed steps skip grounder and normalize through parse_action()
  - Package exports: opengui.skills.__all__ exposes all Phase 25 shortcut executor types

All tests use stub/fake collaborators so no live device, LLM, or network is required.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from opengui.action import Action, parse_action
from opengui.grounding.protocol import GroundingContext, GroundingResult
from opengui.observation import Observation
from opengui.skills.data import SkillStep
from opengui.skills.shortcut import ParameterSlot, ShortcutSkill, StateDescriptor

# Phase 25 imports — these will cause ImportError until Task 2 is implemented (TDD RED)
from opengui.skills.multi_layer_executor import (
    ConditionEvaluator,
    ContractViolationReport,
    ShortcutExecutionSuccess,
    ShortcutExecutor,
)


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Minimal DeviceBackend fake: records execute() calls and returns fixed strings."""

    def __init__(self, screen_width: int = 1080, screen_height: int = 1920) -> None:
        self._screen_width = screen_width
        self._screen_height = screen_height
        self.executed_actions: list[Action] = []

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        # Create a zero-byte file so the executor can capture the path
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.touch()
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=self._screen_width,
            screen_height=self._screen_height,
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


class _StubGrounder:
    """Records every (target, context) call; returns resolved_params from a pre-loaded list."""

    def __init__(self, resolved_params_sequence: list[dict[str, Any]] | None = None) -> None:
        # Default: return a tap action at fixed coordinates
        self._sequence = resolved_params_sequence or [{"action_type": "tap", "x": 100.0, "y": 200.0}]
        self.calls: list[tuple[str, GroundingContext]] = []

    async def ground(self, target: str, context: GroundingContext) -> GroundingResult:
        self.calls.append((target, context))
        params = self._sequence[len(self.calls) - 1] if len(self.calls) <= len(self._sequence) else self._sequence[-1]
        return GroundingResult(
            grounder_id="stub:test",
            confidence=1.0,
            resolved_params=dict(params),
        )


class _NeverCalledGrounder:
    """Grounder that raises AssertionError if called — asserts fixed steps bypass grounding."""

    async def ground(self, target: str, context: GroundingContext) -> GroundingResult:
        raise AssertionError(
            f"Grounder should NOT have been called for fixed step, but was called with target={target!r}"
        )


class _SequenceConditionEvaluator:
    """Pops boolean results from a pre-loaded list; raises AssertionError when exhausted."""

    def __init__(self, results: list[bool]) -> None:
        self._results = list(results)

    async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool:
        if not self._results:
            raise AssertionError("_SequenceConditionEvaluator exhausted — unexpected evaluate() call.")
        return self._results.pop(0)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_shortcut(
    *,
    skill_id: str = "sc-test",
    steps: tuple[SkillStep, ...] = (),
    parameter_slots: tuple[ParameterSlot, ...] = (),
    preconditions: tuple[StateDescriptor, ...] = (),
    postconditions: tuple[StateDescriptor, ...] = (),
) -> ShortcutSkill:
    return ShortcutSkill(
        skill_id=skill_id,
        name="Test Shortcut",
        description="A shortcut for testing",
        app="com.example.app",
        platform="android",
        steps=steps,
        parameter_slots=parameter_slots,
        preconditions=preconditions,
        postconditions=postconditions,
    )


# ---------------------------------------------------------------------------
# Test 1: Pre-condition violation report is returned before step executes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shortcut_executor_returns_pre_contract_violation_report(tmp_path: Path) -> None:
    """ShortcutExecutor returns ContractViolationReport(boundary='pre') before executing the first step."""
    failing_condition = StateDescriptor(kind="app_open", value="com.example.app")
    step = SkillStep(action_type="tap", target="submit button")
    shortcut = _make_shortcut(
        steps=(step,),
        preconditions=(failing_condition,),
    )

    backend = _FakeBackend()
    grounder = _StubGrounder()
    # Evaluator always returns False → pre-condition fails immediately
    evaluator = _SequenceConditionEvaluator(results=[False])

    executor = ShortcutExecutor(
        backend=backend,
        grounder=grounder,
        condition_evaluator=evaluator,
        screenshot_dir=tmp_path,
    )
    result = await executor.execute(shortcut)

    # Must be a violation report, not a success
    assert isinstance(result, ContractViolationReport)
    assert result.is_violation is True
    assert result.boundary == "pre"
    assert result.skill_id == "sc-test"
    assert result.step_index == 0
    assert result.failed_condition == failing_condition

    # Backend must NOT have been called — violation is raised before step execution
    assert backend.executed_actions == []


# ---------------------------------------------------------------------------
# Test 2: Post-condition violation report is returned after step executes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shortcut_executor_returns_post_contract_violation_report(tmp_path: Path) -> None:
    """ShortcutExecutor returns ContractViolationReport(boundary='post') after executing the step."""
    pre_condition = StateDescriptor(kind="app_open", value="com.example.app")
    post_condition = StateDescriptor(kind="screen_visible", value="confirmation_screen")
    # A tap step with fixed values to avoid grounder call complexity
    step = SkillStep(
        action_type="tap",
        target="submit button",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 100, "y": 200},
    )
    shortcut = _make_shortcut(
        steps=(step,),
        preconditions=(pre_condition,),
        postconditions=(post_condition,),
    )

    backend = _FakeBackend()
    grounder = _NeverCalledGrounder()
    # Pre passes, post fails
    evaluator = _SequenceConditionEvaluator(results=[True, False])

    executor = ShortcutExecutor(
        backend=backend,
        grounder=grounder,
        condition_evaluator=evaluator,
        screenshot_dir=tmp_path,
    )
    result = await executor.execute(shortcut)

    # Must be a post-condition violation
    assert isinstance(result, ContractViolationReport)
    assert result.is_violation is True
    assert result.boundary == "post"
    assert result.skill_id == "sc-test"
    assert result.step_index == 0
    assert result.failed_condition == post_condition

    # Step WAS executed (backend was called once)
    assert len(backend.executed_actions) == 1
    assert backend.executed_actions[0].action_type == "tap"


# ---------------------------------------------------------------------------
# Test 3: Unbound parameter slots are routed through the grounder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shortcut_executor_routes_unbound_slots_through_grounder(tmp_path: Path) -> None:
    """An unresolved parameter slot is sent through GrounderProtocol; the backend receives a parsed Action."""
    slot = ParameterSlot(name="button_target", type="element", description="The button to tap")
    step = SkillStep(action_type="tap", target="button_target")
    shortcut = _make_shortcut(
        skill_id="sc-grounding",
        steps=(step,),
        parameter_slots=(slot,),
    )

    grounder = _StubGrounder(resolved_params_sequence=[{"action_type": "tap", "x": 300.0, "y": 400.0}])
    backend = _FakeBackend()
    # No condition evaluator — conditions always pass
    executor = ShortcutExecutor(
        backend=backend,
        grounder=grounder,
        screenshot_dir=tmp_path,
    )
    result = await executor.execute(shortcut)

    # Must succeed
    assert isinstance(result, ShortcutExecutionSuccess)
    assert result.is_violation is False

    # Grounder was called exactly once
    assert len(grounder.calls) == 1
    grounding_target, grounding_context = grounder.calls[0]

    # Context must carry the shortcut's parameter_slots tuple
    assert grounding_context.parameter_slots == shortcut.parameter_slots

    # Backend must have received a parsed Action, not a raw dict
    assert len(backend.executed_actions) == 1
    executed = backend.executed_actions[0]
    assert isinstance(executed, Action)
    assert executed.action_type == "tap"
    assert executed.x == 300.0
    assert executed.y == 400.0


# ---------------------------------------------------------------------------
# Test 4: Fixed steps bypass the grounder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shortcut_executor_uses_fixed_values_without_grounder(tmp_path: Path) -> None:
    """A fixed step uses fixed_values directly; the _NeverCalledGrounder proves the grounder is NOT called."""
    step = SkillStep(
        action_type="tap",
        target="hardcoded button",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 500, "y": 750},
    )
    shortcut = _make_shortcut(steps=(step,))

    grounder = _NeverCalledGrounder()
    backend = _FakeBackend()
    executor = ShortcutExecutor(
        backend=backend,
        grounder=grounder,
        screenshot_dir=tmp_path,
    )
    result = await executor.execute(shortcut)

    # Must succeed (no AssertionError from _NeverCalledGrounder)
    assert isinstance(result, ShortcutExecutionSuccess)
    assert result.is_violation is False

    # Backend received the action constructed from fixed_values
    assert len(backend.executed_actions) == 1
    executed = backend.executed_actions[0]
    assert isinstance(executed, Action)
    assert executed.action_type == "tap"
    assert executed.x == 500.0
    assert executed.y == 750.0


# ---------------------------------------------------------------------------
# Test 5: Package exports
# ---------------------------------------------------------------------------


def test_opengui_skills_exports_phase_25_shortcut_executor_types() -> None:
    """opengui.skills.__all__ includes all Phase 25 shortcut executor types alongside legacy exports."""
    import opengui.skills as skills_pkg

    exported = set(skills_pkg.__all__)

    # Phase 25 new types
    assert "ConditionEvaluator" in exported, "__all__ missing ConditionEvaluator"
    assert "ContractViolationReport" in exported, "__all__ missing ContractViolationReport"
    assert "ShortcutExecutionSuccess" in exported, "__all__ missing ShortcutExecutionSuccess"
    assert "ShortcutExecutor" in exported, "__all__ missing ShortcutExecutor"

    # Legacy types must remain intact
    assert "Skill" in exported, "Legacy Skill removed from __all__"
    assert "SkillStep" in exported, "Legacy SkillStep removed from __all__"
    assert "SkillExecutor" in exported, "Legacy SkillExecutor removed from __all__"
    assert "ShortcutSkill" in exported, "Phase 24 ShortcutSkill removed from __all__"
