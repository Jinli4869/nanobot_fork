"""
opengui.skills.shortcut_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Versioned storage and hybrid search for shortcut-layer and task-layer skills.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import typing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np

from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.shortcut import ShortcutSkill
from opengui.skills.task_skill import TaskSkill

if typing.TYPE_CHECKING:
    from opengui.memory.retrieval import EmbeddingProvider, _BM25Index, _FaissIndex

logger = logging.getLogger(__name__)
_STOPWORDS = frozenset({
    "a", "an", "the", "to", "in", "on", "of", "for", "and", "or", "is", "it",
    "with", "from", "by", "at", "be", "this", "that", "do", "does", "did",
})


def _normalize_name(name: str) -> str:
    tokens = re.findall(r"\w+", name.lower())
    return " ".join(token for token in tokens if token not in _STOPWORDS)


def _action_similarity(sig_a: tuple[str, ...], sig_b: tuple[str, ...]) -> float:
    if not sig_a and not sig_b:
        return 1.0
    max_len = max(len(sig_a), len(sig_b))
    if max_len == 0:
        return 1.0
    matches = sum(1 for left, right in zip(sig_a, sig_b) if left == right)
    return matches / max_len


def _tuple_similarity(values_a: tuple[str, ...], values_b: tuple[str, ...]) -> float:
    set_a = set(values_a)
    set_b = set(values_b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _lazy_bm25() -> _BM25Index:
    from opengui.memory.retrieval import _BM25Index

    return _BM25Index()


def _lazy_faiss() -> _FaissIndex:
    from opengui.memory.retrieval import _FaissIndex

    return _FaissIndex()



@dataclass(frozen=True)
class SkillSearchResult:
    skill: ShortcutSkill | TaskSkill
    layer: Literal["shortcut", "task"]
    score: float
    raw_score: float


@dataclass
class ShortcutSkillStore:
    store_dir: Path
    embedding_provider: EmbeddingProvider | None = None
    alpha: float = 0.6

    _skills: dict[str, ShortcutSkill] = field(default_factory=dict, init=False, repr=False)
    _bm25: _BM25Index = field(default_factory=_lazy_bm25, init=False, repr=False)
    _faiss: _FaissIndex = field(default_factory=_lazy_faiss, init=False, repr=False)
    _ordered_ids: list[str] = field(default_factory=list, init=False, repr=False)
    _documents: list[str] = field(default_factory=list, init=False, repr=False)
    _index_dirty: bool = field(default=True, init=False, repr=False)
    _loaded_mtime_ns: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        self.load_all()

    @property
    def count(self) -> int:
        return len(self._skills)

    def add(self, skill: ShortcutSkill) -> None:
        normalized = self._normalize_skill(skill)
        self._skills[normalized.skill_id] = normalized
        self._index_dirty = True
        self._save_platform(normalized.platform)

    async def add_or_merge(self, skill: ShortcutSkill) -> tuple[str, str | None]:
        incoming = self._normalize_skill(skill)
        conflict = self._find_best_conflict(incoming)
        if conflict is None:
            self.add(incoming)
            return "ADD", incoming.skill_id

        if self._same_origin(conflict, incoming):
            if conflict.skill_id == incoming.skill_id:
                self.update(conflict.skill_id, incoming)
                return "KEEP_NEW", incoming.skill_id
            return "KEEP_OLD", conflict.skill_id

        if conflict.skill_id == incoming.skill_id:
            self.update(conflict.skill_id, incoming)
            return "KEEP_NEW", incoming.skill_id

        merged = self._merge_shortcuts(conflict, incoming)
        self.update(conflict.skill_id, merged)
        return "MERGE", conflict.skill_id

    def remove(self, skill_id: str) -> bool:
        skill = self._skills.pop(skill_id, None)
        if skill is None:
            return False
        self._index_dirty = True
        self._save_platform(skill.platform)
        return True

    def get(self, skill_id: str) -> ShortcutSkill | None:
        return self._skills.get(skill_id)

    def list_all(
        self,
        *,
        platform: str | None = None,
        app: str | None = None,
    ) -> list[ShortcutSkill]:
        normalized_app = self._normalize_filter_app(platform, app)
        results: list[ShortcutSkill] = []
        for skill in self._skills.values():
            if platform is not None and skill.platform != platform:
                continue
            if normalized_app is not None and skill.app != normalized_app:
                continue
            results.append(skill)
        return results

    def update(self, skill_id: str, updated_skill: ShortcutSkill) -> bool:
        if skill_id not in self._skills:
            return False
        current = self._skills[skill_id]
        normalized = self._normalize_skill(updated_skill)
        if normalized.skill_id != skill_id:
            normalized = replace(normalized, skill_id=skill_id)
        self._skills[skill_id] = normalized
        self._index_dirty = True
        if current.platform != normalized.platform:
            self._save_platform(current.platform)
        self._save_platform(normalized.platform)
        return True

    def load_all(self) -> None:
        self._skills.clear()
        if not self.store_dir.exists():
            self._loaded_mtime_ns = 0
            self._index_dirty = True
            return
        for skill_file in sorted(
            platform_dir / "shortcut_skills.json"
            for platform_dir in self.store_dir.iterdir()
            if platform_dir.is_dir() and (platform_dir / "shortcut_skills.json").is_file()
        ):
            try:
                with open(skill_file, encoding="utf-8") as handle:
                    data = json.load(handle)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping invalid shortcut skill store %s: %s", skill_file, exc)
                continue
            if not isinstance(data, dict):
                logger.warning(
                    "Skipping malformed shortcut skill store %s: expected JSON object",
                    skill_file,
                )
                continue
            version = data.get("version")
            if version != 1:
                logger.warning(
                    "Skipping shortcut skill store %s with unsupported version %r",
                    skill_file,
                    version,
                )
                continue
            for skill_data in data.get("skills", []):
                skill = self._normalize_skill(ShortcutSkill.from_dict(skill_data))
                self._skills[skill.skill_id] = skill
        self._loaded_mtime_ns = self._snapshot_mtime_ns()
        self._index_dirty = True

    def refresh_if_stale(self) -> bool:
        current_mtime_ns = self._snapshot_mtime_ns()
        if current_mtime_ns == self._loaded_mtime_ns:
            return False
        self.load_all()
        return True

    @staticmethod
    def _normalize_skill(skill: ShortcutSkill) -> ShortcutSkill:
        normalized_app = normalize_app_identifier(skill.platform, skill.app)
        if normalized_app == skill.app:
            return skill
        return replace(skill, app=normalized_app)

    @staticmethod
    def _normalize_filter_app(platform: str | None, app: str | None) -> str | None:
        if app is None or platform is None:
            return None
        return normalize_app_identifier(platform, app)

    def _find_best_conflict(self, incoming: ShortcutSkill) -> ShortcutSkill | None:
        incoming = self._normalize_skill(incoming)
        incoming_name = _normalize_name(incoming.name)
        incoming_actions = self._action_signature(incoming)
        incoming_conditions = self._condition_signature(incoming)
        incoming_slots = tuple(sorted(slot.name.lower() for slot in incoming.parameter_slots))
        best: ShortcutSkill | None = None
        best_score = 0.0

        for existing in self._skills.values():
            if existing.platform != incoming.platform:
                continue
            if existing.app != incoming.app:
                continue

            same_origin = self._same_origin(existing, incoming)
            existing_name = _normalize_name(existing.name)
            action_similarity = _action_similarity(
                self._action_signature(existing),
                incoming_actions,
            )
            if not same_origin and existing_name != incoming_name and action_similarity < 0.75:
                continue

            score = 0.0
            if same_origin:
                score += 2.0
            if existing_name == incoming_name and existing_name:
                score += 1.0
            score += action_similarity
            score += 0.35 * _tuple_similarity(
                tuple(sorted(slot.name.lower() for slot in existing.parameter_slots)),
                incoming_slots,
            )
            score += 0.25 * _tuple_similarity(
                self._condition_signature(existing),
                incoming_conditions,
            )
            if self._provenance_overlap(existing, incoming):
                score += 0.5

            if score > best_score:
                best = existing
                best_score = score

        return best

    @staticmethod
    def _same_origin(left: ShortcutSkill, right: ShortcutSkill) -> bool:
        if not left.source_trace_path or not right.source_trace_path:
            return False
        if not left.source_step_indices or not right.source_step_indices:
            return False
        return (
            left.source_trace_path == right.source_trace_path
            and left.source_step_indices == right.source_step_indices
        )

    @staticmethod
    def _provenance_overlap(left: ShortcutSkill, right: ShortcutSkill) -> bool:
        same_trace = (
            left.source_trace_path
            and right.source_trace_path
            and left.source_trace_path == right.source_trace_path
        )
        shared_steps = bool(set(left.source_step_indices) & set(right.source_step_indices))
        same_run = left.source_run_id and right.source_run_id and left.source_run_id == right.source_run_id
        return bool(same_trace or shared_steps or same_run)

    @staticmethod
    def _action_signature(skill: ShortcutSkill) -> tuple[str, ...]:
        return tuple(step.action_type for step in skill.steps)

    @staticmethod
    def _condition_signature(skill: ShortcutSkill) -> tuple[str, ...]:
        values = [
            f"pre:{state.kind}:{state.value}:{int(state.negated)}"
            for state in skill.preconditions
        ]
        values.extend(
            f"post:{state.kind}:{state.value}:{int(state.negated)}"
            for state in skill.postconditions
        )
        return tuple(sorted(value.lower() for value in values))

    @staticmethod
    def _merge_shortcuts(old: ShortcutSkill, new: ShortcutSkill) -> ShortcutSkill:
        old_signature = ShortcutSkillStore._action_signature(old)
        new_signature = ShortcutSkillStore._action_signature(new)
        if _action_similarity(old_signature, new_signature) >= 0.8:
            steps = new.steps if len(new.steps) >= len(old.steps) else old.steps
        else:
            steps = new.steps or old.steps

        slot_map = {slot.name.lower(): slot for slot in old.parameter_slots}
        for slot in new.parameter_slots:
            slot_map[slot.name.lower()] = slot

        def _state_key(state: Any) -> str:
            return f"{state.kind}:{state.value}:{int(state.negated)}".lower()

        preconditions = {_state_key(state): state for state in old.preconditions}
        for state in new.preconditions:
            preconditions[_state_key(state)] = state

        postconditions = {_state_key(state): state for state in old.postconditions}
        for state in new.postconditions:
            postconditions[_state_key(state)] = state

        merged_from_ids = set(old.merged_from_ids) | set(new.merged_from_ids)
        if new.skill_id != old.skill_id:
            merged_from_ids.add(new.skill_id)

        promoted_at_candidates = [
            value for value in (old.promoted_at, new.promoted_at) if value is not None
        ]
        promoted_at = max(promoted_at_candidates) if promoted_at_candidates else None

        return replace(
            old,
            name=new.name or old.name,
            description=new.description or old.description,
            app=new.app or old.app,
            platform=new.platform or old.platform,
            steps=steps,
            parameter_slots=tuple(slot_map[key] for key in sorted(slot_map)),
            preconditions=tuple(preconditions[key] for key in sorted(preconditions)),
            postconditions=tuple(postconditions[key] for key in sorted(postconditions)),
            tags=tuple(sorted(set(old.tags) | set(new.tags))),
            source_task=new.source_task or old.source_task,
            source_trace_path=new.source_trace_path or old.source_trace_path,
            source_run_id=new.source_run_id or old.source_run_id,
            source_step_indices=new.source_step_indices or old.source_step_indices,
            promotion_version=max(old.promotion_version, new.promotion_version),
            shortcut_version=max(old.shortcut_version, new.shortcut_version) + 1,
            merged_from_ids=tuple(sorted(merged_from_ids)),
            promoted_at=promoted_at,
            created_at=old.created_at,
        )

    def _save_platform(self, platform: str) -> None:
        dir_path = self.store_dir / platform
        dir_path.mkdir(parents=True, exist_ok=True)
        target = dir_path / "shortcut_skills.json"
        skills = [skill for skill in self._skills.values() if skill.platform == platform]
        if not skills:
            target.unlink(missing_ok=True)
            self._loaded_mtime_ns = self._snapshot_mtime_ns()
            return
        payload = {
            "version": 1,
            "skills": [skill.to_dict() for skill in skills],
        }
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=dir_path,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            Path(tmp.name).replace(target)
            self._loaded_mtime_ns = self._snapshot_mtime_ns()
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    def _snapshot_mtime_ns(self) -> int:
        if not self.store_dir.exists():
            return 0
        max_mtime_ns = 0
        for platform_dir in self.store_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            skill_file = platform_dir / "shortcut_skills.json"
            if not skill_file.is_file():
                continue
            try:
                max_mtime_ns = max(max_mtime_ns, skill_file.stat().st_mtime_ns)
            except FileNotFoundError:
                continue
        return max_mtime_ns

    async def search(self, query: str, *, top_k: int = 5) -> list[tuple[ShortcutSkill, float]]:
        if not self._skills or top_k <= 0:
            return []

        if self._index_dirty:
            await self._rebuild_index()

        mask = np.ones(len(self._ordered_ids), dtype=bool)
        bm25_scores = np.array(self._bm25.score(query), dtype=np.float32)

        # Normalize BM25 to [0, 1] so it blends properly with cosine similarity
        bm25_max = float(bm25_scores.max())
        if bm25_max > 0:
            bm25_scores /= bm25_max

        if self.embedding_provider is not None:
            query_emb = await self.embedding_provider.embed([query])
            faiss_raw, faiss_idx = self._faiss.search(query_emb[0], len(self._ordered_ids))
            emb_scores = np.full(len(self._ordered_ids), -1e9, dtype=np.float32)
            for score, idx in zip(faiss_raw, faiss_idx):
                if idx >= 0:
                    emb_scores[idx] = score
            hybrid = (1.0 - self.alpha) * bm25_scores + self.alpha * emb_scores
        else:
            hybrid = bm25_scores.copy()

        ranked = np.argsort(-hybrid)
        results: list[tuple[ShortcutSkill, float]] = []
        for idx in ranked:
            if hybrid[idx] <= 0:
                break
            results.append((self._skills[self._ordered_ids[idx]], float(hybrid[idx])))
            if len(results) >= top_k:
                break
        return results

    async def _rebuild_index(self) -> None:
        self._ordered_ids = list(self._skills.keys())
        self._documents = [
            self._shortcut_skill_text(self._skills[skill_id])
            for skill_id in self._ordered_ids
        ]
        self._bm25.build(self._documents)
        if self.embedding_provider is not None and self._documents:
            embeddings = await self.embedding_provider.embed(self._documents)
            self._faiss.build(embeddings)
        self._index_dirty = False

    @staticmethod
    def _shortcut_skill_text(skill: ShortcutSkill) -> str:
        parts = [skill.name, skill.description, skill.app, skill.platform]
        parts.extend(skill.tags)
        parts.extend(slot.name for slot in skill.parameter_slots)
        parts.extend(state.value for state in skill.preconditions)
        parts.extend(state.value for state in skill.postconditions)
        if skill.source_task:
            parts.append(skill.source_task)
        return " ".join(part for part in parts if part)


@dataclass
class TaskSkillStore:
    store_dir: Path
    embedding_provider: EmbeddingProvider | None = None
    alpha: float = 0.6

    _skills: dict[str, TaskSkill] = field(default_factory=dict, init=False, repr=False)
    _bm25: _BM25Index = field(default_factory=_lazy_bm25, init=False, repr=False)
    _faiss: _FaissIndex = field(default_factory=_lazy_faiss, init=False, repr=False)
    _ordered_ids: list[str] = field(default_factory=list, init=False, repr=False)
    _documents: list[str] = field(default_factory=list, init=False, repr=False)
    _index_dirty: bool = field(default=True, init=False, repr=False)
    _loaded_mtime_ns: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        self.load_all()

    def add(self, skill: TaskSkill) -> None:
        self._skills[skill.skill_id] = skill
        self._index_dirty = True
        self._save_platform(skill.platform)

    def remove(self, skill_id: str) -> bool:
        skill = self._skills.pop(skill_id, None)
        if skill is None:
            return False
        self._index_dirty = True
        self._save_platform(skill.platform)
        return True

    def get(self, skill_id: str) -> TaskSkill | None:
        return self._skills.get(skill_id)

    def load_all(self) -> None:
        self._skills.clear()
        if not self.store_dir.exists():
            self._loaded_mtime_ns = 0
            self._index_dirty = True
            return
        for skill_file in sorted(
            platform_dir / "task_skills.json"
            for platform_dir in self.store_dir.iterdir()
            if platform_dir.is_dir() and (platform_dir / "task_skills.json").is_file()
        ):
            try:
                with open(skill_file, encoding="utf-8") as handle:
                    data = json.load(handle)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping invalid task skill store %s: %s", skill_file, exc)
                continue
            if not isinstance(data, dict):
                logger.warning(
                    "Skipping malformed task skill store %s: expected JSON object",
                    skill_file,
                )
                continue
            version = data.get("version")
            if version != 1:
                logger.warning(
                    "Skipping task skill store %s with unsupported version %r",
                    skill_file,
                    version,
                )
                continue
            for skill_data in data.get("skills", []):
                skill = TaskSkill.from_dict(skill_data)
                self._skills[skill.skill_id] = skill
        self._loaded_mtime_ns = self._snapshot_mtime_ns()
        self._index_dirty = True

    def refresh_if_stale(self) -> bool:
        current_mtime_ns = self._snapshot_mtime_ns()
        if current_mtime_ns == self._loaded_mtime_ns:
            return False
        self.load_all()
        return True

    def _save_platform(self, platform: str) -> None:
        dir_path = self.store_dir / platform
        dir_path.mkdir(parents=True, exist_ok=True)
        target = dir_path / "task_skills.json"
        skills = [skill for skill in self._skills.values() if skill.platform == platform]
        if not skills:
            target.unlink(missing_ok=True)
            self._loaded_mtime_ns = self._snapshot_mtime_ns()
            return
        payload = {
            "version": 1,
            "skills": [skill.to_dict() for skill in skills],
        }
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=dir_path,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            Path(tmp.name).replace(target)
            self._loaded_mtime_ns = self._snapshot_mtime_ns()
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    def _snapshot_mtime_ns(self) -> int:
        if not self.store_dir.exists():
            return 0
        max_mtime_ns = 0
        for platform_dir in self.store_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            skill_file = platform_dir / "task_skills.json"
            if not skill_file.is_file():
                continue
            try:
                max_mtime_ns = max(max_mtime_ns, skill_file.stat().st_mtime_ns)
            except FileNotFoundError:
                continue
        return max_mtime_ns

    async def search(self, query: str, *, top_k: int = 5) -> list[tuple[TaskSkill, float]]:
        if not self._skills or top_k <= 0:
            return []

        if self._index_dirty:
            await self._rebuild_index()

        mask = np.ones(len(self._ordered_ids), dtype=bool)
        bm25_scores = np.array(self._bm25.score(query), dtype=np.float32)

        # Normalize BM25 to [0, 1] so it blends properly with cosine similarity
        bm25_max = float(bm25_scores.max())
        if bm25_max > 0:
            bm25_scores /= bm25_max

        if self.embedding_provider is not None:
            query_emb = await self.embedding_provider.embed([query])
            faiss_raw, faiss_idx = self._faiss.search(query_emb[0], len(self._ordered_ids))
            emb_scores = np.full(len(self._ordered_ids), -1e9, dtype=np.float32)
            for score, idx in zip(faiss_raw, faiss_idx):
                if idx >= 0:
                    emb_scores[idx] = score
            hybrid = (1.0 - self.alpha) * bm25_scores + self.alpha * emb_scores
        else:
            hybrid = bm25_scores.copy()

        ranked = np.argsort(-hybrid)
        results: list[tuple[TaskSkill, float]] = []
        for idx in ranked:
            if hybrid[idx] <= 0:
                break
            results.append((self._skills[self._ordered_ids[idx]], float(hybrid[idx])))
            if len(results) >= top_k:
                break
        return results

    async def _rebuild_index(self) -> None:
        self._ordered_ids = list(self._skills.keys())
        self._documents = [
            self._task_skill_text(self._skills[skill_id])
            for skill_id in self._ordered_ids
        ]
        self._bm25.build(self._documents)
        if self.embedding_provider is not None and self._documents:
            embeddings = await self.embedding_provider.embed(self._documents)
            self._faiss.build(embeddings)
        self._index_dirty = False

    @staticmethod
    def _task_skill_text(skill: TaskSkill) -> str:
        parts = [skill.name, skill.description, skill.app, skill.platform]
        parts.extend(skill.tags)
        return " ".join(part for part in parts if part)


class UnifiedSkillSearch:
    def __init__(
        self,
        shortcut_store: ShortcutSkillStore,
        task_store: TaskSkillStore,
    ) -> None:
        self.shortcut_store = shortcut_store
        self.task_store = task_store

    def refresh_if_stale(self) -> bool:
        shortcut_refreshed = self.shortcut_store.refresh_if_stale()
        task_refreshed = self.task_store.refresh_if_stale()
        return shortcut_refreshed or task_refreshed

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        shortcut_layer_weight: float = 1.0,
        task_layer_weight: float = 1.0,
    ) -> list[SkillSearchResult]:
        if top_k <= 0:
            return []

        shortcut_hits = await self.shortcut_store.search(query, top_k=top_k * 2)
        task_hits = await self.task_store.search(query, top_k=top_k * 2)

        results = [
            SkillSearchResult(
                skill=skill,
                layer="shortcut",
                score=raw_score * shortcut_layer_weight,
                raw_score=raw_score,
            )
            for skill, raw_score in shortcut_hits
        ]
        results.extend(
            SkillSearchResult(
                skill=skill,
                layer="task",
                score=raw_score * task_layer_weight,
                raw_score=raw_score,
            )
            for skill, raw_score in task_hits
        )
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:top_k]
