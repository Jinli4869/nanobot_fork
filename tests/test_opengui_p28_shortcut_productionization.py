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
from opengui.skills import ShortcutSkill, ShortcutSkillStore
from opengui.skills.data import Skill, SkillStep
from opengui.skills.shortcut import ParameterSlot, StateDescriptor
from opengui.skills.shortcut_extractor import (
    ExtractionRejected,
    ExtractionSuccess,
    TrajectoryVerdict,
)


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
async def test_failed_shortcut_promotion_uses_failure_extractor_and_persists(
    tmp_workspace: Path,
) -> None:
    from nanobot.agent.tools.gui import GuiSubagentTool

    tool = _dry_run_tool(tmp_workspace)
    trace_path = tmp_workspace / "gui_runs" / "failed-trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Open settings", "platform": "dry-run"}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Tap settings icon", "expected_state": "Settings opens", "valid_state": "Desktop is visible", "observation": {"app": "settings"}}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Tap wrong icon", "expected_state": "Wrong app opens", "valid_state": "Desktop is visible", "observation": {"app": "settings"}}',
            '{"type": "result", "success": false, "error": "clicked wrong icon"}',
        ],
    )

    extract_calls: list[tuple[Path, bool]] = []

    async def fake_extract(self, trajectory_path: Path, *, is_success: bool = True) -> Skill:
        del self
        extract_calls.append((trajectory_path, is_success))
        return Skill(
            skill_id="failed-settings-shortcut",
            name="recover_open_settings",
            description="Wrong icon was tapped; retry the Settings icon",
            app="settings",
            platform="dry-run",
            parameters=("app_name",),
            preconditions=("Desktop is visible",),
            steps=(
                SkillStep(
                    action_type="tap",
                    target="Settings icon",
                    parameters={},
                    expected_state="Settings icon is highlighted",
                    valid_state="Desktop is visible",
                ),
                SkillStep(
                    action_type="tap",
                    target="Retry Settings icon instead of the wrong icon",
                    parameters={"is_corrective": True},
                    expected_state="Settings opens",
                    valid_state="Wrong app is not open",
                ),
            ),
        )

    promote_mock = AsyncMock(return_value=None)
    with (
        patch(
            "opengui.skills.extractor.SkillExtractor.extract_from_file",
            new=fake_extract,
        ),
        patch(
            "opengui.skills.shortcut_promotion.ShortcutPromotionPipeline.promote_from_trace",
            new=promote_mock,
        ),
    ):
        promoted_id = await tool._promote_shortcut(trace_path, is_success=False, platform="dry-run")

    assert promoted_id == "failed-settings-shortcut"
    assert extract_calls == [(trace_path, False)]
    promote_mock.assert_not_awaited()

    store = ShortcutSkillStore(tmp_workspace / "gui_skills")
    persisted = store.list_all(platform="dry-run", app="settings")
    assert len(persisted) == 1
    assert persisted[0].skill_id == "failed-settings-shortcut"
    assert persisted[0].source_trace_path == str(trace_path)
    assert persisted[0].source_step_indices == (0, 1)
    assert tuple(slot.name for slot in persisted[0].parameter_slots) == ("app_name",)
    assert tuple(state.value for state in persisted[0].preconditions) == (
        "Desktop is visible",
        "Wrong app is not open",
    )
    assert tuple(state.value for state in persisted[0].postconditions) == (
        "Settings icon is highlighted",
        "Settings opens",
    )


@pytest.mark.asyncio
async def test_promotion_pipeline_ignores_retry_noise_before_final_success(tmp_path: Path) -> None:
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
    assert [step["step_index"] for step in captured["steps"]] == [2]
    assert [step["action"]["action_type"] for step in captured["steps"]] == ["tap"]
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


@pytest.mark.asyncio
async def test_promotion_pipeline_rejects_summary_result_noise(tmp_path: Path) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    trace_path = tmp_path / "summary-noise.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Send a message", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "phase_change", "from_phase": "agent", "to_phase": "agent", "summary": "Opened compose view"}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "   ", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "input_text", "text": "hello"}, "model_output": "", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true, "summary": "Attempt completed"}',
            '{"type": "result", "success": true, "summary": "Message sent"}',
        ],
    )

    store = ShortcutSkillStore(tmp_path / "shortcut_store")
    run_mock = AsyncMock()
    with patch("opengui.skills.shortcut_extractor.ExtractionPipeline.run", new=run_mock):
        promoted_id = await ShortcutPromotionPipeline().promote_from_trace(
            trace_path,
            is_success=True,
            store=store,
        )

    assert promoted_id is None
    run_mock.assert_not_awaited()
    assert store.list_all(platform="android") == []


def test_promoted_shortcut_round_trips_with_provenance() -> None:
    shortcut = ShortcutSkill(
        skill_id="shortcut-compose-v1",
        name="Compose Email",
        description="Open compose and focus the message editor",
        app="com.example.mail",
        platform="android",
        steps=(
            SkillStep(action_type="tap", target="compose button"),
            SkillStep(action_type="input_text", target="message field {{message}}"),
        ),
        parameter_slots=(
            ParameterSlot(name="message", type="string", description="Body text"),
        ),
        preconditions=(StateDescriptor(kind="screen_state", value="inbox"),),
        postconditions=(StateDescriptor(kind="screen_state", value="composer"),),
        source_task="Send a project update",
        source_trace_path="/tmp/gui_runs/run-123/trace.jsonl",
        source_run_id="run-123",
        source_step_indices=(2, 4),
        promotion_version=1,
        shortcut_version=2,
        merged_from_ids=("shortcut-compose-draft",),
        promoted_at=1700000005.5,
        created_at=1700000000.0,
    )

    payload = shortcut.to_dict()

    assert payload["source_trace_path"] == "/tmp/gui_runs/run-123/trace.jsonl"
    assert payload["source_run_id"] == "run-123"
    assert payload["source_step_indices"] == [2, 4]
    assert payload["promotion_version"] == 1
    assert payload["shortcut_version"] == 2

    restored = ShortcutSkill.from_dict(payload)

    assert restored.source_task == "Send a project update"
    assert restored.source_trace_path == "/tmp/gui_runs/run-123/trace.jsonl"
    assert restored.source_run_id == "run-123"
    assert restored.source_step_indices == (2, 4)
    assert restored.promotion_version == 1
    assert restored.shortcut_version == 2
    assert restored.merged_from_ids == ("shortcut-compose-draft",)
    assert restored.promoted_at == 1700000005.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "promotion_store_roundtrip",
    [True],
    ids=["promotion_store_roundtrip"],
)
async def test_promotion_pipeline_persists_full_shortcut_contract_after_store_reload(
    tmp_path: Path,
    promotion_store_roundtrip: bool,
) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline
    assert promotion_store_roundtrip is True

    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Send a project update", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "step", "step_index": 2, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Open compose for {{recipient}}", "valid_state": "Inbox visible", "expected_state": "Composer visible", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 4, "phase": "agent", "action": {"action_type": "input_text", "text": "Draft body"}, "model_output": "Type {{message}} into the body", "valid_state": "Composer visible", "expected_state": "Draft text entered", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
            '{"type": "result", "success": true}',
        ],
    )

    store = ShortcutSkillStore(tmp_path / "shortcut_store")
    promoted_id = await ShortcutPromotionPipeline().promote_from_trace(
        trace_path,
        is_success=True,
        store=store,
    )

    assert promoted_id is not None

    reloaded = ShortcutSkillStore(tmp_path / "shortcut_store")
    promoted = reloaded.list_all(platform="android", app="com.example.mail")

    assert len(promoted) == 1
    assert promoted[0].app == "com.example.mail"
    assert promoted[0].platform == "android"
    assert tuple(slot.name for slot in promoted[0].parameter_slots) == ("recipient",)
    assert tuple(state.value for state in promoted[0].preconditions) == (
        "Inbox visible",
    )
    assert tuple(state.value for state in promoted[0].postconditions) == (
        "Composer visible",
    )
    assert promoted[0].source_trace_path == str(trace_path)
    assert promoted[0].source_step_indices == (2,)


@pytest.mark.asyncio
async def test_promotion_pipeline_rejects_low_value_candidates(tmp_path: Path) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    cases = [
        [
            '{"type": "metadata", "task": "Send a project update", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "   ", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "input_text", "text": "hello"}, "model_output": "   ", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
            '{"type": "result", "success": true}',
        ],
        [
            '{"type": "metadata", "task": "Send a project update", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "drag"}, "model_output": "Drag the draft card", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Open compose", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
            '{"type": "result", "success": true}',
        ],
        [
            '{"type": "metadata", "task": "Send a project update", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Open compose"}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "wait", "duration_ms": 1000}, "model_output": "Wait for draft"}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
            '{"type": "result", "success": true}',
        ],
    ]

    for index, lines in enumerate(cases):
        trace_path = tmp_path / f"low-value-{index}.jsonl"
        _write_jsonl(trace_path, lines)
        store = Mock()
        store.add = Mock()
        store.add_or_merge = AsyncMock()

        result = await ShortcutPromotionPipeline().promote_from_trace(
            trace_path,
            is_success=True,
            store=store,
        )

        assert result is None
        store.add.assert_not_called()
        store.add_or_merge.assert_not_awaited()


@pytest.mark.asyncio
async def test_promotion_pipeline_truncates_after_reusable_prefix(tmp_path: Path) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    trace_path = tmp_path / "prefix-trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Send a project update", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap", "x": 100, "y": 200}, "model_output": "Open compose for {{recipient}}", "valid_state": "Inbox visible", "expected_state": "Composer visible", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "input_text", "text": "hello"}, "model_output": "Type {{message}} into the body", "valid_state": "Composer visible", "expected_state": "Draft text entered", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 2, "phase": "agent", "action": {"action_type": "tap", "x": 300, "y": 400}, "model_output": "Send the message", "valid_state": "Draft text entered", "expected_state": "Message sent", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
            '{"type": "result", "success": true}',
        ],
    )

    store = ShortcutSkillStore(tmp_path / "prefix-store")
    skill_id = await ShortcutPromotionPipeline().promote_from_trace(
        trace_path,
        is_success=True,
        store=store,
    )

    assert skill_id is not None
    promoted = store.list_all(platform="android", app="com.example.mail")
    assert len(promoted) == 1
    assert promoted[0].source_step_indices == (0,)
    assert len(promoted[0].steps) == 1
    assert promoted[0].steps[0].parameters == {}


@pytest.mark.asyncio
@pytest.mark.reusable_boundary
async def test_promotion_pipeline_keeps_reusable_setup_before_payload_boundary(
    tmp_path: Path,
) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    trace_path = tmp_path / "reusable-boundary-trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Send a message", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Open compose", "valid_state": "Inbox visible", "expected_state": "Composer visible", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Focus recipient field", "valid_state": "Composer visible", "expected_state": "Recipient field focused", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 2, "phase": "agent", "action": {"action_type": "input_text", "text": "alice@example.com"}, "model_output": "input_text recipient payload", "valid_state": "Recipient field focused", "expected_state": "Recipient filled", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 3, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Send message", "valid_state": "Recipient filled", "expected_state": "Message sent", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
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
    assert [step["step_index"] for step in captured["steps"]] == [0, 1]
    assert [step["model_output"] for step in captured["steps"]] == [
        "Open compose",
        "Focus recipient field",
    ]
    assert captured["metadata"]["app"] == "com.example.mail"


@pytest.mark.asyncio
async def test_promotion_pipeline_canonicalizes_duplicate_waits_and_unchanged_ui_retries(
    tmp_path: Path,
) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    trace_path = tmp_path / "canonicalize-noise-trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Send a message", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Open compose", "valid_state": "Inbox visible", "expected_state": "Composer visible", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "wait", "duration_ms": 1000}, "model_output": "wait", "valid_state": "Composer visible", "expected_state": "Composer visible", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 2, "phase": "agent", "action": {"action_type": "wait", "duration_ms": 1000}, "model_output": "wait", "valid_state": "Composer visible", "expected_state": "Composer visible", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 3, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Focus recipient field", "valid_state": "Composer visible", "expected_state": "Recipient field focused", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 4, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Focus recipient field", "valid_state": "Composer visible", "expected_state": "Recipient field focused", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 5, "phase": "agent", "action": {"action_type": "input_text", "text": "alice@example.com"}, "model_output": "input_text recipient payload", "valid_state": "Recipient field focused", "expected_state": "Recipient filled", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 6, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Send message", "valid_state": "Recipient filled", "expected_state": "Message sent", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
            '{"type": "result", "success": true}',
        ],
    )

    captured: dict[str, Any] = {}

    async def fake_run(self, steps: list[dict[str, Any]], metadata: dict[str, Any]) -> ExtractionRejected:
        del self, metadata
        captured["steps"] = steps
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
    assert [step["step_index"] for step in captured["steps"]] == [0, 2, 4]
    assert [step["action"]["action_type"] for step in captured["steps"]] == [
        "tap",
        "wait",
        "tap",
    ]
    assert sum(step["action"]["action_type"] == "wait" for step in captured["steps"]) == 1
    assert sum(step["model_output"] == "Focus recipient field" for step in captured["steps"]) == 1


@pytest.mark.asyncio
async def test_promotion_pipeline_keeps_richer_state_evidence_when_collapsing_duplicates(
    tmp_path: Path,
) -> None:
    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    trace_path = tmp_path / "richer-state-trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            '{"type": "metadata", "task": "Send a message", "platform": "android"}',
            '{"type": "attempt_start", "attempt": 1}',
            '{"type": "step", "step_index": 0, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Open compose", "valid_state": "Inbox visible", "expected_state": "Composer visible", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 1, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Focus recipient field", "valid_state": "Composer visible", "expected_state": "", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 2, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Focus recipient field", "valid_state": "Composer visible", "expected_state": "Recipient field focused", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 3, "phase": "agent", "action": {"action_type": "input_text", "text": "alice@example.com"}, "model_output": "input_text recipient payload", "valid_state": "Recipient field focused", "expected_state": "Recipient filled", "observation": {"app": "com.example.mail"}}',
            '{"type": "step", "step_index": 4, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Send message", "valid_state": "Recipient filled", "expected_state": "Message sent", "observation": {"app": "com.example.mail"}}',
            '{"type": "attempt_result", "attempt": 1, "success": true}',
            '{"type": "result", "success": true}',
        ],
    )

    captured: dict[str, Any] = {}

    async def fake_run(self, steps: list[dict[str, Any]], metadata: dict[str, Any]) -> ExtractionRejected:
        del self, metadata
        captured["steps"] = steps
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
    assert [step["step_index"] for step in captured["steps"]] == [0, 2]
    retained = captured["steps"][1]
    assert retained["model_output"] == "Focus recipient field"
    assert retained["expected_state"] == "Recipient field focused"
    assert retained["step_index"] == 2


@pytest.mark.asyncio
async def test_duplicate_promotions_do_not_increase_shortcut_store_count(
    tmp_path: Path,
) -> None:
    def _candidate(skill_id: str, name: str, description: str, created_at: float) -> ShortcutSkill:
        return ShortcutSkill(
            skill_id=skill_id,
            name=name,
            description=description,
            app="com.example.mail",
            platform="android",
            steps=(
                SkillStep(action_type="tap", target="compose"),
                SkillStep(action_type="input_text", target="body {{message}}"),
            ),
            parameter_slots=(
                ParameterSlot(name="message", type="string", description="Email body"),
            ),
            preconditions=(StateDescriptor(kind="screen_state", value="Inbox visible"),),
            postconditions=(StateDescriptor(kind="screen_state", value="Composer visible"),),
            created_at=created_at,
        )

    trace_specs = [
        (
            tmp_path / "run-1" / "trace.jsonl",
            _candidate("shortcut-compose-v1", "Compose Email", "Open compose flow", 1700000000.0),
        ),
        (
            tmp_path / "run-2" / "trace.jsonl",
            _candidate(
                "shortcut-compose-v2",
                "Compose Message",
                "Open compose flow and focus the editor",
                1700000001.0,
            ),
        ),
    ]
    for trace_path, _ in trace_specs:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        _write_jsonl(
            trace_path,
            [
                '{"type": "metadata", "task": "Send a message", "platform": "android"}',
                '{"type": "attempt_start", "attempt": 1}',
                '{"type": "step", "step_index": 2, "phase": "agent", "action": {"action_type": "tap"}, "model_output": "Open compose", "valid_state": "Inbox visible", "expected_state": "Composer visible", "observation": {"app": "com.example.mail"}}',
                '{"type": "step", "step_index": 4, "phase": "agent", "action": {"action_type": "input_text", "text": "hello"}, "model_output": "Type message", "observation": {"app": "com.example.mail"}}',
                '{"type": "attempt_result", "attempt": 1, "success": true}',
                '{"type": "result", "success": true}',
            ],
        )

    outcomes = iter(
        [
            ExtractionSuccess(
                candidate=trace_specs[0][1],
                step_verdicts=(),
                trajectory_verdict=TrajectoryVerdict(passed=True, reason="ok"),
            ),
            ExtractionSuccess(
                candidate=trace_specs[1][1],
                step_verdicts=(),
                trajectory_verdict=TrajectoryVerdict(passed=True, reason="ok"),
            ),
        ]
    )

    async def fake_run(
        self,
        steps: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> ExtractionSuccess:
        del self, steps, metadata
        return next(outcomes)

    from opengui.skills.shortcut_promotion import ShortcutPromotionPipeline

    store = ShortcutSkillStore(tmp_path / "shortcut_store")
    pipeline = ShortcutPromotionPipeline()
    with patch("opengui.skills.shortcut_extractor.ExtractionPipeline.run", new=fake_run):
        first_id = await pipeline.promote_from_trace(trace_specs[0][0], is_success=True, store=store)
        second_id = await pipeline.promote_from_trace(trace_specs[1][0], is_success=True, store=store)

    assert first_id == "shortcut-compose-v1"
    assert second_id == "shortcut-compose-v1"
    assert len(store.list_all(platform="android")) == 1
    stored = store.list_all(platform="android", app="com.example.mail")
    assert stored[0].skill_id == "shortcut-compose-v1"
    assert stored[0].shortcut_version == 2
    assert stored[0].merged_from_ids == ("shortcut-compose-v2",)
