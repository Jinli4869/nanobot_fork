"""Phase orchestrator: phase A → skill extraction → phase B."""

from __future__ import annotations

import csv
import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from eval.batch.aggregate import render_report, summarize_phase
from eval.batch.schemas import PhaseSummary, RunRecord, TaskSpec
from eval.batch.task_runner import run_one_trial

logger = logging.getLogger(__name__)


def load_tasks(csv_path: Path) -> list[TaskSpec]:
    tasks: list[TaskSpec] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = (row.get("task_id") or "").strip()
            if not tid:
                continue
            tasks.append(
                TaskSpec(
                    task_id=tid,
                    instruction=(row.get("instruction") or "").strip(),
                    instruction_ch=(row.get("instruction_ch") or "").strip(),
                )
            )
    return tasks


def _build_tool(config: Any, *, workspace: Path, provider: Any, model: str) -> Any:
    """Build a fresh GuiSubagentTool from a (possibly modified) Config object."""
    from nanobot.agent.tools.gui import GuiSubagentTool

    return GuiSubagentTool(
        gui_config=config.gui,
        provider=provider,
        model=model,
        workspace=workspace,
    )


def _override_gui(config: Any, **overrides: Any) -> Any:
    """Return a deep copy of config with gui.* attributes patched."""
    new = deepcopy(config)
    for k, v in overrides.items():
        setattr(new.gui, k, v)
    return new


async def _run_phase(
    *,
    phase: str,
    tasks: list[TaskSpec],
    trials: int,
    config: Any,
    workspace: Path,
    provider: Any,
    model: str,
    output_dir: Path,
    judge_model: str,
    judge_api_key: str | None,
    judge_api_base: str | None,
) -> tuple[list[RunRecord], PhaseSummary]:
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_path = output_dir / "runs.jsonl"
    summary_path = output_dir / "summary.json"

    tool = _build_tool(config, workspace=workspace, provider=provider, model=model)
    records: list[RunRecord] = []

    with runs_path.open("w", encoding="utf-8") as f:
        for task in tasks:
            for trial in range(1, trials + 1):
                logger.info("[%s] task=%s trial=%d/%d", phase, task.task_id, trial, trials)
                rec = await run_one_trial(
                    tool=tool,
                    task=task,
                    trial_index=trial,
                    judge_model=judge_model,
                    judge_api_key=judge_api_key,
                    judge_api_base=judge_api_base,
                )
                records.append(rec)
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
                f.flush()

    summary = summarize_phase(phase, records, k=trials)
    summary_path.write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return records, summary


async def _extract_skills_from_phase_a(
    *,
    records: list[RunRecord],
    config: Any,
    provider: Any,
    model: str,
    workspace: Path,
    output_path: Path,
) -> None:
    """Run skill extraction over Phase A successful traces."""
    from nanobot.agent.gui_adapter import NanobotEmbeddingAdapter, NanobotLLMAdapter
    from opengui.postprocessing import EvaluationConfig, PostRunProcessor
    from opengui.skills.normalization import get_gui_skill_store_root

    llm = NanobotLLMAdapter(provider, model)
    processor = PostRunProcessor(
        llm=llm,
        merge_llm=llm,
        embedding_provider=None,  # Embeddings optional; library still works without
        embedding_signature=None,
        skill_store_root=get_gui_skill_store_root(workspace),
        enable_skill_extraction=True,
        evaluation=EvaluationConfig(enabled=False),
    )

    extracted: list[dict[str, Any]] = []
    for rec in records:
        if not rec.success or not rec.trace_path:
            continue
        trace = Path(rec.trace_path)
        # Use platform if recoverable from trace metadata; default unknown.
        platform = "unknown"
        try:
            with trace.open("r", encoding="utf-8") as f:
                first = f.readline()
                if first.strip():
                    meta = json.loads(first)
                    if meta.get("type") == "metadata":
                        platform = meta.get("platform", platform)
        except Exception:
            pass

        processor.schedule(
            trace,
            is_success=True,
            platform=platform,
            task=rec.instruction,
        )
        extracted.append({
            "task_id": rec.task_id,
            "trial_index": rec.trial_index,
            "trace_path": str(trace),
            "platform": platform,
        })

    await processor.drain()
    output_path.write_text(
        json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8",
    )


async def run_batch(
    *,
    dataset_csv: Path,
    output_dir: Path,
    config: Any,
    provider: Any,
    model: str,
    workspace: Path,
    trials: int = 3,
    max_tasks: int | None = None,
    phase: str = "both",  # "a-only" | "b-only" | "both"
    judge_model: str | None = None,
    judge_api_key: str | None = None,
    judge_api_base: str | None = None,
) -> Path:
    """Drive the full A → extract → B pipeline. Returns the output_dir."""
    from opengui.evaluation import DEFAULT_API_BASE, DEFAULT_JUDGE_MODEL

    tasks = load_tasks(dataset_csv)
    if max_tasks is not None:
        tasks = tasks[:max_tasks]

    judge_model = judge_model or DEFAULT_JUDGE_MODEL
    judge_api_base = judge_api_base or DEFAULT_API_BASE

    output_dir.mkdir(parents=True, exist_ok=True)

    summary_a: PhaseSummary | None = None
    summary_b: PhaseSummary | None = None

    if phase in ("a-only", "both"):
        cfg_a = _override_gui(
            config,
            enable_skill_execution=False,
            enable_skill_extraction=False,
        )
        records_a, summary_a = await _run_phase(
            phase="phase_a",
            tasks=tasks,
            trials=trials,
            config=cfg_a,
            workspace=workspace,
            provider=provider,
            model=model,
            output_dir=output_dir / "phase_a",
            judge_model=judge_model,
            judge_api_key=judge_api_key,
            judge_api_base=judge_api_base,
        )

        if phase == "both":
            await _extract_skills_from_phase_a(
                records=records_a,
                config=config,
                provider=provider,
                model=model,
                workspace=workspace,
                output_path=output_dir / "skills_extracted.json",
            )

    if phase in ("b-only", "both"):
        cfg_b = _override_gui(
            config,
            enable_skill_execution=True,
            enable_skill_extraction=False,
        )
        _, summary_b = await _run_phase(
            phase="phase_b",
            tasks=tasks,
            trials=trials,
            config=cfg_b,
            workspace=workspace,
            provider=provider,
            model=model,
            output_dir=output_dir / "phase_b",
            judge_model=judge_model,
            judge_api_key=judge_api_key,
            judge_api_base=judge_api_base,
        )

    if summary_a is not None or summary_b is not None:
        report = render_report(summary_a or summary_b, summary_b if summary_a else None)
        (output_dir / "report.md").write_text(report, encoding="utf-8")

    return output_dir
