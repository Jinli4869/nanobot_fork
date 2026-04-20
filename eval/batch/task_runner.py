"""Run a single (task, trial) and parse its trace into a RunRecord."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from eval.batch.judge import judge_run
from eval.batch.metrics import parse_trace
from eval.batch.schemas import RunMetrics, RunRecord, TaskSpec


async def run_one_trial(
    *,
    tool: Any,
    task: TaskSpec,
    trial_index: int,
    judge_model: str,
    judge_api_key: str | None,
    judge_api_base: str | None,
) -> RunRecord:
    """Execute one trial via a constructed GuiSubagentTool. Returns RunRecord."""

    started = time.perf_counter()
    raw = await tool.execute(task=task.prompt)
    duration = time.perf_counter() - started

    try:
        result: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return RunRecord(
            task_id=task.task_id,
            trial_index=trial_index,
            instruction=task.prompt,
            trace_path=None,
            success=False,
            judge_reason="invalid_tool_output",
            error="non-JSON tool result",
            duration_s=duration,
            metrics=RunMetrics(),
        )

    trace_path = result.get("trace_path")
    error = result.get("error")
    metrics = parse_trace(trace_path) if trace_path else RunMetrics()

    success = False
    judge_reason = ""
    if trace_path:
        success, judge_reason = judge_run(
            instruction=task.prompt,
            trace_path=trace_path,
            task_id=task.task_id,
            model=judge_model,
            api_key=judge_api_key,
            api_base=judge_api_base,
        )

    return RunRecord(
        task_id=task.task_id,
        trial_index=trial_index,
        instruction=task.prompt,
        trace_path=trace_path,
        success=success,
        judge_reason=judge_reason,
        error=error,
        duration_s=duration,
        metrics=metrics,
    )
