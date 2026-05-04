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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EVALUATION_FILENAME = "evaluation.json"
_GRAPH_SYNC_LOCKS: dict[Path, asyncio.Lock] = {}

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


def _load_latest_graph_terminal_node_id(trace_path: Path) -> str | None:
    """Return the most recent successfully reached graph runtime terminal id."""
    import json

    def _clean_terminal_id(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    latest_terminal_node_id: str | None = None
    try:
        with open(trace_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") != "graph_runtime_result":
                    continue
                if event.get("state") != "succeeded":
                    continue
                if event.get("prefix_only") is not True:
                    continue
                terminal_node_id = _clean_terminal_id(event.get("prefix_terminal_node_id"))
                if terminal_node_id is not None:
                    latest_terminal_node_id = terminal_node_id
    except OSError:
        return None
    return latest_terminal_node_id


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


def _load_jsonl_events(trace_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with open(trace_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except OSError:
        return []
    return events


def _derive_graph_node_profiles(trace_path: Path, *, step_count: int) -> dict[int | str, dict[str, Any]]:
    events = _load_jsonl_events(trace_path)
    step_profiles: dict[int, dict[str, Any]] = {}
    latest_profile: dict[str, Any] | None = None
    ordered_step_index = 0
    for event in events:
        observation = event.get("observation")
        if not isinstance(observation, dict):
            continue
        profile = _build_retrieval_profile(observation)
        if not profile:
            continue
        latest_profile = profile
        step_index = event.get("step_index")
        if isinstance(step_index, int) and step_index >= 0:
            step_profiles.setdefault(step_index, profile)
            continue
        if ordered_step_index < step_count:
            step_profiles.setdefault(ordered_step_index, profile)
            ordered_step_index += 1
    profiles: dict[int | str, dict[str, Any]] = {
        index: profile
        for index, profile in step_profiles.items()
    }
    if latest_profile is not None:
        profiles["terminal"] = latest_profile
    return profiles


def _build_retrieval_profile(observation: dict[str, Any]) -> dict[str, Any]:
    profile: dict[str, Any] = {}
    for key in ("foreground_app", "app", "platform"):
        value = observation.get(key)
        if value:
            profile[key] = value
    title = _first_text_value(observation, ("page_title", "title", "toolbar_title"))
    extra = observation.get("extra")
    if title is None and isinstance(extra, dict):
        title = _first_text_value(extra, ("page_title", "title", "toolbar_title"))
    if title:
        profile["page_title"] = title
    if isinstance(extra, dict):
        for key in ("visible_text", "clickable_text", "content_desc", "resource_ids"):
            values = _dedupe_bounded_strings(extra.get(key), limit=40)
            if values:
                profile[key] = values
        stable_controls = _extract_stable_controls(extra.get("ui_tree"))
        if stable_controls:
            profile["stable_controls"] = stable_controls
    if _is_sparse_retrieval_profile(profile):
        summary = _short_page_summary(profile)
        if summary:
            profile["page_summary"] = summary
    return profile


def _first_text_value(observation: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = observation.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _dedupe_bounded_strings(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _extract_stable_controls(ui_tree: Any) -> list[dict[str, Any]]:
    if not isinstance(ui_tree, list):
        return []
    controls: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for node in ui_tree:
        if not isinstance(node, dict):
            continue
        text = _clean_text(node.get("text"))
        content_desc = _clean_text(node.get("content_desc"))
        resource_id = _clean_text(node.get("resource_id"))
        if not any((text, content_desc, resource_id)):
            continue
        if not (node.get("clickable") or resource_id or content_desc):
            continue
        key = (text, content_desc, resource_id)
        if key in seen:
            continue
        seen.add(key)
        control: dict[str, Any] = {}
        if text:
            control["text"] = text
        if content_desc:
            control["content_desc"] = content_desc
        if resource_id:
            control["resource_id"] = resource_id
        bounds = node.get("bounds")
        if isinstance(bounds, str) and bounds.strip():
            control["bounds"] = bounds.strip()
        controls.append(control)
        if len(controls) >= 12:
            break
    return controls


def _clean_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _is_sparse_retrieval_profile(profile: dict[str, Any]) -> bool:
    if len(profile.get("visible_text", [])) >= 3:
        return False
    if len(profile.get("clickable_text", [])) >= 3:
        return False
    if len(profile.get("content_desc", [])) >= 3:
        return False
    if len(profile.get("resource_ids", [])) >= 3:
        return False
    return not profile.get("stable_controls")


def _short_page_summary(profile: dict[str, Any]) -> str | None:
    title = profile.get("page_title")
    visible = profile.get("visible_text", [])
    clickable = profile.get("clickable_text", [])
    controls = profile.get("stable_controls", [])
    parts: list[str] = []
    if isinstance(title, str) and title:
        parts.append(title)
    if isinstance(visible, list) and visible:
        parts.append("visible=" + ", ".join(str(v) for v in visible[:3]))
    if isinstance(clickable, list) and clickable:
        parts.append("clickable=" + ", ".join(str(v) for v in clickable[:3]))
    if isinstance(controls, list) and controls:
        control_labels = []
        for control in controls[:3]:
            if not isinstance(control, dict):
                continue
            label = control.get("text") or control.get("content_desc") or control.get("resource_id")
            if label:
                control_labels.append(str(label))
        if control_labels:
            parts.append("controls=" + ", ".join(control_labels))
    if not parts:
        return None
    return " | ".join(parts)[:220]


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
            logger.info("Trajectory state note: %s", summary.replace("\n", " | ")[:200])

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
            canonical_skill = library.get(final_id) or skill
            continuation_anchor_id = _load_latest_graph_terminal_node_id(trace_path)
            node_profiles = _derive_graph_node_profiles(trace_path, step_count=len(canonical_skill.steps))
            graph_synced = await self._sync_skill_graph(
                canonical_skill,
                continuation_anchor_id=continuation_anchor_id,
                node_profiles=node_profiles,
            )
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
                "graph_synced": graph_synced,
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

    async def _sync_skill_graph(
        self,
        skill: Any,
        *,
        continuation_anchor_id: str | None = None,
        node_profiles: dict[int | str, dict[str, Any] | None] | None = None,
    ) -> bool:
        if self._skill_store_root is None:
            return False
        try:
            from opengui.skills.graph import SkillGraphStore

            lock = _GRAPH_SYNC_LOCKS.setdefault(
                self._skill_store_root.expanduser().resolve(strict=False),
                asyncio.Lock(),
            )
            async with lock:
                graph = SkillGraphStore(
                    store_dir=self._skill_store_root,
                    embedding_provider=self._embedding_provider,
                    embedding_signature=self._embedding_signature,
                )
                await graph.ingest_skill(
                    skill,
                    continuation_anchor_id=continuation_anchor_id,
                    node_profiles=node_profiles,
                )
                logger.info(
                    "Synced skill graph for skill=%s app=%s platform=%s",
                    getattr(skill, "skill_id", ""),
                    getattr(skill, "app", ""),
                    getattr(skill, "platform", ""),
                )
                return True
        except Exception:
            logger.warning("Skill graph sync failed", exc_info=True)
            return False

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
