"""
opengui.skills.code_first
~~~~~~~~~~~~~~~~~~~~~~~~~
Code-first extraction and storage for OpenGUI skills.

The canonical skill source is ``skill_graph_code.py``. Runtime graph/cache
artifacts can be rebuilt from this source and should not be treated as the
authoritative editable representation.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import copy
import io
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from opengui.memory.retrieval import _BM25Index, _FaissIndex
from opengui.skills.code_graph import compile_code_skills
from opengui.skills.data import Skill, SkillStep
from opengui.skills.evolution import feedback_for_skill, feedback_task_similarity
from opengui.skills.normalization import normalize_app_identifier, normalize_skill_app
from opengui.skills.state_contract import normalize_state_contract
from opengui.skills.static_selector_filter import (
    filter_static_resource_ids,
    filter_static_texts,
    is_dynamic_resource_id,
    is_dynamic_text,
    is_static_resource_id,
    is_static_text,
    selector_is_static,
)

logger = logging.getLogger(__name__)

CANONICAL_CODE_FILENAME = "skill_graph_code.py"
_CODE_HEADER = "from opengui.skills.code_graph import C, R, action, skill, state, tag, transition"
_SCREENSHOT_EXTRACTION_TIMEOUT_S = 45.0
_TEXT_EXTRACTION_TIMEOUT_S = 180.0
_TARGET_CONTRACT_REPAIR_REASONS = frozenset({
    "ui_tree_static_selector",
    "target_selector_replaced_page_contract",
    "target_element_reduced_page_contract",
    "target_text_contract_from_observation",
})


_CODE_EXTRACTION_PROMPT = """\
You convert GUI task trajectories into reusable OpenGUI skill code.

Return only a JSON object with string fields:
- step_by_step_reasoning
- python_code

python_code must be directly mergeable into skill_graph_code.py and must obey:
- Import only: from opengui.skills.code_graph import C, R, action, skill
- Define one or more top-level async skill/helper functions.
- Reusable top-level skills must use @skill(app=..., platform=..., tags=[...],
  description="natural language summary in the user's task language").
- Do not rely on function docstrings for retrieval; put the natural language
  description on the @skill decorator.
- Every skill function's first argument must be device.
- Generalize task-specific values into function parameters when appropriate.
- Express each GUI action as: await action("...", target="...", ...)
- target must be a plain string or parameter placeholder. Never use target=R(...);
  selectors belong only inside state_contract.
- state_contract is a PRE-action hard gate for the next element this action
  will operate on, except for open_deeplink/open_intent where it is a required
  POST-action verification that the shortcut reached the target page.
- For ordinary tap/long_press/double_tap/input_text actions, state_contract
  should usually contain one required target element. Do not summarize the page
  with background anchors such as More options, tabs, toolbar buttons, or
  unrelated labels.
- Pass state_contract=C(...) inline inside await action(...). Do not assign C(...)
  or R(...) objects to local variables and then reference those variables.
- Put app anchors on C(app="..."), never inside R(...). For example:
  state_contract=C(app="com.example", required=[R(text="Orders", clickable=True)])
- R(...) only accepts text, content_desc, resource_id, class_, xpath, visible,
  clickable, enabled, focused, and scrollable. Avoid focused=True as a hard
  precondition for input_text; focus is often a race-prone runtime state.
- Do not attach a postcondition-like state_contract to open_app unless the trace
  must already be inside that app before opening a deep link.
- You may use await action("open_deeplink", ...) only when the trajectory
  contains a verified deeplink candidate. It must be fixed=True, carry the URI
  in fixed_values["text"], optionally include fixed_values["component"] or
  fixed_values["package"], and include a state_contract proving the target page.
- Keep the skill as the shortest necessary linear prefix. Drop detours, repeated
  taps, retries, waits, back navigation, and already-completed answer/inspection
  steps unless they are required to reach the reusable screen.
- For floating popups such as ads, login prompts, sign-in dialogs, or notices,
  encode the dismiss action only when the trace actually dismissed it, and mark
  it optional=True with a state_contract that proves the popup is present.
- Do not keep unconditional back/wait/recovery actions unless the current screen
  contract proves they are part of the reusable prefix.
- Do not import modules, read files, access backend/env/adb, or write arbitrary Python logic.
- For failed trajectories, extract only the useful completed prefix; do not include repeated waits,
  recovery loops, or the final failing action unless it is part of the reusable prefix.
- Every action in python_code must correspond to an observed successful
  trajectory action in the same order. Do not invent sorting, filtering,
  navigation, or cleanup steps that were not actually executed, even if they
  might make the skill seem more semantically complete.
- If evaluation says the task failed, treat the trajectory as prefix-only even if
  the agent's own result claimed success. Do not encode claimed final answers or
  calculated values unless they are supported by screenshot/UI-tree evidence.

Original task: {task}
Trajectory success flag: {is_success}
Platform hint: {platform}
Evaluation result: {evaluation}
Segment id: {segment_id}
Segment summary: {segment_summary}

Trajectory JSON:
{trajectory}
"""


@dataclass(frozen=True)
class CodeSkillExtraction:
    python_code: str
    reasoning: str = ""
    attempts: tuple[dict[str, Any], ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    screenshots_used: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeRepositoryUpdate:
    source_path: Path
    source: str = ""
    updated_functions: tuple[str, ...] = ()
    skills: tuple[Skill, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeContractRepair:
    source: str
    report: dict[str, Any]


@dataclass(frozen=True)
class CodeContractFilter:
    source: str
    report: dict[str, Any]
    removed_functions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeEntrypointNormalization:
    source: str
    report: dict[str, Any]


@dataclass(frozen=True)
class CodeVisualGuardFallback:
    source: str
    report: dict[str, Any]


@dataclass(frozen=True)
class CodeActionCanonicalization:
    source: str
    report: dict[str, Any]


@dataclass(frozen=True)
class TraceSegment:
    segment_id: str
    start_step_index: int
    end_step_index: int
    events: tuple[dict[str, Any], ...]
    reusable_action_count: int
    reason: str

    def to_result_stub(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "start_step_index": self.start_step_index,
            "end_step_index": self.end_step_index,
            "reusable_action_count": self.reusable_action_count,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class _TraceEvidenceStep:
    index: int
    action_type: str
    parameters: dict[str, Any]
    target: str
    text_blob: str
    pre_observation: dict[str, Any] | None
    post_observation: dict[str, Any] | None


@dataclass(frozen=True)
class _TraceAction:
    index: int
    action_type: str
    target: str
    parameters: dict[str, Any]
    text_blob: str
    pre_observation: dict[str, Any] | None
    post_observation: dict[str, Any] | None


class CodeSkillExtractor:
    """Extract reusable OpenGUI skills as declarative Python source."""

    def __init__(
        self,
        llm: Any,
        *,
        max_events: int = 80,
        include_screenshots: bool = True,
        max_screenshots_per_segment: int = 4,
    ) -> None:
        self._llm = llm
        self._max_events = max_events
        self._include_screenshots = include_screenshots
        self._max_screenshots_per_segment = max(0, max_screenshots_per_segment)
        self._total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    @property
    def total_usage(self) -> dict[str, int]:
        return dict(self._total_usage)

    async def extract_from_file(
        self,
        trajectory_path: Path,
        *,
        is_success: bool,
        platform: str | None = None,
        task: str | None = None,
        evaluation_result: dict[str, Any] | None = None,
        feedback: str | None = None,
    ) -> CodeSkillExtraction | None:
        if not trajectory_path.exists():
            logger.warning("Trajectory file not found: %s", trajectory_path)
            return None
        events = _load_events(trajectory_path)
        return await self.extract_from_events(
            events,
            is_success=is_success,
            platform=platform,
            task=task,
            evaluation_result=evaluation_result,
            feedback=feedback,
        )

    async def extract_from_events(
        self,
        events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        is_success: bool,
        platform: str | None = None,
        task: str | None = None,
        evaluation_result: dict[str, Any] | None = None,
        feedback: str | None = None,
        segment_id: str | None = None,
        segment_summary: str | None = None,
    ) -> CodeSkillExtraction | None:
        event_list = [event for event in events if isinstance(event, dict)]
        step_count = sum(
            1
            for event in event_list
            if (event.get("type") or event.get("event")) in {"step", "skill_step"}
        )
        if step_count < 1:
            return None
        prompt = _CODE_EXTRACTION_PROMPT.format(
            task=task or "",
            is_success=is_success,
            platform=platform or _platform_hint(event_list) or "unknown",
            evaluation=json.dumps(_compact_evaluation(evaluation_result), ensure_ascii=False),
            segment_id=segment_id or "full",
            segment_summary=segment_summary or "",
            trajectory=json.dumps(_compact_events(event_list, self._max_events), ensure_ascii=False, indent=2),
        )
        if feedback:
            prompt += (
                "\n\nPrevious generated code failed validation. Fix the code now.\n"
                "<validation_errors>\n"
                f"{feedback}\n"
                "</validation_errors>"
            )
        messages, screenshots_used = self._build_messages(prompt, event_list)
        try:
            if screenshots_used:
                response = await asyncio.wait_for(
                    self._llm.chat(messages),
                    timeout=_SCREENSHOT_EXTRACTION_TIMEOUT_S,
                )
            else:
                response = await asyncio.wait_for(
                    self._llm.chat(messages),
                    timeout=_TEXT_EXTRACTION_TIMEOUT_S,
                )
        except Exception:
            if not screenshots_used:
                raise
            logger.info(
                "Code skill extraction with screenshots failed; retrying text-only",
                exc_info=True,
            )
            screenshots_used = ()
            messages = [{"role": "user", "content": prompt}]
            response = await asyncio.wait_for(
                self._llm.chat(messages),
                timeout=_TEXT_EXTRACTION_TIMEOUT_S,
            )
        self._accumulate_usage(getattr(response, "usage", {}) or {})
        parsed, violations = _parse_code_response(getattr(response, "content", "") or "")
        attempts = [{
            "violations": violations,
            "raw_response": _safe_json(getattr(response, "content", "") or ""),
            "screenshots_used": list(screenshots_used),
        }]
        if violations:
            return CodeSkillExtraction(
                python_code="",
                attempts=tuple(attempts),
                usage=self.total_usage,
                screenshots_used=screenshots_used,
            )
        return CodeSkillExtraction(
            python_code=parsed["python_code"],
            reasoning=parsed["step_by_step_reasoning"],
            attempts=tuple(attempts),
            usage=self.total_usage,
            screenshots_used=screenshots_used,
        )

    def _build_messages(
        self,
        prompt: str,
        events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
        if (
            not self._include_screenshots
            or self._max_screenshots_per_segment <= 0
            or not _llm_supports_screenshot_input(self._llm)
        ):
            return [{"role": "user", "content": prompt}], ()

        candidates: list[tuple[int, str, str]] = []
        for index, event in enumerate(events):
            path = _screenshot_path_from_event(event)
            if path is None or not path.is_file():
                continue
            action = event.get("action") if isinstance(event.get("action"), dict) else {}
            action_type = action.get("action_type") or "?"
            step_index = event.get("step_index", index)
            label = f"Segment step {step_index} - {action_type}"
            candidates.append((index, str(path), label))
        if not candidates:
            return [{"role": "user", "content": prompt}], ()

        selected = _sample_screenshot_candidates(candidates, self._max_screenshots_per_segment)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.append({
            "type": "text",
            "text": (
                "\n\nThe following screenshots are offline extraction evidence only. "
                "Use them to understand page semantics, redundant steps, popups, and segment boundaries. "
                "Do not invent actions or resource_id/content_desc selectors from screenshots; "
                "selectors and state_contracts must be supported by the trajectory JSON observation/UI tree."
            ),
        })
        screenshots_used: list[str] = []
        for _, path, label in selected:
            encoded = _encode_image_b64(path)
            if encoded is None:
                continue
            screenshots_used.append(path)
            content.append({"type": "text", "text": f"\n{label}:"})
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            })
        if not screenshots_used:
            return [{"role": "user", "content": prompt}], ()
        return [{"role": "user", "content": content}], tuple(screenshots_used)

    def _accumulate_usage(self, usage: dict[str, int]) -> None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self._total_usage[key] = self._total_usage.get(key, 0) + int(usage.get(key, 0) or 0)


class TraceSegmenter:
    """Split long GUI traces into short extraction windows."""

    def __init__(
        self,
        *,
        max_reusable_actions: int = 10,
        overlap_reusable_actions: int = 2,
        page_change_threshold: float = 0.35,
        min_reusable_actions_for_page_split: int = 8,
    ) -> None:
        self.max_reusable_actions = max(1, max_reusable_actions)
        self.overlap_reusable_actions = max(0, overlap_reusable_actions)
        self.page_change_threshold = page_change_threshold
        self.min_reusable_actions_for_page_split = max(1, min_reusable_actions_for_page_split)

    def segment(self, events: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[TraceSegment]:
        step_events = [
            event
            for event in events
            if isinstance(event, dict) and (event.get("type") or event.get("event")) == "step"
        ]
        segments: list[TraceSegment] = []
        current: list[dict[str, Any]] = []
        current_reason = "initial"
        previous_step: dict[str, Any] | None = None

        for event in step_events:
            if current and _reusable_event_count(current) > 0 and self._crosses_app(previous_step, event):
                self._append_segment(segments, current, current_reason or "app_changed")
                current = []
                current_reason = "app_changed"
            elif (
                current
                and _reusable_event_count(current) >= self.min_reusable_actions_for_page_split
                and self._is_page_change(previous_step, event)
            ):
                self._append_segment(segments, current, current_reason or "page_changed")
                current = _overlap_events(current, self.overlap_reusable_actions)
                current_reason = "page_changed"

            if (
                current
                and _event_is_reusable_action(event)
                and _reusable_event_count(current) >= self.max_reusable_actions
            ):
                self._append_segment(segments, current, current_reason or "max_reusable_actions")
                current = _overlap_events(current, self.overlap_reusable_actions)
                current_reason = "max_reusable_actions"

            current.append(event)
            previous_step = event

        self._append_segment(segments, current, current_reason or "end")
        return segments

    def _append_segment(
        self,
        segments: list[TraceSegment],
        events: list[dict[str, Any]],
        reason: str,
    ) -> None:
        reusable_count = _reusable_event_count(events)
        if reusable_count < 1:
            return
        step_indices = [_event_step_index(event, fallback=i) for i, event in enumerate(events)]
        segments.append(TraceSegment(
            segment_id=f"seg-{len(segments):03d}",
            start_step_index=min(step_indices),
            end_step_index=max(step_indices),
            events=tuple(copy.deepcopy(events)),
            reusable_action_count=reusable_count,
            reason=reason,
        ))

    def _crosses_app(
        self,
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> bool:
        previous_app = _event_foreground_app(previous)
        current_app = _event_foreground_app(current)
        return bool(previous_app and current_app and previous_app != current_app)

    def _is_page_change(
        self,
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> bool:
        previous_signature = _event_page_signature(previous)
        current_signature = _event_page_signature(current)
        if not previous_signature or not current_signature:
            return False
        similarity = _jaccard_similarity(previous_signature, current_signature)
        return similarity < self.page_change_threshold


class CodeSkillRepository:
    """Manage the canonical ``skill_graph_code.py`` source file."""

    def __init__(self, store_dir: Path) -> None:
        self.store_dir = Path(store_dir).expanduser()
        self.source_path = self.store_dir / CANONICAL_CODE_FILENAME

    def read_source(self) -> str:
        if not self.source_path.exists():
            return _CODE_HEADER + "\n"
        return self.source_path.read_text(encoding="utf-8")

    def add_code(
        self,
        code_update: str,
        *,
        description_hint: str | None = None,
    ) -> CodeRepositoryUpdate:
        code_update = _normalize_generated_code(
            _strip_code_fences(code_update).strip(),
            description_hint=description_hint,
        )
        if not code_update:
            return CodeRepositoryUpdate(
                source_path=self.source_path,
                errors=("empty python_code",),
            )
        incoming_result = compile_code_skills(code_update)
        if incoming_result.errors:
            return CodeRepositoryUpdate(
                source_path=self.source_path,
                errors=tuple(incoming_result.errors),
            )
        if not incoming_result.skills:
            return CodeRepositoryUpdate(
                source_path=self.source_path,
                errors=("python_code must define at least one @skill function",),
            )
        try:
            merged_source, updated_functions = _merge_code_source(self.read_source(), code_update)
        except SyntaxError as exc:
            return CodeRepositoryUpdate(
                source_path=self.source_path,
                errors=(f"syntax error: {exc}",),
            )
        merged_result = compile_code_skills(merged_source)
        if merged_result.errors:
            return CodeRepositoryUpdate(
                source_path=self.source_path,
                source=merged_source,
                updated_functions=updated_functions,
                errors=tuple(merged_result.errors),
            )
        normalized_skills = _normalize_compiled_skills(list(merged_result.skills))
        self._write_atomic(merged_source)
        return CodeRepositoryUpdate(
            source_path=self.source_path,
            source=merged_source,
            updated_functions=updated_functions,
            skills=tuple(normalized_skills),
            errors=(),
        )

    def list_all(self, *, platform: str | None = None, app: str | None = None) -> list[Skill]:
        result = compile_code_skills(self.read_source())
        if result.errors:
            logger.warning("Cannot list code skills: %s", result.errors)
            return []
        normalized_skills = _normalize_compiled_skills(list(result.skills))
        normalized_app = _normalize_app_filter(platform, app)
        return [
            skill
            for skill in normalized_skills
            if (platform is None or skill.platform == platform)
            and (normalized_app is None or skill.app == normalized_app)
        ]

    def _write_atomic(self, source: str) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.source_path.name}.",
            suffix=".tmp",
            dir=str(self.store_dir),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(source.rstrip() + "\n")
            os.replace(tmp_name, self.source_path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


class CodeSkillLibrary:
    """Search adapter over code-backed skills with optional legacy fallback."""

    def __init__(
        self,
        *,
        store_dir: Path,
        embedding_provider: Any | None = None,
        merge_llm: Any | None = None,
        embedding_signature: str | None = None,
        legacy_fallback: bool = True,
    ) -> None:
        self.store_dir = Path(store_dir).expanduser()
        self.embedding_provider = embedding_provider
        self.merge_llm = merge_llm
        self.embedding_signature = embedding_signature
        self._repository = CodeSkillRepository(self.store_dir)
        self._legacy_fallback_enabled = legacy_fallback
        self._legacy_library: Any | None = None
        self._source_mtime: float | None = _mtime(self._repository.source_path)
        self._graph_source_mtime: float | None = None
        self.graph_compile_errors: tuple[str, ...] = ()
        self.alpha = 0.6
        self._index_source_mtime: float | None = None
        self._indexed_skills: list[Skill] = []
        self._ordered_ids: list[str] = []
        self._documents: list[str] = []
        self._bm25 = _BM25Index()
        self._faiss = _FaissIndex()
        self._embeddings: dict[str, np.ndarray] = {}

    def refresh_if_stale(self) -> bool:
        current = _mtime(self._repository.source_path)
        changed = current != self._source_mtime
        self._source_mtime = current
        if changed:
            self._index_source_mtime = None
        legacy = self._legacy()
        if legacy is not None:
            refresh = getattr(legacy, "refresh_if_stale", None)
            if callable(refresh):
                changed = bool(refresh()) or changed
        return changed

    def load_all(self) -> None:
        self.refresh_if_stale()

    async def sync_graph_cache(self) -> bool:
        self.graph_compile_errors = ()
        source = self._repository.read_source()
        self._graph_source_mtime = _mtime(self._repository.source_path)
        if not _has_graph_transitions(source):
            return False

        from opengui.skills.code_graph import compile_code_graph
        from opengui.skills.graph import SkillGraphStore

        store = SkillGraphStore(
            store_dir=self.store_dir,
            embedding_provider=self.embedding_provider,
            embedding_signature=self.embedding_signature,
        )
        result = await compile_code_graph(source, store)
        self.graph_compile_errors = tuple(result.errors)
        if result.errors:
            return False
        if result.nodes or result.edges:
            store.compact_canonical_graph(save=True)
        return bool(store.count_nodes or store.count_edges)

    def list_all(self, *, platform: str | None = None, app: str | None = None) -> list[Skill]:
        skills = self._repository.list_all(platform=platform, app=app)
        if skills:
            return skills
        legacy = self._legacy()
        if legacy is None:
            return []
        return legacy.list_all(platform=platform, app=app)

    async def search(
        self,
        query: str,
        *,
        platform: str | None = None,
        app: str | None = None,
        top_k: int = 5,
    ) -> list[tuple[Skill, float]]:
        skills = self._repository.list_all()
        if skills:
            return await self._search_code_skills(
                query,
                skills,
                platform=platform,
                app=app,
                top_k=top_k,
            )
        legacy = self._legacy()
        if legacy is None:
            return []
        return await legacy.search(query, platform=platform, app=app, top_k=top_k)

    def get(self, skill_id: str) -> Skill | None:
        for skill in self._repository.list_all():
            if skill.skill_id == skill_id:
                return skill
        legacy = self._legacy()
        return legacy.get(skill_id) if legacy is not None else None

    def feedback_for_skill(self, skill_id: str) -> dict[str, Any]:
        return feedback_for_skill(self.store_dir, skill_id)

    def update(self, skill_id: str, updated_skill: Skill) -> bool:
        del updated_skill
        return self.get(skill_id) is not None

    def remove(self, skill_id: str) -> bool:
        del skill_id
        return False

    def _legacy(self) -> Any | None:
        if not self._legacy_fallback_enabled:
            return None
        if self._legacy_library is not None:
            return self._legacy_library
        if not any(self.store_dir.glob("*/skills.json")):
            return None
        try:
            from opengui.skills.legacy_json import SkillLibrary

            self._legacy_library = SkillLibrary(
                store_dir=self.store_dir,
                embedding_provider=self.embedding_provider,
                merge_llm=self.merge_llm,
                embedding_signature=self.embedding_signature,
            )
        except Exception:
            logger.warning("Legacy SkillLibrary fallback failed", exc_info=True)
            return None
        return self._legacy_library

    async def _search_code_skills(
        self,
        query: str,
        skills: list[Skill],
        *,
        platform: str | None,
        app: str | None,
        top_k: int,
    ) -> list[tuple[Skill, float]]:
        if not query.strip() or top_k <= 0:
            return []
        await self._ensure_index(skills)
        if not self._indexed_skills:
            return []

        normalized_app = _normalize_app_filter(platform, app)
        mask = np.ones(len(self._indexed_skills), dtype=bool)
        for index, skill in enumerate(self._indexed_skills):
            if platform is not None and skill.platform != platform:
                mask[index] = False
            elif normalized_app is not None and skill.app != normalized_app:
                mask[index] = False
        if not np.any(mask):
            return []

        bm25_scores = np.array(self._bm25.score(query), dtype=np.float32)
        bm25_scores[~mask] = -1e9
        valid_bm25 = bm25_scores[mask]
        bm25_max = float(valid_bm25.max()) if valid_bm25.size else 0.0
        if bm25_max > 0:
            bm25_scores = np.where(mask, bm25_scores / bm25_max, bm25_scores)

        query_emb = await self._query_embedding(query)
        if query_emb is not None and self._embeddings:
            faiss_raw, faiss_idx = self._faiss.search(query_emb, max(top_k * 4, top_k))
            emb_scores = np.full(len(self._indexed_skills), -1e9, dtype=np.float32)
            for score, index in zip(faiss_raw, faiss_idx, strict=False):
                if 0 <= index < len(self._indexed_skills):
                    emb_scores[index] = score
            emb_scores[~mask] = -1e9
            scores = (1.0 - self.alpha) * bm25_scores + self.alpha * emb_scores
        else:
            scores = bm25_scores

        self._apply_feedback_scores(query, scores, mask)

        ranked = np.argsort(-scores)
        results: list[tuple[Skill, float]] = []
        for index in ranked:
            if not mask[index] or scores[index] <= 0:
                break
            results.append((self._indexed_skills[int(index)], float(scores[index])))
            if len(results) >= top_k:
                break
        return results

    def _apply_feedback_scores(self, query: str, scores: np.ndarray, mask: np.ndarray) -> None:
        for index, skill in enumerate(self._indexed_skills):
            if not mask[index] or scores[index] <= 0:
                continue
            feedback = feedback_for_skill(self.store_dir, skill.skill_id)
            if not feedback:
                continue
            preferred_similarity = feedback_task_similarity(
                query,
                feedback.get("preferred_for_tasks"),
            )
            if preferred_similarity >= 0.72:
                scores[index] = max(float(scores[index]), 1.25 + 0.25 * preferred_similarity)
                continue
            negative_similarity = feedback_task_similarity(
                query,
                feedback.get("negative_tasks"),
            )
            if negative_similarity >= 0.72:
                scores[index] = min(float(scores[index]) * 0.1, 0.05)
                continue
            positive_similarity = feedback_task_similarity(
                query,
                feedback.get("positive_tasks"),
            )
            if positive_similarity >= 0.8:
                scores[index] = max(float(scores[index]), min(1.15, float(scores[index]) + 0.15))

    async def _ensure_index(self, skills: list[Skill]) -> None:
        source_mtime = _mtime(self._repository.source_path)
        skill_ids = [skill.skill_id for skill in skills]
        if (
            self._index_source_mtime == source_mtime
            and self._ordered_ids == skill_ids
            and len(self._documents) == len(skills)
        ):
            return

        self._indexed_skills = list(skills)
        self._ordered_ids = skill_ids
        self._documents = [_code_skill_search_text(skill) for skill in self._indexed_skills]
        self._bm25 = _BM25Index()
        self._bm25.build(self._documents)
        self._faiss = _FaissIndex()
        self._embeddings = {}

        if self.embedding_provider is not None and self._documents:
            try:
                vectors = await self.embedding_provider.embed(self._documents)
                for skill, vector in zip(self._indexed_skills, vectors, strict=False):
                    self._embeddings[skill.skill_id] = np.asarray(vector, dtype=np.float32)
                if self._embeddings:
                    self._faiss.build(np.stack([
                        self._embeddings[skill.skill_id]
                        for skill in self._indexed_skills
                        if skill.skill_id in self._embeddings
                    ]).astype(np.float32))
            except Exception as exc:
                logger.warning("Failed to embed code skills during index rebuild: %s", exc)
                self._embeddings = {}
                self._faiss = _FaissIndex()

        self._index_source_mtime = source_mtime

    async def _query_embedding(self, query: str) -> np.ndarray | None:
        if self.embedding_provider is None or not query.strip():
            return None
        try:
            vectors = await self.embedding_provider.embed([query])
        except Exception as exc:
            logger.warning("Failed to embed code skill query: %s", exc)
            return None
        if vectors is None or len(vectors) == 0:
            return None
        return np.asarray(vectors[0], dtype=np.float32)


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _event_step_index(event: dict[str, Any], *, fallback: int) -> int:
    try:
        return int(event.get("step_index"))
    except (TypeError, ValueError):
        return fallback


def _event_action_type(event: dict[str, Any]) -> str:
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    return _canonical_trace_action_type(action)


def _event_is_reusable_action(event: dict[str, Any]) -> bool:
    action_type = _event_action_type(event)
    return bool(action_type and _is_reusable_action_type(action_type))


def _reusable_event_count(events: list[dict[str, Any]]) -> int:
    return sum(1 for event in events if _event_is_reusable_action(event))


def _overlap_events(events: list[dict[str, Any]], reusable_count: int) -> list[dict[str, Any]]:
    if reusable_count <= 0:
        return []
    seen_reusable = 0
    start_index = len(events)
    for index in range(len(events) - 1, -1, -1):
        if _event_is_reusable_action(events[index]):
            seen_reusable += 1
            if seen_reusable >= reusable_count:
                start_index = index
                break
    if start_index >= len(events):
        return []
    return list(events[start_index:])


def _event_foreground_app(event: dict[str, Any] | None) -> str:
    if not isinstance(event, dict):
        return ""
    observation = _event_post_observation(event) or _event_prompt_observation(event)
    if not isinstance(observation, dict):
        return ""
    app = observation.get("foreground_app") or observation.get("app") or ""
    return str(app).strip()


def _event_page_signature(event: dict[str, Any] | None) -> set[str]:
    if not isinstance(event, dict):
        return set()
    observation = _event_post_observation(event) or _event_prompt_observation(event)
    if not isinstance(observation, dict):
        return set()
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    values: set[str] = set()
    for key in ("visible_text", "resource_ids", "content_desc"):
        raw = extra.get(key)
        if isinstance(raw, list):
            values.update(str(item).strip().casefold() for item in raw if str(item).strip())
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if not isinstance(node, dict):
                continue
            for key in ("text", "content_desc", "resource_id"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    values.add(value.strip().casefold())
    return values


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def canonicalize_code_actions_from_trace(
    code_update: str,
    trace_path: Path,
) -> CodeActionCanonicalization:
    """Rewrite generated skill actions so they are a subsequence of the trace."""
    events = _load_events(trace_path) if trace_path.exists() else []
    return canonicalize_code_actions_from_events(code_update, events)


def canonicalize_code_actions_from_events(
    code_update: str,
    events: list[dict[str, Any]],
) -> CodeActionCanonicalization:
    source = _normalize_generated_code(_strip_code_fences(code_update).strip())
    result = compile_code_skills(source)
    trace_actions = _trace_actions_from_events(events)
    report = _empty_action_sequence_report(trace_actions)
    if result.errors or not result.skills:
        report["quality"] = "unvalidated"
        report["errors"] = list(result.errors)
        return CodeActionCanonicalization(source=code_update, report=report)

    replacements: dict[str, list[tuple[int | None, _TraceAction]]] = {}
    for skill in result.skills:
        trace_cursor = -1
        aligned: list[tuple[int | None, _TraceAction]] = []
        last_source_step: Any | None = None
        last_match: _TraceAction | None = None
        for step_index, step in enumerate(skill.steps):
            match = _next_trace_action(
                trace_actions,
                step,
                skill_app=skill.app,
                skill_platform=skill.platform,
                after=trace_cursor,
            )
            if match is None:
                report["removed_steps"].append({
                    "function": skill.name,
                    "step_index": step_index,
                    "action_type": step.action_type,
                    "target": step.target,
                    "reason": "no_matching_trace_action",
                })
                continue
            for gap_action in _gap_trace_actions(
                trace_actions,
                skill_app=skill.app,
                skill_platform=skill.platform,
                after=trace_cursor,
                before=match.index,
                source_step=step,
                match=match,
            ):
                aligned.append((None, gap_action))
                report["synthesized_steps"].append({
                    "function": skill.name,
                    "trace_step_index": gap_action.index,
                    "action_type": gap_action.action_type,
                    "target": gap_action.target,
                    "reason": "trace_gap",
                })
            trace_cursor = match.index
            aligned.append((step_index, match))
            report["aligned_steps"].append({
                "function": skill.name,
                "step_index": step_index,
                "trace_step_index": match.index,
                "action_type": match.action_type,
                "generated_target": step.target,
                "trace_target": match.target,
                "target_rewritten": bool(match.target and match.target != step.target),
            })
            last_source_step = step
            last_match = match
        if last_source_step is not None and last_match is not None:
            for tail_action in _tail_trace_actions(
                trace_actions,
                skill_app=skill.app,
                skill_platform=skill.platform,
                after=trace_cursor,
                source_step=last_source_step,
                match=last_match,
            ):
                aligned.append((None, tail_action))
                report["synthesized_steps"].append({
                    "function": skill.name,
                    "trace_step_index": tail_action.index,
                    "action_type": tail_action.action_type,
                    "target": tail_action.target,
                    "reason": "trace_tail",
                })
        if not aligned and trace_actions:
            aligned = [
                (None, action)
                for action in trace_actions
                if _should_synthesize_trace_action(
                    action,
                    skill_app=skill.app,
                    skill_platform=skill.platform,
                )
            ]
            report["synthesized_functions"].append(skill.name)
        replacements[skill.name] = aligned

    canonical_source = _apply_action_replacements(source, replacements, result.skills)
    report["kept_action_count"] = sum(len(items) for items in replacements.values())
    report["reusable_action_count"] = sum(
        1
        for items in replacements.values()
        for _, action in items
        if _is_reusable_action_type(action.action_type)
    )
    report["removed_action_count"] = len(report["removed_steps"])
    if report["kept_action_count"] and not report["removed_action_count"]:
        report["quality"] = "aligned"
    elif report["kept_action_count"]:
        report["quality"] = "partial"
    else:
        report["quality"] = "none"
    return CodeActionCanonicalization(source=canonical_source, report=report)


def _empty_action_sequence_report(trace_actions: list[_TraceAction]) -> dict[str, Any]:
    return {
        "quality": "none",
        "trace_action_count": len(trace_actions),
        "kept_action_count": 0,
        "reusable_action_count": 0,
        "removed_action_count": 0,
        "aligned_steps": [],
        "removed_steps": [],
        "synthesized_functions": [],
        "synthesized_steps": [],
    }


def _is_reusable_action_type(action_type: str) -> bool:
    return action_type not in {
        "open_app",
        "close_app",
        "home",
        "back",
        "app_switch",
        "screenshot",
        "wait",
        "done",
        "request_intervention",
    }


def _trace_actions_from_events(events: list[dict[str, Any]]) -> list[_TraceAction]:
    actions: list[_TraceAction] = []
    latest_observation: dict[str, Any] | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type") or event.get("event")
        if event_type != "step":
            continue
        raw_action = event.get("action") if isinstance(event.get("action"), dict) else {}
        action_type = _canonical_trace_action_type(raw_action)
        post_observation = _event_post_observation(event)
        pre_observation = _event_pre_observation(event, latest_observation)
        if (
            action_type
            and action_type not in {"screenshot", "wait", "done", "request_intervention"}
            and not _observation_has_auth_gate(pre_observation)
        ):
            text_blob = _trace_text_blob(event, raw_action)
            action = _TraceAction(
                index=int(event.get("step_index") or len(actions)),
                action_type=action_type,
                target=_target_from_trace_action(
                    raw_action,
                    action_type=action_type,
                    pre_observation=pre_observation,
                    text_blob=text_blob,
                ),
                parameters=_parameters_from_trace_action(raw_action, action_type=action_type),
                text_blob=text_blob,
                pre_observation=pre_observation,
                post_observation=post_observation,
            )
            actions.append(action)
        if post_observation is not None:
            latest_observation = post_observation
        elif action_type not in {"", "screenshot", "wait"}:
            latest_observation = None
    return actions


def _event_pre_observation(
    event: dict[str, Any],
    fallback: dict[str, Any] | None,
) -> dict[str, Any] | None:
    for key in ("pre_observation", "before_observation", "observation_before"):
        value = event.get(key)
        if isinstance(value, dict):
            return value
    prompt_observation = _event_prompt_observation(event)
    if prompt_observation is not None:
        return prompt_observation
    return fallback


def _event_post_observation(event: dict[str, Any]) -> dict[str, Any] | None:
    observation = event.get("observation")
    if isinstance(observation, dict):
        return observation
    execution = event.get("execution")
    if isinstance(execution, dict):
        next_observation = execution.get("next_observation")
        if isinstance(next_observation, dict):
            return next_observation
    return None


def _event_prompt_observation(event: dict[str, Any]) -> dict[str, Any] | None:
    prompt = event.get("prompt")
    if isinstance(prompt, dict):
        current_observation = prompt.get("current_observation")
        if isinstance(current_observation, dict):
            return current_observation
    return None


def _canonical_trace_action_type(action: dict[str, Any]) -> str:
    raw_type = action.get("action_type") or action.get("action") or ""
    value = str(raw_type).strip().lower()
    aliases = {
        "click": "tap",
        "type": "input_text",
        "long_click": "long_press",
        "double_click": "double_tap",
        "navigate_back": "back",
        "navigate_home": "home",
        "recents": "app_switch",
        "recent_apps": "app_switch",
    }
    return aliases.get(value, value)


def _target_from_trace_action(
    action: dict[str, Any],
    *,
    action_type: str,
    pre_observation: dict[str, Any] | None,
    text_blob: str,
) -> str:
    explicit = _explicit_action_target(action, action_type=action_type)
    if explicit:
        return explicit
    if action_type in {"tap", "long_press", "double_tap"}:
        target = _target_from_point_action(action, pre_observation)
        if target:
            return target
    if action_type == "input_text":
        target = _focused_target_from_observation(pre_observation)
        if target:
            return target
    return _target_from_blob(text_blob)


def _explicit_action_target(action: dict[str, Any], *, action_type: str) -> str:
    target = action.get("target")
    if isinstance(target, str) and target.strip():
        return target.strip()
    text = action.get("text")
    if isinstance(text, str) and text.strip() and action_type in {
        "open_app",
        "close_app",
        "tap",
        "long_press",
        "double_tap",
    }:
        return text.strip()
    package = action.get("package")
    if isinstance(package, str) and package.strip() and action_type in {"open_app", "close_app"}:
        return package.strip()
    return ""


def _parameters_from_trace_action(action: dict[str, Any], *, action_type: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if action_type == "input_text":
        text = action.get("text")
        if isinstance(text, str):
            params["text"] = text
        if "auto_enter" in action:
            params["auto_enter"] = bool(action.get("auto_enter"))
    if action_type == "scroll":
        direction = action.get("direction") or action.get("text")
        if isinstance(direction, str) and direction.strip():
            params["text"] = direction.strip().lower()
        if action.get("pixels") is not None:
            params["pixels"] = action.get("pixels")
    if action_type == "hotkey" and action.get("key") is not None:
        params["key"] = action.get("key")
    for key in ("x", "y", "x2", "y2", "duration_ms"):
        value = action.get(key)
        if value is not None:
            params[key] = value
    if "relative" in action:
        params["relative"] = bool(action.get("relative"))
    return params


def _target_from_point_action(
    action: dict[str, Any],
    observation: dict[str, Any] | None,
) -> str:
    if not isinstance(observation, dict):
        return ""
    try:
        raw_x = float(action.get("x"))
        raw_y = float(action.get("y"))
    except (TypeError, ValueError):
        return ""
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    ui_tree = extra.get("ui_tree")
    if not isinstance(ui_tree, list):
        return ""
    nodes: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
    for node in ui_tree:
        if not isinstance(node, dict):
            continue
        bounds = _parse_ui_bounds(node.get("bounds"))
        if bounds is not None:
            nodes.append((node, bounds))
    if not nodes:
        return ""

    max_right = max(bounds[2] for _, bounds in nodes)
    max_bottom = max(bounds[3] for _, bounds in nodes)
    x, y = _point_in_ui_tree_coordinates(
        raw_x,
        raw_y,
        bool(action.get("relative", False)),
        observation=observation,
        max_right=max_right,
        max_bottom=max_bottom,
    )
    matches = [
        (node, bounds)
        for node, bounds in nodes
        if bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]
    ]
    if not matches:
        return ""
    for node, _ in sorted(matches, key=_point_target_rank):
        label = _target_label_from_node(node)
        if label:
            return label
    return ""


def _point_in_ui_tree_coordinates(
    x: float,
    y: float,
    relative: bool,
    *,
    observation: dict[str, Any],
    max_right: float,
    max_bottom: float,
) -> tuple[float, float]:
    width = _observation_extent(observation, "screen_width") or max_right
    height = _observation_extent(observation, "screen_height") or max_bottom
    if relative:
        x = x / 999.0 * max(width - 1.0, 1.0)
        y = y / 999.0 * max(height - 1.0, 1.0)
    if width > 0 and max_right > width:
        x *= max_right / width
    if height > 0 and max_bottom > height:
        y *= max_bottom / height
    return x, y


def _observation_extent(observation: dict[str, Any], key: str) -> float:
    value = observation.get(key)
    if value is None and isinstance(observation.get("extra"), dict):
        value = observation["extra"].get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _point_target_rank(
    item: tuple[dict[str, Any], tuple[float, float, float, float]],
) -> tuple[int, int, float]:
    node, bounds = item
    left, top, right, bottom = bounds
    area = max(0.0, right - left) * max(0.0, bottom - top)
    label = _target_label_from_node(node)
    identity_rank = 0 if label else 2
    clickable_rank = 0 if node.get("clickable") else 1
    return (identity_rank, clickable_rank, area)


def _target_label_from_node(node: dict[str, Any]) -> str:
    content_desc = _clean_node_label(node.get("content_desc"))
    if content_desc:
        return content_desc
    text = _clean_node_label(node.get("text"))
    if text:
        return text
    resource_id = _clean_node_label(node.get("resource_id"))
    if resource_id:
        return resource_id
    return ""


def _clean_node_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split()).strip()
    return value[:180]


def _focused_target_from_observation(observation: dict[str, Any] | None) -> str:
    if not isinstance(observation, dict):
        return ""
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    ui_tree = extra.get("ui_tree")
    if not isinstance(ui_tree, list):
        return ""
    for node in ui_tree:
        if isinstance(node, dict) and node.get("focused"):
            label = _target_label_from_node(node)
            if label:
                return label
    return ""


def _target_from_blob(blob: str) -> str:
    quoted = _quoted_target_from_blob(blob)
    if quoted:
        return quoted
    for pattern in (
        r"(?:点击|点按|选择|打开|进入)\s*([^，,。.!?；;\n]{1,40}?)(?:入口|按钮|标签|选项|菜单|页面)",
        r"(?:点击|点按|选择|打开|进入)\s*([^，,。.!?；;\n]{1,40})",
    ):
        match = re.search(pattern, blob)
        if match is None:
            continue
        target = match.group(1).strip()
        target = re.sub(r"^(?:底部|顶部)?(?:导航栏)?(?:的)", "", target).strip()
        if target:
            return target[:80]
    return ""


def _quoted_target_from_blob(blob: str) -> str:
    for pattern in (r'"([^"\n]{1,80})"', r"'([^'\n]{1,80})'", r"“([^”\n]{1,80})”"):
        match = re.search(pattern, blob)
        if match is not None:
            return match.group(1).strip()
    return ""


def _parse_ui_bounds(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            left, top, right, bottom = (float(item) for item in value)
        except (TypeError, ValueError):
            return None
        return (left, top, right, bottom) if right > left and bottom > top else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\[(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\]"
        r"\[(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\]",
        value.strip(),
    )
    if match is None:
        return None
    left, top, right, bottom = (float(match.group(index)) for index in range(1, 5))
    return (left, top, right, bottom) if right > left and bottom > top else None


def _next_trace_action(
    trace_actions: list[_TraceAction],
    step: Any,
    *,
    skill_app: str,
    skill_platform: str,
    after: int,
) -> _TraceAction | None:
    action_type = getattr(step, "action_type", "")
    candidates = [
        action
        for action in trace_actions
        if action.index > after and action.action_type == action_type
    ]
    if not candidates:
        return None
    in_app_candidates = [
        action
        for action in candidates
        if not _trace_action_crosses_app(action, skill_app=skill_app, skill_platform=skill_platform)
    ]
    if not in_app_candidates:
        return None

    target = str(getattr(step, "target", "") or "").strip().casefold()
    scored: list[tuple[int, int, _TraceAction]] = []
    for action in in_app_candidates:
        score = 0
        if target and target == action.target.casefold():
            score += 12
        if target and target in action.text_blob:
            score += 4
        if _step_coordinates_match_trace_action(step, action):
            score += 6
        if action.target and target and not _is_placeholder_value(target):
            score += 1
        if score > 0 or not target:
            scored.append((-score, action.index, action))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    return scored[0][2]


def _is_generic_target_text(target: str) -> bool:
    lowered = str(target or "").strip().casefold()
    if _looks_like_resource_id(lowered):
        name = lowered.split("/")[-1].split(":")[-1]
        return name in {"", "a"}
    return bool(
        lowered
        and (
            _is_placeholder_value(lowered)
            or is_dynamic_text(lowered)
            or lowered.endswith(":id/a")
            or lowered.endswith("/id/a")
            or lowered in {"a", "ctrip.android.view:id/a", "com.ctrip.ctrip:id/a"}
        )
    )


def _looks_like_resource_id(value: str) -> bool:
    value = str(value or "").strip()
    return bool(value and (":id/" in value or "/id/" in value))


def _observation_has_auth_gate(observation: dict[str, Any] | None) -> bool:
    if not isinstance(observation, dict):
        return False
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    values: list[str] = []
    for key in ("visible_text", "content_desc", "clickable_text", "enabled_text"):
        raw = extra.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item is not None)
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if not isinstance(node, dict):
                continue
            values.extend(
                str(node.get(key))
                for key in ("text", "content_desc")
                if node.get(key) is not None
            )
    blob = "\n".join(values)
    if not blob:
        return False
    return any(
        marker in blob
        for marker in ("获取验证码", "手机验证码登录", "账号密码登录", "登录密码", "短信验证码")
    )


def _gap_trace_actions(
    trace_actions: list[_TraceAction],
    *,
    skill_app: str,
    skill_platform: str,
    after: int,
    before: int,
    source_step: Any,
    match: _TraceAction,
) -> list[_TraceAction]:
    return [
        action
        for action in trace_actions
        if after < action.index < before
        and _should_synthesize_trace_action(
            action,
            skill_app=skill_app,
            skill_platform=skill_platform,
        )
        and _should_synthesize_bridge_action(action, source_step=source_step, match=match)
        and _trace_action_has_precondition_evidence(action)
    ]


def _tail_trace_actions(
    trace_actions: list[_TraceAction],
    *,
    skill_app: str,
    skill_platform: str,
    after: int,
    source_step: Any,
    match: _TraceAction,
) -> list[_TraceAction]:
    return [
        action
        for action in trace_actions
        if action.index > after
        and _should_synthesize_trace_action(
            action,
            skill_app=skill_app,
            skill_platform=skill_platform,
        )
        and _should_synthesize_bridge_action(action, source_step=source_step, match=match)
        and _trace_action_has_precondition_evidence(action)
    ]


def _should_synthesize_trace_action(
    action: _TraceAction,
    *,
    skill_app: str,
    skill_platform: str,
) -> bool:
    return _is_reusable_action_type(action.action_type) and not _trace_action_crosses_app(
        action,
        skill_app=skill_app,
        skill_platform=skill_platform,
    )


def _should_synthesize_bridge_action(
    action: _TraceAction,
    *,
    source_step: Any,
    match: _TraceAction,
) -> bool:
    target = str(getattr(source_step, "target", "") or "").strip().casefold()
    if not target:
        return False
    action_related = _targets_equal(target, action.target)
    match_related = _targets_equal(target, match.target)
    return action_related and match_related


def _trace_action_has_precondition_evidence(action: _TraceAction) -> bool:
    if action.action_type in {"open_app", "close_app", "back", "home", "enter", "app_switch"}:
        return True
    if action.action_type in {"tap", "long_press", "double_tap", "input_text"}:
        if _best_selector_for_point_action(action.parameters, action.pre_observation, action.action_type):
            return True
        if action.target and _best_selector_for_action(action.pre_observation, action.target, action.action_type):
            return True
        return False
    return isinstance(action.pre_observation, dict)


def _targets_equal(left: str, right: str) -> bool:
    left = left.strip().casefold()
    right = right.strip().casefold()
    return bool(left and right and left == right)


def _targets_related(left: str, right: str) -> bool:
    left = left.strip().casefold()
    right = right.strip().casefold()
    if not left or not right:
        return False
    if left == right:
        return True
    return len(left) > 1 and (left in right or right in left)


def _trace_action_crosses_app(
    action: _TraceAction,
    *,
    skill_app: str,
    skill_platform: str,
) -> bool:
    if action.action_type in {"open_app", "close_app", "app_switch"}:
        return False
    post_observation = action.post_observation
    if not isinstance(post_observation, dict):
        return False
    actual_app = str(
        post_observation.get("foreground_app")
        or post_observation.get("app")
        or ""
    ).strip()
    if not actual_app or not skill_app:
        return False
    left = normalize_app_identifier(skill_platform or "", actual_app)
    right = normalize_app_identifier(skill_platform or "", skill_app)
    return bool(left and right and left != "unknown" and right != "unknown" and left != right)


def _step_coordinates_match_trace_action(step: Any, action: _TraceAction) -> bool:
    parameters = getattr(step, "parameters", {}) or {}
    try:
        step_x = float(parameters.get("x"))
        step_y = float(parameters.get("y"))
        action_x = float(action.parameters.get("x"))
        action_y = float(action.parameters.get("y"))
    except (TypeError, ValueError):
        return False
    return abs(step_x - action_x) <= 1.0 and abs(step_y - action_y) <= 1.0


def _apply_action_replacements(
    source: str,
    replacements: dict[str, list[tuple[int | None, _TraceAction]]],
    skills: tuple[Skill, ...],
) -> str:
    if not replacements:
        return source
    source_steps = {skill.name: list(skill.steps) for skill in skills}
    tree = ast.parse(source)

    class Transformer(ast.NodeTransformer):
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
            if node.name not in replacements or not _has_decorator(node, "skill"):
                return node
            body: list[ast.stmt] = []
            for source_index, trace_action in replacements[node.name]:
                source_step = (
                    source_steps.get(node.name, [])[source_index]
                    if source_index is not None
                    and source_index < len(source_steps.get(node.name, []))
                    else None
                )
                body.append(_action_stmt_from_trace(
                    trace_action,
                    source_step,
                    parameter_names=[
                        arg.arg
                        for arg in node.args.args[1:]
                        if arg.arg
                    ],
                ))
            node.body = body or [ast.Pass()]
            return node

    transformed = Transformer().visit(tree)
    ast.fix_missing_locations(transformed)
    return ast.unparse(transformed) + "\n"


def _action_stmt_from_trace(
    action: _TraceAction,
    source_step: Any | None,
    *,
    parameter_names: list[str] | None = None,
) -> ast.stmt:
    call = ast.Call(
        func=ast.Name(id="action", ctx=ast.Load()),
        args=[ast.Constant(value=action.action_type)],
        keywords=[],
    )
    target = action.target or (getattr(source_step, "target", "") if source_step is not None else "")
    if target:
        call.keywords.append(ast.keyword(arg="target", value=ast.Constant(value=target)))
    for key, value in _merged_trace_parameters(action, source_step, parameter_names or []).items():
        call.keywords.append(ast.keyword(arg=key, value=_parameter_value_expr(value)))
    if (
        source_step is not None
        and action.action_type == getattr(source_step, "action_type", "")
        and target == getattr(source_step, "target", "")
        and getattr(source_step, "state_contract", None)
    ):
        _replace_state_contract_kw(
            call,
            _contract_call_expr({"contract": getattr(source_step, "state_contract", None)}),
        )
    return ast.Expr(value=ast.Await(value=call))


def _merged_trace_parameters(
    action: _TraceAction,
    source_step: Any | None,
    parameter_names: list[str],
) -> dict[str, Any]:
    params = dict(action.parameters)
    if source_step is None:
        if (
            action.action_type == "input_text"
            and len(parameter_names) == 1
            and isinstance(params.get("text"), str)
            and params.get("text")
        ):
            params["text"] = "{{" + parameter_names[0] + "}}"
        return params
    source_params = getattr(source_step, "parameters", {}) or {}
    if action.action_type == "input_text":
        text = source_params.get("text")
        if _is_placeholder_value(text):
            params["text"] = text
        elif len(parameter_names) == 1 and isinstance(params.get("text"), str) and params.get("text"):
            params["text"] = "{{" + parameter_names[0] + "}}"
    return params


def _is_placeholder_value(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"\{\{[A-Za-z_]\w*\}\}", value.strip()) is not None


def _parameter_value_expr(value: Any) -> ast.expr:
    if _is_placeholder_value(value):
        name = str(value).strip()[2:-2]
        return ast.Name(id=name, ctx=ast.Load())
    try:
        return ast.parse(repr(value), mode="eval").body
    except SyntaxError:
        return ast.Constant(value=str(value))


def repair_code_contracts_from_trace(
    code_update: str,
    trace_path: Path,
) -> CodeContractRepair:
    """Strengthen generated code contracts with deterministic UI-tree evidence."""
    events = _load_events(trace_path) if trace_path.exists() else []
    return repair_code_contracts_from_events(code_update, events)


def repair_code_contracts_from_events(
    code_update: str,
    events: list[dict[str, Any]],
) -> CodeContractRepair:
    source = _normalize_generated_code(_strip_code_fences(code_update).strip())
    result = compile_code_skills(source)
    if result.errors or not result.skills:
        return CodeContractRepair(source=code_update, report=_empty_contract_quality_report())
    evidence = _TraceEvidenceIndex(events)
    replacements: dict[str, dict[int, dict[str, Any]]] = {}
    repaired_steps: list[dict[str, Any]] = []
    audit_steps: list[dict[str, Any]] = []
    for skill in result.skills:
        trace_cursor = -1
        for index, step in enumerate(skill.steps):
            if step.action_type not in {"tap", "long_press", "double_tap", "input_text"}:
                continue
            trace_cursor, selector, evidence_observation = evidence.selector_for_step(
                target=step.target,
                action_type=step.action_type,
                parameters=step.parameters,
                after=trace_cursor,
            )
            current = normalize_state_contract(step.state_contract)
            current, sanitize_steps = _sanitize_action_contract(current, step)
            repaired_steps.extend(
                _repair_records(
                    skill=skill,
                    step=step,
                    index=index,
                    selector=None,
                    reasons=sanitize_steps,
                )
            )
            current_has_stable = _contract_has_stable_identity(current)
            current_supported = _contract_supported_by_observation(current, evidence_observation)
            if selector and _selector_has_stable_identity(selector):
                replacements.setdefault(skill.name, {})[index] = {
                    "app": skill.app,
                    "selector": _selector_identity(selector),
                    "states": _contract_states_for_selector(step.action_type, selector),
                }
                reason = (
                    "target_selector_replaced_page_contract"
                    if _contract_required_count(current) > 1 or not current_has_stable
                    else "ui_tree_static_selector"
                )
                repaired_steps.append({
                    "function": skill.name,
                    "step_index": index,
                    "action_type": step.action_type,
                    "target": step.target,
                    "selector": selector,
                    "reason": reason,
                })
                continue
            target_contract, target_reason = _target_contract_from_existing_contract(
                current,
                step,
                app=skill.app,
            )
            if target_contract is not None and target_contract != current:
                replacements.setdefault(skill.name, {})[index] = {
                    "app": skill.app,
                    "contract": target_contract,
                }
                repaired_steps.append({
                    "function": skill.name,
                    "step_index": index,
                    "action_type": step.action_type,
                    "target": step.target,
                    "selector": _first_required_selector(target_contract),
                    "reason": target_reason,
                })
                continue
            if current != normalize_state_contract(step.state_contract):
                replacements.setdefault(skill.name, {})[index] = {
                    "app": skill.app,
                    "contract": current,
                }
                continue
            if current_has_stable and current_supported:
                continue
            replacement: dict[str, Any] | None = None
            states = _contract_states_for_selector(step.action_type, selector)
            reason = "ui_tree_static_selector"
            if selector and _selector_has_stable_identity(selector):
                replacement = {
                    "app": skill.app,
                    "selector": _selector_identity(selector),
                    "states": states,
                }
                if _contract_required_count(current) > 1 or not current_has_stable:
                    reason = "target_selector_replaced_page_contract"
            elif selector is None and evidence_observation is not None:
                fallback_contract = _fallback_target_contract_from_observation(
                    evidence_observation,
                    app=skill.app,
                    step=step,
                )
                if fallback_contract is not None:
                    replacement = {
                        "app": skill.app,
                        "contract": fallback_contract,
                    }
                    reason = "target_text_contract_from_observation"
            if replacement is None:
                if selector is None:
                    audit_steps.append({
                        "function": skill.name,
                        "step_index": index,
                        "action_type": step.action_type,
                        "target": step.target,
                        "selector": None,
                        "reason": "no_target_selector",
                    })
                continue
            replacements.setdefault(skill.name, {})[index] = replacement
            repaired_steps.append({
                "function": skill.name,
                "step_index": index,
                "action_type": step.action_type,
                "target": step.target,
                "selector": selector,
                "reason": reason,
            })
    repaired_source = _apply_contract_replacements(source, replacements) if replacements else source
    repaired_result = compile_code_skills(repaired_source)
    skills = repaired_result.skills if not repaired_result.errors else result.skills
    report = _contract_quality_report(skills, repaired_steps=tuple(repaired_steps))
    _append_contract_audit_steps(report, audit_steps)
    return CodeContractRepair(source=repaired_source, report=report)


def filter_code_to_contract_complete(
    code_update: str,
    *,
    repair_report: dict[str, Any] | None = None,
) -> CodeContractFilter:
    """Drop or trim generated functions that still have weak step contracts."""
    source = _normalize_generated_code(_strip_code_fences(code_update).strip())
    result = compile_code_skills(source)
    if result.errors or not result.skills:
        return CodeContractFilter(source=code_update, report=_empty_contract_quality_report())
    report = _merge_repair_steps_into_quality_report(
        _contract_quality_report(result.skills),
        repair_report,
    )
    weak_functions = {
        str(step.get("function"))
        for step in report.get("weak_steps", [])
        if isinstance(step, dict) and step.get("function")
    }
    if not weak_functions:
        return CodeContractFilter(source=source, report=report)
    tree = ast.parse(source)
    first_weak_step_by_function: dict[str, int] = {}
    for step in report.get("weak_steps", []):
        if not isinstance(step, dict):
            continue
        function_name = str(step.get("function") or "")
        step_index = step.get("step_index")
        if not function_name or not isinstance(step_index, int):
            continue
        existing = first_weak_step_by_function.get(function_name)
        if existing is None or step_index < existing:
            first_weak_step_by_function[function_name] = step_index

    removed: list[str] = []
    trimmed: list[str] = []
    kept_body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in weak_functions:
            first_weak_step = first_weak_step_by_function.get(node.name, 0)
            if first_weak_step > 0 and _trim_skill_function_to_action_prefix(node, first_weak_step):
                trimmed.append(node.name)
                kept_body.append(node)
                continue
            else:
                removed.append(node.name)
                continue
        kept_body.append(node)
    tree.body = kept_body
    ast.fix_missing_locations(tree)
    filtered_source = ast.unparse(tree) + "\n"
    filtered_result = compile_code_skills(filtered_source)
    filtered_report = report if filtered_result.errors or not filtered_result.skills else (
        _merge_repair_steps_into_quality_report(
            _contract_quality_report(filtered_result.skills),
            repair_report,
            removed_functions=set(removed),
        )
    )
    if trimmed:
        filtered_report = {
            **filtered_report,
            "trimmed_functions": trimmed,
        }
    return CodeContractFilter(
        source=filtered_source,
        report=filtered_report,
        removed_functions=tuple(removed),
    )


def build_visual_guarded_code_fallback(
    code_update: str,
    events: list[dict[str, Any]],
    *,
    action_sequence_report: dict[str, Any] | None = None,
) -> CodeVisualGuardFallback:
    """Convert trace-aligned weak-contract skills into vision-gated UI skills.

    This is intentionally a fallback path for apps where accessibility/UI-tree
    evidence is unavailable but screenshots still exist.  It strips weak
    structured contracts from ordinary UI actions and replaces them with
    ``valid_state`` strings, so runtime execution must pass the vision validator
    before grounding and acting.
    """
    source = _normalize_generated_code(_strip_code_fences(code_update).strip())
    report: dict[str, Any] = {
        "mode": "visual_guarded",
        "enabled": False,
        "visual_guarded_functions": [],
        "visual_guarded_steps": [],
        "rejected_functions": [],
        "reason": None,
    }
    if not _events_have_screenshot_evidence(events):
        report["reason"] = "missing_screenshot_evidence"
        return CodeVisualGuardFallback(source=code_update, report=report)

    result = compile_code_skills(source)
    if result.errors or not result.skills:
        report["reason"] = "code_compile_error" if result.errors else "no_skills"
        if result.errors:
            report["errors"] = list(result.errors)
        return CodeVisualGuardFallback(source=code_update, report=report)

    aligned = _aligned_trace_steps_by_function(action_sequence_report or {})
    event_by_step = _events_by_step_index(events)
    skills_by_name = {skill.name: skill for skill in result.skills}
    tree = ast.parse(source)
    kept_body: list[ast.stmt] = []

    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef) or not _has_decorator(node, "skill"):
            kept_body.append(node)
            continue
        skill = skills_by_name.get(node.name)
        if skill is None:
            kept_body.append(node)
            continue
        if str(skill.platform or "").lower() != "android":
            kept_body.append(node)
            continue

        action_index = 0
        guarded_steps: list[dict[str, Any]] = []
        rejected_reason: str | None = None
        for stmt in node.body:
            call = _awaited_action_call(stmt)
            if call is None:
                continue
            action_type = _action_call_type(call)
            if action_type in {"open_app", "open_deeplink", "open_intent", "wait", "done", "request_intervention"}:
                if action_type == "open_app":
                    _remove_action_keyword(call, "state_contract")
                action_index += 1
                continue

            step = skill.steps[action_index] if action_index < len(skill.steps) else None
            aligned_step = aligned.get((node.name, action_index), {})
            trace_step_index = _int_or_none(aligned_step.get("trace_step_index"))
            event = event_by_step.get(trace_step_index) if trace_step_index is not None else None
            if event is None:
                rejected_reason = "missing_aligned_trace_step"
                break
            valid_state = _visual_valid_state_for_action(
                skill=skill,
                step=step,
                event=event,
                trace_target=str(aligned_step.get("trace_target") or ""),
            )
            if not valid_state:
                rejected_reason = "missing_visual_valid_state"
                break

            _remove_action_keyword(call, "state_contract")
            _replace_string_keyword(call, "valid_state", valid_state)
            guarded_steps.append({
                "function": node.name,
                "step_index": action_index,
                "trace_step_index": trace_step_index,
                "action_type": action_type,
                "target": getattr(step, "target", "") if step is not None else "",
                "valid_state": valid_state,
            })
            action_index += 1

        if rejected_reason is not None:
            report["rejected_functions"].append({
                "function": node.name,
                "reason": rejected_reason,
            })
            continue
        if guarded_steps:
            _ensure_skill_decorator_tag(node, "visual_guarded")
            _ensure_skill_decorator_tag(node, "ui")
            report["visual_guarded_functions"].append(node.name)
            report["visual_guarded_steps"].extend(guarded_steps)
        kept_body.append(node)

    tree.body = kept_body
    ast.fix_missing_locations(tree)
    transformed_source = ast.unparse(tree) + "\n"
    transformed_result = compile_code_skills(transformed_source)
    if transformed_result.errors:
        report["reason"] = "visual_guard_compile_error"
        report["errors"] = list(transformed_result.errors)
        return CodeVisualGuardFallback(source=code_update, report=report)
    if not report["visual_guarded_functions"]:
        report["reason"] = report["reason"] or "no_guarded_functions"
        return CodeVisualGuardFallback(source=code_update, report=report)

    report["enabled"] = True
    return CodeVisualGuardFallback(source=transformed_source, report=report)


def normalize_code_skill_entrypoints(code_update: str) -> CodeEntrypointNormalization:
    """Add deterministic Android app entrypoints and clean ``open_app`` contracts.

    Extraction segments often begin after launcher/app-open actions have been
    cut away.  For Android package-scoped skills, prepend a plain ``open_app``
    entry action when the learned prefix starts mid-flow.  ``open_deeplink`` is
    already a stronger entry action and is left untouched.
    """
    source = _normalize_generated_code(_strip_code_fences(code_update).strip())
    report: dict[str, Any] = {
        "entrypoint_normalized_functions": [],
        "open_app_contract_stripped_functions": [],
    }
    result = compile_code_skills(source)
    if result.errors or not result.skills:
        if result.errors:
            report["errors"] = list(result.errors)
        return CodeEntrypointNormalization(source=code_update, report=report)

    skills_by_name = {skill.name: skill for skill in result.skills}
    tree = ast.parse(source)

    class Transformer(ast.NodeTransformer):
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
            self.generic_visit(node)
            stripped = _strip_open_app_state_contracts_in_function(node)
            if stripped:
                report["open_app_contract_stripped_functions"].append(node.name)

            skill = skills_by_name.get(node.name)
            if skill is None or not _has_decorator(node, "skill"):
                return node
            if not _should_normalize_android_skill_entrypoint(skill):
                return node

            first_action = skill.steps[0].action_type if skill.steps else ""
            if first_action in _ENTRY_ACTION_TYPES:
                return node

            app_target = normalize_app_identifier(skill.platform, skill.app)
            node.body.insert(
                _skill_entry_insert_index(node),
                _open_app_action_stmt(app_target),
            )
            report["entrypoint_normalized_functions"].append(node.name)
            return node

    transformed = Transformer().visit(tree)
    ast.fix_missing_locations(transformed)
    return CodeEntrypointNormalization(source=ast.unparse(transformed) + "\n", report=report)


def _trim_skill_function_to_action_prefix(func: ast.AsyncFunctionDef, action_limit: int) -> bool:
    """Trim ``func`` after ``action_limit`` direct action calls.

    Generated flat skills are usually a sequence of ``await action(...)``
    statements.  When a weak action appears after a useful canonical prefix,
    keeping that prefix is safer than dropping the whole learned skill.
    """
    kept: list[ast.stmt] = []
    action_count = 0
    kept_reusable_actions = 0
    for stmt in func.body:
        if _is_direct_action_await(stmt):
            if action_count >= action_limit:
                break
            action_type = _direct_action_type(stmt)
            if action_type not in {"open_app", "wait", "done", "request_intervention"}:
                kept_reusable_actions += 1
            action_count += 1
        kept.append(stmt)
    if kept_reusable_actions <= 0:
        return False
    func.body = kept
    return True


def _is_direct_action_await(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
        return False
    call = stmt.value.value
    if not isinstance(call, ast.Call):
        return False
    return _call_name_from_ast(call.func) == "action"


def _direct_action_type(stmt: ast.stmt) -> str:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
        return ""
    call = stmt.value.value
    if not isinstance(call, ast.Call) or _call_name_from_ast(call.func) != "action":
        return ""
    first_arg = call.args[0] if call.args else None
    if isinstance(first_arg, ast.Constant):
        return str(first_arg.value or "")
    return ""


_ENTRY_ACTION_TYPES = frozenset({"open_app", "open_deeplink", "open_intent"})
_ANDROID_LAUNCHER_PACKAGES = frozenset({
    "com.android.launcher",
    "com.android.launcher3",
    "com.google.android.apps.nexuslauncher",
    "com.miui.home",
})


def _should_normalize_android_skill_entrypoint(skill: Skill) -> bool:
    platform = str(getattr(skill, "platform", "") or "").strip().lower()
    if platform != "android":
        return False
    normalized_app = normalize_app_identifier(platform, str(getattr(skill, "app", "") or ""))
    if normalized_app in _ANDROID_LAUNCHER_PACKAGES:
        return False
    return bool(normalized_app and normalized_app != "unknown" and "." in normalized_app)


def _skill_entry_insert_index(func: ast.AsyncFunctionDef) -> int:
    if (
        func.body
        and isinstance(func.body[0], ast.Expr)
        and isinstance(func.body[0].value, ast.Constant)
        and isinstance(func.body[0].value.value, str)
    ):
        return 1
    return 0


def _open_app_action_stmt(app_target: str) -> ast.stmt:
    return ast.Expr(
        value=ast.Await(
            value=ast.Call(
                func=ast.Name(id="action", ctx=ast.Load()),
                args=[ast.Constant(value="open_app")],
                keywords=[ast.keyword(arg="target", value=ast.Constant(value=app_target))],
            )
        )
    )


def _strip_open_app_state_contracts_in_function(
    func: ast.AsyncFunctionDef | ast.FunctionDef,
) -> bool:
    stripped = False
    for stmt in func.body:
        call = _awaited_action_call(stmt)
        if call is None or _action_call_type(call) != "open_app":
            continue
        if _remove_action_keyword(call, "state_contract"):
            stripped = True
    return stripped


def _action_call_type(call: ast.Call) -> str:
    first_arg = call.args[0] if call.args else None
    if isinstance(first_arg, ast.Constant):
        return str(first_arg.value or "")
    return ""


def _remove_action_keyword(call: ast.Call, keyword_name: str) -> bool:
    before = len(call.keywords)
    call.keywords = [keyword for keyword in call.keywords if keyword.arg != keyword_name]
    return len(call.keywords) != before


def _replace_string_keyword(call: ast.Call, keyword_name: str, value: str) -> None:
    expr = ast.Constant(value=value)
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            keyword.value = expr
            return
    call.keywords.append(ast.keyword(arg=keyword_name, value=expr))


def _ensure_skill_decorator_tag(func: ast.AsyncFunctionDef, tag: str) -> None:
    for decorator in func.decorator_list:
        if not isinstance(decorator, ast.Call) or _call_name_from_ast(decorator.func) != "skill":
            continue
        tags_kw = next((kw for kw in decorator.keywords if kw.arg == "tags"), None)
        if tags_kw is None:
            tags_kw = ast.keyword(arg="tags", value=ast.List(elts=[], ctx=ast.Load()))
            decorator.keywords.append(tags_kw)
        if isinstance(tags_kw.value, ast.Tuple):
            existing = [
                elt.value
                for elt in tags_kw.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
            if tag not in existing:
                tags_kw.value.elts.append(ast.Constant(value=tag))
            return
        if isinstance(tags_kw.value, ast.List):
            existing = [
                elt.value
                for elt in tags_kw.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
            if tag not in existing:
                tags_kw.value.elts.append(ast.Constant(value=tag))
            return
        tags_kw.value = ast.List(elts=[ast.Constant(value=tag)], ctx=ast.Load())
        return


def _events_have_screenshot_evidence(events: list[dict[str, Any]]) -> bool:
    return any(_screenshot_path_from_event(event) is not None for event in events)


def _aligned_trace_steps_by_function(
    action_sequence_report: dict[str, Any],
) -> dict[tuple[str, int], dict[str, Any]]:
    aligned: dict[tuple[str, int], dict[str, Any]] = {}
    for item in action_sequence_report.get("aligned_steps") or []:
        if not isinstance(item, dict):
            continue
        function_name = str(item.get("function") or "")
        step_index = _int_or_none(item.get("step_index"))
        if function_name and step_index is not None:
            aligned[(function_name, step_index)] = item
    return aligned


def _events_by_step_index(events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    mapped: dict[int, dict[str, Any]] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        if (event.get("type") or event.get("event")) != "step":
            continue
        step_index = _int_or_none(event.get("step_index"))
        mapped[step_index if step_index is not None else index] = event
    return mapped


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _visual_valid_state_for_action(
    *,
    skill: Skill,
    step: SkillStep | None,
    event: dict[str, Any],
    trace_target: str,
) -> str:
    target = (
        trace_target
        or (step.target if step is not None else "")
        or _target_from_trace_action(
            event.get("action") if isinstance(event.get("action"), dict) else {},
            action_type=str(getattr(step, "action_type", "") or ""),
            pre_observation=_event_pre_observation(event, None),
            text_blob=_trace_text_blob(event, event.get("action") if isinstance(event.get("action"), dict) else {}),
        )
    )
    action_summary = _first_nonempty_string(
        event.get("state_summary"),
        event.get("summary"),
        event.get("action_summary"),
        event.get("model_output"),
    )
    app = normalize_app_identifier(str(skill.platform or ""), str(skill.app or ""))
    action_type = str(getattr(step, "action_type", "") or "")
    target_clause = f" target {target!r}" if target else " the intended target"
    if action_summary:
        return _trim_visual_state(
            f"The current {app} screen visually matches this step context: "
            f"{action_summary}. The next {action_type or 'GUI'} action can be applied to{target_clause}."
        )
    return _trim_visual_state(
        f"The current {app} screen visually shows{target_clause} and is ready for the next "
        f"{action_type or 'GUI'} action."
    )


def _first_nonempty_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _trim_visual_state(text: str, *, limit: int = 360) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _merge_repair_steps_into_quality_report(
    quality_report: dict[str, Any],
    repair_report: dict[str, Any] | None,
    *,
    removed_functions: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(repair_report, dict):
        return quality_report
    removed_functions = removed_functions or set()
    repaired_steps = [
        step
        for step in repair_report.get("repaired_steps", [])
        if isinstance(step, dict) and str(step.get("function") or "") not in removed_functions
    ]
    merged = dict(quality_report)
    merged["repaired_steps"] = repaired_steps
    merged.update(_contract_audit_fields(repaired_steps))
    for field in _contract_audit_fields():
        if field != "no_target_selector_steps":
            continue
        audit_steps = [
            step
            for step in repair_report.get(field, [])
            if isinstance(step, dict) and str(step.get("function") or "") not in removed_functions
        ]
        if audit_steps:
            merged[field] = audit_steps
    target_repair_keys = {
        (str(step.get("function") or ""), step.get("step_index"))
        for step in repaired_steps
        if str(step.get("reason") or "") in _TARGET_CONTRACT_REPAIR_REASONS
    }
    if target_repair_keys:
        weak_steps = [
            step for step in merged.get("weak_steps", [])
            if (str(step.get("function") or ""), step.get("step_index")) not in target_repair_keys
        ]
        promoted_count = len(merged.get("weak_steps", [])) - len(weak_steps)
        merged["weak_steps"] = weak_steps
        merged["canonical_step_count"] = int(merged.get("canonical_step_count") or 0) + promoted_count
        merged["canonical_node_count"] = int(merged.get("canonical_node_count") or 0) + promoted_count
        merged["auxiliary_node_count"] = len(weak_steps)
        merged["quality"] = (
            "canonical"
            if merged["canonical_step_count"] and not weak_steps
            else "partial"
            if merged["canonical_step_count"]
            else "weak"
        )
    return merged


def _append_contract_audit_steps(report: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    if not steps:
        return
    for field in _contract_audit_fields():
        report.setdefault(field, [])
    for step in steps:
        reason = str(step.get("reason") or "")
        if reason == "no_target_selector":
            report["no_target_selector_steps"].append(step)


class _TraceEvidenceIndex:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._steps: list[_TraceEvidenceStep] = []
        latest_observation: dict[str, Any] | None = None
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type") or event.get("event")
            if event_type == "step":
                action = event.get("action") if isinstance(event.get("action"), dict) else {}
                action_type = str(action.get("action_type") or "").strip()
                post_observation = _event_post_observation(event)
                pre_observation = _event_pre_observation(event, latest_observation)
                if _observation_has_auth_gate(pre_observation):
                    if post_observation is not None:
                        latest_observation = post_observation
                    elif action_type not in {"", "screenshot", "wait"}:
                        latest_observation = None
                    continue
                text_blob = _trace_text_blob(event, action)
                self._steps.append(_TraceEvidenceStep(
                    index=int(event.get("step_index") or len(self._steps)),
                    action_type=action_type,
                    parameters=_parameters_from_trace_action(action, action_type=action_type),
                    target=_target_from_trace_action(
                        action,
                        action_type=action_type,
                        pre_observation=pre_observation,
                        text_blob=text_blob,
                    ),
                    text_blob=text_blob,
                    pre_observation=pre_observation,
                    post_observation=post_observation,
                ))
                if post_observation is not None:
                    latest_observation = post_observation
                elif action_type not in {"", "screenshot", "wait"}:
                    latest_observation = None

    def selector_for_step(
        self,
        *,
        target: str,
        action_type: str,
        parameters: dict[str, Any] | None = None,
        after: int,
    ) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
        if action_type not in {"tap", "long_press", "double_tap", "input_text"}:
            return after, None, None
        target_text = str(target or "").strip()
        if not target_text:
            return after, None, None
        candidates = [
            step
            for step in self._steps
            if step.index > after and step.action_type == action_type
        ]
        if candidates:
            match = _best_trace_step(candidates, target_text)
            if match is None:
                match = candidates[0]
            selector = _best_selector_for_point_action(
                parameters or match.parameters,
                match.pre_observation,
                action_type,
            )
            if selector is None and not _is_placeholder_value(target_text):
                selector = _best_selector_for_action(match.pre_observation, target_text, action_type)
            evidence_observation = match.pre_observation
            if selector is None and not _observation_has_selector_evidence(match.pre_observation):
                selector = _best_selector_for_point_action(
                    parameters or match.parameters,
                    match.post_observation,
                    action_type,
                )
                if selector is None and not _is_placeholder_value(target_text):
                    selector = _best_selector_for_action(match.post_observation, target_text, action_type)
                evidence_observation = match.post_observation
            return match.index, selector, evidence_observation
        for step in self._steps:
            if step.index <= after:
                continue
            selector = _best_selector_for_action(step.post_observation, target_text, action_type)
            if selector is not None:
                return step.index, selector, step.post_observation
        return after, None, None


def _best_trace_step(candidates: list[_TraceEvidenceStep], target_text: str) -> _TraceEvidenceStep | None:
    exact_matches = [
        candidate
        for candidate in candidates
        if candidate.target.strip().casefold() == target_text.strip().casefold()
    ]
    if exact_matches:
        return min(exact_matches, key=lambda candidate: candidate.index)

    scored: list[tuple[int, int, _TraceEvidenceStep]] = []
    for candidate in candidates:
        score = 0
        if (
            _best_selector_for_point_action(candidate.parameters, candidate.pre_observation, candidate.action_type)
            or (
                not _is_placeholder_value(target_text)
                and _best_selector_for_action(candidate.pre_observation, target_text, candidate.action_type)
            )
        ):
            score += 8
        if candidate.target.strip().casefold() == target_text.strip().casefold():
            score += 12
        if _blob_mentions_target(candidate.text_blob, target_text):
            score += 4
        if _observation_mentions_target(candidate.pre_observation, target_text):
            score += 2
        if _observation_mentions_target(candidate.post_observation, target_text):
            score += 1
        if score > 0:
            scored.append((-score, candidate.index, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    return scored[0][2]


def _best_selector_for_action(
    observation: dict[str, Any] | None,
    target_text: str,
    action_type: str,
) -> dict[str, Any] | None:
    if not isinstance(observation, dict):
        return None
    matches = [
        selector
        for selector in _selectors_for_target(observation, target_text, action_type=action_type)
        if _selector_compatible_with_action(selector, action_type)
    ]
    if not matches:
        return None
    matches.sort(key=_selector_strength, reverse=True)
    return matches[0]


def _best_selector_for_point_action(
    parameters: dict[str, Any] | None,
    observation: dict[str, Any] | None,
    action_type: str,
) -> dict[str, Any] | None:
    if action_type not in {"tap", "long_press", "double_tap", "input_text"}:
        return None
    if not isinstance(parameters, dict) or not isinstance(observation, dict):
        return None
    try:
        raw_x = float(parameters.get("x"))
        raw_y = float(parameters.get("y"))
    except (TypeError, ValueError):
        return None
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    ui_tree = extra.get("ui_tree")
    if not isinstance(ui_tree, list):
        return None
    nodes: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
    for node in ui_tree:
        if not isinstance(node, dict):
            continue
        bounds = _parse_ui_bounds(node.get("bounds"))
        if bounds is not None:
            nodes.append((node, bounds))
    if not nodes:
        return None
    max_right = max(bounds[2] for _, bounds in nodes)
    max_bottom = max(bounds[3] for _, bounds in nodes)
    x, y = _point_in_ui_tree_coordinates(
        raw_x,
        raw_y,
        bool(parameters.get("relative", False)),
        observation=observation,
        max_right=max_right,
        max_bottom=max_bottom,
    )
    matches = [
        (node, bounds)
        for node, bounds in nodes
        if bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]
    ]
    selectors: list[dict[str, Any]] = []
    for node, _ in sorted(matches, key=_point_target_rank):
        selector = _input_selector_from_node(node) if action_type == "input_text" else _stable_selector_from_node(node)
        if selector and _selector_has_stable_identity(selector):
            selectors.append(selector)
    if not selectors:
        return None
    return selectors[0]


def _contract_states_for_selector(action_type: str, selector: dict[str, Any] | None) -> list[str]:
    states = ["visible"]
    if not isinstance(selector, dict):
        return states
    if selector.get("enabled"):
        states.append("enabled")
    if action_type in {"tap", "long_press", "double_tap"} and selector.get("clickable"):
        states.append("clickable")
    return list(dict.fromkeys(states))


def _sanitize_action_contract(
    contract: dict[str, Any] | None,
    step: SkillStep,
) -> tuple[dict[str, Any] | None, list[str]]:
    current = normalize_state_contract(contract)
    reasons: list[str] = []
    sanitized_input_contract = _strip_parameterized_input_text_from_contract(current, step)
    if sanitized_input_contract is not None and sanitized_input_contract != current:
        current = sanitized_input_contract
        reasons.append("parameterized_input_text_removed")
    sanitized_dynamic_contract = _strip_dynamic_target_text_from_contract(current, step)
    if sanitized_dynamic_contract is not None and sanitized_dynamic_contract != current:
        current = sanitized_dynamic_contract
        reasons.append("dynamic_target_text_removed")
    sanitized_volatile_contract = _strip_volatile_action_states_from_contract(current, step)
    if sanitized_volatile_contract is not None and sanitized_volatile_contract != current:
        current = sanitized_volatile_contract
        reasons.append("volatile_state_stripped")
    return current, reasons


def _repair_records(
    *,
    skill: Skill,
    step: SkillStep,
    index: int,
    selector: dict[str, Any] | None,
    reasons: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "function": skill.name,
            "step_index": index,
            "action_type": step.action_type,
            "target": step.target,
            "selector": selector,
            "reason": reason,
        }
        for reason in reasons
    ]


def _strip_volatile_action_states_from_contract(
    contract: dict[str, Any] | None,
    step: SkillStep,
) -> dict[str, Any] | None:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return None
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return None
    changed = False
    sanitized_required: list[Any] = []
    for element in required:
        if not isinstance(element, dict):
            sanitized_required.append(element)
            continue
        state = element.get("state") if isinstance(element.get("state"), list) else []
        sanitized_state = [item for item in state if item != "focused"]
        if step.action_type == "input_text":
            sanitized_state = [
                item for item in sanitized_state if item in {"visible", "enabled"}
            ]
        if not sanitized_state and state:
            sanitized_state = ["visible"]
        if sanitized_state == state:
            sanitized_required.append(element)
            continue
        updated = dict(element)
        updated["state"] = sanitized_state
        sanitized_required.append(updated)
        changed = True
    if not changed:
        return None
    sanitized = dict(normalized)
    sanitized_signature = dict(signature)
    sanitized_signature["required"] = sanitized_required
    sanitized["signature"] = sanitized_signature
    return normalize_state_contract(sanitized)


def _target_contract_from_existing_contract(
    contract: dict[str, Any] | None,
    step: SkillStep,
    *,
    app: str,
) -> tuple[dict[str, Any] | None, str | None]:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return None, None
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list) or len(required) <= 1:
        return None, None
    target = str(step.target or "").strip()
    if not target or _is_placeholder_value(target) or (
        is_dynamic_text(target) and not _looks_like_resource_id(target)
    ):
        return None, None

    candidates: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for element in required:
        if not isinstance(element, dict):
            continue
        selector = element.get("selector")
        if not isinstance(selector, dict):
            continue
        if not _selector_mentions_target(selector, target):
            continue
        if _is_background_selector(selector) and not _selector_exactly_matches_target(selector, target):
            continue
        selector_identity = _selector_identity(selector)
        if not selector_identity:
            continue
        if not (
            _selector_has_stable_identity(selector_identity)
            or selector_identity.get("text")
            or _selector_has_input_identity(selector_identity)
        ):
            continue
        updated_element = {
            "selector": selector_identity,
            "state": _contract_states_for_selector(step.action_type, selector),
        }
        candidates.append((_selector_strength(selector_identity), updated_element))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0], reverse=True)
    anchor_app = str(normalized.get("anchor", {}).get("app_package") or app or "").strip()
    contract_out = normalize_state_contract({
        "anchor": {"app_package": anchor_app},
        "signature": {"required": [candidates[0][1]], "forbidden": []},
    })
    return contract_out, "target_element_reduced_page_contract"


def _fallback_target_contract_from_observation(
    observation: dict[str, Any] | None,
    *,
    app: str,
    step: SkillStep,
) -> dict[str, Any] | None:
    target = str(step.target or "").strip()
    if not target or _is_placeholder_value(target) or (
        is_dynamic_text(target) and not _looks_like_resource_id(target)
    ):
        return None
    if not isinstance(observation, dict) or not _observation_mentions_target(observation, target):
        return None
    selector = _best_selector_for_action(observation, target, step.action_type)
    if selector is not None and _selector_has_stable_identity(selector):
        anchor_app = str(observation.get("foreground_app") or observation.get("app") or app or "").strip() or app
        return normalize_state_contract({
            "anchor": {"app_package": anchor_app},
            "signature": {
                "required": [
                    {
                        "selector": _selector_identity(selector),
                        "state": _contract_states_for_selector(step.action_type, selector),
                    }
                ],
                "forbidden": [],
            },
        })
    if not is_static_text(target):
        return None
    anchor_app = str(observation.get("foreground_app") or observation.get("app") or app or "").strip() or app
    return normalize_state_contract({
        "anchor": {"app_package": anchor_app},
        "signature": {
            "required": [{"selector": {"text": target}, "state": ["visible"]}],
            "forbidden": [],
        },
    })


def _first_required_selector(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    normalized = normalize_state_contract(contract)
    signature = normalized.get("signature") if isinstance(normalized, dict) else None
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list) or not required:
        return None
    first = required[0]
    selector = first.get("selector") if isinstance(first, dict) else None
    return dict(selector) if isinstance(selector, dict) else None


def _selector_identity(selector: dict[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for key in ("resource_id", "content_desc", "text", "class", "xpath"):
        value = selector.get(key)
        if value is None:
            continue
        if key == "text" and (
            is_dynamic_text(value)
            or (selector.get("resource_id") or selector.get("content_desc"))
        ):
            continue
        identity[key] = value
    return identity


def _selector_mentions_target(selector: dict[str, Any], target: str) -> bool:
    target_clean = target.strip()
    if not target_clean:
        return False
    for key in ("text", "content_desc", "resource_id"):
        value = selector.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if _value_mentions_target(value, target_clean):
            return True
        if key == "resource_id" and _resource_id_mentions_target(value, target_clean):
            return True
    return False


def _selector_exactly_matches_target(selector: dict[str, Any], target: str) -> bool:
    target_clean = target.strip().casefold()
    for key in ("text", "content_desc"):
        value = selector.get(key)
        if isinstance(value, str) and value.strip().casefold() == target_clean:
            return True
    return False


def _resource_id_mentions_target(resource_id: str, target: str) -> bool:
    target_clean = target.strip().casefold()
    if not target_clean:
        return False
    name = resource_id.split("/")[-1].split(":")[-1].casefold()
    tokens = [token for token in re.split(r"[^a-z0-9]+", name) if token]
    target_tokens = [token for token in re.split(r"[^a-z0-9]+", target_clean) if token]
    return (
        target_clean in tokens
        or name.endswith(target_clean)
        or bool(target_tokens and all(token in tokens for token in target_tokens))
    )


def _is_background_selector(selector: dict[str, Any]) -> bool:
    values = [
        selector.get("text"),
        selector.get("content_desc"),
        selector.get("resource_id"),
    ]
    joined = " ".join(str(value).casefold() for value in values if value)
    if not joined:
        return False
    return any(
        marker in joined
        for marker in (
            "more options",
            "overflow",
            "toolbar",
            "tab_menu",
            "menu_",
            "alarm",
            "clock",
            "cancel",
            "save",
        )
    )


def _selector_compatible_with_action(selector: dict[str, Any], action_type: str) -> bool:
    if action_type in {"tap", "long_press", "double_tap"}:
        return _selector_has_stable_identity(selector)
    if action_type == "input_text":
        selector_class = str(selector.get("class") or "").casefold()
        return bool(
            selector.get("focused")
            or "edittext" in selector_class
            or "input" in selector_class
        )
    return True


def _strip_parameterized_input_text_from_contract(
    contract: dict[str, Any] | None,
    step: SkillStep,
) -> dict[str, Any] | None:
    if step.action_type != "input_text" or not _is_placeholder_value(step.parameters.get("text")):
        return None
    normalized = normalize_state_contract(contract)
    if not normalized:
        return None
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return None
    changed = False
    sanitized_required: list[Any] = []
    for element in required:
        if not isinstance(element, dict):
            sanitized_required.append(element)
            continue
        selector = element.get("selector")
        if not isinstance(selector, dict) or not selector.get("resource_id") or "text" not in selector:
            sanitized_required.append(element)
            continue
        updated_selector = dict(selector)
        updated_selector.pop("text", None)
        updated_element = dict(element)
        updated_element["selector"] = updated_selector
        sanitized_required.append(updated_element)
        changed = True
    if not changed:
        return None
    sanitized = dict(normalized)
    sanitized_signature = dict(signature)
    sanitized_signature["required"] = sanitized_required
    sanitized["signature"] = sanitized_signature
    return normalize_state_contract(sanitized)


def _strip_dynamic_target_text_from_contract(
    contract: dict[str, Any] | None,
    step: SkillStep,
) -> dict[str, Any] | None:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return None
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return None

    dynamic_values = {
        str(value).strip().casefold()
        for value in (
            step.target,
            step.parameters.get("text") if isinstance(step.parameters, dict) else None,
        )
        if isinstance(value, str)
        and value.strip()
        and (_is_placeholder_value(value) or is_dynamic_text(value))
    }
    changed = False
    sanitized_required: list[Any] = []
    for element in required:
        if not isinstance(element, dict):
            sanitized_required.append(element)
            continue
        selector = element.get("selector")
        if not isinstance(selector, dict):
            sanitized_required.append(element)
            continue
        selector_text = selector.get("text")
        if (
            not isinstance(selector_text, str)
            or not selector_text.strip()
            or not (selector.get("resource_id") or selector.get("content_desc"))
        ):
            sanitized_required.append(element)
            continue
        normalized_text = selector_text.strip().casefold()
        if normalized_text not in dynamic_values and not is_dynamic_text(selector_text):
            sanitized_required.append(element)
            continue
        updated_selector = dict(selector)
        updated_selector.pop("text", None)
        updated_element = dict(element)
        updated_element["selector"] = updated_selector
        sanitized_required.append(updated_element)
        changed = True
    if not changed:
        return None
    sanitized = dict(normalized)
    sanitized_signature = dict(signature)
    sanitized_signature["required"] = sanitized_required
    sanitized["signature"] = sanitized_signature
    return normalize_state_contract(sanitized)


def _trace_text_blob(event: dict[str, Any], action: dict[str, Any]) -> str:
    parts: list[str] = []
    for value in (
        action.get("target"),
        action.get("text"),
        event.get("target"),
        event.get("action_summary"),
        event.get("summary"),
        event.get("model_output"),
    ):
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts).casefold()


def _observation_mentions_target(observation: dict[str, Any] | None, target_text: str) -> bool:
    if not isinstance(observation, dict):
        return False
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    values: list[str] = []
    for key in ("visible_text", "clickable_text", "content_desc", "resource_ids"):
        raw = extra.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item is not None)
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if isinstance(node, dict):
                values.extend(
                    str(value)
                    for value in (node.get("text"), node.get("content_desc"), node.get("resource_id"))
                    if value is not None
                )
    return any(_value_mentions_target(value, target_text) for value in values)


def _blob_mentions_target(blob: str, target_text: str) -> bool:
    target = target_text.strip().casefold()
    if not target:
        return False
    blob = blob.casefold()
    if any(line.strip() == target for line in blob.splitlines()):
        return True
    quoted = (f'"{target}"', f"'{target}'", f"“{target}”", f"‘{target}’")
    if any(mark in blob for mark in quoted):
        return True
    return len(target) > 1 and target in blob


def _value_mentions_target(value: str, target_text: str) -> bool:
    value_clean = value.strip().casefold()
    target = target_text.strip().casefold()
    if not value_clean or not target:
        return False
    if value_clean == target:
        return True
    return len(target) > 1 and target in value_clean


def _selectors_for_target(
    observation: dict[str, Any],
    target_text: str,
    *,
    action_type: str,
) -> list[dict[str, Any]]:
    extra = observation.get("extra") if isinstance(observation, dict) else None
    ui_tree = extra.get("ui_tree") if isinstance(extra, dict) else None
    if not isinstance(ui_tree, list):
        return []
    matches: list[dict[str, Any]] = []
    for node in ui_tree:
        if not isinstance(node, dict):
            continue
        if not _node_matches_target(node, target_text):
            continue
        if action_type == "input_text":
            selector = _input_selector_from_node(node)
            if selector:
                matches.append(selector)
                continue
        selector = _stable_selector_from_node(node)
        if selector:
            matches.append(selector)
            continue
    return matches


def _node_matches_target(node: dict[str, Any], target_text: str) -> bool:
    target = str(target_text or "").strip()
    if not target:
        return False
    text = node.get("text")
    if isinstance(text, str) and text.strip() and not _is_generic_target_text(target):
        if _value_mentions_target(text, target):
            return True
    content_desc = node.get("content_desc")
    if isinstance(content_desc, str) and content_desc.strip():
        if _value_mentions_target(content_desc, target):
            return True
    resource_id = node.get("resource_id")
    if isinstance(resource_id, str) and resource_id.strip():
        return _value_mentions_target(resource_id, target) or _resource_id_mentions_target(
            resource_id,
            target,
        )
    return False


def _selector_strength(selector: dict[str, Any]) -> tuple[int, int]:
    if selector.get("resource_id"):
        return (3, len(str(selector.get("resource_id"))))
    if selector.get("content_desc"):
        return (2, len(str(selector.get("content_desc"))))
    if selector.get("text"):
        return (1, len(str(selector.get("text"))))
    return (0, 0)


def _selector_has_stable_identity(selector: dict[str, Any]) -> bool:
    if _selector_has_input_identity(selector):
        return True
    return bool(selector.get("resource_id") or selector.get("content_desc")) and selector_is_static(selector)


def _selector_has_input_identity(selector: dict[str, Any]) -> bool:
    selector_class = str(selector.get("class") or "").casefold()
    return bool(
        (selector.get("resource_id") or selector.get("text") or selector.get("content_desc"))
        and ("edittext" in selector_class or "input" in selector_class)
        and (selector.get("focused") or selector.get("enabled"))
    )


def _contract_supported_by_observation(
    contract: dict[str, Any] | None,
    observation: dict[str, Any] | None,
) -> bool:
    normalized = normalize_state_contract(contract)
    if not normalized or not isinstance(observation, dict):
        return False
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return False
    observed = _observation_selectors(observation)
    saw_stable_identity = False
    for element in required:
        selector = element.get("selector") if isinstance(element, dict) else None
        if not isinstance(selector, dict) or not _selector_has_stable_identity(selector):
            continue
        saw_stable_identity = True
        expected_state = set(element.get("state") if isinstance(element.get("state"), list) else [])
        if not any(
            _selector_matches_observed(selector, candidate)
            and expected_state.issubset(set(_selector_states_from_observed(candidate)))
            for candidate in observed
        ):
            return False
    return saw_stable_identity


def _observation_selectors(observation: dict[str, Any]) -> list[dict[str, Any]]:
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    selectors: list[dict[str, Any]] = []
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if not isinstance(node, dict):
                continue
            selector = _stable_selector_from_node(node)
            if selector:
                selectors.append(selector)
                continue
            selector = _input_selector_from_node(node)
            if selector:
                selectors.append(selector)
    for resource_id in filter_static_resource_ids(extra.get("resource_ids"), limit=20):
        selectors.append({"resource_id": resource_id})
    for text in [
        *filter_static_texts(extra.get("clickable_text"), limit=20),
        *filter_static_texts(extra.get("visible_text"), limit=20),
    ]:
        selectors.append({"text": text})
    return selectors


def _observation_has_selector_evidence(observation: dict[str, Any] | None) -> bool:
    if not isinstance(observation, dict):
        return False
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        return any(isinstance(node, dict) for node in ui_tree)
    return any(
        isinstance(extra.get(key), list) and bool(extra.get(key))
        for key in ("resource_ids", "clickable_text", "visible_text", "content_desc")
    )


def _stable_selector_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    selector: dict[str, Any] = {}
    resource_id = _clean_selector_text(node.get("resource_id"))
    content_desc = _clean_selector_text(node.get("content_desc"))
    text = _clean_selector_text(node.get("text"))

    if resource_id and (is_static_resource_id(resource_id) or not is_dynamic_resource_id(resource_id)):
        selector["resource_id"] = resource_id
    elif content_desc and is_static_text(content_desc):
        selector["content_desc"] = content_desc
    elif text and is_static_text(text):
        selector["text"] = text
    else:
        return None

    for flag in ("clickable", "enabled", "focused", "scrollable"):
        if node.get(flag):
            selector[flag] = True
    return selector or None


def _input_selector_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    resource_id = node.get("resource_id")
    text = node.get("text")
    content_desc = node.get("content_desc")
    node_class = node.get("class")
    if not isinstance(node_class, str) or not node_class.strip():
        return None
    class_key = node_class.casefold()
    if not (node.get("focused") or "edittext" in class_key or "input" in class_key):
        return None
    selector: dict[str, Any] = {"class": node_class.strip()}
    if isinstance(resource_id, str) and resource_id.strip():
        selector["resource_id"] = resource_id.strip()
    elif isinstance(content_desc, str) and content_desc.strip():
        selector["content_desc"] = content_desc.strip()
    elif isinstance(text, str) and text.strip() and not is_dynamic_text(text):
        selector["text"] = text.strip()
    else:
        return None
    for flag in ("clickable", "enabled", "focused", "scrollable"):
        if node.get(flag):
            selector[flag] = True
    return selector


def _clean_selector_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _selector_matches_observed(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    for key in ("resource_id", "content_desc", "text", "xpath"):
        value = expected.get(key)
        if value is None:
            continue
        if observed.get(key) != value:
            return False
    return True


def _selector_states_from_observed(selector: dict[str, Any]) -> list[str]:
    states = ["visible"]
    for flag in ("clickable", "enabled", "focused", "scrollable"):
        if selector.get(flag):
            states.append(flag)
    return states


def _page_contract_from_observation(
    observation: dict[str, Any] | None,
    *,
    app: str,
    target: str,
) -> dict[str, Any] | None:
    if not isinstance(observation, dict):
        return None
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    text_values: list[str] = []
    for text in [
        *filter_static_texts(extra.get("clickable_text"), limit=20),
        *filter_static_texts(extra.get("visible_text"), limit=20),
    ]:
        if text not in text_values:
            text_values.append(text)
    target_text = str(target or "").strip()
    if target_text:
        text_values.sort(key=lambda value: 0 if _value_mentions_target(value, target_text) else 1)
    if len(text_values) < 2:
        return None
    anchor_app = str(observation.get("foreground_app") or observation.get("app") or app or "").strip()
    if not anchor_app:
        anchor_app = app
    return normalize_state_contract({
        "anchor": {"app_package": anchor_app},
        "signature": {
            "required": [
                {"selector": {"text": text}, "state": ["visible"]}
                for text in text_values[:3]
            ],
            "forbidden": [],
        },
    })


def _fallback_target_contract(app: str, target: str) -> dict[str, Any] | None:
    target_text = str(target or "").strip()
    if not target_text:
        return normalize_state_contract({"anchor": {"app_package": app}, "signature": {"required": [], "forbidden": []}})
    return normalize_state_contract({
        "anchor": {"app_package": app},
        "signature": {
            "required": [{"selector": {"text": target_text}, "state": ["visible"]}],
            "forbidden": [],
        },
    })


def _contract_has_stable_identity(contract: dict[str, Any] | None) -> bool:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return False
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return False
    for element in required:
        selector = element.get("selector") if isinstance(element, dict) else None
        if isinstance(selector, dict) and _selector_has_stable_identity(selector):
            return True
    return False


def _contract_required_count(contract: dict[str, Any] | None) -> int:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return 0
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    return len(required) if isinstance(required, list) else 0


def _apply_contract_replacements(
    source: str,
    replacements: dict[str, dict[int, dict[str, Any]]],
) -> str:
    if not replacements:
        return source
    tree = ast.parse(source)

    class Transformer(ast.NodeTransformer):
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
            step_replacements = replacements.get(node.name)
            if not step_replacements:
                return node
            action_index = 0
            for stmt in node.body:
                call = _awaited_action_call(stmt)
                if call is None:
                    continue
                replacement = step_replacements.get(action_index)
                if replacement is not None:
                    _replace_state_contract_kw(call, _contract_call_expr(replacement))
                action_index += 1
            return node

    transformed = Transformer().visit(tree)
    ast.fix_missing_locations(transformed)
    return ast.unparse(transformed) + "\n"


def _awaited_action_call(stmt: ast.stmt) -> ast.Call | None:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
        return None
    call = stmt.value.value
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if isinstance(func, ast.Name) and func.id == "action":
        return call
    return None


def _replace_state_contract_kw(call: ast.Call, value: ast.expr) -> None:
    for keyword in call.keywords:
        if keyword.arg == "state_contract":
            keyword.value = value
            return
    call.keywords.append(ast.keyword(arg="state_contract", value=value))


def _contract_call_expr(replacement: dict[str, Any]) -> ast.expr:
    contract = replacement.get("contract")
    if isinstance(contract, dict):
        return ast.Call(
            func=ast.Attribute(value=ast.Name(id="C", ctx=ast.Load()), attr="from_dict", ctx=ast.Load()),
            args=[ast.parse(repr(contract), mode="eval").body],
            keywords=[],
        )
    selector = dict(replacement.get("selector") or {})
    states = set(replacement.get("states") or ())
    r_keywords: list[ast.keyword] = []
    for key in ("text", "content_desc", "resource_id", "class", "xpath"):
        value = selector.get(key)
        if value is None:
            continue
        arg = "class_" if key == "class" else key
        r_keywords.append(ast.keyword(arg=arg, value=ast.Constant(value=value)))
    for flag in ("visible", "clickable", "enabled", "focused", "scrollable"):
        if flag in states:
            r_keywords.append(ast.keyword(arg=flag, value=ast.Constant(value=True)))
    r_call = ast.Call(func=ast.Name(id="R", ctx=ast.Load()), args=[], keywords=r_keywords)
    return ast.Call(
        func=ast.Name(id="C", ctx=ast.Load()),
        args=[],
        keywords=[
            ast.keyword(arg="app", value=ast.Constant(value=replacement.get("app") or "")),
            ast.keyword(arg="required", value=ast.List(elts=[r_call], ctx=ast.Load())),
        ],
    )


def _empty_contract_quality_report() -> dict[str, Any]:
    return {
        "quality": "weak",
        "canonical_step_count": 0,
        "weak_steps": [],
        "repaired_steps": [],
        "target_selector_repaired_steps": [],
        "target_contract_steps": [],
        "multi_required_action_contract_reduced_steps": [],
        "background_anchor_dropped_steps": [],
        "volatile_state_stripped_steps": [],
        "no_target_selector_steps": [],
        "dynamic_target_text_stripped_steps": [],
        "page_anchor_downgraded_steps": [],
        "canonical_node_count": 0,
        "auxiliary_node_count": 0,
    }


def _contract_quality_report(
    skills: tuple[Skill, ...],
    *,
    repaired_steps: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    canonical_steps = 0
    weak_steps: list[dict[str, Any]] = []
    for skill in skills:
        for index, step in enumerate(skill.steps):
            if step.action_type in {"open_app", "wait", "done", "request_intervention"}:
                continue
            if _is_canonical_step_contract(step.state_contract):
                canonical_steps += 1
                continue
            weak_steps.append({
                "function": skill.name,
                "step_index": index,
                "action_type": step.action_type,
                "target": step.target,
                "reason": _weak_contract_reason(step.state_contract),
            })
    quality = "canonical" if canonical_steps and not weak_steps else "partial" if canonical_steps else "weak"
    report = _empty_contract_quality_report()
    report.update({
        "quality": quality,
        "canonical_step_count": canonical_steps,
        "canonical_node_count": canonical_steps,
        "auxiliary_node_count": len(weak_steps),
        "weak_steps": weak_steps,
        "repaired_steps": list(repaired_steps),
        **_contract_audit_fields(repaired_steps),
    })
    return report


def _contract_audit_fields(
    repaired_steps: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "target_selector_repaired_steps": [
            dict(step)
            for step in repaired_steps
            if str(step.get("reason") or "") in _TARGET_CONTRACT_REPAIR_REASONS
        ],
        "target_contract_steps": [
            dict(step)
            for step in repaired_steps
            if str(step.get("reason") or "") in _TARGET_CONTRACT_REPAIR_REASONS
        ],
        "multi_required_action_contract_reduced_steps": [
            dict(step)
            for step in repaired_steps
            if str(step.get("reason") or "") in {
                "target_selector_replaced_page_contract",
                "target_element_reduced_page_contract",
            }
        ],
        "background_anchor_dropped_steps": [
            dict(step)
            for step in repaired_steps
            if str(step.get("reason") or "") in {
                "target_selector_replaced_page_contract",
                "target_element_reduced_page_contract",
            }
        ],
        "volatile_state_stripped_steps": [
            dict(step)
            for step in repaired_steps
            if str(step.get("reason") or "") == "volatile_state_stripped"
        ],
        "no_target_selector_steps": [
            dict(step)
            for step in repaired_steps
            if str(step.get("reason") or "") == "no_target_selector"
        ],
        "dynamic_target_text_stripped_steps": [
            dict(step)
            for step in repaired_steps
            if str(step.get("reason") or "") in {
                "parameterized_input_text_removed",
                "dynamic_target_text_removed",
            }
        ],
        "page_anchor_downgraded_steps": [
            dict(step)
            for step in repaired_steps
            if str(step.get("reason") or "") in {
                "target_selector_replaced_page_contract",
                "target_element_reduced_page_contract",
            }
        ],
    }


def _is_canonical_step_contract(contract: dict[str, Any] | None) -> bool:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return False
    anchor = normalized.get("anchor")
    if not isinstance(anchor, dict) or not anchor.get("app_package"):
        return False
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return False
    text_selectors: set[str] = set()
    for element in required:
        selector = element.get("selector") if isinstance(element, dict) else None
        if not isinstance(selector, dict):
            continue
        if _selector_has_input_identity(selector) or _element_has_input_identity(element):
            return True
        if not selector_is_static(selector):
            continue
        if selector.get("resource_id") or selector.get("content_desc"):
            return True
        text = selector.get("text")
        if isinstance(text, str) and text.strip():
            text_selectors.add(text.strip())
    return len(text_selectors) >= 2


def _weak_contract_reason(contract: dict[str, Any] | None) -> str:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return "missing_state_contract"
    anchor = normalized.get("anchor")
    if not isinstance(anchor, dict) or not anchor.get("app_package"):
        return "missing_app_anchor"
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list) or not required:
        return "missing_required_selector"
    text_count = 0
    has_identity = False
    for element in required:
        selector = element.get("selector") if isinstance(element, dict) else None
        if not isinstance(selector, dict):
            continue
        if _selector_has_input_identity(selector) or _element_has_input_identity(element):
            has_identity = True
        if selector.get("resource_id") or selector.get("content_desc"):
            has_identity = True
        if selector.get("text"):
            text_count += 1
    if text_count == 1 and not has_identity:
        return "single_text_selector"
    return "noncanonical_selector"


def _element_has_input_identity(element: dict[str, Any]) -> bool:
    selector = element.get("selector")
    if not isinstance(selector, dict):
        return False
    selector_class = str(selector.get("class") or "").casefold()
    state = set(element.get("state") if isinstance(element.get("state"), list) else [])
    return bool(
        (selector.get("resource_id") or selector.get("text") or selector.get("content_desc"))
        and ("edittext" in selector_class or "input" in selector_class)
        and ({"focused", "enabled"} & state)
    )


def _compact_events(events: list[dict[str, Any]], max_events: int) -> list[dict[str, Any]]:
    selected = events[-max_events:] if len(events) > max_events else events
    compacted: list[dict[str, Any]] = []
    for event in selected:
        item = {
            key: value
            for key, value in event.items()
            if key
            in {
                "type",
                "step_index",
                "action",
                "action_summary",
                "model_output",
                "observation",
                "goal",
                "instruction",
                "task",
                "state",
                "success",
                "error",
                "total_steps",
            }
        }
        compacted.append(item)
    return compacted


def _screenshot_path_from_event(event: dict[str, Any]) -> Path | None:
    value = event.get("screenshot_path")
    if value is None:
        observation = _event_post_observation(event) or _event_prompt_observation(event)
        if isinstance(observation, dict):
            value = observation.get("screenshot_path")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _llm_supports_screenshot_input(llm: Any) -> bool:
    model = str(
        getattr(llm, "_model", "")
        or getattr(llm, "model", "")
        or ""
    ).casefold()
    if not model:
        return True
    vision_markers = (
        "vision",
        "vl",
        "gpt-4o",
        "gpt-5",
        "gemini",
        "claude-3",
        "qwen-vl",
        "qwen2.5-vl",
        "qwen3-vl",
        "ui-tars",
    )
    return any(marker in model for marker in vision_markers)


def _sample_screenshot_candidates(
    candidates: list[tuple[int, str, str]],
    limit: int,
) -> list[tuple[int, str, str]]:
    if limit <= 0 or not candidates:
        return []
    if len(candidates) <= limit:
        return candidates
    if limit == 1:
        return [candidates[-1]]
    selected_indices = {0, len(candidates) - 1}
    remaining = limit - len(selected_indices)
    if remaining > 0:
        span = len(candidates) - 1
        for i in range(1, remaining + 1):
            selected_indices.add(round(i * span / (remaining + 1)))
    return [candidates[index] for index in sorted(selected_indices)]


def _encode_image_b64(path: str) -> str | None:
    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
            scaled = img.resize((max(width // 4, 1), max(height // 4, 1)), Image.LANCZOS)
            buffer = io.BytesIO()
            scaled.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception as exc:
        logger.debug("Could not encode screenshot %s: %s", path, exc)
        return None


def _compact_evaluation(evaluation_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(evaluation_result, dict):
        return {}
    compact: dict[str, Any] = {}
    if isinstance(evaluation_result.get("success"), bool):
        compact["success"] = evaluation_result["success"]
    reason = evaluation_result.get("reason")
    if isinstance(reason, str) and reason.strip():
        compact["reason"] = reason.strip()[:600]
    return compact


def _platform_hint(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        observation = _event_post_observation(event) or _event_prompt_observation(event)
        if isinstance(observation, dict) and isinstance(observation.get("platform"), str):
            return observation["platform"]
    return None


def _parse_code_response(text: str) -> tuple[dict[str, str], list[str]]:
    cleaned = text.strip()
    parsed: Any
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match is None:
            parsed = {
                "step_by_step_reasoning": "",
                "python_code": _strip_code_fences(cleaned),
            }
        else:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = {}
    if not isinstance(parsed, dict):
        return {"step_by_step_reasoning": "", "python_code": ""}, ["response was not an object"]
    reasoning = parsed.get("step_by_step_reasoning", "")
    python_code = parsed.get("python_code", "")
    violations: list[str] = []
    if not isinstance(reasoning, str):
        violations.append("step_by_step_reasoning must be a string")
        reasoning = str(reasoning)
    if not isinstance(python_code, str) or not python_code.strip():
        violations.append("python_code must be a non-empty string")
        python_code = str(python_code or "")
    return {
        "step_by_step_reasoning": reasoning,
        "python_code": _strip_code_fences(python_code),
    }, violations


def _strip_code_fences(code: str) -> str:
    code = code.strip()
    for fence in ("```python3", "```python", "```"):
        code = code.replace(fence, "")
    return code.strip()


def _normalize_generated_code(
    source: str,
    *,
    description_hint: str | None = None,
) -> str:
    if not source:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    transformer = _GeneratedCodeNormalizer(description_hint=description_hint)
    transformed = transformer.visit(tree)
    if not transformer.changed:
        return source
    ast.fix_missing_locations(transformed)
    return ast.unparse(transformed) + "\n"


class _GeneratedCodeNormalizer(ast.NodeTransformer):
    def __init__(self, *, description_hint: str | None = None) -> None:
        self.changed = False
        self.description_hint = " ".join(str(description_hint or "").split())
        self._default_stack: list[dict[str, Any]] = []

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self._default_stack.append(_literal_function_defaults(node))
        self.generic_visit(node)
        self._default_stack.pop()
        return self._merge_skill_description(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if _is_r_call(node):
            self._normalize_selector_keyword_expressions(node)
            return node
        if not _is_action_call(node):
            return node
        target_kw = next((kw for kw in node.keywords if kw.arg == "target"), None)
        if target_kw is not None and _is_r_call(target_kw.value):
            label = _target_label_from_r_call(target_kw.value)
            if label:
                selector_call = copy.deepcopy(target_kw.value)
                target_kw.value = ast.Constant(value=label)
                if not _action_call_has_required_state_contract(node):
                    _set_or_add_state_contract(node, selector_call)
                self.changed = True
        self._normalize_action_keyword_expressions(node)
        return node

    def _merge_skill_description(self, node: ast.AsyncFunctionDef) -> ast.AST:
        description = _merge_description_hint(
            ast.get_docstring(node, clean=True) or "",
            self.description_hint,
        )
        if not description:
            return node
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if _call_name_from_ast(decorator.func) != "skill":
                continue
            description_kw = next((kw for kw in decorator.keywords if kw.arg == "description"), None)
            if description_kw is not None:
                if not isinstance(description_kw.value, ast.Constant) or not isinstance(description_kw.value.value, str):
                    return node
                merged = _merge_description_hint(description_kw.value.value, self.description_hint)
                if merged == description_kw.value.value:
                    return node
                description_kw.value = ast.Constant(value=merged)
                self.changed = True
                return node
            decorator.keywords.append(ast.keyword(
                arg="description",
                value=ast.Constant(value=description),
            ))
            self.changed = True
            return node
        return node

    def _normalize_action_keyword_expressions(self, node: ast.Call) -> None:
        defaults = self._default_stack[-1] if self._default_stack else {}
        for keyword in node.keywords:
            if keyword.arg in {None, "state_contract", "fixed_values", "parameters"}:
                continue
            try:
                ast.literal_eval(keyword.value)
                continue
            except (TypeError, ValueError):
                pass
            if isinstance(keyword.value, ast.Name):
                continue
            normalized = _literalize_safe_generated_expr(keyword.value, defaults)
            if normalized is None:
                continue
            keyword.value = ast.Constant(value=normalized)
            self.changed = True

    def _normalize_selector_keyword_expressions(self, node: ast.Call) -> None:
        defaults = self._default_stack[-1] if self._default_stack else {}
        for keyword in node.keywords:
            if keyword.arg is None:
                continue
            try:
                ast.literal_eval(keyword.value)
                continue
            except (TypeError, ValueError):
                pass
            if isinstance(keyword.value, ast.Name):
                continue
            normalized = _literalize_safe_generated_expr(keyword.value, defaults)
            if normalized is None:
                continue
            keyword.value = ast.Constant(value=normalized)
            self.changed = True


def _literal_function_defaults(node: ast.AsyncFunctionDef) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    if not node.args.defaults:
        return defaults
    default_args = node.args.args[-len(node.args.defaults):]
    for arg, default in zip(default_args, node.args.defaults, strict=False):
        try:
            defaults[arg.arg] = ast.literal_eval(default)
        except (TypeError, ValueError):
            continue
    return defaults


def _literalize_safe_generated_expr(node: ast.AST, defaults: dict[str, Any]) -> Any | None:
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
                continue
            if isinstance(value, ast.FormattedValue):
                formatted = value.value
                if isinstance(formatted, ast.Name):
                    if formatted.id in defaults:
                        parts.append(str(defaults[formatted.id]))
                    else:
                        parts.append("{{" + formatted.id + "}}")
                    continue
                literal = _literalize_safe_generated_expr(formatted, defaults)
                if literal is None:
                    return None
                parts.append(str(literal))
                continue
            return None
        return "".join(parts)
    if isinstance(node, ast.BinOp):
        left = _literalize_safe_generated_expr(node.left, defaults)
        right = _literalize_safe_generated_expr(node.right, defaults)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
        except (TypeError, ZeroDivisionError):
            return None
        return None
    if isinstance(node, ast.UnaryOp):
        operand = _literalize_safe_generated_expr(node.operand, defaults)
        if operand is None:
            return None
        try:
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
        except TypeError:
            return None
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        base = _literalize_safe_generated_expr(node.func.value, defaults)
        args = [_literalize_safe_generated_expr(arg, defaults) for arg in node.args]
        if base is None or any(arg is None for arg in args) or any(kw.arg is None for kw in node.keywords):
            return None
        if node.keywords:
            return None
        if isinstance(base, str):
            try:
                if node.func.attr == "lower" and not args:
                    return base.lower()
                if node.func.attr == "casefold" and not args:
                    return base.casefold()
                if node.func.attr == "upper" and not args:
                    return base.upper()
                if node.func.attr == "strip" and len(args) <= 1:
                    return base.strip(*args)
                if node.func.attr == "replace" and len(args) in {2, 3}:
                    return base.replace(*args)
            except (TypeError, ValueError):
                return None
        return None
    if isinstance(node, ast.Name):
        return defaults.get(node.id)
    try:
        return ast.literal_eval(node)
    except (TypeError, ValueError):
        return None


def _is_action_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Name)
        and node.func.id == "action"
    ) or (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "action"
    )


def _is_r_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "R")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "R")
        )
    )


def _target_label_from_r_call(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    values: dict[str, str] = {}
    for kw in node.keywords:
        if kw.arg not in {"text", "content_desc", "resource_id"}:
            continue
        value = kw.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.strip():
            values[kw.arg] = value.value.strip()
    return values.get("text") or values.get("content_desc") or values.get("resource_id")


def _action_call_has_required_state_contract(node: ast.Call) -> bool:
    state_kw = next((kw for kw in node.keywords if kw.arg == "state_contract"), None)
    if state_kw is None:
        return False
    value = state_kw.value
    if not isinstance(value, ast.Call):
        return True
    if _call_name_from_ast(value.func) != "C":
        return True
    required_kw = next((kw for kw in value.keywords if kw.arg == "required"), None)
    if required_kw is None:
        return False
    if isinstance(required_kw.value, (ast.List, ast.Tuple)):
        return bool(required_kw.value.elts)
    return True


def _set_or_add_state_contract(node: ast.Call, selector_call: ast.Call) -> None:
    contract = ast.Call(
        func=ast.Name(id="C", ctx=ast.Load()),
        args=[],
        keywords=[
            ast.keyword(
                arg="required",
                value=ast.List(elts=[selector_call], ctx=ast.Load()),
            )
        ],
    )
    for kw in node.keywords:
        if kw.arg != "state_contract":
            continue
        if isinstance(kw.value, ast.Call) and _call_name_from_ast(kw.value.func) == "C":
            for contract_kw in kw.value.keywords:
                if contract_kw.arg == "required":
                    contract_kw.value = ast.List(elts=[selector_call], ctx=ast.Load())
                    return
            kw.value.keywords.append(ast.keyword(
                arg="required",
                value=ast.List(elts=[selector_call], ctx=ast.Load()),
            ))
            return
        kw.value = contract
        return
    node.keywords.append(ast.keyword(arg="state_contract", value=contract))


def _merge_description_hint(description: str, hint: str) -> str:
    description = " ".join(str(description or "").split())
    hint = " ".join(str(hint or "").split())
    if not hint:
        return description
    if not description:
        return hint
    if hint in description:
        return description
    return f"{hint}\n{description}"


def _call_name_from_ast(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parent = _call_name_from_ast(func.value)
        return f"{parent}.{func.attr}" if parent else func.attr
    return ""


def _safe_json(value: str) -> str:
    return value[:4000]


def _merge_code_source(existing_source: str, code_update: str) -> tuple[str, tuple[str, ...]]:
    existing_tree = ast.parse(existing_source)
    update_tree = ast.parse(code_update)
    _strip_open_app_state_contracts_in_tree(update_tree)
    _rename_incompatible_same_name_skills(existing_tree, update_tree)
    _preserve_existing_entry_actions(existing_tree, update_tree)
    _preserve_existing_optional_prelude_actions(existing_tree, update_tree)
    ast.fix_missing_locations(update_tree)
    code_update = ast.unparse(update_tree) + "\n"
    update_tree = ast.parse(code_update)
    existing_functions = _function_sources(existing_source, existing_tree)
    update_functions = _function_sources(code_update, update_tree)
    existing_nodes = _function_nodes(existing_tree)
    update_nodes = _function_nodes(update_tree)
    updated_skill_names = _decorated_function_names(update_tree, "skill")
    if not update_functions:
        return existing_source, ()
    existing_functions = {
        name: source
        for name, source in existing_functions.items()
        if not _is_stale_graph_projection_for_skills(
            existing_nodes[name],
            source,
            updated_skill_names,
        )
    }
    merged: dict[str, str] = dict(existing_functions)
    for name, source in update_functions.items():
        merged[name] = source
    ordered_names = list(existing_functions)
    for name in update_functions:
        if name not in ordered_names:
            ordered_names.append(name)
    parts = [_CODE_HEADER, ""]
    for name in ordered_names:
        parts.append(merged[name].strip())
        parts.append("")
        parts.append("")
    updated_public_functions = tuple(
        name for name in update_functions if _has_decorator(update_nodes[name], "skill")
    )
    return "\n".join(parts).rstrip() + "\n", updated_public_functions


def _strip_open_app_state_contracts_in_tree(tree: ast.Module) -> None:
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            _strip_open_app_state_contracts_in_function(node)


def _rename_incompatible_same_name_skills(existing_tree: ast.Module, update_tree: ast.Module) -> None:
    existing_nodes = _function_nodes(existing_tree)
    used_names = set(existing_nodes)
    for update_node in list(update_tree.body):
        if not isinstance(update_node, ast.AsyncFunctionDef) or not _has_decorator(update_node, "skill"):
            continue
        existing_node = existing_nodes.get(update_node.name)
        if not isinstance(existing_node, ast.AsyncFunctionDef) or not _has_decorator(existing_node, "skill"):
            used_names.add(update_node.name)
            continue
        same_bucket = _skill_app_platform(existing_node) == _skill_app_platform(update_node)
        compatible = same_bucket and _skill_action_signatures_compatible(existing_node, update_node)
        if compatible:
            used_names.add(update_node.name)
            continue
        old_name = update_node.name
        new_name = _dedupe_function_name(f"{old_name}_variant", used_names)
        if _first_direct_entry_action_stmt(update_node) is None:
            existing_entry = _first_direct_entry_action_stmt(existing_node)
            if existing_entry is not None:
                entry_stmt = copy.deepcopy(existing_entry)
                entry_call = _awaited_action_call(entry_stmt)
                if entry_call is not None and _action_call_type(entry_call) == "open_app":
                    _remove_action_keyword(entry_call, "state_contract")
                update_node.body.insert(_skill_entry_insert_index(update_node), entry_stmt)
        _set_skill_decorator_keyword(update_node, "skill_id", f"code:{new_name}")
        update_node.name = new_name
        used_names.add(new_name)


def _preserve_existing_optional_prelude_actions(existing_tree: ast.Module, update_tree: ast.Module) -> None:
    existing_nodes = _function_nodes(existing_tree)
    update_nodes = _function_nodes(update_tree)
    for name, update_node in update_nodes.items():
        existing_node = existing_nodes.get(name)
        if not isinstance(existing_node, ast.AsyncFunctionDef) or not isinstance(update_node, ast.AsyncFunctionDef):
            continue
        if not (_has_decorator(existing_node, "skill") and _has_decorator(update_node, "skill")):
            continue
        existing_optional = _leading_optional_action_stmts(existing_node)
        if not existing_optional:
            continue
        update_keys = {_action_stmt_key(stmt) for stmt, _call in _direct_action_calls(update_node)}
        insert_at = _after_leading_entry_actions_index(update_node)
        inserted = 0
        for stmt, _call in existing_optional:
            key = _action_stmt_key(stmt)
            if not key or key in update_keys:
                continue
            update_node.body.insert(insert_at + inserted, copy.deepcopy(stmt))
            update_keys.add(key)
            inserted += 1


def _skill_app_platform(func: ast.AsyncFunctionDef | ast.FunctionDef) -> tuple[str, str]:
    kwargs = _decorator_literal_kwargs(func, "skill")
    platform = str(kwargs.get("platform") or "unknown").strip().lower()
    app = str(kwargs.get("app") or "").strip()
    return platform, normalize_app_identifier(platform, app) if app else ""


def _decorator_literal_kwargs(
    func: ast.AsyncFunctionDef | ast.FunctionDef,
    decorator_name: str,
) -> dict[str, Any]:
    for decorator in func.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = (
            decorator.func.id
            if isinstance(decorator.func, ast.Name)
            else decorator.func.attr
            if isinstance(decorator.func, ast.Attribute)
            else ""
        )
        if name != decorator_name:
            continue
        values: dict[str, Any] = {}
        for keyword in decorator.keywords:
            if keyword.arg is None:
                continue
            try:
                values[keyword.arg] = ast.literal_eval(keyword.value)
            except (TypeError, ValueError):
                continue
        return values
    return {}


def _set_skill_decorator_keyword(
    func: ast.AsyncFunctionDef | ast.FunctionDef,
    keyword_name: str,
    value: Any,
) -> None:
    for decorator in func.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not (
            (isinstance(decorator.func, ast.Name) and decorator.func.id == "skill")
            or (isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "skill")
        ):
            continue
        expr = ast.parse(repr(value), mode="eval").body
        for keyword in decorator.keywords:
            if keyword.arg == keyword_name:
                keyword.value = expr
                return
        decorator.keywords.append(ast.keyword(arg=keyword_name, value=expr))
        return


def _skill_action_signatures_compatible(
    existing_node: ast.AsyncFunctionDef,
    update_node: ast.AsyncFunctionDef,
) -> bool:
    existing_signature = _comparable_action_signature(existing_node)
    update_signature = _comparable_action_signature(update_node)
    if not existing_signature or not update_signature:
        return bool(existing_signature == update_signature)
    shared_len = min(len(existing_signature), len(update_signature))
    if shared_len <= 0:
        return False
    return all(
        _action_signature_item_compatible(old, new)
        for old, new in zip(
            existing_signature[:shared_len],
            update_signature[:shared_len],
            strict=False,
        )
    )


def _comparable_action_signature(func: ast.AsyncFunctionDef) -> tuple[tuple[str, str], ...]:
    signature: list[tuple[str, str]] = []
    for _stmt, call in _direct_action_calls(func):
        action_type = _action_call_type(call)
        if action_type in _ENTRY_ACTION_TYPES or action_type in {"wait", "done", "request_intervention"}:
            continue
        if _action_call_optional(call):
            continue
        signature.append((action_type, _normalize_action_target(_action_call_target(call))))
    return tuple(signature)


def _action_signature_item_compatible(
    existing: tuple[str, str],
    update: tuple[str, str],
) -> bool:
    if existing[0] != update[0]:
        return False
    old_target = existing[1]
    new_target = update[1]
    if old_target == new_target:
        return True
    if not old_target or not new_target:
        return True
    if _is_placeholder_value(old_target) or _is_placeholder_value(new_target):
        return True
    old_tokens = _tokens(old_target)
    new_tokens = _tokens(new_target)
    if not old_tokens or not new_tokens:
        return False
    overlap = len(old_tokens & new_tokens) / max(1, min(len(old_tokens), len(new_tokens)))
    return overlap >= 0.5


def _direct_action_calls(func: ast.AsyncFunctionDef) -> list[tuple[ast.stmt, ast.Call]]:
    calls: list[tuple[ast.stmt, ast.Call]] = []
    for stmt in func.body:
        call = _awaited_action_call(stmt)
        if call is not None:
            calls.append((stmt, call))
    return calls


def _leading_optional_action_stmts(func: ast.AsyncFunctionDef) -> list[tuple[ast.stmt, ast.Call]]:
    optional: list[tuple[ast.stmt, ast.Call]] = []
    seen_body_action = False
    for stmt, call in _direct_action_calls(func):
        action_type = _action_call_type(call)
        if action_type in _ENTRY_ACTION_TYPES:
            if seen_body_action:
                break
            continue
        if _action_call_optional(call) and _action_has_state_contract(call):
            optional.append((stmt, call))
            seen_body_action = True
            continue
        break
    return optional


def _after_leading_entry_actions_index(func: ast.AsyncFunctionDef) -> int:
    index = _skill_entry_insert_index(func)
    while index < len(func.body):
        call = _awaited_action_call(func.body[index])
        if call is None or _action_call_type(call) not in _ENTRY_ACTION_TYPES:
            break
        index += 1
    return index


def _action_stmt_key(stmt: ast.stmt) -> str:
    call = _awaited_action_call(stmt)
    if call is None:
        return ""
    contract = ""
    for keyword in call.keywords:
        if keyword.arg == "state_contract":
            contract = ast.unparse(keyword.value)
            break
    return "|".join((
        _action_call_type(call),
        _normalize_action_target(_action_call_target(call)),
        "optional" if _action_call_optional(call) else "required",
        contract,
    ))


def _action_call_optional(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "optional":
            continue
        value = keyword.value
        return isinstance(value, ast.Constant) and value.value is True
    return False


def _action_has_state_contract(call: ast.Call) -> bool:
    return any(keyword.arg == "state_contract" for keyword in call.keywords)


def _action_call_target(call: ast.Call) -> str:
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        return str(call.args[1].value or "")
    for keyword in call.keywords:
        if keyword.arg == "target" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value or "")
    return ""


def _normalize_action_target(target: str) -> str:
    return " ".join(str(target or "").split()).casefold()


def _dedupe_function_name(base_name: str, used_names: set[str]) -> str:
    candidate = base_name
    suffix = 2
    while candidate in used_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def _preserve_existing_entry_actions(existing_tree: ast.Module, update_tree: ast.Module) -> None:
    existing_nodes = _function_nodes(existing_tree)
    update_nodes = _function_nodes(update_tree)
    for name, update_node in update_nodes.items():
        existing_node = existing_nodes.get(name)
        if not isinstance(existing_node, ast.AsyncFunctionDef) or not isinstance(update_node, ast.AsyncFunctionDef):
            continue
        if not (_has_decorator(existing_node, "skill") and _has_decorator(update_node, "skill")):
            continue
        existing_entry = _first_direct_entry_action_stmt(existing_node)
        if existing_entry is None:
            continue
        update_first = _first_direct_action_stmt(update_node)
        update_first_type = _action_call_type(update_first[1]) if update_first is not None else ""
        if update_first_type in _ENTRY_ACTION_TYPES:
            continue
        entry_stmt = copy.deepcopy(existing_entry)
        entry_call = _awaited_action_call(entry_stmt)
        if entry_call is not None and _action_call_type(entry_call) == "open_app":
            _remove_action_keyword(entry_call, "state_contract")
        update_node.body.insert(_skill_entry_insert_index(update_node), entry_stmt)


def _first_direct_action_stmt(func: ast.AsyncFunctionDef) -> tuple[ast.stmt, ast.Call] | None:
    for stmt in func.body:
        call = _awaited_action_call(stmt)
        if call is not None:
            return stmt, call
    return None


def _first_direct_entry_action_stmt(func: ast.AsyncFunctionDef) -> ast.stmt | None:
    first = _first_direct_action_stmt(func)
    if first is None:
        return None
    stmt, call = first
    return stmt if _action_call_type(call) in _ENTRY_ACTION_TYPES else None


def _is_graph_declaration(func: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    return _has_decorator(func, "state") or _has_decorator(func, "transition")


def _has_graph_declarations(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if _has_decorator(node, "state") or _has_decorator(node, "transition"):
            return True
    return False


def _has_graph_transitions(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and _has_decorator(node, "transition")
        for node in tree.body
    )


def _has_decorator(func: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> bool:
    return any(
        (
            isinstance(decorator, ast.Call)
            and (
                (isinstance(decorator.func, ast.Name) and decorator.func.id == name)
                or (isinstance(decorator.func, ast.Attribute) and decorator.func.attr == name)
            )
        )
        or (isinstance(decorator, ast.Name) and decorator.id == name)
        for decorator in func.decorator_list
    )


def _function_nodes(tree: ast.Module) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }


def _decorated_function_names(tree: ast.Module, decorator_name: str) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and _has_decorator(node, decorator_name)
    }


def _is_stale_graph_projection_for_skills(
    func: ast.AsyncFunctionDef | ast.FunctionDef,
    source: str,
    skill_names: set[str],
) -> bool:
    if not skill_names:
        return False
    if not (_has_decorator(func, "state") or _has_decorator(func, "transition")):
        return False
    for skill_name in skill_names:
        if func.name.startswith((f"state_{skill_name}_", f"transition_{skill_name}_")):
            return True
        if f"code:{skill_name}" in source:
            return True
    return False


def _function_sources(source: str, tree: ast.Module) -> dict[str, str]:
    lines = source.splitlines()
    functions: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        starts = [node.lineno, *(decorator.lineno for decorator in node.decorator_list)]
        start = min(starts) - 1
        end = node.end_lineno or node.lineno
        functions[node.name] = "\n".join(lines[start:end])
    return functions


def _rank_skills(query: str, skills: list[Skill], *, top_k: int) -> list[tuple[Skill, float]]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    scored: list[tuple[Skill, float]] = []
    for skill in skills:
        text = _skill_text(skill)
        text_tokens = _tokens(text)
        if not text_tokens:
            continue
        overlap = len(query_tokens & text_tokens) / len(query_tokens)
        exact_bonus = 0.25 if query.strip().casefold() in text.casefold() else 0.0
        score = min(1.0, overlap + exact_bonus)
        if score > 0:
            scored.append((skill, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def _skill_text(skill: Skill) -> str:
    parts = [skill.name, skill.description, skill.app, skill.platform, " ".join(skill.tags)]
    for step in skill.steps:
        parts.append(step.action_type)
        parts.append(step.target)
        parts.extend(str(value) for value in step.parameters.values())
    return " ".join(part for part in parts if part)


def _code_skill_search_text(skill: Skill) -> str:
    description = " ".join(str(skill.description or "").split())
    parts: list[str] = []
    if description:
        # The decorator description is the human-authored/repaired retrieval
        # contract. Weight it more heavily than structural names or step labels.
        parts.extend([description, description, description])
    parts.extend([skill.name, skill.app, skill.platform])
    parts.extend(skill.tags)
    for step in skill.steps:
        target = re.sub(r"\{\{[^}]+\}\}", "", step.target or "").strip()
        if target:
            parts.append(target)
        if step.expected_state:
            parts.append(step.expected_state)
        if step.valid_state and step.valid_state.lower() != "no need to verify":
            parts.append(step.valid_state)
        if step.state_contract:
            parts.extend(_state_contract_search_text(step.state_contract))
    return " ".join(part for part in parts if part)


def _state_contract_search_text(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for nested in value.values():
            parts.extend(_state_contract_search_text(nested))
        return parts
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for nested in value:
            parts.extend(_state_contract_search_text(nested))
        return parts
    return []


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]+", value.casefold()))


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _normalize_compiled_skills(skills: list[Skill]) -> list[Skill]:
    normalized: list[Skill] = []
    for skill in skills:
        skill = normalize_skill_app(skill)
        if _is_android_launcher_skill(skill):
            continue
        steps = []
        for step in skill.steps:
            state_contract = normalize_state_contract(step.state_contract)
            if state_contract != step.state_contract:
                step = replace(step, state_contract=state_contract)
            steps.append(step)
        if tuple(steps) != skill.steps:
            skill = replace(skill, steps=tuple(steps))
        normalized.append(skill)
    return normalized


def _is_android_launcher_skill(skill: Skill) -> bool:
    platform = str(getattr(skill, "platform", "") or "").strip().lower()
    if platform != "android":
        return False
    app = normalize_app_identifier(platform, str(getattr(skill, "app", "") or ""))
    if app not in _ANDROID_LAUNCHER_PACKAGES:
        return False
    steps = tuple(getattr(skill, "steps", ()) or ())
    if not steps:
        return True
    first_step = steps[0]
    first_action = str(getattr(first_step, "action_type", "") or "")
    if first_action != "open_app":
        return True
    target = normalize_app_identifier(platform, str(getattr(first_step, "target", "") or ""))
    fixed_values = getattr(first_step, "fixed_values", None)
    if isinstance(fixed_values, dict):
        for key in ("text", "package", "app", "target"):
            value = fixed_values.get(key)
            if value:
                target = normalize_app_identifier(platform, str(value))
                break
    return target in _ANDROID_LAUNCHER_PACKAGES


def _normalize_app_filter(platform: str | None, app: str | None) -> str | None:
    if platform is None or app is None:
        return app
    from opengui.skills.normalization import normalize_app_identifier

    return normalize_app_identifier(platform, app)
