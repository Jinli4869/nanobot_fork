"""
opengui.skills.shortcut_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Versioned storage and hybrid search for shortcut-layer and task-layer skills.
"""

from __future__ import annotations

import json
import logging
import tempfile
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from opengui.skills.shortcut import ShortcutSkill
from opengui.skills.task_skill import TaskSkill

if typing.TYPE_CHECKING:
    from opengui.memory.retrieval import EmbeddingProvider, _BM25Index, _FaissIndex

logger = logging.getLogger(__name__)


def _lazy_bm25() -> _BM25Index:
    from opengui.memory.retrieval import _BM25Index

    return _BM25Index()


def _lazy_faiss() -> _FaissIndex:
    from opengui.memory.retrieval import _FaissIndex

    return _FaissIndex()


def _min_max_norm(scores: np.ndarray, mask: np.ndarray) -> np.ndarray:
    valid = scores[mask]
    if len(valid) == 0:
        return np.zeros_like(scores)
    lo, hi = valid.min(), valid.max()
    if hi - lo < 1e-9:
        out = np.zeros_like(scores)
        out[mask] = 0.5
        return out
    return np.where(mask, (scores - lo) / (hi - lo), 0.0)


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

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        self.load_all()

    def add(self, skill: ShortcutSkill) -> None:
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

    def get(self, skill_id: str) -> ShortcutSkill | None:
        return self._skills.get(skill_id)

    def load_all(self) -> None:
        self._skills.clear()
        if not self.store_dir.exists():
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
                skill = ShortcutSkill.from_dict(skill_data)
                self._skills[skill.skill_id] = skill
        self._index_dirty = True

    def _save_platform(self, platform: str) -> None:
        dir_path = self.store_dir / platform
        dir_path.mkdir(parents=True, exist_ok=True)
        target = dir_path / "shortcut_skills.json"
        skills = [skill for skill in self._skills.values() if skill.platform == platform]
        if not skills:
            target.unlink(missing_ok=True)
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
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    async def search(self, query: str, *, top_k: int = 5) -> list[tuple[ShortcutSkill, float]]:
        if not self._skills or top_k <= 0:
            return []

        if self._index_dirty:
            await self._rebuild_index()

        mask = np.ones(len(self._ordered_ids), dtype=bool)
        bm25_scores = np.array(self._bm25.score(query), dtype=np.float32)

        if self.embedding_provider is not None:
            query_emb = await self.embedding_provider.embed([query])
            faiss_raw, faiss_idx = self._faiss.search(query_emb[0], len(self._ordered_ids))
            emb_scores = np.full(len(self._ordered_ids), -1e9, dtype=np.float32)
            for score, idx in zip(faiss_raw, faiss_idx):
                if idx >= 0:
                    emb_scores[idx] = score
            hybrid = (1.0 - self.alpha) * _min_max_norm(bm25_scores, mask) + self.alpha * _min_max_norm(
                emb_scores, mask
            )
        else:
            hybrid = _min_max_norm(bm25_scores, mask)

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
        self._index_dirty = True

    def _save_platform(self, platform: str) -> None:
        dir_path = self.store_dir / platform
        dir_path.mkdir(parents=True, exist_ok=True)
        target = dir_path / "task_skills.json"
        skills = [skill for skill in self._skills.values() if skill.platform == platform]
        if not skills:
            target.unlink(missing_ok=True)
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
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    async def search(self, query: str, *, top_k: int = 5) -> list[tuple[TaskSkill, float]]:
        if not self._skills or top_k <= 0:
            return []

        if self._index_dirty:
            await self._rebuild_index()

        mask = np.ones(len(self._ordered_ids), dtype=bool)
        bm25_scores = np.array(self._bm25.score(query), dtype=np.float32)

        if self.embedding_provider is not None:
            query_emb = await self.embedding_provider.embed([query])
            faiss_raw, faiss_idx = self._faiss.search(query_emb[0], len(self._ordered_ids))
            emb_scores = np.full(len(self._ordered_ids), -1e9, dtype=np.float32)
            for score, idx in zip(faiss_raw, faiss_idx):
                if idx >= 0:
                    emb_scores[idx] = score
            hybrid = (1.0 - self.alpha) * _min_max_norm(bm25_scores, mask) + self.alpha * _min_max_norm(
                emb_scores, mask
            )
        else:
            hybrid = _min_max_norm(bm25_scores, mask)

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
