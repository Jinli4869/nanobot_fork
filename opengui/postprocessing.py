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

from opengui.skills.static_selector_filter import (
    filter_static_controls,
    filter_static_resource_ids,
    filter_static_texts,
)

logger = logging.getLogger(__name__)

DEFAULT_EVALUATION_FILENAME = "evaluation.json"
_GRAPH_SYNC_LOCKS: dict[Path, asyncio.Lock] = {}
_CODE_SKILL_LOCKS: dict[Path, asyncio.Lock] = {}

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


def _updated_skill_ids(update: Any) -> list[str]:
    updated_names = set(getattr(update, "updated_functions", ()) or ())
    skills = tuple(getattr(update, "skills", ()) or ())
    if not updated_names:
        return [skill.skill_id for skill in skills if getattr(skill, "skill_id", None)]
    return [
        skill.skill_id
        for skill in skills
        if getattr(skill, "skill_id", None) and getattr(skill, "name", None) in updated_names
    ]


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


def _load_completed_reuse(trace_path: Path) -> dict[str, Any] | None:
    """Return reuse metadata when a full reused skill already completed the task."""
    prefix_reuse_seen = False
    full_reuse: dict[str, Any] | None = None
    agent_work_after_full_reuse = False
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
                event_type = event.get("type")
                if event_type == "step" and full_reuse is not None:
                    action = event.get("action")
                    action_type = action.get("action_type") if isinstance(action, dict) else None
                    if action_type != "done":
                        agent_work_after_full_reuse = True
                    continue
                if (
                    event_type == "graph_prefix_result"
                    and event.get("prefix_only") is True
                    and int(event.get("edge_count") or 0) > 0
                ):
                    prefix_reuse_seen = True
                    continue
                if (
                    event_type == "graph_runtime_result"
                    and event.get("state") == "succeeded"
                    and event.get("prefix_only") is True
                ):
                    prefix_reuse_seen = True
                    continue
                if (
                    event_type == "graph_runtime_result"
                    and event.get("state") == "succeeded"
                    and event.get("prefix_only") is not True
                ):
                    full_reuse = {
                        "reuse_source": "graph",
                        "skill_id": event.get("skill_id"),
                        "terminal_node_id": event.get("prefix_terminal_node_id"),
                    }
                    agent_work_after_full_reuse = False
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
    if prefix_reuse_seen or agent_work_after_full_reuse:
        return None
    return full_reuse


def _is_abnormal_termination(result_event: dict[str, Any]) -> bool:
    """True if the trajectory was cut short by a detector/infra fault."""
    error = result_event.get("error")
    total_steps = result_event.get("total_steps") or 0
    # Preflight errors never execute a step; `error` is an arbitrary exception string.
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
        for key in ("visible_text", "clickable_text", "content_desc"):
            values = filter_static_texts(extra.get(key), limit=40)
            if values:
                profile[key] = values
        values = filter_static_resource_ids(extra.get("resource_ids"), limit=40)
        if values:
            profile["resource_ids"] = values
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


def _extract_stable_controls(ui_tree: Any) -> list[dict[str, Any]]:
    if not isinstance(ui_tree, list):
        return []
    return filter_static_controls(ui_tree, limit=12)


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


def _learning_mode(is_success: bool) -> str:
    return "success_full" if is_success else "failure_prefix"


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
        enable_deeplink_skill_extraction: bool = False,
        deeplink_probe_backend: Any | None = None,
        evaluation: EvaluationConfig = field(default_factory=EvaluationConfig),
    ) -> None:
        self._llm = llm
        self._merge_llm = merge_llm
        self._embedding_provider = embedding_provider
        self._embedding_signature = embedding_signature
        self._skill_store_root = skill_store_root
        self._enable_skill_extraction = enable_skill_extraction
        self._enable_deeplink_skill_extraction = enable_deeplink_skill_extraction
        self._deeplink_probe_backend = deeplink_probe_backend
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
        summary, evaluation_result = await asyncio.gather(
            self._summarize_trajectory(trace_path),
            self._run_evaluation(trace_path=trace_path, is_success=is_success, task=task),
        )
        effective_success = is_success
        if isinstance(evaluation_result, dict) and evaluation_result.get("success") is False:
            effective_success = False
        await self._extract_deeplink_skill(
            trace_path,
            effective_success,
            platform,
            task=task,
            evaluation_result=evaluation_result,
            agent_success=is_success,
        )
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
        learning_mode = _learning_mode(is_success)

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
                "learning_mode": learning_mode,
                "reason": reason,
                "total_steps": result_event.get("total_steps"),
            })
            return None

        completed_reuse = _load_completed_reuse(trace_path) if (is_success or agent_success) else None
        if completed_reuse is not None:
            logger.info(
                "Skipping skill extraction for completed reused %s path: %s",
                completed_reuse.get("reuse_source"),
                trace_path,
            )
            self._write_extraction_result(trace_path, {
                "status": "skipped_reused_skill_complete",
                "trace": str(trace_path),
                "is_success": is_success,
                "agent_success": agent_success,
                "evaluation_success": evaluation_result.get("success") if isinstance(evaluation_result, dict) else None,
                "platform": platform,
                "learning_mode": learning_mode,
                **completed_reuse,
            })
            return None

        from opengui.skills.code_first import (
            CodeSkillExtractor,
            CodeSkillLibrary,
            CodeSkillRepository,
            TraceSegmenter,
            _load_events,
            build_visual_guarded_code_fallback,
            canonicalize_code_actions_from_events,
            filter_code_to_contract_complete,
            normalize_code_skill_entrypoints,
            repair_code_contracts_from_events,
        )
        from opengui.skills.code_graph import compile_code_skills

        try:
            extractor = CodeSkillExtractor(llm=self._llm)
            events = _load_events(trace_path)
            segments = TraceSegmenter().segment(events)
            if not segments:
                self._write_extraction_result(trace_path, {
                    "status": "no_candidate",
                    "reason": "no_trace_aligned_reusable_actions",
                    "trace": str(trace_path),
                    "is_success": is_success,
                    "agent_success": agent_success,
                    "evaluation_success": evaluation_result.get("success") if isinstance(evaluation_result, dict) else None,
                    "platform": platform,
                    "learning_mode": learning_mode,
                    "updated_functions": [],
                    "compiled_skill_ids": [],
                    "graph_synced": False,
                    "code_graph_synced": False,
                    "action_sequence": {"quality": "none", "reusable_action_count": 0},
                    "segments": [],
                    "segment_count": 0,
                    "processed_segment_count": 0,
                })
                return None

            store_root = self._skill_store_root or trace_path.parent
            repository = CodeSkillRepository(store_root)
            code_lock = _CODE_SKILL_LOCKS.setdefault(
                store_root.expanduser().resolve(strict=False),
                asyncio.Lock(),
            )
            segment_results: list[dict[str, Any]] = []
            all_attempts: list[dict[str, Any]] = []
            updated_functions: list[str] = []
            returned_skill_ids: list[str] = []
            all_compiled_skill_ids: list[str] = []
            first_action_sequence: dict[str, Any] | None = None
            first_contract_quality: dict[str, Any] | None = None
            code_compile_error_seen = False
            extraction_error_seen = False

            async with code_lock:
                for segment in segments:
                    segment_record = segment.to_result_stub()
                    segment_record.update({
                        "status": "no_candidate",
                        "updated_functions": [],
                        "compiled_skill_ids": [],
                        "screenshots_used": [],
                        "action_sequence": {},
                        "contract_quality": {},
                        "learning_mode": learning_mode,
                        "rejected_reason": None,
                    })

                    try:
                        extraction = await extractor.extract_from_events(
                            list(segment.events),
                            is_success=is_success,
                            platform=platform,
                            task=task,
                            evaluation_result=evaluation_result,
                            segment_id=segment.segment_id,
                            segment_summary=segment.reason,
                        )
                    except Exception as exc:
                        extraction_error_seen = True
                        segment_record["status"] = "error"
                        segment_record["rejected_reason"] = "extraction_error"
                        segment_record["attempts"] = [{
                            "errors": [str(exc) or type(exc).__name__],
                            "error_type": type(exc).__name__,
                        }]
                        segment_results.append(segment_record)
                        continue
                    if extraction is None:
                        segment_record["rejected_reason"] = "no_candidate"
                        segment_results.append(segment_record)
                        continue
                    all_attempts.extend(extraction.attempts)
                    segment_record["screenshots_used"] = list(extraction.screenshots_used)
                    if not extraction.python_code:
                        code_compile_error_seen = True
                        if all_attempts:
                            all_attempts[-1] = {
                                **all_attempts[-1],
                                "errors": list(
                                    all_attempts[-1].get("violations")
                                    or ["empty python_code"]
                                ),
                            }
                        segment_record["status"] = "code_compile_error"
                        segment_record["rejected_reason"] = "empty python_code"
                        segment_record["attempts"] = list(extraction.attempts)
                        segment_results.append(segment_record)
                        continue

                    canonicalized = canonicalize_code_actions_from_events(
                        extraction.python_code,
                        list(segment.events),
                    )
                    segment_record["action_sequence"] = canonicalized.report
                    if (
                        canonicalized.report.get("quality") != "unvalidated"
                        and int(canonicalized.report.get("reusable_action_count") or 0) < 1
                    ):
                        segment_record["rejected_reason"] = "no_trace_aligned_reusable_actions"
                        segment_results.append(segment_record)
                        continue

                    repaired = repair_code_contracts_from_events(
                        canonicalized.source,
                        list(segment.events),
                    )
                    filtered = filter_code_to_contract_complete(
                        repaired.source,
                        repair_report=repaired.report,
                    )
                    segment_record["contract_quality"] = filtered.report
                    normalized = normalize_code_skill_entrypoints(filtered.source)
                    normalization_report = dict(normalized.report)
                    segment_record["action_sequence"] = {
                        **segment_record["action_sequence"],
                        "entrypoint_normalized_functions": list(
                            normalization_report.get("entrypoint_normalized_functions") or []
                        ),
                        "open_app_contract_stripped_functions": list(
                            normalization_report.get("open_app_contract_stripped_functions") or []
                        ),
                    }
                    if filtered.removed_functions:
                        segment_record["removed_weak_functions"] = list(filtered.removed_functions)
                    filtered_compile = compile_code_skills(normalized.source)
                    used_visual_guarded_fallback = False
                    if filtered.removed_functions and (
                        not filtered.report.get("canonical_step_count")
                        or not filtered_compile.skills
                    ):
                        visual_guarded = build_visual_guarded_code_fallback(
                            repaired.source,
                            list(segment.events),
                            action_sequence_report=canonicalized.report,
                        )
                        segment_record["visual_guarded_fallback"] = visual_guarded.report
                        if not visual_guarded.report.get("enabled"):
                            segment_record["rejected_reason"] = "weak_contracts"
                            segment_results.append(segment_record)
                            continue
                        normalized = normalize_code_skill_entrypoints(visual_guarded.source)
                        normalization_report = dict(normalized.report)
                        segment_record["action_sequence"] = {
                            **segment_record["action_sequence"],
                            "entrypoint_normalized_functions": list(
                                normalization_report.get("entrypoint_normalized_functions") or []
                            ),
                            "open_app_contract_stripped_functions": list(
                                normalization_report.get("open_app_contract_stripped_functions") or []
                            ),
                            "visual_guarded_functions": list(
                                visual_guarded.report.get("visual_guarded_functions") or []
                            ),
                        }
                        segment_record["contract_quality"] = {
                            **segment_record["contract_quality"],
                            "visual_guarded": True,
                            "quality": "visual_guarded",
                        }
                        filtered_compile = compile_code_skills(normalized.source)
                        if not filtered_compile.skills:
                            segment_record["rejected_reason"] = "visual_guarded_compile_error"
                            segment_results.append(segment_record)
                            continue
                        used_visual_guarded_fallback = True
                    update = repository.add_code(
                        normalized.source,
                        description_hint=task,
                    )
                    if update.errors:
                        code_compile_error_seen = True
                        error_attempt = {
                            "segment_id": segment.segment_id,
                            "errors": list(update.errors),
                        }
                        if all_attempts and "errors" not in all_attempts[-1]:
                            all_attempts[-1] = {**all_attempts[-1], **error_attempt}
                        else:
                            all_attempts.append(error_attempt)
                        segment_record["status"] = "code_compile_error"
                        segment_record["rejected_reason"] = "code_compile_error"
                        segment_record["attempts"] = [{"errors": list(update.errors)}]
                        segment_results.append(segment_record)
                        continue

                    segment_skill_ids = _updated_skill_ids(update)
                    segment_record["status"] = "processed_visual_guarded_code" if used_visual_guarded_fallback else "processed_code"
                    segment_record["updated_functions"] = list(update.updated_functions)
                    segment_record["compiled_skill_ids"] = segment_skill_ids
                    segment_results.append(segment_record)
                    for name in update.updated_functions:
                        if name not in updated_functions:
                            updated_functions.append(name)
                    for skill_id in segment_skill_ids:
                        if skill_id not in returned_skill_ids:
                            returned_skill_ids.append(skill_id)
                    all_compiled_skill_ids = [
                        skill.skill_id
                        for skill in update.skills
                        if getattr(skill, "skill_id", None)
                    ]
                    if first_action_sequence is None:
                        first_action_sequence = segment_record["action_sequence"]
                    if first_contract_quality is None:
                        first_contract_quality = segment_record["contract_quality"]

                code_library = CodeSkillLibrary(
                    store_dir=store_root,
                    embedding_provider=self._embedding_provider,
                    merge_llm=self._merge_llm,
                    embedding_signature=self._embedding_signature,
                    legacy_fallback=False,
                )
                code_graph_synced = await code_library.sync_graph_cache()
                graph_synced = False

            self._write_extraction_usage(trace_path, extractor.total_usage)
            processed_segment_count = sum(
                1
                for segment in segment_results
                if segment.get("status") in {"processed_code", "processed_visual_guarded_code"}
            )
            visual_guarded_segment_count = sum(
                1
                for segment in segment_results
                if segment.get("status") == "processed_visual_guarded_code"
            )
            if processed_segment_count < 1:
                if extraction_error_seen:
                    status = "error"
                elif code_compile_error_seen:
                    status = "code_compile_error"
                else:
                    status = "no_candidate"
                self._write_extraction_result(trace_path, {
                    "status": status,
                    "trace": str(trace_path),
                    "is_success": is_success,
                    "agent_success": agent_success,
                    "evaluation_success": evaluation_result.get("success") if isinstance(evaluation_result, dict) else None,
                    "platform": platform,
                    "learning_mode": learning_mode,
                    "attempts": all_attempts,
                    "updated_functions": [],
                    "compiled_skill_ids": [],
                    "graph_synced": False,
                    "code_graph_synced": False,
                    "segments": segment_results,
                    "segment_count": len(segments),
                    "processed_segment_count": 0,
                    "visual_guarded_segment_count": 0,
                })
                return None

            compiled_skill_ids = all_compiled_skill_ids or returned_skill_ids
            final_id = returned_skill_ids[0] if returned_skill_ids else None
            self._write_extraction_result(trace_path, {
                "status": "processed_code",
                "trace": str(trace_path),
                "is_success": is_success,
                "agent_success": agent_success,
                "evaluation_success": evaluation_result.get("success") if isinstance(evaluation_result, dict) else None,
                "platform": platform,
                "learning_mode": learning_mode,
                "updated_functions": updated_functions,
                "compiled_skill_ids": compiled_skill_ids,
                "graph_synced": graph_synced,
                "code_graph_synced": code_graph_synced,
                "attempts": all_attempts,
                "action_sequence": first_action_sequence or {},
                "contract_quality": first_contract_quality or {},
                "segments": segment_results,
                "segment_count": len(segments),
                "processed_segment_count": processed_segment_count,
                "visual_guarded_segment_count": visual_guarded_segment_count,
            })
            return final_id
        except Exception as exc:
            logger.warning("Skill extraction failed for %s", trace_path, exc_info=True)
            self._write_extraction_result(trace_path, {
                "status": "error",
                "reason": str(exc) or type(exc).__name__,
                "error_type": type(exc).__name__,
                "trace": str(trace_path),
                "is_success": is_success,
                "agent_success": agent_success,
                "evaluation_success": evaluation_result.get("success") if isinstance(evaluation_result, dict) else None,
                "platform": platform,
                "learning_mode": learning_mode,
            })
            return None

    async def _extract_deeplink_skill(
        self,
        trace_path: Path,
        is_success: bool,
        platform: str,
        *,
        task: str | None = None,
        evaluation_result: dict[str, Any] | None = None,
        agent_success: bool | None = None,
    ) -> dict[str, Any] | None:
        if not self._enable_deeplink_skill_extraction:
            return None
        if not trace_path.exists():
            return None

        result_event = _load_trajectory_result(trace_path)
        if result_event is not None and _is_abnormal_termination(result_event):
            result = {
                "status": "skipped",
                "reason": "abnormal_termination",
                "error": result_event.get("error"),
            }
            _write_deeplink_audit_result(trace_path, result)
            self._merge_deeplink_extraction_result(
                trace_path,
                result,
                is_success=is_success,
                agent_success=agent_success,
                evaluation_result=evaluation_result,
                platform=platform,
            )
            return result

        if self._deeplink_probe_backend is None:
            result = {"status": "skipped", "reason": "missing_probe_backend"}
            _write_deeplink_audit_result(trace_path, result)
            self._merge_deeplink_extraction_result(
                trace_path,
                result,
                is_success=is_success,
                agent_success=agent_success,
                evaluation_result=evaluation_result,
                platform=platform,
            )
            return result

        store_root = self._skill_store_root or trace_path.parent
        lock = _CODE_SKILL_LOCKS.setdefault(
            store_root.expanduser().resolve(strict=False),
            asyncio.Lock(),
        )
        try:
            from opengui.skills.deeplink import discover_deeplink_skills_from_trace

            async with lock:
                discovery = await discover_deeplink_skills_from_trace(
                    trace_path,
                    backend=self._deeplink_probe_backend,
                    task=task,
                    platform=platform,
                    is_success=is_success,
                    store_root=store_root,
                )
                code_graph_synced = False
                if discovery.status == "processed_deeplink_code":
                    from opengui.skills.code_first import CodeSkillLibrary

                    code_graph_synced = await CodeSkillLibrary(
                        store_dir=store_root,
                        embedding_provider=self._embedding_provider,
                        merge_llm=self._merge_llm,
                        embedding_signature=self._embedding_signature,
                        legacy_fallback=False,
                    ).sync_graph_cache()
            result = discovery.to_dict()
            if code_graph_synced:
                result["code_graph_synced"] = True
        except Exception as exc:
            logger.warning("Deeplink skill discovery failed for %s", trace_path, exc_info=True)
            result = {"status": "error", "reason": str(exc)}
            _write_deeplink_audit_result(trace_path, result)

        self._merge_deeplink_extraction_result(
            trace_path,
            result,
            is_success=is_success,
            agent_success=agent_success,
            evaluation_result=evaluation_result,
            platform=platform,
        )
        return result

    def _merge_deeplink_extraction_result(
        self,
        trace_path: Path,
        deeplink_result: dict[str, Any],
        *,
        is_success: bool,
        agent_success: bool | None,
        evaluation_result: dict[str, Any] | None,
        platform: str,
    ) -> None:
        result_path = trace_path.parent / "extraction_result.json"
        existing: dict[str, Any] = {}
        if result_path.exists():
            try:
                loaded = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except (json.JSONDecodeError, OSError):
                existing = {}

        if not existing:
            existing = {
                "status": deeplink_result.get("status") or "deeplink_processed",
                "trace": str(trace_path),
                "is_success": is_success,
                "agent_success": agent_success,
                "evaluation_success": evaluation_result.get("success") if isinstance(evaluation_result, dict) else None,
                "platform": platform,
                "learning_mode": _learning_mode(is_success),
                "updated_functions": [],
                "compiled_skill_ids": [],
                "graph_synced": False,
                "code_graph_synced": False,
            }
        elif existing.get("status") in {None, "no_candidate"} and deeplink_result.get("status") == "processed_deeplink_code":
            existing["status"] = "processed_deeplink_code"

        existing["deeplink"] = deeplink_result
        existing["deeplink_skill_extraction_enabled"] = True
        for key in ("updated_functions", "compiled_skill_ids"):
            merged = list(existing.get(key) or [])
            for value in deeplink_result.get(key) or []:
                if value not in merged:
                    merged.append(value)
            existing[key] = merged
        self._write_extraction_result(trace_path, existing)

    async def _sync_code_skills_graph(self, skills: tuple[Any, ...]) -> bool:
        if self._skill_store_root is None:
            return False
        try:
            from opengui.skills.graph import SkillGraphStore

            graph = SkillGraphStore(
                store_dir=self._skill_store_root,
                embedding_provider=self._embedding_provider,
                embedding_signature=self._embedding_signature,
            )
            for skill in skills:
                await graph.ingest_skill(skill)
            return bool(skills)
        except Exception:
            logger.warning("Code skill graph fallback sync failed", exc_info=True)
            return False

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
                compacted = graph.compact_canonical_graph()
                if compacted.get("nodes") or compacted.get("edges"):
                    logger.info(
                        "Compacted skill graph after sync: nodes=%s edges=%s exact=%s hard_aliases=%s candidates=%s",
                        compacted.get("nodes", 0),
                        compacted.get("edges", 0),
                        compacted.get("exact_merges", 0),
                        compacted.get("hard_aliases", 0),
                        compacted.get("candidate_aliases", 0),
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
        if result_path.exists():
            try:
                loaded = json.loads(result_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                loaded = None
            if isinstance(loaded, dict):
                _preserve_existing_deeplink_result(result, loaded)
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


def _preserve_existing_deeplink_result(result: dict[str, Any], existing: dict[str, Any]) -> None:
    deeplink = existing.get("deeplink")
    if "deeplink" not in result and deeplink is not None:
        result["deeplink"] = deeplink
    if existing.get("deeplink_skill_extraction_enabled") and "deeplink_skill_extraction_enabled" not in result:
        result["deeplink_skill_extraction_enabled"] = True

    for key in ("updated_functions", "compiled_skill_ids"):
        merged = list(existing.get(key) or [])
        for value in result.get(key) or []:
            if value not in merged:
                merged.append(value)
        if merged:
            result[key] = merged

    for key in ("graph_synced", "code_graph_synced"):
        if existing.get(key):
            result[key] = True

    existing_deeplink = existing.get("deeplink")
    deeplink_status = existing_deeplink.get("status") if isinstance(existing_deeplink, dict) else None
    if deeplink_status == "processed_deeplink_code" and result.get("status") in {None, "no_candidate"}:
        result["status"] = "processed_deeplink_code"


def _write_deeplink_audit_result(trace_path: Path, result: dict[str, Any]) -> None:
    try:
        (trace_path.parent / "deeplink_result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Could not write deeplink result for %s: %s", trace_path, exc)
