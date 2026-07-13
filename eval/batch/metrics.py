"""Parse compact ``traj.json`` artifacts into RunMetrics."""

from __future__ import annotations

import json
from pathlib import Path

from eval.batch.schemas import RunMetrics


def parse_trace(trace_path: Path | str) -> RunMetrics:
    """Walk events and produce RunMetrics."""

    trace_path = Path(trace_path)
    if not trace_path.exists():
        return RunMetrics()

    metrics = RunMetrics()
    prompt_tok = 0
    comp_tok = 0
    total_tok = 0

    try:
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return metrics
    for step in payload.get("steps", []) if isinstance(payload, dict) else []:
        if not isinstance(step, dict):
            continue
        metrics.steps += 1
        usage = step.get("token_usage") or {}
        prompt_tok += int(usage.get("prompt_tokens", 0))
        comp_tok += int(usage.get("completion_tokens", 0))
        total_tok += int(usage.get("total_tokens", 0))
        skill = step.get("skill")
        if isinstance(skill, dict):
            metrics.skill_hit = True
            if skill.get("state") == "succeeded":
                metrics.skill_executed_success = True

    metrics.prompt_tokens = prompt_tok
    metrics.completion_tokens = comp_tok
    metrics.total_tokens = total_tok or (prompt_tok + comp_tok)
    return metrics
