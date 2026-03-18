"""Phase 3 nanobot integration tests.

Wave 0 starts with xfail stubs for the full phase boundary, then later tasks in
this plan promote the adapter/config coverage to real passing tests.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

try:
    from opengui.interfaces import LLMResponse as OpenGuiLLMResponse
    from opengui.interfaces import ToolCall as OpenGuiToolCall
except Exception as exc:  # pragma: no cover - only used if imports break
    OpenGuiLLMResponse = None
    OpenGuiToolCall = None
    _OPENGUI_IMPORT_ERROR: Exception | None = exc
else:
    _OPENGUI_IMPORT_ERROR = None

try:
    from nanobot.config.schema import Config
    from nanobot.providers.base import LLMProvider as NanobotLLMProvider
    from nanobot.providers.base import LLMResponse as NanobotLLMResponse
    from nanobot.providers.base import ToolCallRequest
except Exception as exc:  # pragma: no cover - only used if imports break
    Config = None
    NanobotLLMProvider = object
    NanobotLLMResponse = None
    ToolCallRequest = None
    _NANOBOT_IMPORT_ERROR: Exception | None = exc
else:
    _NANOBOT_IMPORT_ERROR = None


@dataclass
class _QueuedResponse:
    response: Any


if _NANOBOT_IMPORT_ERROR is None:

    class _MockNanobotProvider(NanobotLLMProvider):
        """Minimal nanobot LLM provider for adapter tests."""

        def __init__(self, responses: list[Any]) -> None:
            super().__init__(api_key="test-key")
            self._responses = [_QueuedResponse(response=r) for r in responses]
            self.calls: list[dict[str, Any]] = []

        async def chat(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]] | None = None,
            model: str | None = None,
            max_tokens: int = 4096,
            temperature: float = 0.7,
            reasoning_effort: str | None = None,
            tool_choice: str | dict[str, Any] | None = None,
        ) -> Any:
            return await self.chat_with_retry(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
            )

        async def chat_with_retry(self, messages, tools=None, model=None, **kwargs) -> Any:
            self.calls.append(
                {
                    "messages": messages,
                    "tools": tools,
                    "model": model,
                    **kwargs,
                }
            )
            if not self._responses:
                raise AssertionError("No scripted nanobot responses left")
            return self._responses.pop(0).response

        def get_default_model(self) -> str:
            return "test-model"

else:

    class _MockNanobotProvider:
        def __init__(self, responses: list[Any]) -> None:
            raise RuntimeError("nanobot provider imports unavailable") from _NANOBOT_IMPORT_ERROR


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "gui_runs").mkdir()
    (tmp_path / "gui_skills").mkdir()
    return tmp_path


@pytest.mark.xfail(strict=False, reason="NANO-01 not yet implemented")
def test_gui_tool_registered(tmp_workspace: Path) -> None:
    from nanobot.agent.tools.gui import GuiSubagentTool
    from nanobot.agent.tools.registry import ToolRegistry

    registry = ToolRegistry()
    tool = GuiSubagentTool(config=Config(), workspace=tmp_workspace)
    registry.register(tool)

    definitions = registry.get_definitions()
    assert any(defn["function"]["name"] == tool.name for defn in definitions)


@pytest.mark.xfail(strict=False, reason="NANO-02 not yet implemented")
@pytest.mark.asyncio
async def test_llm_adapter_maps_response() -> None:
    from nanobot.agent.gui_adapter import NanobotLLMAdapter

    provider = _MockNanobotProvider(
        [
            NanobotLLMResponse(
                content="tap settings",
                tool_calls=[
                    ToolCallRequest(
                        id="tc1",
                        name="computer_use",
                        arguments={"action_type": "tap", "x": 100, "y": 200},
                    )
                ],
            )
        ]
    )
    adapter = NanobotLLMAdapter(provider=provider, model=provider.get_default_model())

    result = await adapter.chat(messages=[{"role": "user", "content": "Open Settings"}])

    assert isinstance(result, OpenGuiLLMResponse)
    assert isinstance(result.tool_calls[0], OpenGuiToolCall)
    assert result.tool_calls[0].arguments["action_type"] == "tap"


@pytest.mark.xfail(strict=False, reason="NANO-02 not yet implemented")
@pytest.mark.asyncio
async def test_llm_adapter_empty_tool_calls() -> None:
    from nanobot.agent.gui_adapter import NanobotLLMAdapter

    provider = _MockNanobotProvider([NanobotLLMResponse(content="done", tool_calls=[])])
    adapter = NanobotLLMAdapter(provider=provider, model=provider.get_default_model())

    result = await adapter.chat(messages=[{"role": "user", "content": "Finish"}])

    assert result.tool_calls is None


@pytest.mark.xfail(strict=False, reason="NANO-03 not yet implemented")
def test_backend_selection(tmp_workspace: Path) -> None:
    from nanobot.agent.tools.gui import GuiSubagentTool
    from nanobot.config.schema import GuiConfig

    config = Config(gui=GuiConfig(backend="dry-run"))
    tool = GuiSubagentTool(config=config, workspace=tmp_workspace)

    assert getattr(tool, "_backend_override", None) in (None, "dry-run")


@pytest.mark.xfail(strict=False, reason="NANO-04 not yet implemented")
@pytest.mark.asyncio
async def test_trajectory_saved_to_workspace(tmp_workspace: Path) -> None:
    from nanobot.agent.tools.gui import GuiSubagentTool

    tool = GuiSubagentTool(config=Config(gui={"backend": "dry-run"}), workspace=tmp_workspace)
    result = await tool.execute(task="Open Settings")

    traces = list((tmp_workspace / "gui_runs").glob("**/*.jsonl"))
    assert result["trace_path"]
    assert traces


@pytest.mark.xfail(strict=False, reason="NANO-05 not yet implemented")
@pytest.mark.asyncio
async def test_auto_skill_extraction(tmp_workspace: Path) -> None:
    from nanobot.agent.tools.gui import GuiSubagentTool

    tool = GuiSubagentTool(config=Config(gui={"backend": "dry-run"}), workspace=tmp_workspace)
    await tool.execute(task="Open calculator")

    skills_dir = tmp_workspace / "gui_skills"
    manifests = list(skills_dir.glob("**/*.json"))
    assert manifests


def test_scaffolding_uses_phase3_patterns() -> None:
    """Sanity check the helper imports used by later tasks."""
    assert asyncio.iscoroutinefunction(_MockNanobotProvider.chat_with_retry)
    assert json.dumps({"phase": 3}) == '{"phase": 3}'
