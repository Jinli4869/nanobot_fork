"""Unit tests for SkillExecutor wiring into GuiSubagentTool via enable_skill_execution config.

Tests verify:
- GuiConfig accepts enable_skill_execution=True and defaults to False.
- When enable_skill_execution=False, GuiAgent receives skill_executor=None.
- When enable_skill_execution=True, GuiAgent receives a SkillExecutor instance.
- The SkillExecutor is built with backend=active_backend and
  state_validator=LLMStateValidator(llm_adapter).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import GuiConfig


# ---------------------------------------------------------------------------
# GuiConfig field tests
# ---------------------------------------------------------------------------


class TestGuiConfigSkillExecutionField:
    """GuiConfig.enable_skill_execution must default to False and accept True."""

    def test_defaults_to_false(self) -> None:
        config = GuiConfig()
        assert config.enable_skill_execution is False

    def test_accepts_true(self) -> None:
        config = GuiConfig(enable_skill_execution=True)
        assert config.enable_skill_execution is True

    def test_accepts_false_explicitly(self) -> None:
        config = GuiConfig(enable_skill_execution=False)
        assert config.enable_skill_execution is False

    def test_accepts_camel_case_key(self) -> None:
        """GuiConfig uses camelCase aliases; enableSkillExecution must be accepted."""
        config = GuiConfig.model_validate({"enableSkillExecution": True})
        assert config.enable_skill_execution is True


# ---------------------------------------------------------------------------
# GuiSubagentTool wiring tests
# ---------------------------------------------------------------------------


def _make_gui_config(enable_skill_execution: bool) -> GuiConfig:
    return GuiConfig(backend="dry-run", enable_skill_execution=enable_skill_execution)


def _make_tool(gui_config: GuiConfig) -> "GuiSubagentTool":  # type: ignore[name-defined]
    """Build a GuiSubagentTool with mocked provider/model/workspace."""
    from nanobot.agent.tools.gui import GuiSubagentTool

    provider = MagicMock()
    provider.api_key = "test-key"
    provider.api_base = None
    provider.extra_headers = None
    # Simulate the _client attribute used by NanobotLLMAdapter
    provider._client = None

    return GuiSubagentTool(
        gui_config=gui_config,
        provider=provider,
        model="test/model",
        workspace=Path("/tmp/test_workspace"),
    )


class TestSkillExecutorWiringDisabled:
    """When enable_skill_execution=False, GuiAgent must receive skill_executor=None."""

    def test_skill_executor_is_none_when_disabled(self) -> None:
        gui_config = _make_gui_config(enable_skill_execution=False)
        tool = _make_tool(gui_config)

        captured_kwargs: dict = {}

        async def _run() -> None:
            with (
                patch("nanobot.agent.tools.gui.GuiAgent.__init__", return_value=None) as mock_init,
                patch(
                    "nanobot.agent.tools.gui.TrajectoryRecorder",
                    return_value=MagicMock(path=None),
                ),
            ):
                # Patch run so we don't actually execute the agent.
                with patch("opengui.agent.GuiAgent.run", new_callable=AsyncMock) as mock_run:
                    mock_run.return_value = MagicMock(
                        success=True,
                        summary="ok",
                        model_summary="",
                        trace_path=None,
                        steps_taken=0,
                        error=None,
                    )
                    mock_init.side_effect = lambda *a, **kw: captured_kwargs.update(kw)
                    try:
                        await tool._run_task(tool._backend, "open settings")
                    except Exception:
                        pass  # GuiAgent.__init__ is mocked, run may raise

        asyncio.run(_run())

        # skill_executor must be None (or absent, which defaults to None)
        assert captured_kwargs.get("skill_executor") is None


class TestSkillExecutorWiringEnabled:
    """When enable_skill_execution=True, GuiAgent must receive a SkillExecutor instance."""

    def test_skill_executor_is_passed_when_enabled(self) -> None:
        from opengui.skills.executor import SkillExecutor

        gui_config = _make_gui_config(enable_skill_execution=True)
        tool = _make_tool(gui_config)

        captured_kwargs: dict = {}

        async def _run() -> None:
            with (
                patch("nanobot.agent.tools.gui.GuiAgent.__init__", return_value=None) as mock_init,
                patch(
                    "nanobot.agent.tools.gui.TrajectoryRecorder",
                    return_value=MagicMock(path=None),
                ),
            ):
                with patch("opengui.agent.GuiAgent.run", new_callable=AsyncMock) as mock_run:
                    mock_run.return_value = MagicMock(
                        success=True,
                        summary="ok",
                        model_summary="",
                        trace_path=None,
                        steps_taken=0,
                        error=None,
                    )
                    mock_init.side_effect = lambda *a, **kw: captured_kwargs.update(kw)
                    try:
                        await tool._run_task(tool._backend, "open settings")
                    except Exception:
                        pass

        asyncio.run(_run())

        assert "skill_executor" in captured_kwargs
        assert isinstance(captured_kwargs["skill_executor"], SkillExecutor)

    def test_skill_executor_built_with_correct_backend(self) -> None:
        """SkillExecutor.backend must be the active_backend passed to _run_task."""
        from opengui.skills.executor import SkillExecutor

        gui_config = _make_gui_config(enable_skill_execution=True)
        tool = _make_tool(gui_config)

        captured_kwargs: dict = {}
        active_backend = tool._backend  # dry-run backend

        async def _run() -> None:
            with (
                patch("nanobot.agent.tools.gui.GuiAgent.__init__", return_value=None) as mock_init,
                patch(
                    "nanobot.agent.tools.gui.TrajectoryRecorder",
                    return_value=MagicMock(path=None),
                ),
            ):
                with patch("opengui.agent.GuiAgent.run", new_callable=AsyncMock) as mock_run:
                    mock_run.return_value = MagicMock(
                        success=True,
                        summary="ok",
                        model_summary="",
                        trace_path=None,
                        steps_taken=0,
                        error=None,
                    )
                    mock_init.side_effect = lambda *a, **kw: captured_kwargs.update(kw)
                    try:
                        await tool._run_task(active_backend, "open settings")
                    except Exception:
                        pass

        asyncio.run(_run())

        skill_executor = captured_kwargs.get("skill_executor")
        assert isinstance(skill_executor, SkillExecutor)
        assert skill_executor.backend is active_backend

    def test_skill_executor_built_with_llm_state_validator(self) -> None:
        """SkillExecutor.state_validator must be an LLMStateValidator backed by the LLM adapter."""
        from opengui.skills.executor import LLMStateValidator, SkillExecutor

        gui_config = _make_gui_config(enable_skill_execution=True)
        tool = _make_tool(gui_config)

        captured_kwargs: dict = {}

        async def _run() -> None:
            with (
                patch("nanobot.agent.tools.gui.GuiAgent.__init__", return_value=None) as mock_init,
                patch(
                    "nanobot.agent.tools.gui.TrajectoryRecorder",
                    return_value=MagicMock(path=None),
                ),
            ):
                with patch("opengui.agent.GuiAgent.run", new_callable=AsyncMock) as mock_run:
                    mock_run.return_value = MagicMock(
                        success=True,
                        summary="ok",
                        model_summary="",
                        trace_path=None,
                        steps_taken=0,
                        error=None,
                    )
                    mock_init.side_effect = lambda *a, **kw: captured_kwargs.update(kw)
                    try:
                        await tool._run_task(tool._backend, "open settings")
                    except Exception:
                        pass

        asyncio.run(_run())

        skill_executor = captured_kwargs.get("skill_executor")
        assert isinstance(skill_executor, SkillExecutor)
        assert isinstance(skill_executor.state_validator, LLMStateValidator)
        # Verify the state_validator is backed by the tool's LLM adapter
        assert skill_executor.state_validator._llm is tool._llm_adapter
