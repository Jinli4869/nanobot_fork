"""
opengui.skills.executor
~~~~~~~~~~~~~~~~~~~~~~
Step-by-step skill execution with parameter grounding and per-step
valid-state verification.

Execution pipeline per step:
1. Verify ``valid_state`` against current screenshot (LLM-based)
2. Ground ``{{param}}`` placeholders with actual values
3. Execute action via DeviceBackend
4. Record step result

Supports optional steps (graceful degradation) and pre/postconditions.
"""

from __future__ import annotations

import logging
import re
import typing
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from opengui.action import Action
from opengui.interfaces import DeviceBackend
from opengui.skills.data import Skill, SkillStep

if typing.TYPE_CHECKING:
    from opengui.interfaces import LLMProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Execution state
# ---------------------------------------------------------------------------

class ExecutionState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Outcome of a single skill step."""

    step_index: int
    action: Action
    backend_result: str
    state: ExecutionState
    valid_state_check: bool = True
    error: str | None = None


@dataclass
class SkillExecutionResult:
    """Outcome of a full skill execution."""

    skill: Skill
    step_results: list[StepResult]
    state: ExecutionState
    error: str | None = None


# ---------------------------------------------------------------------------
# State validator protocol
# ---------------------------------------------------------------------------

@typing.runtime_checkable
class StateValidator(typing.Protocol):
    """Validates current screen state against a ``valid_state`` description.

    Implementations typically use a vision LLM to compare the screenshot
    with the expected state text.
    """

    async def validate(
        self,
        valid_state: str,
        screenshot: Path | bytes | None = None,
    ) -> bool:
        """Return True if the current screen matches *valid_state*."""
        ...


# ---------------------------------------------------------------------------
# LLM-based state validator
# ---------------------------------------------------------------------------

_VALIDATION_PROMPT = """\
Look at this screenshot and answer: does the current screen state match \
the following description?

Expected state: {valid_state}

Respond with ONLY a JSON object: {{"valid": true/false, "reason": "one-line"}}
"""


class LLMStateValidator:
    """Validate screen state using a vision LLM."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def validate(
        self,
        valid_state: str,
        screenshot: Path | bytes | None = None,
    ) -> bool:
        if _should_skip_validation(valid_state):
            return True

        if screenshot is None:
            logger.warning("No screenshot for state validation; allowing execution")
            return True

        prompt = _VALIDATION_PROMPT.format(valid_state=valid_state)

        # Build multimodal message
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if isinstance(screenshot, Path):
            import base64
            image_data = base64.b64encode(screenshot.read_bytes()).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_data}"},
            })
        elif isinstance(screenshot, bytes):
            import base64
            image_data = base64.b64encode(screenshot).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_data}"},
            })

        messages = [{"role": "user", "content": content}]
        try:
            response = await self._llm.chat(messages)
        except Exception as exc:
            logger.error("State validation LLM call failed: %s", exc)
            return True  # Fail-open on LLM error

        return self._parse_response(response.content)

    @staticmethod
    def _parse_response(text: str) -> bool:
        import json as _json
        text = text.strip()
        # Try JSON parse
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                obj = _json.loads(match.group(0))
                valid = obj.get("valid", obj.get("is_valid", obj.get("match")))
                if isinstance(valid, bool):
                    return valid
                if isinstance(valid, str):
                    return valid.strip().lower() in ("true", "yes", "matched")
            except _json.JSONDecodeError:
                pass
        # Fallback: look for yes/no
        lowered = text.lower()
        if "true" in lowered or "yes" in lowered or "match" in lowered:
            return True
        return False


def _should_skip_validation(valid_state: str | None) -> bool:
    """Check if valid_state indicates no verification is needed."""
    if not valid_state:
        return True
    lowered = valid_state.strip().lower()
    skip_hints = ("no need to verify", "return true", "skip", "none", "n/a")
    return any(hint in lowered for hint in skip_hints)


# ---------------------------------------------------------------------------
# Parameter grounding
# ---------------------------------------------------------------------------

def _ground_text(text: str, params: dict[str, str]) -> str:
    """Replace ``{{param}}`` placeholders with actual values."""
    for key, value in params.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    remaining = re.findall(r"\{\{(\w+)\}\}", text)
    if remaining:
        logger.warning("Unresolved placeholders: %s", remaining)
    return text


def _ground_step(step: SkillStep, params: dict[str, str]) -> dict[str, Any]:
    """Ground a step's target and parameters into Action kwargs."""
    target = _ground_text(step.target, params)
    grounded: dict[str, Any] = {}
    for k, v in step.parameters.items():
        grounded[k] = _ground_text(str(v), params) if isinstance(v, str) else v

    kwargs: dict[str, Any] = {"action_type": step.action_type}

    if "x" in grounded:
        kwargs["x"] = float(grounded["x"])
    if "y" in grounded:
        kwargs["y"] = float(grounded["y"])
    if "text" in grounded:
        kwargs["text"] = grounded["text"]
    elif step.action_type == "input_text":
        kwargs["text"] = target

    return kwargs


# ---------------------------------------------------------------------------
# SkillExecutor
# ---------------------------------------------------------------------------

@dataclass
class SkillExecutor:
    """Execute a :class:`Skill` step-by-step with state validation.

    Parameters
    ----------
    backend:
        Device backend for action execution.
    state_validator:
        Optional validator for per-step ``valid_state`` checks.
        If None, all state checks pass (with a warning).
    screenshot_getter:
        Optional callable that returns the current screenshot path or bytes.
        Used to supply screenshots for state validation between steps.
    stop_on_failure:
        Whether to halt execution on the first non-optional step failure.
    """

    backend: DeviceBackend
    state_validator: StateValidator | None = None
    screenshot_getter: typing.Callable[[], Path | bytes | None] | None = None
    stop_on_failure: bool = True

    async def execute(
        self,
        skill: Skill,
        params: dict[str, str] | None = None,
        *,
        timeout: float = 5.0,
    ) -> SkillExecutionResult:
        """Run all steps of *skill* sequentially with state verification."""
        params = params or {}
        step_results: list[StepResult] = []
        state = ExecutionState.RUNNING
        error_msg: str | None = None

        # Get initial screenshot for first step validation
        current_screenshot = self._get_screenshot()

        for i, step in enumerate(skill.steps):
            # Step 1: valid_state verification BEFORE execution
            valid_state_ok = await self._validate_state(step, current_screenshot)
            if not valid_state_ok:
                is_optional = step.parameters.get("optional", False)
                step_results.append(StepResult(
                    step_index=i,
                    action=Action(action_type=step.action_type),
                    backend_result="",
                    state=ExecutionState.FAILED,
                    valid_state_check=False,
                    error=f"State validation failed: {step.valid_state}",
                ))
                if is_optional:
                    logger.info("Optional step %d failed state check, skipping", i)
                    continue
                state = ExecutionState.FAILED
                error_msg = f"Step {i} state validation failed: {step.valid_state}"
                if self.stop_on_failure:
                    break
                continue

            # Step 2: Ground parameters and execute
            try:
                action_kwargs = _ground_step(step, params)
                action = Action(**action_kwargs)
                result = await self.backend.execute(action, timeout=timeout)
                step_results.append(StepResult(
                    step_index=i,
                    action=action,
                    backend_result=result,
                    state=ExecutionState.SUCCEEDED,
                ))
            except Exception as exc:
                logger.error("Skill step %d execution failed: %s", i, exc)
                is_optional = step.parameters.get("optional", False)
                step_results.append(StepResult(
                    step_index=i,
                    action=Action(action_type=step.action_type),
                    backend_result=str(exc),
                    state=ExecutionState.FAILED,
                    error=str(exc),
                ))
                if is_optional:
                    logger.info("Optional step %d failed, continuing", i)
                    continue
                state = ExecutionState.FAILED
                error_msg = f"Step {i} failed: {exc}"
                if self.stop_on_failure:
                    break
                continue

            # Update screenshot for next step's validation
            current_screenshot = self._get_screenshot()

        if state != ExecutionState.FAILED:
            state = ExecutionState.SUCCEEDED

        return SkillExecutionResult(
            skill=skill,
            step_results=step_results,
            state=state,
            error=error_msg,
        )

    async def _validate_state(
        self,
        step: SkillStep,
        screenshot: Path | bytes | None,
    ) -> bool:
        """Validate per-step valid_state before execution."""
        if _should_skip_validation(step.valid_state):
            return True
        if self.state_validator is None:
            logger.debug("No state validator; allowing step %s", step.action_type)
            return True
        try:
            return await self.state_validator.validate(
                step.valid_state or "",
                screenshot=screenshot,
            )
        except Exception as exc:
            logger.error("State validator error: %s", exc)
            return True  # Fail-open

    def _get_screenshot(self) -> Path | bytes | None:
        if self.screenshot_getter is not None:
            try:
                return self.screenshot_getter()
            except Exception as exc:
                logger.warning("Screenshot getter failed: %s", exc)
        return None
