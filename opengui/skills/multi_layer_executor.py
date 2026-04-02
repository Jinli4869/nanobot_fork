"""
opengui.skills.multi_layer_executor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Phase 25 two-layer executor with structured contract verification and pluggable
grounding.

Public symbols
--------------
ConditionEvaluator      — @runtime_checkable Protocol for pre/post condition checks
ContractViolationReport — frozen dataclass returned on the first failed condition
ShortcutStepResult      — per-step execution record in the success path
ShortcutExecutionSuccess — full success result holding all step records
ShortcutExecutor        — dataclass executor for ShortcutSkill objects
MissingShortcutReport   — frozen dataclass returned when a ShortcutRefNode cannot be
                           resolved and no contiguous inline fallback block exists
TaskExecutionSuccess    — full success result for TaskSkillExecutor execution
TaskSkillExecutor       — dataclass executor for TaskSkill objects

Design decisions (Phase 25)
----------------------------
* `ShortcutExecutor` is NOT an extension of the legacy `SkillExecutor`.  The
  legacy executor has fail-open validation and template-substitution fallback
  semantics that are incompatible with Phase 25 contract requirements.
* Every `SkillStep` that has `fixed=True` is normalized through `parse_action()`
  from `fixed_values` — the grounder is never called.
* Every `SkillStep` that is NOT fixed goes through `GrounderProtocol.ground()`.
  There is no template-substitution fallback.
* `ConditionEvaluator` is optional at construction.  When not supplied, all
  conditions silently pass, which enables dry-run and test scenarios without a
  live device or LLM.
* Literal `params` values passed into `execute()` are merged with the grounder's
  `resolved_params`, with caller-supplied values winning on key conflicts.
* `TaskSkillExecutor` delegates shortcut execution to the injected
  `ShortcutExecutor` and routes inline `SkillStep` nodes through the same shared
  `_execute_step` helper that `ShortcutExecutor` uses — ensuring EXEC-03: the
  grounding and action-normalisation path is identical for both.
* The locked same-node fallback rule: because `ShortcutRefNode` has no embedded
  ``fallback_steps`` field in the Phase 24 schema, the fallback block is derived
  structurally as the maximal contiguous run of `SkillStep` siblings immediately
  after the `ShortcutRefNode` in the enclosing tuple.  `BranchNode` siblings are
  never part of a fallback block.
"""

from __future__ import annotations

import logging
import tempfile
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from opengui.action import Action, parse_action
from opengui.grounding.protocol import GrounderProtocol, GroundingContext, GroundingResult
from opengui.interfaces import DeviceBackend
from opengui.skills.data import SkillStep
from opengui.skills.shortcut import ShortcutSkill, StateDescriptor
from opengui.skills.task_skill import BranchNode, ShortcutRefNode, TaskNode, TaskSkill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ConditionEvaluator protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ConditionEvaluator(Protocol):
    """Evaluate a single ``StateDescriptor`` condition against a screenshot.

    Called before each step (pre-conditions) and after each step
    (post-conditions).  Implementations may use a vision-LLM, a rule engine,
    or any other mechanism that maps a condition + screenshot to a bool.

    The signature is intentionally minimal — no backend or LLM dependency at
    the protocol level — so dry-run and test fakes remain trivial to construct.
    """

    async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool:
        """Return ``True`` if the current screen satisfies *condition*."""
        ...


# ---------------------------------------------------------------------------
# Result / report dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractViolationReport:
    """Returned by ``ShortcutExecutor.execute()`` on the first failed condition.

    Carries enough information for a caller to understand *which* condition
    failed, *when* it failed (before or after a step), and *at which step index*.

    The ``is_violation`` discriminator field lets callers pattern-match cleanly::

        result = await executor.execute(shortcut)
        if result.is_violation:
            # ContractViolationReport
            log(result.failed_condition)
        else:
            # ShortcutExecutionSuccess
            for step in result.step_results: ...
    """

    skill_id: str
    step_index: int
    failed_condition: StateDescriptor
    boundary: Literal["pre", "post"]
    is_violation: Literal[True] = True


@dataclass(frozen=True)
class ShortcutStepResult:
    """Per-step execution record within a successful shortcut execution.

    ``screenshot_path`` is the path of the screenshot taken *before* the step
    so that post-execution analysis can correlate grounding with visual state.
    """

    step_index: int
    action: Action
    backend_result: str
    grounding: GroundingResult | None
    screenshot_path: str


@dataclass(frozen=True)
class ShortcutExecutionSuccess:
    """Returned by ``ShortcutExecutor.execute()`` when all steps and conditions pass.

    The ``is_violation`` discriminator is always ``False`` here; see
    ``ContractViolationReport`` for the mirror case.
    """

    skill_id: str
    step_results: tuple[ShortcutStepResult, ...]
    is_violation: Literal[False] = False


# ---------------------------------------------------------------------------
# Private always-pass evaluator (used when caller does not inject one)
# ---------------------------------------------------------------------------


class _AlwaysPassEvaluator:
    """No-op ConditionEvaluator: every condition passes unconditionally."""

    async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool:
        return True


# ---------------------------------------------------------------------------
# ShortcutExecutor
# ---------------------------------------------------------------------------


@dataclass
class ShortcutExecutor:
    """Execute a :class:`~opengui.skills.shortcut.ShortcutSkill` with
    per-step pre/post contract verification and pluggable grounding.

    Parameters
    ----------
    backend:
        Device backend for screen observation and action execution.
    grounder:
        Grounding protocol implementation used to resolve unbound parameter
        slots into concrete action parameters.
    condition_evaluator:
        Optional protocol implementation for evaluating ``StateDescriptor``
        conditions.  When ``None``, all conditions pass (always-pass default).
    screenshot_dir:
        Root directory for screenshots captured during execution.  Defaults to
        ``<tempdir>/opengui-skill-execution``.  Callers may pass ``tmp_path``
        in tests for deterministic isolation.
    """

    backend: DeviceBackend
    grounder: GrounderProtocol
    condition_evaluator: ConditionEvaluator | None = None
    screenshot_dir: Path = field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "opengui-skill-execution"
    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        shortcut: ShortcutSkill,
        params: dict[str, str] | None = None,
        *,
        timeout: float = 5.0,
    ) -> ShortcutExecutionSuccess | ContractViolationReport:
        """Execute *shortcut* step-by-step with contract verification.

        For each step:
        1. Capture current screenshot.
        2. Evaluate every precondition; abort with :class:`ContractViolationReport`
           on the first failure (``boundary="pre"``).
        3. Execute the step (grounded or fixed).
        4. Evaluate every postcondition; abort with :class:`ContractViolationReport`
           on the first failure (``boundary="post"``).

        Parameters
        ----------
        shortcut:
            The :class:`~opengui.skills.shortcut.ShortcutSkill` to execute.
        params:
            Caller-supplied literal parameter bindings.  These are merged with
            grounder-returned ``resolved_params``; caller values win on conflict.
        timeout:
            Per-operation timeout passed to ``DeviceBackend`` calls.

        Returns
        -------
        :class:`ShortcutExecutionSuccess` or :class:`ContractViolationReport`
        """
        params = params or {}
        evaluator: ConditionEvaluator = self.condition_evaluator or _AlwaysPassEvaluator()
        step_results: list[ShortcutStepResult] = []

        for step_index, step in enumerate(shortcut.steps):
            # 1. Capture screenshot before execution (used for pre-check and grounding)
            pre_screenshot_path = self._screenshot_path(shortcut.skill_id, step_index, "pre")
            observation = await self.backend.observe(pre_screenshot_path, timeout=timeout)

            # 2. Check preconditions
            for condition in shortcut.preconditions:
                if not await evaluator.evaluate(condition, pre_screenshot_path):
                    logger.info(
                        "Shortcut %r step %d: precondition failed: %r",
                        shortcut.skill_id,
                        step_index,
                        condition,
                    )
                    return ContractViolationReport(
                        skill_id=shortcut.skill_id,
                        step_index=step_index,
                        failed_condition=condition,
                        boundary="pre",
                    )

            # 3. Execute step
            action, grounding = await self._execute_step(
                step=step,
                shortcut=shortcut,
                params=params,
                screenshot_path=pre_screenshot_path,
                observation=observation,
                timeout=timeout,
            )
            backend_result = await self.backend.execute(action, timeout=timeout)

            step_result = ShortcutStepResult(
                step_index=step_index,
                action=action,
                backend_result=backend_result,
                grounding=grounding,
                screenshot_path=str(pre_screenshot_path),
            )
            step_results.append(step_result)

            # 4. Check postconditions
            post_screenshot_path = self._screenshot_path(shortcut.skill_id, step_index, "post")
            await self.backend.observe(post_screenshot_path, timeout=timeout)

            for condition in shortcut.postconditions:
                if not await evaluator.evaluate(condition, post_screenshot_path):
                    logger.info(
                        "Shortcut %r step %d: postcondition failed: %r",
                        shortcut.skill_id,
                        step_index,
                        condition,
                    )
                    return ContractViolationReport(
                        skill_id=shortcut.skill_id,
                        step_index=step_index,
                        failed_condition=condition,
                        boundary="post",
                    )

        return ShortcutExecutionSuccess(
            skill_id=shortcut.skill_id,
            step_results=tuple(step_results),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _screenshot_path(self, skill_id: str, step_index: int, boundary: str) -> Path:
        """Build a deterministic screenshot path for a step boundary."""
        filename = f"{skill_id}-step-{step_index:03d}-{boundary}.png"
        return self.screenshot_dir / filename

    async def _execute_step(
        self,
        *,
        step: SkillStep,
        shortcut: ShortcutSkill,
        params: dict[str, str],
        screenshot_path: Path,
        observation: Any,
        timeout: float,
    ) -> tuple[Action, GroundingResult | None]:
        """Build and return a concrete (Action, grounding) pair for *step*.

        Fixed steps bypass the grounder entirely; their ``fixed_values`` are
        normalized through ``parse_action()`` so action validation stays
        centralized.  Non-fixed steps are grounded via ``GrounderProtocol`` and
        then also normalized through ``parse_action()``.
        """
        if step.fixed:
            # Fixed step: use fixed_values directly (no grounder call)
            payload: dict[str, Any] = {"action_type": step.action_type, **step.fixed_values}
            action = parse_action(payload)
            return action, None

        # Non-fixed step: route through GrounderProtocol
        context = GroundingContext(
            screenshot_path=screenshot_path,
            observation=observation,
            parameter_slots=shortcut.parameter_slots,
            task_hint=shortcut.description,
        )
        grounding = await self.grounder.ground(step.target, context)

        # Merge: caller-supplied literal params win over grounder-returned params
        merged: dict[str, Any] = {"action_type": step.action_type, **grounding.resolved_params}
        for key, value in params.items():
            merged[key] = value

        action = parse_action(merged)
        return action, grounding


# ---------------------------------------------------------------------------
# Task-layer result / report dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MissingShortcutReport:
    """Returned by ``TaskSkillExecutor.execute()`` when a ``ShortcutRefNode`` cannot
    be resolved **and** no contiguous inline fallback block exists at that position.

    ``fallback_block_length`` encodes the length of the fallback block that was
    structurally scanned; when it is ``0`` the next sibling was not a ``SkillStep``
    (or the ``ShortcutRefNode`` was the last node in the tuple).

    The ``is_missing_shortcut`` discriminator field lets callers pattern-match::

        result = await executor.execute(task)
        if result.is_missing_shortcut:
            # MissingShortcutReport — handle gracefully
            ...
    """

    task_skill_id: str
    shortcut_id: str
    node_index: int
    fallback_block_length: int
    is_missing_shortcut: Literal[True] = True


@dataclass(frozen=True)
class TaskExecutionSuccess:
    """Returned by ``TaskSkillExecutor.execute()`` when the task skill completes
    without contract violations or unresolvable shortcuts.

    ``step_results`` accumulates every ``ShortcutStepResult`` generated during the
    run, both from resolved shortcut delegation and from inline atom execution.
    ``executed_shortcut_ids`` lists shortcut IDs in execution order.
    ``branch_trace`` records the boolean outcome of each ``BranchNode`` evaluation.
    """

    task_skill_id: str
    step_results: tuple[ShortcutStepResult, ...]
    executed_shortcut_ids: tuple[str, ...]
    branch_trace: tuple[bool, ...]
    is_violation: Literal[False] = False
    is_missing_shortcut: Literal[False] = False


# ---------------------------------------------------------------------------
# TaskSkillExecutor
# ---------------------------------------------------------------------------


@dataclass
class TaskSkillExecutor:
    """Execute a :class:`~opengui.skills.task_skill.TaskSkill` by walking its
    node sequence and applying the locked same-node fallback rule for missing
    shortcuts.

    Parameters
    ----------
    shortcut_executor:
        A fully configured :class:`ShortcutExecutor` used for both resolved-
        shortcut delegation and inline ``SkillStep`` execution (EXEC-03 shared
        grounding seam).
    shortcut_resolver:
        Callable that maps a shortcut_id string to a :class:`ShortcutSkill`
        instance, or ``None`` when the shortcut is not found.
    condition_evaluator:
        Optional :class:`ConditionEvaluator` used to evaluate ``BranchNode``
        conditions.  When ``None``, all branch conditions evaluate to ``True``
        (always-pass default), which enables dry-run and test scenarios.

    Traversal rules
    ---------------
    For each node in ``TaskSkill.steps`` (index ``i``):

    * **ShortcutRefNode**:
        1. Measure the contiguous fallback block: the maximal run of ``SkillStep``
           siblings at positions ``i+1, i+2, …`` that are all ``SkillStep`` instances
           (stop at the first non-``SkillStep`` sibling or end of tuple).
        2. Attempt ``shortcut_resolver(node.shortcut_id)``.
        3. If resolved: delegate to ``shortcut_executor`` with ``node.param_bindings``;
           advance the cursor past the entire fallback block (skip those siblings).
        4. If missing and ``fallback_block_length > 0``: execute fallback steps
           in-order through the shared step runner; advance past all of them.
        5. If missing and ``fallback_block_length == 0``: return
           ``MissingShortcutReport`` immediately.

    * **SkillStep** (inline atom at top level):
        Route through the shared ``_execute_step`` helper on the injected
        ``shortcut_executor`` using an anonymous ``ShortcutSkill`` context.

    * **BranchNode**:
        Evaluate ``node.condition`` via the ``condition_evaluator``; execute only the
        selected branch subtree recursively; append the boolean to ``branch_trace``.
    """

    shortcut_executor: ShortcutExecutor
    shortcut_resolver: Callable[[str], ShortcutSkill | None]
    condition_evaluator: ConditionEvaluator | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        task_skill: TaskSkill,
        *,
        timeout: float = 5.0,
    ) -> TaskExecutionSuccess | ContractViolationReport | MissingShortcutReport:
        """Execute *task_skill* by traversing its node sequence.

        Returns
        -------
        :class:`TaskExecutionSuccess`
            All nodes completed without error.
        :class:`ContractViolationReport`
            A resolved shortcut failed a pre- or post-condition check.
        :class:`MissingShortcutReport`
            A shortcut could not be resolved and no contiguous inline fallback
            block was available at that position.
        """
        all_step_results: list[ShortcutStepResult] = []
        executed_shortcut_ids: list[str] = []
        branch_trace: list[bool] = []

        outcome = await self._walk_nodes(
            nodes=task_skill.steps,
            task_skill=task_skill,
            all_step_results=all_step_results,
            executed_shortcut_ids=executed_shortcut_ids,
            branch_trace=branch_trace,
            timeout=timeout,
        )
        if outcome is not None:
            # A ContractViolationReport or MissingShortcutReport was returned
            return outcome

        return TaskExecutionSuccess(
            task_skill_id=task_skill.skill_id,
            step_results=tuple(all_step_results),
            executed_shortcut_ids=tuple(executed_shortcut_ids),
            branch_trace=tuple(branch_trace),
        )

    # ------------------------------------------------------------------
    # Private traversal helpers
    # ------------------------------------------------------------------

    async def _walk_nodes(
        self,
        nodes: tuple[TaskNode, ...],
        *,
        task_skill: TaskSkill,
        all_step_results: list[ShortcutStepResult],
        executed_shortcut_ids: list[str],
        branch_trace: list[bool],
        timeout: float,
    ) -> ContractViolationReport | MissingShortcutReport | None:
        """Walk *nodes* in order, applying all traversal rules.

        Returns ``None`` on success, or the first early-exit report.
        """
        evaluator: ConditionEvaluator = (
            self.condition_evaluator or _AlwaysPassEvaluator()
        )
        index = 0
        while index < len(nodes):
            node = nodes[index]

            if isinstance(node, ShortcutRefNode):
                # Measure contiguous fallback block before resolution attempt
                fallback_start = index + 1
                fallback_end = fallback_start
                while fallback_end < len(nodes) and isinstance(nodes[fallback_end], SkillStep):
                    fallback_end += 1
                fallback_block: tuple[SkillStep, ...] = tuple(
                    nodes[fallback_start:fallback_end]  # type: ignore[misc]
                )
                fallback_block_length = len(fallback_block)

                resolved_shortcut = self.shortcut_resolver(node.shortcut_id)

                if resolved_shortcut is not None:
                    # Execute the resolved shortcut and skip the fallback block
                    shortcut_result = await self.shortcut_executor.execute(
                        resolved_shortcut,
                        params=dict(node.param_bindings),
                        timeout=timeout,
                    )
                    if isinstance(shortcut_result, ContractViolationReport):
                        return shortcut_result
                    all_step_results.extend(shortcut_result.step_results)
                    executed_shortcut_ids.append(node.shortcut_id)
                    # Advance past shortcut ref node AND its fallback block
                    index = fallback_end
                else:
                    # Shortcut missing
                    if fallback_block_length == 0:
                        # No contiguous inline fallback available
                        return MissingShortcutReport(
                            task_skill_id=task_skill.skill_id,
                            shortcut_id=node.shortcut_id,
                            node_index=index,
                            fallback_block_length=0,
                        )
                    # Execute fallback block inline through the shared step runner
                    for fallback_step in fallback_block:
                        step_result = await self._run_inline_step(
                            step=fallback_step,
                            task_skill=task_skill,
                            timeout=timeout,
                        )
                        all_step_results.append(step_result)
                    # Advance past shortcut ref node AND the consumed fallback block
                    index = fallback_end

            elif isinstance(node, SkillStep):
                # Top-level inline atom: run through shared step runner
                step_result = await self._run_inline_step(
                    step=node,
                    task_skill=task_skill,
                    timeout=timeout,
                )
                all_step_results.append(step_result)
                index += 1

            elif isinstance(node, BranchNode):
                # Evaluate condition; execute selected branch subtree
                branch_screenshot = self.shortcut_executor._screenshot_path(
                    task_skill.skill_id, index, "branch"
                )
                await self.shortcut_executor.backend.observe(
                    branch_screenshot, timeout=timeout
                )
                condition_result = await evaluator.evaluate(
                    node.condition, branch_screenshot
                )
                branch_trace.append(condition_result)

                branch_subtree = node.then_steps if condition_result else node.else_steps
                sub_outcome = await self._walk_nodes(
                    nodes=branch_subtree,
                    task_skill=task_skill,
                    all_step_results=all_step_results,
                    executed_shortcut_ids=executed_shortcut_ids,
                    branch_trace=branch_trace,
                    timeout=timeout,
                )
                if sub_outcome is not None:
                    return sub_outcome
                index += 1

            else:
                logger.warning(
                    "TaskSkillExecutor: unknown node type %r at index %d — skipping",
                    type(node).__name__,
                    index,
                )
                index += 1

        return None

    async def _run_inline_step(
        self,
        *,
        step: SkillStep,
        task_skill: TaskSkill,
        timeout: float,
    ) -> ShortcutStepResult:
        """Execute a single inline ``SkillStep`` through the shared step runner.

        Constructs a minimal ``ShortcutSkill`` context so the shared
        ``_execute_step`` helper on the injected ``ShortcutExecutor`` can resolve
        grounding metadata, then executes the resulting action via the backend.
        The step index used for the screenshot path is derived from the current
        total step count accumulated so far (caller responsibility for ordering).
        """
        # Build a minimal ShortcutSkill so _execute_step has its required context.
        # parameter_slots is empty — inline atoms don't carry slot definitions.
        inline_context = ShortcutSkill(
            skill_id=task_skill.skill_id,
            name=task_skill.name,
            description=task_skill.description,
            app=task_skill.app,
            platform=task_skill.platform,
            steps=(step,),
        )
        # Use a pseudo-index based on current time to generate a unique screenshot path.
        # The exact index value is not semantically load-bearing here; uniqueness is.
        import time as _time
        pseudo_index = int(_time.monotonic() * 1000) % 100000
        pre_screenshot_path = self.shortcut_executor._screenshot_path(
            task_skill.skill_id, pseudo_index, "inline"
        )
        observation = await self.shortcut_executor.backend.observe(
            pre_screenshot_path, timeout=timeout
        )

        action, grounding = await self.shortcut_executor._execute_step(
            step=step,
            shortcut=inline_context,
            params={},
            screenshot_path=pre_screenshot_path,
            observation=observation,
            timeout=timeout,
        )
        backend_result = await self.shortcut_executor.backend.execute(
            action, timeout=timeout
        )
        return ShortcutStepResult(
            step_index=pseudo_index,
            action=action,
            backend_result=backend_result,
            grounding=grounding,
            screenshot_path=str(pre_screenshot_path),
        )


__all__ = [
    "ConditionEvaluator",
    "ContractViolationReport",
    "MissingShortcutReport",
    "ShortcutExecutionSuccess",
    "ShortcutStepResult",
    "ShortcutExecutor",
    "TaskExecutionSuccess",
    "TaskSkillExecutor",
]
