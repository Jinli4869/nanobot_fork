"""Phase 30 - Stable shortcut execution: live binding, settle timing, and fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from opengui.action import Action
from opengui.grounding.protocol import GroundingResult
from opengui.observation import Observation
from opengui.skills.data import SkillStep
from opengui.skills.multi_layer_executor import (
    LLMConditionEvaluator,
    ShortcutExecutionSuccess,
    ShortcutExecutor,
)
from opengui.skills.shortcut import ShortcutSkill, StateDescriptor


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
