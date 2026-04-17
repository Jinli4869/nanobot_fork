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
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EVALUATION_FILENAME = "evaluation.json"
DEFAULT_MEMORY_CANDIDATE_FILENAME = "memory_candidate.json"
DEFAULT_MEMORY_REVIEW_QUEUE = Path.home() / ".opengui" / "memory" / "review_queue.jsonl"


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
        skill_store_root: Path | None = None,
        enable_skill_extraction: bool = False,
        evaluation: EvaluationConfig = field(default_factory=EvaluationConfig),
        max_pending: int = 6,
        max_parallel: int = 1,
        summarize_timeout_seconds: float = 20.0,
        skill_timeout_seconds: float = 60.0,
        evaluation_timeout_seconds: float = 60.0,
        memory_candidate_timeout_seconds: float = 5.0,
    ) -> None:
        self._llm = llm
        self._merge_llm = merge_llm
        self._embedding_provider = embedding_provider
        self._skill_store_root = skill_store_root
        self._enable_skill_extraction = enable_skill_extraction
        self._evaluation = evaluation
        self._pending: set[asyncio.Task[None]] = set()
        self._max_pending = max(1, int(max_pending))
        self._semaphore = asyncio.Semaphore(max(1, int(max_parallel)))
        self._summarize_timeout_seconds = max(1.0, float(summarize_timeout_seconds))
        self._skill_timeout_seconds = max(1.0, float(skill_timeout_seconds))
        self._evaluation_timeout_seconds = max(1.0, float(evaluation_timeout_seconds))
        self._memory_candidate_timeout_seconds = max(1.0, float(memory_candidate_timeout_seconds))

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
        if len(self._pending) >= self._max_pending:
            logger.warning(
                "Skipping post-processing for %s: pending queue is full (%d/%d)",
                trace_path,
                len(self._pending),
                self._max_pending,
            )
            return

        bg = asyncio.create_task(
            self._run_guarded(trace_path, is_success=is_success, platform=platform, task=task),
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

    async def _run_guarded(
        self,
        trace_path: Path,
        *,
        is_success: bool,
        platform: str,
        task: str,
    ) -> None:
        """Limit concurrent postprocessing so learning never blocks user work."""
        async with self._semaphore:
            await self._run_all(trace_path, is_success=is_success, platform=platform, task=task)

    async def _run_all(
        self,
        trace_path: Path,
        *,
        is_success: bool,
        platform: str,
        task: str,
    ) -> None:
        summary, _, evaluation_result = await asyncio.gather(
            self._run_with_timeout(
                self._summarize_trajectory(trace_path),
                timeout_seconds=self._summarize_timeout_seconds,
                stage="summarization",
                default="",
            ),
            self._run_with_timeout(
                self._extract_skill(trace_path, is_success, platform),
                timeout_seconds=self._skill_timeout_seconds,
                stage="skill_extraction",
                default=None,
            ),
            self._run_with_timeout(
                self._run_evaluation(trace_path=trace_path, is_success=is_success, task=task),
                timeout_seconds=self._evaluation_timeout_seconds,
                stage="evaluation",
                default=None,
            ),
        )
        await self._run_with_timeout(
            self._emit_memory_candidate(
                trace_path=trace_path,
                is_success=is_success,
                platform=platform,
                task=task,
                summary=summary,
                evaluation_result=evaluation_result,
            ),
            timeout_seconds=self._memory_candidate_timeout_seconds,
            stage="memory_candidate",
            default=None,
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

    async def _emit_memory_candidate(
        self,
        *,
        trace_path: Path,
        is_success: bool,
        platform: str,
        task: str,
        summary: str,
        evaluation_result: dict[str, Any] | None,
    ) -> None:
        """Create a pending memory candidate for successful common tasks.

        This is a conservative "online learning" queue:
        - only emits candidates for high-quality successful traces,
        - writes to a review queue,
        - does NOT auto-promote into memory files.
        """
        if not is_success or not trace_path.exists():
            return
        if evaluation_result is not None and not bool(evaluation_result.get("success", False)):
            return

        quality = self._analyze_trace_quality(trace_path)
        if not quality["eligible"]:
            return

        latest_app = quality.get("latest_foreground_app")
        memory_type = self._classify_memory_type(task=task, summary=summary, latest_app=latest_app)
        content = self._build_memory_candidate_content(task=task, summary=summary, latest_app=latest_app)
        confidence = self._estimate_candidate_confidence(
            quality=quality,
            has_summary=bool(summary.strip()),
            eval_success=bool(evaluation_result and evaluation_result.get("success")),
        )
        candidate = {
            "entry_id": str(uuid.uuid4()),
            "memory_type": memory_type,
            "platform": platform,
            "app": latest_app if memory_type == "app" else None,
            "tags": ["online_learning", "post_run_candidate"],
            "created_at": time.time(),
            "access_count": 0,
            "confidence": confidence,
            "source": "online_learning",
            "review_status": "pending",
            "success_count": 1,
            "failure_count": 0,
            "last_verified_at": None,
            "content": content,
            "candidate_meta": {
                "task": task,
                "trace_path": str(trace_path),
                "summary_present": bool(summary.strip()),
                "step_count": quality["step_count"],
                "max_repeat_count": quality["max_repeat_count"],
                "intervention_count": quality["intervention_count"],
                "stagnation_event_count": quality["stagnation_event_count"],
            },
        }
        self._write_memory_candidate(trace_path=trace_path, candidate=candidate)

    @staticmethod
    def _analyze_trace_quality(trace_path: Path) -> dict[str, Any]:
        step_count = 0
        max_repeat_count = 0
        intervention_count = 0
        stagnation_event_count = 0
        latest_foreground_app: str | None = None

        try:
            with open(trace_path, encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue

                    event_type = row.get("event") or row.get("type")
                    if event_type == "step":
                        step_count += 1
                        stability = row.get("stability") if isinstance(row.get("stability"), dict) else {}
                        repeat_count = stability.get("repeat_count")
                        if isinstance(repeat_count, int):
                            max_repeat_count = max(max_repeat_count, repeat_count)
                        if bool(stability.get("stagnation_detected")):
                            stagnation_event_count += 1

                        execution = row.get("execution")
                        if isinstance(execution, dict):
                            obs = execution.get("next_observation")
                            if isinstance(obs, dict):
                                app = obs.get("foreground_app")
                                if isinstance(app, str) and app.strip():
                                    latest_foreground_app = app.strip()
                    elif event_type in {"intervention_requested", "intervention_cancelled"}:
                        intervention_count += 1
        except OSError:
            logger.warning("Could not read trace for memory candidate: %s", trace_path, exc_info=True)
            return {"eligible": False}

        eligible = (
            step_count > 0
            and step_count <= 30
            and intervention_count == 0
            and max_repeat_count <= 4
            and stagnation_event_count <= 2
        )
        return {
            "eligible": eligible,
            "step_count": step_count,
            "max_repeat_count": max_repeat_count,
            "intervention_count": intervention_count,
            "stagnation_event_count": stagnation_event_count,
            "latest_foreground_app": latest_foreground_app,
        }

    @staticmethod
    def _classify_memory_type(*, task: str, summary: str, latest_app: str | None) -> str:
        text = f"{task}\n{summary}".lower()
        policy_keywords = (
            "支付", "付款", "转账", "下单", "购买",
            "permission", "authorize", "allow", "camera", "microphone", "location",
            "delete", "send", "message",
        )
        icon_keywords = ("icon", "图标", "按钮样式", "齿轮", "铅笔", "pencil", "trash")
        if any(keyword in text for keyword in policy_keywords):
            return "policy"
        if any(keyword in text for keyword in icon_keywords):
            return "icon"
        if latest_app and latest_app.lower() not in {"unknown", "launcher", "home", "dryrun"}:
            return "app"
        return "os"

    @staticmethod
    def _build_memory_candidate_content(*, task: str, summary: str, latest_app: str | None) -> str:
        app_hint = f" [app={latest_app}]" if latest_app else ""
        if summary.strip():
            base = f"Task: {task}{app_hint}\nObserved reliable path: {summary.strip()}"
        else:
            base = f"Task: {task}{app_hint}\nObserved reliable path from successful trajectory."
        return base[:800]

    @staticmethod
    def _estimate_candidate_confidence(
        *,
        quality: dict[str, Any],
        has_summary: bool,
        eval_success: bool,
    ) -> float:
        score = 0.45
        step_count = int(quality.get("step_count", 0) or 0)
        if step_count <= 8:
            score += 0.20
        elif step_count <= 15:
            score += 0.10
        if has_summary:
            score += 0.10
        if int(quality.get("max_repeat_count", 0) or 0) <= 2:
            score += 0.10
        if eval_success:
            score += 0.15
        return max(0.0, min(0.95, round(score, 3)))

    @staticmethod
    def _write_memory_candidate(trace_path: Path, candidate: dict[str, Any]) -> None:
        candidate_path = trace_path.parent / DEFAULT_MEMORY_CANDIDATE_FILENAME
        try:
            candidate_path.write_text(
                json.dumps(candidate, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not write memory candidate to %s: %s", candidate_path, exc)

        queue_path = DEFAULT_MEMORY_REVIEW_QUEUE
        try:
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            with open(queue_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(candidate, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Could not append memory candidate queue %s: %s", queue_path, exc)

    async def _run_with_timeout(
        self,
        awaitable: Any,
        *,
        timeout_seconds: float,
        stage: str,
        default: Any,
    ) -> Any:
        """Execute a postprocessing stage with a timeout and safe fallback."""
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("Post-processing stage timed out: %s (%.1fs)", stage, timeout_seconds)
            return default
        except Exception:
            logger.warning("Post-processing stage failed: %s", stage, exc_info=True)
            return default

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

    @staticmethod
    def _legacy_skill_to_shortcut(*, skill: Any, trace_path: Path) -> Any:
        """Convert a legacy Skill object to a ShortcutSkill for storage."""
        from datetime import datetime

        from opengui.skills.shortcut import ParameterSlot, ShortcutSkill, StateDescriptor

        parameter_slots = tuple(
            ParameterSlot(
                name=str(name),
                type="string",
                description=f"Value for {name}",
            )
            for name in getattr(skill, "parameters", ())
        )
        preconditions = _dedupe_state_descriptors(
            [
                StateDescriptor(kind="screen_state", value=str(value))
                for value in getattr(skill, "preconditions", ())
                if str(value).strip()
            ]
            + [
                StateDescriptor(kind="screen_state", value=str(step.valid_state))
                for step in getattr(skill, "steps", ())
                if getattr(step, "valid_state", None)
                and str(step.valid_state).strip().lower() != "no need to verify"
            ]
        )
        postconditions = _dedupe_state_descriptors(
            [
                StateDescriptor(kind="screen_state", value=str(step.expected_state))
                for step in getattr(skill, "steps", ())
                if getattr(step, "expected_state", None)
                and str(step.expected_state).strip()
            ]
        )
        source_step_indices = tuple(_load_trace_step_indices(trace_path))
        return ShortcutSkill(
            skill_id=str(skill.skill_id),
            name=str(skill.name),
            description=str(skill.description),
            app=str(skill.app),
            platform=str(skill.platform),
            steps=tuple(getattr(skill, "steps", ())),
            parameter_slots=parameter_slots,
            preconditions=preconditions,
            postconditions=postconditions,
            tags=tuple(getattr(skill, "tags", ())),
            source_task=getattr(skill, "description", None),
            source_trace_path=str(trace_path),
            source_run_id=trace_path.parent.name or None,
            source_step_indices=source_step_indices,
            promotion_version=1,
            shortcut_version=1,
            created_at=float(getattr(skill, "created_at", datetime.now().timestamp())),
        )


def _dedupe_state_descriptors(states: list) -> tuple:
    """Remove duplicate StateDescriptor entries by (kind, value, negated)."""
    deduped: dict[tuple, Any] = {}
    for state in states:
        key = (state.kind, state.value, state.negated)
        deduped[key] = state
    return tuple(deduped.values())


def _load_trace_step_indices(trace_path: Path) -> list[int]:
    """Extract step indices from a JSONL trace file."""
    import json

    step_indices: list[int] = []
    try:
        with open(trace_path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("type") != "step":
                    continue
                index = row.get("step_index")
                if isinstance(index, int):
                    step_indices.append(index)
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load step indices from %s", trace_path, exc_info=True)
    return step_indices
