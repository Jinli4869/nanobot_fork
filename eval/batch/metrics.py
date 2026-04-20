"""Parse a trace JSONL into RunMetrics."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from eval.batch.schemas import RunMetrics


def _iter_events(trace_path: Path):
    with trace_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _avg(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return mean(xs) if xs else None


def parse_trace(trace_path: Path | str) -> RunMetrics:
    """Walk events and produce RunMetrics."""

    trace_path = Path(trace_path)
    if not trace_path.exists():
        return RunMetrics()

    metrics = RunMetrics()
    step_durations: list[float] = []
    chat_latencies: list[float] = []
    ttfts: list[float] = []
    prompt_tok = 0
    comp_tok = 0
    total_tok = 0

    for event in _iter_events(trace_path):
        etype = event.get("type")
        if etype == "step":
            metrics.steps += 1
            usage = event.get("token_usage") or {}
            prompt_tok += int(usage.get("prompt_tokens", 0))
            comp_tok += int(usage.get("completion_tokens", 0))
            total_tok += int(usage.get("total_tokens", 0))
            if event.get("duration_s") is not None:
                step_durations.append(float(event["duration_s"]))
            if event.get("chat_latency_s") is not None:
                chat_latencies.append(float(event["chat_latency_s"]))
            if event.get("ttft_s") is not None:
                ttfts.append(float(event["ttft_s"]))
        elif etype in {"subgoal_step", "skill_step"}:
            usage = event.get("token_usage") or {}
            prompt_tok += int(usage.get("prompt_tokens", 0))
            comp_tok += int(usage.get("completion_tokens", 0))
            total_tok += int(usage.get("total_tokens", 0))
            if event.get("chat_latency_s") is not None:
                chat_latencies.append(float(event["chat_latency_s"]))
            if event.get("ttft_s") is not None:
                ttfts.append(float(event["ttft_s"]))
        elif etype == "skill_search":
            if event.get("matched") is True:
                metrics.skill_hit = True
        elif etype == "skill_execution_result":
            if event.get("state") == "succeeded":
                metrics.skill_executed_success = True

    metrics.prompt_tokens = prompt_tok
    metrics.completion_tokens = comp_tok
    metrics.total_tokens = total_tok or (prompt_tok + comp_tok)
    metrics.avg_step_duration_s = _avg(step_durations)
    metrics.avg_chat_latency_s = _avg(chat_latencies)
    metrics.avg_ttft_s = _avg(ttfts)
    return metrics
