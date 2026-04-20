"""Vision-LLM judge wrapper with on-disk cache keyed by trace path."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from opengui.evaluation import (
    DEFAULT_API_BASE,
    DEFAULT_JUDGE_MODEL,
    evaluate_gui_trajectory_sync,
)


def judge_run(
    *,
    instruction: str,
    trace_path: Path | str,
    task_id: str,
    model: str = DEFAULT_JUDGE_MODEL,
    api_key: str | None = None,
    api_base: str | None = DEFAULT_API_BASE,
    cache_dir: Path | None = None,
) -> tuple[bool, str]:
    """Judge one trace; cache the result next to the trace by default."""

    trace_path = Path(trace_path)
    api_key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return False, "missing_api_key"

    cache_path = (cache_dir or trace_path.parent) / f"{trace_path.stem}.judge.json"
    if cache_path.exists():
        try:
            cached: dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8"))
            return bool(cached.get("success", False)), str(cached.get("reason", ""))
        except Exception:
            pass

    record = evaluate_gui_trajectory_sync(
        instruction=instruction,
        trace_path=trace_path,
        model=model,
        api_key=api_key,
        api_base=api_base,
        task_id=task_id,
        output_path=None,
    )
    success = bool(record.get("success", False))
    reason = str(record.get("reason", "")).strip()
    try:
        cache_path.write_text(
            json.dumps({"success": success, "reason": reason}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
    return success, reason
