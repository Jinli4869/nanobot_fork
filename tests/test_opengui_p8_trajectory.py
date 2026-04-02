"""Phase 8 tests: TrajectorySummarizer wiring and nanobot.agent public API exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers (reuse _MockNanobotProvider pattern from test_opengui_p3_nanobot)
# ---------------------------------------------------------------------------

try:
    from nanobot.config.schema import Config
    from nanobot.providers.base import LLMProvider as NanobotLLMProvider
    from nanobot.providers.base import LLMResponse as NanobotLLMResponse
    from nanobot.providers.base import ToolCallRequest
except Exception as exc:  # pragma: no cover
    Config = None
    NanobotLLMProvider = object
    NanobotLLMResponse = None
    ToolCallRequest = None
    _NANOBOT_IMPORT_ERROR: Exception | None = exc
else:
    _NANOBOT_IMPORT_ERROR = None


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


if _NANOBOT_IMPORT_ERROR is None:

    class _MockNanobotProvider(NanobotLLMProvider):
        """Minimal scripted nanobot LLM provider for tests."""

        def __init__(self, responses: list[Any]) -> None:
            super().__init__(api_key="test-key")
            self._responses = list(responses)
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
            self.calls.append({"messages": messages, "tools": tools, "model": model, **kwargs})
            if not self._responses:
                raise AssertionError("No scripted nanobot responses left")
            return self._responses.pop(0)

        def get_default_model(self) -> str:
            return "test-model"

else:

    class _MockNanobotProvider:
        def __init__(self, responses: list[Any]) -> None:
            raise RuntimeError("nanobot imports unavailable") from _NANOBOT_IMPORT_ERROR


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
    """Build a GuiSubagentTool with dry-run backend and two standard action responses."""
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


# ---------------------------------------------------------------------------
# Task 1 tests: TrajectorySummarizer wiring into GuiSubagentTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarizer_called_post_run(
    tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """summarize_file should be awaited with a Path after a successful GUI run."""
    from nanobot.agent.tools.gui import GuiSubagentTool  # noqa: F401 — import check

    monkeypatch.setattr(
        "opengui.skills.extractor.SkillExtractor.extract_from_file",
        AsyncMock(return_value=None),
    )

    tool = _dry_run_tool(tmp_workspace)
    with patch(
        "opengui.trajectory.summarizer.TrajectorySummarizer.summarize_file",
        new_callable=AsyncMock,
        return_value="Summary text",
    ) as mock_summarize:
        await tool.execute(task="test task")
        await tool._wait_for_pending_postprocessing()

    mock_summarize.assert_awaited_once()
    call_arg = mock_summarize.call_args[0][0]  # first positional arg
    assert isinstance(call_arg, Path), f"Expected Path, got {type(call_arg)}"


@pytest.mark.asyncio
async def test_summarizer_failure_non_fatal(
    tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If summarize_file raises, execute() should still return valid JSON and _extract_skill runs."""
    extract_calls: list[Path] = []

    async def fake_extract(self_inner, trajectory_path: Path, *, is_success: bool = True):
        extract_calls.append(trajectory_path)
        return None

    monkeypatch.setattr(
        "opengui.skills.extractor.SkillExtractor.extract_from_file",
        fake_extract,
    )

    tool = _dry_run_tool(tmp_workspace)
    with patch(
        "opengui.trajectory.summarizer.TrajectorySummarizer.summarize_file",
        new_callable=AsyncMock,
        side_effect=RuntimeError("summarizer exploded"),
    ):
        raw = await tool.execute(task="test task")
        await tool._wait_for_pending_postprocessing()

    result = json.loads(raw)
    assert "success" in result, "execute() must return JSON with 'success' key"
    assert len(extract_calls) == 1, "_extract_skill must still be called after summarizer failure"


@pytest.mark.asyncio
async def test_gui_evaluation_runs_from_background_postprocessing(
    tmp_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "opengui.skills.extractor.SkillExtractor.extract_from_file",
        AsyncMock(return_value=None),
    )
    eval_mock = AsyncMock(return_value={"success": True, "reason": "final state matches"})
    monkeypatch.setattr("nanobot.agent.tools.gui.evaluate_gui_trajectory", eval_mock)

    tool = _dry_run_tool(
        tmp_workspace,
        gui_overrides={
            "evaluation": {
                "enabled": True,
                "judgeModel": "judge-model",
                "apiKey": "judge-key",
                "apiBase": "https://judge.example/v1",
            }
        },
    )

    await tool.execute(task="test task")
    await tool._wait_for_pending_postprocessing()

    eval_mock.assert_awaited_once()
    kwargs = eval_mock.await_args.kwargs
    assert kwargs["instruction"] == "test task"
    assert kwargs["model"] == "judge-model"
    assert kwargs["api_key"] == "judge-key"
    assert kwargs["api_base"] == "https://judge.example/v1"
    assert isinstance(kwargs["trace_path"], Path)


@pytest.mark.asyncio
async def test_gui_evaluation_failure_is_non_fatal(
    tmp_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extract_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "opengui.skills.extractor.SkillExtractor.extract_from_file",
        extract_mock,
    )
    monkeypatch.setattr(
        "nanobot.agent.tools.gui.evaluate_gui_trajectory",
        AsyncMock(side_effect=RuntimeError("judge unavailable")),
    )

    tool = _dry_run_tool(
        tmp_workspace,
        gui_overrides={
            "evaluation": {
                "enabled": True,
                "judgeModel": "judge-model",
                "apiKey": "judge-key",
            }
        },
    )

    raw = await tool.execute(task="test task")
    await tool._wait_for_pending_postprocessing()

    result = json.loads(raw)
    assert result["success"] is True
    extract_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_summarizer_skipped_when_no_trace(
    tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If trace_path is None, summarize_file must NOT be called."""
    from opengui.agent import AgentResult

    async def fake_run(self_inner, task: str, *, max_retries: int = 3, app_hint: str | None = None):
        return AgentResult(
            success=False,
            summary="no trace",
            trace_path=None,
            steps_taken=0,
            error="dry run no trace",
        )

    monkeypatch.setattr("opengui.agent.GuiAgent.run", fake_run)
    monkeypatch.setattr(
        "opengui.skills.extractor.SkillExtractor.extract_from_file",
        AsyncMock(return_value=None),
    )

    tool = _dry_run_tool(tmp_workspace)

    # recorder.path will also be None because agent.run() didn't write anything
    # and we need to ensure the recorder itself returns None for its path.
    # Patch recorder.path to be None via monkeypatching the recorder class.
    from opengui.trajectory import recorder as rec_module

    original_path_property = rec_module.TrajectoryRecorder.path.fget  # type: ignore[attr-defined]

    monkeypatch.setattr(
        rec_module.TrajectoryRecorder,
        "path",
        property(lambda self: None),
    )

    with patch(
        "opengui.trajectory.summarizer.TrajectorySummarizer.summarize_file",
        new_callable=AsyncMock,
    ) as mock_summarize:
        await tool.execute(task="test task")
        await tool._wait_for_pending_postprocessing()

    mock_summarize.assert_not_awaited()


# ---------------------------------------------------------------------------
# Task 2 test: nanobot.agent public API exports
# ---------------------------------------------------------------------------


def test_planner_router_exported_from_agent_package() -> None:
    """TaskPlanner, PlanNode, TreeRouter, NodeResult, RouterContext must be importable from nanobot.agent."""
    from nanobot.agent import NodeResult, PlanNode, RouterContext, TaskPlanner, TreeRouter

    for cls in (TaskPlanner, PlanNode, TreeRouter, NodeResult, RouterContext):
        assert isinstance(cls, type), f"{cls!r} is not a class"


def test_evaluate_gui_trajectory_counts_only_step_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.utils.gui_evaluation import evaluate_gui_trajectory_sync

    trace_path = tmp_path / "trace.jsonl"
    rows = [
        {"type": "metadata", "screenshot_file": "meta.png"},
        {"type": "step", "step_num": 1, "action": "tap", "screenshot_file": "step_001.png"},
        {"type": "attempt_result"},
        {"type": "step", "step_num": 2, "action": "done", "screenshot_file": "step_002.png"},
    ]
    trace_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    for name in ("meta.png", "step_001.png", "step_002.png"):
        (tmp_path / name).write_bytes(b"png")

    captured: dict[str, Any] = {}

    def fake_judge_success(*, client, instruction, traj_rows, screenshots, model, task_id):
        captured["traj_rows"] = traj_rows
        captured["screenshots"] = screenshots
        return True, "ok"

    monkeypatch.setattr("nanobot.utils.gui_evaluation.judge_success", fake_judge_success)
    monkeypatch.setattr("nanobot.utils.gui_evaluation.OpenAI", lambda **kwargs: object())

    result = evaluate_gui_trajectory_sync(
        instruction="test instruction",
        trace_path=trace_path,
        model="judge-model",
        api_key="judge-key",
        api_base="https://judge.example/v1",
        task_id="task-1",
        output_path=None,
    )

    assert result["steps"] == 2
    assert [row.get("type") for row in captured["traj_rows"]] == ["step", "step"]
    assert len(captured["screenshots"]) == 2


def test_eval_script_uses_step_only_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eval.eval import run_eval

    dataset_csv = tmp_path / "dataset.csv"
    dataset_csv.write_text(
        "task_id,instruction,instruction_ch\n"
        "task-1,Open settings,\n",
        encoding="utf-8",
    )

    traj_root = tmp_path / "traces"
    task_dir = traj_root / "task-1"
    task_dir.mkdir(parents=True)
    (task_dir / "traj.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "metadata"}),
                json.dumps({"type": "step", "step_num": 1}),
                json.dumps({"type": "step", "step_num": 2}),
                json.dumps({"type": "result"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_eval(*, instruction, trace_path, model, api_key, api_base, task_id, output_path):
        rows = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {
            "task_id": task_id,
            "instruction": instruction,
            "trace_path": str(trace_path),
            "judge_model": model,
            "success": True,
            "reason": "ok",
            "steps": sum(1 for row in rows if row.get("type") == "step"),
        }

    monkeypatch.setattr("eval.eval.evaluate_gui_trajectory_sync", fake_eval)

    output_dir = tmp_path / "results"
    run_eval(
        dataset_csv=dataset_csv,
        traj_root=traj_root,
        output_dir=output_dir,
        model="judge-model",
        api_key="judge-key",
        api_base="https://judge.example/v1",
        max_samples=None,
    )

    per_task = [
        json.loads(line)
        for line in (output_dir / "per_task_results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))

    assert per_task[0]["steps"] == 2
    assert summary["steps_stats_all"]["mean"] == 2.0
