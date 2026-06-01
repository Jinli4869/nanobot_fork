"""
opengui.postprocessing
======================
Post-run background processor for GUI task trajectories.

This module intentionally keeps the learning path flat:

    summarize/evaluate trace -> evolve failed reused Skill or extract Skill -> write skills.py

There is no skill graph, transition evidence, deeplink discovery, or
JSON-backed skill store in this path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EVALUATION_FILENAME = "evaluation.json"
_FLAT_SKILL_LOCKS: dict[Path, asyncio.Lock] = {}

_ABNORMAL_TERMINATION_PREFIXES: tuple[str, ...] = (
    "stagnation_detected",
    "step_timeout",
    "intervention_cancelled",
)


def _load_trajectory_result(trace_path: Path) -> dict[str, Any] | None:
    """Return the final result event from a trajectory JSONL, or None."""
    try:
        last: dict[str, Any] | None = None
        with open(trace_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") == "result":
                    last = event
        return last
    except OSError:
        return None


def _load_completed_reuse(trace_path: Path) -> dict[str, Any] | None:
    """Return reuse metadata when a reused flat skill completed the task."""
    full_reuse: dict[str, Any] | None = None
    agent_work_after_full_reuse = False
    try:
        with open(trace_path, "r", encoding="utf-8") as handle:
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
                event_type = event.get("type")
                if event_type == "step" and full_reuse is not None:
                    action = event.get("action")
                    action_type = action.get("action_type") if isinstance(action, dict) else None
                    if action_type != "done":
                        agent_work_after_full_reuse = True
                    continue
                if event_type == "skill_execution_result" and event.get("state") == "succeeded":
                    full_reuse = {
                        "reuse_source": "skill",
                        "skill_id": event.get("skill_id"),
                        "skill_name": event.get("skill_name"),
                    }
                    agent_work_after_full_reuse = False
    except OSError:
        return None
    if agent_work_after_full_reuse:
        return None
    return full_reuse


def _is_abnormal_termination(result_event: dict[str, Any]) -> bool:
    """True if the trajectory was cut short by detector or infrastructure noise."""
    error = result_event.get("error")
    total_steps = result_event.get("total_steps") or 0
    if total_steps == 0 and error:
        return True
    if not isinstance(error, str):
        return False
    if total_steps > 0 and (
        error == "stagnation_detected"
        or error.startswith("stagnation_detected:")
        or error == "step_timeout"
        or error.startswith("step_timeout:")
    ):
        return False
    return any(
        error == prefix or error.startswith(prefix + ":")
        for prefix in _ABNORMAL_TERMINATION_PREFIXES
    )


def _learning_mode(is_success: bool) -> str:
    return "success_full" if is_success else "failure_prefix"


@dataclass
class EvaluationConfig:
    """Mirrors the evaluation subset of the host config."""

    enabled: bool = False
    judge_model: str = "qwen3-vl-plus"
    api_key: str = ""
    api_base: str | None = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class PostRunProcessor:
    """Schedule and manage post-run background tasks for GUI trajectories."""

    def __init__(
        self,
        *,
        llm: Any,
        merge_llm: Any | None = None,
        embedding_provider: Any | None = None,
        embedding_signature: str | None = None,
        skill_store_root: Path | None = None,
        enable_skill_extraction: bool = False,
        evaluation: EvaluationConfig | None = None,
    ) -> None:
        self._llm = llm
        self._merge_llm = merge_llm
        self._embedding_provider = embedding_provider
        self._embedding_signature = embedding_signature
        self._skill_store_root = skill_store_root
        self._enable_skill_extraction = enable_skill_extraction
        self._evaluation = evaluation or EvaluationConfig()
        self._pending: set[asyncio.Task[None]] = set()

    def schedule(
        self,
        trace_path: Path | None,
        *,
        is_success: bool,
        platform: str,
        task: str,
    ) -> None:
        if trace_path is None or not trace_path.exists():
            return
        bg = asyncio.create_task(
            self._run_all(trace_path, is_success=is_success, platform=platform, task=task),
            name=f"postprocess-{trace_path.stem}",
        )
        self._pending.add(bg)
        bg.add_done_callback(self._on_done)

    async def drain(self) -> None:
        if not self._pending:
            return
        await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def _run_all(
        self,
        trace_path: Path,
        *,
        is_success: bool,
        platform: str,
        task: str,
    ) -> None:
        summary, evaluation_result = await asyncio.gather(
            self._summarize_trajectory(trace_path),
            self._run_evaluation(trace_path=trace_path, is_success=is_success, task=task),
        )
        effective_success = is_success
        if isinstance(evaluation_result, dict) and evaluation_result.get("success") is False:
            effective_success = False
        evolution_result = await self._evolve_failed_skill(
            trace_path,
            effective_success,
            platform,
            task=task,
            evaluation_result=evaluation_result,
            agent_success=is_success,
        )
        if evolution_result is not None and evolution_result.get("status") != "no_failure_case":
            if summary:
                logger.info("Trajectory state note: %s", summary.replace("\n", " | ")[:200])
            return
        await self._extract_skill(
            trace_path,
            effective_success,
            platform,
            task=task,
            evaluation_result=evaluation_result,
            agent_success=is_success,
        )
        if summary:
            logger.info("Trajectory state note: %s", summary.replace("\n", " | ")[:200])

    async def _summarize_trajectory(self, trace_path: Path) -> str:
        if not trace_path.exists():
            return ""
        try:
            from opengui.trajectory.summarizer import TrajectorySummarizer

            summarizer = TrajectorySummarizer(llm=self._llm)
            return await summarizer.summarize_file(trace_path)
        except Exception:
            logger.warning("Trajectory summarization failed for %s", trace_path, exc_info=True)
            return ""

    async def _evolve_failed_skill(
        self,
        trace_path: Path,
        is_success: bool,
        platform: str,
        *,
        task: str | None = None,
        evaluation_result: dict[str, Any] | None = None,
        agent_success: bool | None = None,
    ) -> dict[str, Any] | None:
        if not self._enable_skill_extraction:
            return None
        if not trace_path.exists():
            return None

        store_root = self._skill_store_root or trace_path.parent
        lock = _FLAT_SKILL_LOCKS.setdefault(
            store_root.expanduser().resolve(strict=False),
            asyncio.Lock(),
        )
        try:
            from opengui.skills.evolution import evolve_failed_skill_from_trace

            async with lock:
                result = await evolve_failed_skill_from_trace(
                    llm=self._llm,
                    trace_path=trace_path,
                    store_root=store_root,
                    task=task,
                    platform=platform,
                    embedding_provider=self._embedding_provider,
                    embedding_signature=self._embedding_signature,
                )
        except Exception as exc:
            logger.warning("Skill evolution failed for %s", trace_path, exc_info=True)
            result = {
                "status": "error",
                "trace": str(trace_path),
                "reason": str(exc) or type(exc).__name__,
                "error_type": type(exc).__name__,
            }

        self._write_evolution_result(trace_path, result)
        if result.get("status") == "no_failure_case":
            return result

        status = "processed_evolution" if result.get("status") == "processed_evolution" else "evolution_error"
        self._write_extraction_result(trace_path, {
            "status": status,
            "trace": str(trace_path),
            "is_success": is_success,
            "agent_success": agent_success,
            "evaluation_success": _evaluation_success(evaluation_result),
            "platform": platform,
            "task": task,
            "learning_mode": _learning_mode(is_success),
            "updated_functions": list(result.get("updated_functions") or []),
            "compiled_skill_ids": list(result.get("compiled_skill_ids") or []),
            "evolution": result,
            "reuse_failure_trace": True,
            "ordinary_code_extraction_skipped": True,
        })
        return result

    async def _extract_skill(
        self,
        trace_path: Path,
        is_success: bool,
        platform: str,
        *,
        task: str | None = None,
        evaluation_result: dict[str, Any] | None = None,
        agent_success: bool | None = None,
    ) -> str | None:
        if not self._enable_skill_extraction:
            logger.info("Skipping skill extraction: disabled")
            return None
        if not trace_path.exists():
            return None

        result_event = _load_trajectory_result(trace_path)
        if result_event is not None and _is_abnormal_termination(result_event):
            self._write_extraction_result(trace_path, {
                "status": "skipped",
                "reason": "abnormal_termination",
                "trace": str(trace_path),
                "is_success": is_success,
                "agent_success": agent_success,
                "evaluation_success": _evaluation_success(evaluation_result),
                "platform": platform,
                "learning_mode": _learning_mode(is_success),
                "updated_functions": [],
                "compiled_skill_ids": [],
            })
            return None

        completed_reuse = _load_completed_reuse(trace_path)
        if completed_reuse is not None:
            self._write_extraction_result(trace_path, {
                "status": "skipped_reused_skill_complete",
                "trace": str(trace_path),
                "is_success": is_success,
                "agent_success": agent_success,
                "evaluation_success": _evaluation_success(evaluation_result),
                "platform": platform,
                "learning_mode": _learning_mode(is_success),
                "updated_functions": [],
                "compiled_skill_ids": [],
                **completed_reuse,
            })
            return None

        try:
            from opengui.skills.extractor import SkillExtractor

            extractor = SkillExtractor(llm=self._llm)
            skills = await extractor.extract_from_file_multi(trace_path, is_success=is_success)
            self._write_extraction_usage(trace_path, extractor.total_usage)
            if not skills:
                self._write_extraction_result(trace_path, {
                    "status": "no_candidate",
                    "reason": "extractor_returned_none",
                    "trace": str(trace_path),
                    "is_success": is_success,
                    "agent_success": agent_success,
                    "evaluation_success": _evaluation_success(evaluation_result),
                    "platform": platform,
                    "learning_mode": _learning_mode(is_success),
                    "updated_functions": [],
                    "compiled_skill_ids": [],
                    "extractor_diagnostics": extractor.last_diagnostics,
                })
                return None

            store_root = self._skill_store_root or trace_path.parent
            lock = _FLAT_SKILL_LOCKS.setdefault(
                store_root.expanduser().resolve(strict=False),
                asyncio.Lock(),
            )
            skill_infos = []
            compiled_skill_ids: list[str] = []

            async with lock:
                from opengui.skills.flat import FlatSkillLibrary

                library = FlatSkillLibrary(
                    store_dir=store_root,
                    embedding_provider=self._embedding_provider,
                    merge_llm=self._merge_llm,
                    embedding_signature=self._embedding_signature,
                )
                for skill in skills:
                    decision, skill_id = await library.add_or_merge(skill)
                    skill_infos.append(
                        {
                            "skill_id": skill_id,
                            "decision": decision,
                            "name": skill.name,
                            "description": skill.description,
                            "app": skill.app,
                            "platform": skill.platform,
                            "step_count": len(skill.steps),
                        },
                    )
                    if skill_id is not None:
                        compiled_skill_ids.append(skill_id)

            first_skill = skills[0]

            self._write_extraction_result(trace_path, {
                "status": "processed_code",
                "trace": str(trace_path),
                "is_success": is_success,
                "agent_success": agent_success,
                "evaluation_success": _evaluation_success(evaluation_result),
                "platform": platform,
                "task": task,
                "learning_mode": _learning_mode(is_success),
                "updated_functions": [skill.name for skill in skills],
                "compiled_skill_ids": compiled_skill_ids,
                "source_path": str((store_root / "skills.py").expanduser()),
                "extractor_diagnostics": extractor.last_diagnostics,
                "skills": skill_infos,
                "skill": {
                    "skill_id": first_skill.skill_id,
                    "name": first_skill.name,
                    "description": first_skill.description,
                    "app": first_skill.app,
                    "platform": first_skill.platform,
                    "step_count": len(first_skill.steps),
                },
            })
            return compiled_skill_ids[0]
        except Exception as exc:
            logger.warning("Skill extraction failed for %s", trace_path, exc_info=True)
            self._write_extraction_result(trace_path, {
                "status": "error",
                "trace": str(trace_path),
                "reason": str(exc) or type(exc).__name__,
                "error_type": type(exc).__name__,
                "is_success": is_success,
                "agent_success": agent_success,
                "evaluation_success": _evaluation_success(evaluation_result),
                "platform": platform,
                "learning_mode": _learning_mode(is_success),
                "updated_functions": [],
                "compiled_skill_ids": [],
            })
            return None

    async def _run_evaluation(
        self,
        *,
        trace_path: Path,
        is_success: bool,
        task: str,
    ) -> dict[str, Any] | None:
        if not self._evaluation.enabled:
            return None
        if not is_success:
            logger.info("Skipping GUI evaluation for unsuccessful task: %s", task)
            return None
        if not trace_path.exists():
            logger.info("Skipping GUI evaluation: trace missing %s", trace_path)
            return None

        api_key = self._evaluation.api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            logger.info("Skipping GUI evaluation: no api_key configured")
            return None

        try:
            from opengui.evaluation import evaluate_gui_trajectory

            result = await evaluate_gui_trajectory(
                instruction=task,
                trace_path=trace_path,
                model=self._evaluation.judge_model,
                api_key=api_key,
                api_base=self._evaluation.api_base,
                task_id=trace_path.parent.name,
                output_path=trace_path.parent / DEFAULT_EVALUATION_FILENAME,
            )
            logger.info(
                "GUI evaluation completed: success=%s reason=%s",
                result.get("success"),
                result.get("reason"),
            )
            return result
        except Exception:
            logger.warning("GUI evaluation failed for %s", trace_path, exc_info=True)
            return None

    def _on_done(self, task: asyncio.Task[None]) -> None:
        self._pending.discard(task)
        if task.cancelled():
            logger.debug("Post-processing task was cancelled: %s", task.get_name())
            return
        try:
            exc = task.exception()
        except Exception:
            logger.warning("Post-processing task failed", exc_info=True)
            return
        if exc is not None:
            logger.warning(
                "Post-processing task failed: %s",
                task.get_name(),
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    @staticmethod
    def _write_extraction_usage(trace_path: Path, usage: dict[str, int]) -> None:
        usage_path = trace_path.parent / "extraction_usage.json"
        try:
            usage_path.write_text(json.dumps(usage, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write extraction usage to %s: %s", usage_path, exc)

    @staticmethod
    def _write_evolution_result(trace_path: Path, result: dict[str, Any]) -> None:
        result.setdefault("timestamp", time.time())
        result_path = trace_path.parent / "evolution_result.json"
        try:
            result_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not write evolution result to %s: %s", result_path, exc)

    @staticmethod
    def _write_extraction_result(trace_path: Path, result: dict[str, Any]) -> None:
        result.setdefault("timestamp", time.time())
        result_path = trace_path.parent / "extraction_result.json"
        try:
            result_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not write extraction result to %s: %s", result_path, exc)


def _evaluation_success(evaluation_result: dict[str, Any] | None) -> bool | None:
    if not isinstance(evaluation_result, dict):
        return None
    value = evaluation_result.get("success")
    return value if isinstance(value, bool) else None


__all__ = [
    "DEFAULT_EVALUATION_FILENAME",
    "EvaluationConfig",
    "PostRunProcessor",
    "_is_abnormal_termination",
    "_learning_mode",
    "_load_completed_reuse",
    "_load_trajectory_result",
]
