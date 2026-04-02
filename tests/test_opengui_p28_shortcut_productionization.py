"""Phase 28 — production shortcut promotion seam tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider as NanobotLLMProvider
from nanobot.providers.base import LLMResponse as NanobotLLMResponse
from nanobot.providers.base import ToolCallRequest
from opengui.skills.shortcut_extractor import ExtractionRejected


def _nanobot_tool_response(
    *,
    content: str,
    arguments: dict[str, Any],
    call_id: str,
) -> Any:
    return NanobotLLMResponse(
        content=content,
        tool_calls=[
            ToolCallRequest(
                id=call_id,
                name="computer_use",
                arguments=arguments,
            )
        ],
    )


class _MockNanobotProvider(NanobotLLMProvider):
    """Minimal scripted nanobot LLM provider for tests."""

    def __init__(self, responses: list[Any]) -> None:
        super().__init__(api_key="test-key")
        self._responses = list(responses)

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
        del messages, tools, model, kwargs
        if not self._responses:
            raise AssertionError("No scripted nanobot responses left")
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return "test-model"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "gui_runs").mkdir()
    (tmp_path / "gui_skills").mkdir()
    return tmp_path


def _dry_run_tool(
    tmp_workspace: Path,
    extra_responses: list[Any] | None = None,
    gui_overrides: dict[str, Any] | None = None,
) -> Any:
    from nanobot.agent.tools.gui import GuiSubagentTool

    responses = [
        _nanobot_tool_response(
            content="Action: wait",
            arguments={"action_type": "wait", "duration_ms": 1},
            call_id="tc_wait",
        ),
        _nanobot_tool_response(
            content="Action: done",
            arguments={"action_type": "done", "status": "success"},
            call_id="tc_done",
        ),
    ]
    if extra_responses:
        responses.extend(extra_responses)

    provider = _MockNanobotProvider(responses)
    gui_config = {"backend": "dry-run"}
    if gui_overrides:
        gui_config.update(gui_overrides)
    return GuiSubagentTool(
        gui_config=Config(gui=gui_config).gui,
        provider=provider,
        model=provider.get_default_model(),
        workspace=tmp_workspace,
    )


def _write_jsonl(trace_path: Path, lines: list[str]) -> None:
    trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_gui_postprocessing_uses_shortcut_promotion_not_legacy_extractor(
    tmp_workspace: Path,
) -> None:
    tool = _dry_run_tool(tmp_workspace)
    promote_mock = AsyncMock(return_value="shortcut-promoted")
    legacy_extract_mock = AsyncMock(return_value=None)

    with (
        patch(
            "opengui.skills.shortcut_promotion.ShortcutPromotionPipeline.promote_from_trace",
            new=promote_mock,
        ),
        patch(
            "opengui.skills.extractor.SkillExtractor.extract_from_file",
            new=legacy_extract_mock,
        ),
    ):
        raw = await tool.execute(task="open compose")
        await tool._wait_for_pending_postprocessing()

    result = json.loads(raw)
    assert result["success"] is True
    promote_mock.assert_awaited_once()
    legacy_extract_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_promotion_pipeline_filters_final_successful_attempt_steps_only(tmp_path: Path) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Send a message", "platform": "android"}',
            'not valid json at all',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "phase_change", "from_phase": "agent", "to_phase": "agent"}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "tap old compose", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": false}',
            '{"type": "attempt_start", "attempt": 2}',
            '{"type": "phase_change", "from_phase": "agent", "to_phase": "agent"}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": ""}, "model_output": "invalid action", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 2, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Open compose", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 3, "phase": "skill", "action": {"action_type": "tap"}, "model_output": "skill phase row", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 4, "phase": "agent", "action": {"action_type": "input_text", "text": "hello"}, "model_output": "Type message", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "phase": "agent", "action": {"action_type": "tap"}, "model_output": "missing step index", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 2, "success": true}',
            '{"type": "result", "success": true}',
        ],
    )

    captured: dict[str, Any] = {}

    async def fake_run(self, steps: list[dict[str, Any]], metadata: dict[str, Any]) -> ExtractionRejected:
        del self
        captured["steps"] = steps
        captured["metadata"] = metadata
        return ExtractionRejected(
            reason="trajectory_critic",
            failed_step_verdict=None,
            failed_trajectory_verdict=None,
        )

    store = Mock()
    with patch("opengui.skills.shortcut_extractor.ExtractionPipeline.run", new=fake_run):
        result = await ShortcutPromotionPipeline().promote_from_trace(
            trace_path,
            is_success=True,
            store=store,
        )

    assert result is None
    assert [step["step_index"] for step in captured["steps"]] == [2, 4]
    assert [step["action"]["action_type"] for step in captured["steps"]] == ["tap", "input_text"]
    assert all(step["phase"] == "agent" for step in captured["steps"])
    assert captured["metadata"]["task"] == "Send a message"
    assert captured["metadata"]["platform"] == "android"
    assert captured["metadata"]["app"] == "com.example.mail"
    store.add.assert_not_called()


@pytest.mark.asyncio
async def test_promotion_pipeline_skips_non_step_or_malformed_trace_without_store_write(
    tmp_path: Path,
) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Send a message", "platform": "android"}',
            'definitely not json',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "phase_change", "from_phase": "agent", "to_phase": "agent"}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": ""}}',
            '{"type": "step", "step_index": 1, "phase": "skill", "action": {"action_type": "tap"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
            '{"type": "result", "success": true}',
        ],
    )

    store = Mock()
    run_mock = AsyncMock()
    with patch("opengui.skills.shortcut_extractor.ExtractionPipeline.run", new=run_mock):
        result = await ShortcutPromotionPipeline().promote_from_trace(
            trace_path,
            is_success=True,
            store=store,
        )

    assert result is None
    run_mock.assert_not_awaited()
    store.add.assert_not_called()
