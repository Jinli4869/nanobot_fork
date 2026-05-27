from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import reextract_gui_skill as single
from opengui.postprocessing import EvaluationConfig


@dataclass(frozen=True)
class TraceJob:
    task_dir: Path
    run_dir: Path
    trace_path: Path
    task: str
    platform: str
    success: bool


@dataclass(frozen=True)
class SkippedTrace:
    trace_path: Path
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch re-run OpenGUI post-run skill extraction under task/nanobot_gui_task_runs directories.",
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Root directory containing task directories, each optionally with nanobot_gui_task_runs/.",
    )
    parser.add_argument(
        "--config-source",
        choices=("nanobot", "opengui"),
        default="nanobot",
        help="Provider config source. Defaults to ~/.nanobot/config.json.",
    )
    parser.add_argument(
        "--nanobot-config",
        type=Path,
        default=single.DEFAULT_NANOBOT_CONFIG,
        help="nanobot config path when --config-source=nanobot.",
    )
    parser.add_argument(
        "--opengui-config",
        type=Path,
        default=single.DEFAULT_OPENGUI_CONFIG,
        help="OpenGUI YAML config path when --config-source=opengui.",
    )
    parser.add_argument(
        "--skill-store-root",
        type=Path,
        default=None,
        help="Override skill store root. Defaults to nanobot gui_skills or OpenGUI skills_dir.",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="Override platform for all traces. Defaults to trace metadata, then android.",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Run only ordinary flat skill extraction, skipping failed-skill evolution.",
    )
    parser.add_argument(
        "--keep-logs",
        action="store_true",
        help="Do not delete existing extraction/evolution log files before rerun.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Extract at most N completed traces.",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="Optional JSON summary output path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List completed/skipped traces without calling the LLM or writing logs.",
    )
    return parser.parse_args()


def discover_jobs(root: Path, *, platform_override: str | None = None) -> tuple[list[TraceJob], list[SkippedTrace]]:
    jobs: list[TraceJob] = []
    skipped: list[SkippedTrace] = []
    for task_dir in _task_dirs(root.expanduser()):
        runs_root = task_dir / "nanobot_gui_task_runs"
        if not runs_root.is_dir():
            continue
        for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            trace_path = _select_trace_file(run_dir)
            if trace_path is None:
                skipped.append(SkippedTrace(run_dir, "missing_trace_jsonl"))
                continue
            completion = _read_attempt_completion(trace_path)
            if completion is None:
                skipped.append(SkippedTrace(trace_path, "missing_completed_attempt_result"))
                continue
            metadata = single.read_trace_metadata(trace_path)
            task = str(metadata.get("task") or "").strip()
            if not task:
                skipped.append(SkippedTrace(trace_path, "missing_task"))
                continue
            platform = str(platform_override or metadata.get("platform") or "android")
            jobs.append(TraceJob(
                task_dir=task_dir,
                run_dir=run_dir,
                trace_path=trace_path,
                task=task,
                platform=platform,
                success=completion,
            ))
    return jobs, skipped


def _task_dirs(root: Path) -> list[Path]:
    if (root / "nanobot_gui_task_runs").is_dir():
        return [root]
    return sorted(path for path in root.iterdir() if path.is_dir())


def _select_trace_file(run_dir: Path) -> Path | None:
    candidates = sorted(run_dir.glob("trace*.jsonl"))
    if not candidates:
        candidates = sorted(run_dir.glob("*.jsonl"))
    if not candidates:
        candidates = sorted(run_dir.rglob("trace*.jsonl"))
    if not candidates:
        candidates = sorted(run_dir.rglob("*.jsonl"))
    if not candidates:
        return None
    for name in ("trace.jsonl",):
        for path in candidates:
            if path.name == name:
                return path
    return candidates[0]


def _read_attempt_completion(trace_path: Path) -> bool | None:
    last_success: bool | None = None
    with trace_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = event.get("type") or event.get("event")
            if event_type == "attempt_result" and isinstance(event.get("success"), bool):
                last_success = bool(event["success"])
    return last_success


async def run(args: argparse.Namespace) -> int:
    jobs, skipped = discover_jobs(args.root, platform_override=args.platform)
    if args.limit is not None:
        jobs = jobs[: max(0, args.limit)]

    bundle = single.load_provider_bundle(args)
    print(f"root: {args.root.expanduser()}")
    print(f"skill_store_root: {bundle.skill_store_root}")
    print(f"embedding: {'enabled' if bundle.embedding_provider is not None else 'disabled'}")
    print(f"completed_traces: {len(jobs)}")
    print(f"skipped_traces: {len(skipped)}")

    records: list[dict[str, Any]] = []
    for skipped_trace in skipped:
        records.append({
            "trace": str(skipped_trace.trace_path),
            "status": "skipped",
            "reason": skipped_trace.reason,
        })

    if args.dry_run:
        for job in jobs:
            print(f"would_extract: {job.trace_path} success={job.success}")
            records.append(_job_record(job, status="dry_run"))
        _write_summary(args.summary_path, records)
        return 0

    processor = single.NoSummaryPostRunProcessor(
        llm=bundle.llm,
        merge_llm=bundle.llm,
        embedding_provider=bundle.embedding_provider,
        embedding_signature=bundle.embedding_signature,
        skill_store_root=bundle.skill_store_root,
        enable_skill_extraction=True,
        evaluation=EvaluationConfig(enabled=False),
    )

    for index, job in enumerate(jobs, start=1):
        print(f"[{index}/{len(jobs)}] extract: {job.trace_path} success={job.success}")
        if not args.keep_logs:
            single.remove_previous_logs(job.trace_path)
        try:
            if args.extract_only:
                await processor._extract_skill(
                    job.trace_path,
                    job.success,
                    job.platform,
                    task=job.task,
                    evaluation_result=None,
                    agent_success=job.success,
                )
            else:
                await processor._run_all(
                    job.trace_path,
                    is_success=job.success,
                    platform=job.platform,
                    task=job.task,
                )
            records.append(_job_record(job, status=_read_extraction_status(job.trace_path)))
        except Exception as exc:
            records.append(_job_record(job, status="error", reason=f"{type(exc).__name__}: {exc}"))

    _write_summary(args.summary_path, records)
    extracted = sum(1 for record in records if record.get("status") not in {"skipped", "dry_run", "error"})
    errors = sum(1 for record in records if record.get("status") == "error")
    print(f"extracted_or_processed: {extracted}")
    print(f"errors: {errors}")
    return 1 if errors else 0


def _read_extraction_status(trace_path: Path) -> str:
    result_path = trace_path.parent / "extraction_result.json"
    if not result_path.exists():
        return "missing_extraction_result"
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid_extraction_result"
    return str(payload.get("status") or "unknown")


def _job_record(job: TraceJob, *, status: str, reason: str | None = None) -> dict[str, Any]:
    record = {
        "task_dir": str(job.task_dir),
        "run_dir": str(job.run_dir),
        "trace": str(job.trace_path),
        "task": job.task,
        "platform": job.platform,
        "success": job.success,
        "status": status,
    }
    if reason:
        record["reason"] = reason
    usage_path = job.trace_path.parent / "extraction_usage.json"
    usage = _read_extraction_usage(usage_path)
    if usage is not None:
        record["extraction_usage_path"] = str(usage_path)
        record["extraction_usage"] = usage
    return record


def _read_extraction_usage(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    usage: dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            usage[str(key)] = value
            continue
        if isinstance(value, float) and value.is_integer():
            usage[str(key)] = int(value)
    return usage


def _write_summary(path: Path | None, records: list[dict[str, Any]]) -> None:
    if path is None:
        return
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    usage_totals: dict[str, int] = {}
    for record in records:
        status = str(record.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        usage = record.get("extraction_usage")
        if isinstance(usage, dict):
            for key, value in usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    usage_totals[str(key)] = usage_totals.get(str(key), 0) + value
    path.write_text(
        json.dumps(
            {
                "status_counts": counts,
                "usage_totals": usage_totals,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"summary_path: {path}")


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
