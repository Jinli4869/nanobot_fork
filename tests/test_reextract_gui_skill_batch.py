from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_batch_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "reextract_gui_skill_batch.py"
    spec = importlib.util.spec_from_file_location("reextract_gui_skill_batch", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def test_discover_jobs_requires_completed_attempt_result(tmp_path: Path) -> None:
    batch = _load_batch_module()
    root = tmp_path / "runs"
    complete = root / "TaskA" / "nanobot_gui_task_runs" / "0" / "trace.jsonl"
    failed = root / "TaskB" / "nanobot_gui_task_runs" / "0" / "trace_001.jsonl"
    incomplete = root / "TaskC" / "nanobot_gui_task_runs" / "0" / "trace.jsonl"
    result_only = root / "TaskD" / "nanobot_gui_task_runs" / "0" / "trace.jsonl"

    _write_jsonl(complete, [
        {"event": "attempt_start", "task": "Open YouTube"},
        {"event": "step", "prompt": {"current_observation": {"platform": "android"}}},
        {"event": "attempt_result", "success": True},
    ])
    _write_jsonl(failed, [
        {"type": "metadata", "task": "Open Bilibili", "platform": "android"},
        {"type": "attempt_result", "success": False},
    ])
    _write_jsonl(incomplete, [
        {"event": "attempt_start", "task": "Still running"},
        {"event": "step", "prompt": {"current_observation": {"platform": "android"}}},
    ])
    _write_jsonl(result_only, [
        {"type": "metadata", "task": "Has result only", "platform": "android"},
        {"type": "result", "success": True},
    ])

    jobs, skipped = batch.discover_jobs(root)

    assert [(job.trace_path.name, job.task, job.platform, job.success) for job in jobs] == [
        ("trace.jsonl", "Open YouTube", "android", True),
        ("trace_001.jsonl", "Open Bilibili", "android", False),
    ]
    assert [item.reason for item in skipped] == [
        "missing_completed_attempt_result",
        "missing_completed_attempt_result",
    ]


def test_discover_jobs_supports_task_root_directly(tmp_path: Path) -> None:
    batch = _load_batch_module()
    task_root = tmp_path / "TaskA"
    trace = task_root / "nanobot_gui_task_runs" / "0" / "trace.jsonl"
    _write_jsonl(trace, [
        {"event": "attempt_start", "task": "Open Settings"},
        {"event": "attempt_result", "success": True},
    ])

    jobs, skipped = batch.discover_jobs(task_root, platform_override="android")

    assert not skipped
    assert len(jobs) == 1
    assert jobs[0].task_dir == task_root
    assert jobs[0].platform == "android"


def test_summary_includes_extraction_usage(tmp_path: Path) -> None:
    batch = _load_batch_module()
    task_root = tmp_path / "TaskA"
    run_dir = task_root / "nanobot_gui_task_runs" / "0"
    trace = run_dir / "trace.jsonl"
    _write_jsonl(trace, [
        {"event": "attempt_start", "task": "Open Settings"},
        {"event": "attempt_result", "success": True},
    ])
    (run_dir / "extraction_usage.json").write_text(
        json.dumps({"prompt": 10, "completion": 3, "cached": 2}, ensure_ascii=False),
        encoding="utf-8",
    )
    jobs, _skipped = batch.discover_jobs(task_root, platform_override="android")
    record = batch._job_record(jobs[0], status="processed_code")
    summary_path = tmp_path / "summary.json"

    batch._write_summary(summary_path, [record])

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["usage_totals"] == {"prompt": 10, "completion": 3, "cached": 2}
    assert summary["processed_code_total"] == 1
    assert summary["no_candidate_total"] == 0
    assert summary["skipped_total"] == 0
    assert summary["error_total"] == 0
    assert summary["records"][0]["extraction_usage"] == {
        "prompt": 10,
        "completion": 3,
        "cached": 2,
    }
    assert summary["records"][0]["extraction_usage_path"] == str(run_dir / "extraction_usage.json")
