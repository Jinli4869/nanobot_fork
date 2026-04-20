"""
opengui.postprocessing
======================
Post-run background processor for GUI task trajectories.

Manages trajectory summarization, skill extraction/promotion, and evaluation
as non-blocking background tasks with explicit lifecycle control via
:meth:`PostRunProcessor.drain`.

Usage::

    processor = PostRunProcessor(
        llm=my_llm_adapter,
        embedding_provider=my_embedding_adapter,
        skill_store_root=Path("~/.opengui/skills"),
        enable_skill_extraction=True,
        evaluation=EvaluationConfig(enabled=True, ...),
    )

    # After each GUI task completes — returns immediately, work runs in background.
    processor.schedule(trace_path, is_success=True, platform="android", task="Open Settings")

    # Before process shutdown — blocks until all background work finishes.
    await processor.drain()
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EVALUATION_FILENAME = "evaluation.json"

# Error strings (or prefixes) on the trajectory's final `result` event that
# indicate the run was cut short by a detector or infrastructure fault rather
# than reaching a meaningful outcome. These trajectories are excluded from
# skill extraction to avoid polluting the library with noise.
_ABNORMAL_TERMINATION_PREFIXES: tuple[str, ...] = (
    "stagnation_detected",     # opengui/agent.py — SSIM-detected repeat action/screen
    "step_timeout",            # opengui/agent.py — per-step timeout
    "intervention_cancelled",  # opengui/agent.py — human intervention cancelled (prefix)
)


def _load_trajectory_result(trace_path: Path) -> dict[str, Any] | None:
    """Return the final `result` event from a trajectory JSONL, or None."""
    import json

    try:
        with open(trace_path, "r", encoding="utf-8") as f:
            last: dict[str, Any] | None = None
            for line in f:
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


def _is_abnormal_termination(result_event: dict[str, Any]) -> bool:
    """True if the trajectory was cut short by a detector/infra fault."""
    error = result_event.get("error")
    total_steps = result_event.get("total_steps") or 0
    # Preflight errors never execute a step; `error` is an arbitrary exception string.
    if total_steps == 0 and error:
        return True
    if not isinstance(error, str):
        return False
    return any(
        error == prefix or error.startswith(prefix + ":")
        for prefix in _ABNORMAL_TERMINATION_PREFIXES
    )


@dataclass
class EvaluationConfig:
    """Mirrors the evaluation subset of the host config."""

    enabled: bool = False
    judge_model: str = "qwen3-vl-plus"
    api_key: str = ""
    api_base: str | None = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class _TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


class PostRunProcessor:
    """Schedule and manage post-run background tasks for GUI trajectories.

    All public methods are thread-safe with respect to the asyncio event loop
    they are called from.  Background work is tracked via :pyclass:`asyncio.Task`
    instances and can be awaited collectively through :meth:`drain`.
    """

    def __init__(
        self,
        *,
        llm: Any,
        merge_llm: Any | None = None,
        embedding_provider: Any | None = None,
        embedding_signature: str | None = None,
        skill_store_root: Path | None = None,
        enable_skill_extraction: bool = False,
        evaluation: EvaluationConfig = field(default_factory=EvaluationConfig),
    ) -> None:
        self._llm = llm
        self._merge_llm = merge_llm
        self._embedding_provider = embedding_provider
        self._embedding_signature = embedding_signature
        self._skill_store_root = skill_store_root
        self._enable_skill_extraction = enable_skill_extraction
        self._evaluation = evaluation
        self._pending: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def schedule(
        self,
        trace_path: Path | None,
        *,
        is_success: bool,
        platform: str,
        task: str,
    ) -> None:
        """Fire-and-forget post-processing for a completed GUI run.

        Returns immediately.  The actual work (summarize, extract, evaluate)
        runs concurrently in the background.
        """
        if trace_path is None or not trace_path.exists():
            return

        bg = asyncio.create_task(
            self._run_all(trace_path, is_success=is_success, platform=platform, task=task),
            name=f"postprocess-{trace_path.stem}",
        )
        self._pending.add(bg)
        bg.add_done_callback(self._on_done)

    async def drain(self) -> None:
        """Await all pending background tasks.  Safe to call multiple times."""
        if not self._pending:
            return
        await asyncio.gather(*list(self._pending), return_exceptions=True)

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    async def _run_all(
        self,
        trace_path: Path,
        *,
        is_success: bool,
        platform: str,
        task: str,
    ) -> None:
        summary, _, _ = await asyncio.gather(
            self._summarize_trajectory(trace_path),
            self._extract_skill(trace_path, is_success, platform),
            self._run_evaluation(trace_path=trace_path, is_success=is_success, task=task),
        )
        if summary:
            logger.info("Trajectory summary: %s", summary[:200])

    # ------------------------------------------------------------------
    # Summarization
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Skill extraction / shortcut promotion
    # ------------------------------------------------------------------

    async def _extract_skill(
        self, trace_path: Path, is_success: bool, platform: str,
    ) -> str | None:
        if not self._enable_skill_extraction:
            logger.info("Skipping skill extraction: disabled")
            return None
        if not trace_path.exists():
            return None

        # Skip runs cut short by a detector or infra fault — stagnation (repeat
        # action/screen), step timeout, intervention cancel, preflight error.
        result_event = _load_trajectory_result(trace_path)
        if result_event is not None and _is_abnormal_termination(result_event):
            reason = result_event.get("error")
            logger.info(
                "Skipping skill extraction for abnormally-terminated trajectory "
                "(reason=%s, total_steps=%s): %s",
                reason,
                result_event.get("total_steps"),
                trace_path,
            )
            self._write_extraction_result(trace_path, {
                "status": "skipped_abnormal",
                "trace": str(trace_path),
                "is_success": is_success,
                "platform": platform,
                "reason": reason,
                "total_steps": result_event.get("total_steps"),
            })
            return None

        from opengui.skills.extractor import SkillExtractor
        from opengui.skills.library import SkillLibrary

        try:
            extractor = SkillExtractor(llm=self._llm)
            skill = await extractor.extract_from_file(trace_path, is_success=is_success)
            self._write_extraction_usage(trace_path, extractor.total_usage)
            if skill is None:
                logger.info(
                    "No skill candidate extracted from %s",
                    trace_path,
                )
                self._write_extraction_result(trace_path, {
                    "status": "no_candidate",
                    "trace": str(trace_path),
                    "is_success": is_success,
                    "platform": platform,
                })
                return None

            library = SkillLibrary(
                store_dir=self._skill_store_root,
                embedding_provider=self._embedding_provider,
                merge_llm=self._merge_llm,
                embedding_signature=self._embedding_signature,
            )
            decision, skill_id = await library.add_or_merge(skill)
            final_id = skill_id or skill.skill_id
            logger.info(
                "Extracted skill %s from %s via %s",
                final_id,
                trace_path,
                decision,
            )

            self._write_extraction_result(trace_path, {
                "status": "processed",
                "decision": decision,
                "trace": str(trace_path),
                "is_success": is_success,
                "platform": platform,
                "extracted_skill": {
                    "skill_id": skill.skill_id,
                    "name": skill.name,
                    "app": skill.app,
                    "step_count": len(skill.steps),
                },
                "result_skill_id": final_id,
            })
            return final_id
        except Exception:
            logger.warning("Skill extraction failed for %s", trace_path, exc_info=True)
            self._write_extraction_result(trace_path, {
                "status": "error",
                "trace": str(trace_path),
                "is_success": is_success,
                "platform": platform,
            })
            return None

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        """Persist LLM token usage from skill extraction next to the trace file."""
        import json

        usage_path = trace_path.parent / "extraction_usage.json"
        try:
            usage_path.write_text(json.dumps(usage, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write extraction usage to %s: %s", usage_path, exc)

    @staticmethod
    def _write_extraction_result(
        trace_path: Path, result: dict[str, Any],
    ) -> None:
        """Persist skill extraction outcome next to the trace file.

        Writes ``extraction_result.json`` containing the decision
        (ADD / MERGE / KEEP_OLD / KEEP_NEW), extracted skill metadata,
        or a ``no_candidate`` / ``error`` status so that every extraction
        attempt leaves an auditable record.
        """
        import json
        import time as _time

        result.setdefault("timestamp", _time.time())
        result_path = trace_path.parent / "extraction_result.json"
        try:
            result_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(
                "Could not write extraction result to %s: %s",
                result_path, exc,
            )
