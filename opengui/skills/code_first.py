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
import copy
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
from opengui.skills.code_graph import compile_code_graph, compile_code_skills
from opengui.skills.data import Skill, SkillStep
from opengui.skills.graph import SkillGraphStore
from opengui.skills.normalization import normalize_app_identifier, normalize_skill_app
from opengui.skills.state_contract import normalize_state_contract
from opengui.skills.static_selector_filter import (
    filter_static_resource_ids,
    filter_static_texts,
    selector_is_static,
    static_control_from_node,
)

logger = logging.getLogger(__name__)

CANONICAL_CODE_FILENAME = "skill_graph_code.py"
_CODE_HEADER = "from opengui.skills.code_graph import C, R, action, skill, state, tag, transition"


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
- state_contract is a PRE-action check for the screen before that action.
- Put app anchors on C(app="..."), never inside R(...). For example:
  state_contract=C(app="com.example", required=[R(text="Orders", clickable=True)])
- R(...) only accepts text, content_desc, resource_id, class_, xpath, visible,
  clickable, enabled, focused, and scrollable.
- Do not attach a postcondition-like state_contract to open_app unless the trace
  must already be inside that app before opening a deep link.
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

Trajectory JSON:
{trajectory}
"""


@dataclass(frozen=True)
class CodeSkillExtraction:
    python_code: str
    reasoning: str = ""
    attempts: tuple[dict[str, Any], ...] = ()
    usage: dict[str, int] = field(default_factory=dict)


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
class CodeActionCanonicalization:
    source: str
    report: dict[str, Any]


@dataclass(frozen=True)
class _TraceEvidenceStep:
    index: int
    action_type: str
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

    def __init__(self, llm: Any, *, max_events: int = 80) -> None:
        self._llm = llm
        self._max_events = max_events
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
        step_count = sum(1 for event in events if event.get("type") in {"step", "skill_step"})
        if step_count < 1:
            return None
        prompt = _CODE_EXTRACTION_PROMPT.format(
            task=task or "",
            is_success=is_success,
            platform=platform or _platform_hint(events) or "unknown",
            evaluation=json.dumps(_compact_evaluation(evaluation_result), ensure_ascii=False),
            trajectory=json.dumps(_compact_events(events, self._max_events), ensure_ascii=False, indent=2),
        )
        if feedback:
            prompt += (
                "\n\nPrevious generated code failed validation. Fix the code now.\n"
                "<validation_errors>\n"
                f"{feedback}\n"
                "</validation_errors>"
            )
        response = await self._llm.chat([{"role": "user", "content": prompt}])
        self._accumulate_usage(getattr(response, "usage", {}) or {})
        parsed, violations = _parse_code_response(getattr(response, "content", "") or "")
        attempts = [{
            "violations": violations,
            "raw_response": _safe_json(getattr(response, "content", "") or ""),
        }]
        if violations:
            return CodeSkillExtraction(
                python_code="",
                attempts=tuple(attempts),
                usage=self.total_usage,
            )
        return CodeSkillExtraction(
            python_code=parsed["python_code"],
            reasoning=parsed["step_by_step_reasoning"],
            attempts=tuple(attempts),
            usage=self.total_usage,
        )

    def _accumulate_usage(self, usage: dict[str, int]) -> None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self._total_usage[key] = self._total_usage.get(key, 0) + int(usage.get(key, 0) or 0)


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
        source_path = self._repository.source_path
        if not source_path.is_file():
            return False
        source = source_path.read_text(encoding="utf-8")
        if not _has_graph_transitions(source):
            return False
        source_mtime = _mtime(source_path)
        graph_path = self.store_dir / "skill_graph.json"
        graph_mtime = _mtime(graph_path)
        if (
            self._graph_source_mtime == source_mtime
            and graph_mtime is not None
            and source_mtime is not None
            and graph_mtime >= source_mtime
        ):
            return True

        graph_path.unlink(missing_ok=True)
        (self.store_dir / "skill_graph_embeddings.npy").unlink(missing_ok=True)
        graph = SkillGraphStore(
            store_dir=self.store_dir,
            embedding_provider=self.embedding_provider,
            embedding_signature=self.embedding_signature,
        )
        result = await compile_code_graph(source, graph)
        self.graph_compile_errors = tuple(result.errors)
        if result.errors:
            logger.warning("Cannot sync code graph cache: %s", result.errors)
            return False
        self._graph_source_mtime = source_mtime
        return bool(result.nodes or result.edges)

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

        ranked = np.argsort(-scores)
        results: list[tuple[Skill, float]] = []
        for index in ranked:
            if not mask[index] or scores[index] <= 0:
                break
            results.append((self._indexed_skills[int(index)], float(scores[index])))
            if len(results) >= top_k:
                break
        return results

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
        observation = event.get("observation")
        post_observation = observation if isinstance(observation, dict) else None
        pre_observation = _event_pre_observation(event, latest_observation)
        if action_type and action_type not in {"screenshot", "wait", "done", "request_intervention"}:
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
    return fallback


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
    return _quoted_target_from_blob(text_blob)


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
        if action.target:
            score += 1
        scored.append((-score, action.index, action))
    scored.sort(key=lambda item: (item[0], item[1]))
    return scored[0][2]


def _gap_trace_actions(
    trace_actions: list[_TraceAction],
    *,
    skill_app: str,
    skill_platform: str,
    after: int,
    before: int,
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
    for skill in result.skills:
        trace_cursor = -1
        for index, step in enumerate(skill.steps):
            if step.action_type not in {"tap", "long_press", "double_tap", "input_text"}:
                continue
            trace_cursor, selector, evidence_observation = evidence.selector_for_step(
                target=step.target,
                action_type=step.action_type,
                after=trace_cursor,
            )
            current = normalize_state_contract(step.state_contract)
            sanitized_input_contract = _strip_parameterized_input_text_from_contract(
                current,
                step,
            )
            if sanitized_input_contract is not None and sanitized_input_contract != current:
                replacements.setdefault(skill.name, {})[index] = {
                    "app": skill.app,
                    "contract": sanitized_input_contract,
                }
                repaired_steps.append({
                    "function": skill.name,
                    "step_index": index,
                    "action_type": step.action_type,
                    "target": step.target,
                    "selector": None,
                    "reason": "parameterized_input_text_removed",
                })
                continue
            current_has_stable = _contract_has_stable_identity(current)
            current_supported = _contract_supported_by_observation(current, evidence_observation)
            if current_has_stable and current_supported:
                continue
            replacement: dict[str, Any] | None = None
            states = ["visible"]
            if step.action_type in {"tap", "long_press", "double_tap"}:
                states.append("clickable")
            if step.action_type == "input_text":
                states.append("focused")
            reason = "ui_tree_static_selector"
            if selector and _selector_has_stable_identity(selector):
                replacement = {
                    "app": skill.app,
                    "selector": selector,
                    "states": states,
                }
            elif current_has_stable and not current_supported:
                page_contract = _page_contract_from_observation(
                    evidence_observation,
                    app=skill.app,
                    target=step.target,
                )
                replacement = {
                    "app": skill.app,
                    "contract": page_contract or _fallback_target_contract(skill.app, step.target),
                }
                reason = "unsupported_static_selector_replaced"
            if replacement is None:
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
    return CodeContractRepair(source=repaired_source, report=report)


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
                observation = event.get("observation")
                post_observation = observation if isinstance(observation, dict) else None
                pre_observation = _event_pre_observation(event, latest_observation)
                self._steps.append(_TraceEvidenceStep(
                    index=int(event.get("step_index") or len(self._steps)),
                    action_type=action_type,
                    text_blob=_trace_text_blob(event, action),
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
            selector = _best_selector_for_action(match.pre_observation, target_text, action_type)
            evidence_observation = match.pre_observation
            if selector is None and match.pre_observation is None:
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
    scored: list[tuple[int, int, _TraceEvidenceStep]] = []
    for candidate in candidates:
        score = 0
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


def _selector_compatible_with_action(selector: dict[str, Any], action_type: str) -> bool:
    if action_type in {"tap", "long_press", "double_tap"}:
        return bool(selector.get("clickable"))
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
        labels = [
            str(value).strip()
            for value in (
                node.get("text"),
                node.get("content_desc"),
                node.get("resource_id"),
            )
            if value is not None and str(value).strip()
        ]
        if not any(_value_mentions_target(label, target_text) for label in labels):
            continue
        selector = _stable_selector_from_node(node)
        if selector:
            matches.append(selector)
            continue
        if action_type == "input_text":
            selector = _input_selector_from_node(node)
            if selector:
                matches.append(selector)
    return matches


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
        selector.get("resource_id")
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


def _stable_selector_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    control = static_control_from_node(node)
    if not control:
        return None
    selector: dict[str, Any] = {}
    for key in ("resource_id", "content_desc", "text"):
        value = control.get(key)
        if value:
            selector[key] = value
    for flag in ("clickable", "enabled", "focused", "scrollable"):
        if node.get(flag):
            selector[flag] = True
    return selector or None


def _input_selector_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    resource_id = node.get("resource_id")
    node_class = node.get("class")
    if not isinstance(resource_id, str) or not resource_id.strip():
        return None
    if not isinstance(node_class, str) or not node_class.strip():
        return None
    class_key = node_class.casefold()
    if not (node.get("focused") or "edittext" in class_key or "input" in class_key):
        return None
    selector: dict[str, Any] = {
        "resource_id": resource_id.strip(),
        "class": node_class.strip(),
    }
    for flag in ("clickable", "enabled", "focused", "scrollable"):
        if node.get(flag):
            selector[flag] = True
    return selector


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
        if flag in states or selector.get(flag):
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
    })
    return report


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
        if _selector_has_input_identity(selector):
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
        if selector.get("resource_id") or selector.get("content_desc"):
            has_identity = True
        if selector.get("text"):
            text_count += 1
    if text_count == 1 and not has_identity:
        return "single_text_selector"
    return "noncanonical_selector"


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
        observation = event.get("observation")
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

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self.generic_visit(node)
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

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if not _is_action_call(node):
            return node
        target_kw = next((kw for kw in node.keywords if kw.arg == "target"), None)
        if target_kw is None or not _is_r_call(target_kw.value):
            return node
        label = _target_label_from_r_call(target_kw.value)
        if not label:
            return node
        selector_call = copy.deepcopy(target_kw.value)
        target_kw.value = ast.Constant(value=label)
        if not _action_call_has_required_state_contract(node):
            _set_or_add_state_contract(node, selector_call)
        self.changed = True
        return node


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
    existing_functions = _function_sources(existing_source, existing_tree)
    update_functions = _function_sources(code_update, update_tree)
    if not update_functions:
        return existing_source, ()
    updated_skill_names = _decorated_function_names(update_tree, "skill")
    existing_nodes = _function_nodes(existing_tree)
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
    return "\n".join(parts).rstrip() + "\n", tuple(update_functions)


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


def _normalize_app_filter(platform: str | None, app: str | None) -> str | None:
    if platform is None or app is None:
        return app
    from opengui.skills.normalization import normalize_app_identifier

    return normalize_app_identifier(platform, app)
