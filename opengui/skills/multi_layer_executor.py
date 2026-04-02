"""
opengui.skills.multi_layer_executor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Phase 25 shortcut-layer executor with structured contract verification and
pluggable grounding.

Public symbols
--------------
ConditionEvaluator     — @runtime_checkable Protocol for pre/post condition checks
ContractViolationReport — frozen dataclass returned on the first failed condition
ShortcutStepResult     — per-step execution record in the success path
ShortcutExecutionSuccess — full success result holding all step records
ShortcutExecutor       — dataclass executor for ShortcutSkill objects

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
"""

from __future__ import annotations

import logging
import tempfile
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from opengui.action import Action, parse_action
from opengui.grounding.protocol import GrounderProtocol, GroundingContext, GroundingResult
from opengui.interfaces import DeviceBackend
from opengui.skills.data import SkillStep
from opengui.skills.shortcut import ShortcutSkill, StateDescriptor

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


__all__ = [
    "ConditionEvaluator",
    "ContractViolationReport",
    "ShortcutExecutionSuccess",
    "ShortcutStepResult",
    "ShortcutExecutor",
]
