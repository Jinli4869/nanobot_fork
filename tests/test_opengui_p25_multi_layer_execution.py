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


# ===========================================================================
# Phase 25 Wave 2 — Task-layer execution tests
# ===========================================================================
#
# These tests cover TaskSkillExecutor traversal semantics:
#   - Resolved shortcut: execute the shortcut and skip the contiguous inline
#     fallback block represented by contiguous SkillStep siblings after it.
#   - Missing shortcut with contiguous inline fallback: execute the fallback
#     steps through the same grounder path (EXEC-03 grounding seam).
#   - Missing shortcut without contiguous inline fallback: return
#     MissingShortcutReport with fallback_block_length=0.
#   - BranchNode evaluation through ConditionEvaluator.
#   - Top-level inline SkillStep routed through the shared grounder.
#   - Package exports for task-layer types.
#
# All tests import task-layer symbols lazily (inside function body) so that
# TDD RED phase failures are isolated to individual tests, not collection.


def _make_task_skill(
    *,
    skill_id: str = "ts-test",
    steps: tuple,  # type: ignore[type-arg]
) -> "TaskSkill":  # noqa: F821
    """Helper factory: construct a TaskSkill with the given node tuple."""
    from opengui.skills.task_skill import TaskSkill

    return TaskSkill(
        skill_id=skill_id,
        name="Test TaskSkill",
        description="A task skill for testing",
        app="com.example.app",
        platform="android",
        steps=steps,
    )


def _make_task_executor(
    backend: _FakeBackend,
    grounder: "_StubGrounder",
    *,
    resolver,  # type: ignore[type-arg]
    condition_evaluator=None,
    tmp_path: Path,
) -> "TaskSkillExecutor":  # noqa: F821
    """Helper factory: construct a TaskSkillExecutor with the given collaborators."""
    from opengui.skills.multi_layer_executor import TaskSkillExecutor

    shortcut_executor = ShortcutExecutor(
        backend=backend,
        grounder=grounder,
        condition_evaluator=condition_evaluator,
        screenshot_dir=tmp_path,
    )
    return TaskSkillExecutor(
        shortcut_executor=shortcut_executor,
        shortcut_resolver=resolver,
        condition_evaluator=condition_evaluator,
    )


# ---------------------------------------------------------------------------
# Test 6: Resolved shortcut skips the contiguous inline fallback block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_skill_executor_skips_contiguous_atom_fallback_when_shortcut_resolves(
    tmp_path: Path,
) -> None:
    """Resolved ShortcutRefNode executes the shortcut and skips the contiguous inline fallback
    SkillStep siblings that structurally represent the locked same-node fallback block."""
    from opengui.skills.multi_layer_executor import MissingShortcutReport, TaskExecutionSuccess, TaskSkillExecutor
    from opengui.skills.task_skill import ShortcutRefNode, TaskSkill

    # The shortcut that the resolver will return
    tap_step = SkillStep(
        action_type="tap",
        target="resolved_button",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 10.0, "y": 20.0},
    )
    resolved_shortcut = _make_shortcut(
        skill_id="resolved-sc",
        steps=(tap_step,),
    )

    # Contiguous inline fallback: these are the SkillStep siblings immediately after the
    # ShortcutRefNode — they represent the locked same-node fallback in the current schema.
    fallback_step_1 = SkillStep(
        action_type="tap",
        target="fallback_step_1",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 99.0, "y": 99.0},
    )
    fallback_step_2 = SkillStep(
        action_type="tap",
        target="fallback_step_2",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 98.0, "y": 98.0},
    )

    # Build task: [ShortcutRefNode → fallback_step_1 → fallback_step_2]
    ref_node = ShortcutRefNode(shortcut_id="resolved-sc", param_bindings={})
    task_skill = _make_task_skill(
        skill_id="ts-skip-fallback",
        steps=(ref_node, fallback_step_1, fallback_step_2),
    )

    backend = _FakeBackend()
    grounder = _NeverCalledGrounder()  # fallback steps must not be executed

    def resolver(shortcut_id: str):
        if shortcut_id == "resolved-sc":
            return resolved_shortcut
        return None

    executor = _make_task_executor(
        backend, grounder, resolver=resolver, tmp_path=tmp_path
    )
    result = await executor.execute(task_skill)

    assert isinstance(result, TaskExecutionSuccess)
    assert result.is_missing_shortcut is False
    assert result.is_violation is False
    assert result.task_skill_id == "ts-skip-fallback"
    # The resolved shortcut's step was executed; fallback steps were skipped
    assert "resolved-sc" in result.executed_shortcut_ids
    # Only 1 action executed (the shortcut's tap), not the 2 fallback taps
    assert len(backend.executed_actions) == 1
    assert backend.executed_actions[0].x == 10.0


# ---------------------------------------------------------------------------
# Test 7: Missing shortcut executes the contiguous inline fallback block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_skill_executor_runs_contiguous_atom_fallback_when_shortcut_missing(
    tmp_path: Path,
) -> None:
    """Unresolved ShortcutRefNode executes the contiguous inline fallback SkillStep
    siblings in order through the shared grounding seam (EXEC-03 grounding seam shared
    with ShortcutExecutor). The run continues past the fallback block to subsequent nodes."""
    from opengui.skills.multi_layer_executor import MissingShortcutReport, TaskExecutionSuccess, TaskSkillExecutor
    from opengui.skills.task_skill import ShortcutRefNode, TaskSkill

    # Contiguous inline fallback steps immediately after the ShortcutRefNode
    fallback_step_a = SkillStep(
        action_type="tap",
        target="fallback_a",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 11.0, "y": 22.0},
    )
    fallback_step_b = SkillStep(
        action_type="tap",
        target="fallback_b",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 33.0, "y": 44.0},
    )

    # Build task: [ShortcutRefNode(missing) → fallback_step_a → fallback_step_b]
    ref_node = ShortcutRefNode(shortcut_id="missing-sc", param_bindings={})
    task_skill = _make_task_skill(
        skill_id="ts-run-fallback",
        steps=(ref_node, fallback_step_a, fallback_step_b),
    )

    backend = _FakeBackend()
    grounder = _NeverCalledGrounder()  # fallback steps are fixed, no grounder needed

    def resolver(shortcut_id: str):
        return None  # always missing

    executor = _make_task_executor(
        backend, grounder, resolver=resolver, tmp_path=tmp_path
    )
    result = await executor.execute(task_skill)

    # Must succeed using the fallback; this is NOT a MissingShortcutReport
    assert isinstance(result, TaskExecutionSuccess), (
        f"Expected TaskExecutionSuccess but got {type(result).__name__}"
    )
    assert result.is_missing_shortcut is False
    assert result.task_skill_id == "ts-run-fallback"
    # Both contiguous inline fallback steps were executed
    assert len(backend.executed_actions) == 2
    assert backend.executed_actions[0].x == 11.0
    assert backend.executed_actions[1].x == 33.0


# ---------------------------------------------------------------------------
# Test 8: Missing shortcut without contiguous inline fallback → MissingShortcutReport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_skill_executor_returns_missing_shortcut_report_without_contiguous_atom_fallback(
    tmp_path: Path,
) -> None:
    """Unresolved ShortcutRefNode with no contiguous SkillStep siblings returns
    MissingShortcutReport with fallback_block_length=0 immediately."""
    from opengui.skills.multi_layer_executor import MissingShortcutReport, TaskExecutionSuccess, TaskSkillExecutor
    from opengui.skills.task_skill import BranchNode, ShortcutRefNode, TaskSkill

    # BranchNode is NOT part of a contiguous inline fallback block
    branch_node = BranchNode(
        condition=StateDescriptor(kind="app_open", value="com.example.app"),
        then_steps=(),
        else_steps=(),
    )

    # Build task: [ShortcutRefNode(missing) → BranchNode]
    # Since the next sibling is a BranchNode (not a SkillStep), fallback_block_length=0
    ref_node = ShortcutRefNode(shortcut_id="also-missing-sc", param_bindings={})
    task_skill = _make_task_skill(
        skill_id="ts-no-fallback",
        steps=(ref_node, branch_node),
    )

    backend = _FakeBackend()
    grounder = _NeverCalledGrounder()

    def resolver(shortcut_id: str):
        return None

    executor = _make_task_executor(
        backend, grounder, resolver=resolver, tmp_path=tmp_path
    )
    result = await executor.execute(task_skill)

    assert isinstance(result, MissingShortcutReport)
    assert result.is_missing_shortcut is True
    assert result.task_skill_id == "ts-no-fallback"
    assert result.shortcut_id == "also-missing-sc"
    assert result.node_index == 0
    assert result.fallback_block_length == 0
    # No backend actions should have run
    assert backend.executed_actions == []


# ---------------------------------------------------------------------------
# Test 9: BranchNode evaluates condition and routes to the correct branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_skill_executor_evaluates_branch_condition(tmp_path: Path) -> None:
    """BranchNode.condition is evaluated through ConditionEvaluator; then_steps run
    when the condition is True and else_steps run when False."""
    from opengui.skills.multi_layer_executor import MissingShortcutReport, TaskExecutionSuccess, TaskSkillExecutor
    from opengui.skills.task_skill import BranchNode, ShortcutRefNode, TaskSkill

    then_step = SkillStep(
        action_type="tap",
        target="then_button",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 1.0, "y": 1.0},
    )
    else_step = SkillStep(
        action_type="tap",
        target="else_button",
        fixed=True,
        fixed_values={"action_type": "tap", "x": 2.0, "y": 2.0},
    )

    branch_condition = StateDescriptor(kind="screen_visible", value="confirm_dialog")

    # --- Case A: condition evaluates True → then_steps runs ---
    branch_node = BranchNode(
        condition=branch_condition,
        then_steps=(then_step,),
        else_steps=(else_step,),
    )
    task_skill_true = _make_task_skill(
        skill_id="ts-branch-true",
        steps=(branch_node,),
    )

    backend_true = _FakeBackend()
    grounder_true = _NeverCalledGrounder()
    # Condition evaluates True
    evaluator_true = _SequenceConditionEvaluator(results=[True])

    executor_true = _make_task_executor(
        backend_true,
        grounder_true,
        resolver=lambda _: None,
        condition_evaluator=evaluator_true,
        tmp_path=tmp_path,
    )
    result_true = await executor_true.execute(task_skill_true)

    assert isinstance(result_true, TaskExecutionSuccess)
    assert result_true.branch_trace == (True,)
    assert len(backend_true.executed_actions) == 1
    assert backend_true.executed_actions[0].x == 1.0  # then_step ran

    # --- Case B: condition evaluates False → else_steps runs ---
    task_skill_false = _make_task_skill(
        skill_id="ts-branch-false",
        steps=(branch_node,),
    )

    backend_false = _FakeBackend()
    grounder_false = _NeverCalledGrounder()
    evaluator_false = _SequenceConditionEvaluator(results=[False])

    executor_false = _make_task_executor(
        backend_false,
        grounder_false,
        resolver=lambda _: None,
        condition_evaluator=evaluator_false,
        tmp_path=tmp_path,
    )
    result_false = await executor_false.execute(task_skill_false)

    assert isinstance(result_false, TaskExecutionSuccess)
    assert result_false.branch_trace == (False,)
    assert len(backend_false.executed_actions) == 1
    assert backend_false.executed_actions[0].x == 2.0  # else_step ran


# ---------------------------------------------------------------------------
# Test 10: Top-level inline SkillStep routes through the shared grounder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_skill_executor_routes_top_level_atom_through_grounder(
    tmp_path: Path,
) -> None:
    """A top-level SkillStep node in a TaskSkill uses the same grounder path as
    ShortcutExecutor — proving EXEC-03: inline ATOM execution and resolved shortcut
    execution share the same grounding and action-normalization path."""
    from opengui.skills.multi_layer_executor import MissingShortcutReport, TaskExecutionSuccess, TaskSkillExecutor
    from opengui.skills.task_skill import TaskSkill

    # Non-fixed step: must go through the grounder
    atom_step = SkillStep(action_type="tap", target="some_button")
    task_skill = _make_task_skill(
        skill_id="ts-top-atom",
        steps=(atom_step,),
    )

    backend = _FakeBackend()
    grounder = _StubGrounder(
        resolved_params_sequence=[{"action_type": "tap", "x": 77.0, "y": 88.0}]
    )

    executor = _make_task_executor(
        backend, grounder, resolver=lambda _: None, tmp_path=tmp_path
    )
    result = await executor.execute(task_skill)

    assert isinstance(result, TaskExecutionSuccess)
    assert result.is_violation is False
    # Grounder was called exactly once for the inline atom
    assert len(grounder.calls) == 1
    # Backend received the grounder-resolved Action
    assert len(backend.executed_actions) == 1
    assert backend.executed_actions[0].x == 77.0
    assert backend.executed_actions[0].y == 88.0


# ---------------------------------------------------------------------------
# Test 11: Package exports include task-layer types
# ---------------------------------------------------------------------------


def test_opengui_skills_exports_phase_25_task_executor_types() -> None:
    """opengui.skills.__all__ includes MissingShortcutReport, TaskExecutionSuccess,
    and TaskSkillExecutor alongside all previously exported types."""
    import opengui.skills as skills_pkg

    exported = set(skills_pkg.__all__)

    # Phase 25 Wave 2 new task-layer types
    assert "MissingShortcutReport" in exported, "__all__ missing MissingShortcutReport"
    assert "TaskExecutionSuccess" in exported, "__all__ missing TaskExecutionSuccess"
    assert "TaskSkillExecutor" in exported, "__all__ missing TaskSkillExecutor"

    # Wave 1 shortcut-layer types must remain intact
    assert "ConditionEvaluator" in exported, "__all__ missing ConditionEvaluator"
    assert "ContractViolationReport" in exported, "__all__ missing ContractViolationReport"
    assert "ShortcutExecutionSuccess" in exported, "__all__ missing ShortcutExecutionSuccess"
    assert "ShortcutExecutor" in exported, "__all__ missing ShortcutExecutor"
