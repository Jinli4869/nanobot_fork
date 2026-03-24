"""
opengui.skills.library
~~~~~~~~~~~~~~~~~~~~~~
Persistent skill storage with BM25 + optional FAISS hybrid retrieval,
and LLM-based or heuristic skill deduplication/merge.

Inspired by KnowAct's four-bucket model, simplified for opengui's scope:
- Single primary bucket per (platform, app)
- Multi-factor conflict detection (name + action sequence similarity)
- LLM or heuristic merge decision
- Retrieval-gated merge to prevent false positives
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import typing
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from opengui.skills.data import Skill, SkillStep
from opengui.skills.normalization import normalize_app_identifier, normalize_skill_app

if typing.TYPE_CHECKING:
    from opengui.interfaces import LLMProvider
    from opengui.memory.retrieval import EmbeddingProvider, _BM25Index, _FaissIndex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Name / action similarity helpers
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "a", "an", "the", "to", "in", "on", "of", "for", "and", "or", "is", "it",
    "with", "from", "by", "at", "be", "this", "that", "do", "does", "did",
})


def _normalize_name(name: str) -> str:
    """Lowercase, strip stopwords, collapse whitespace."""
    tokens = re.findall(r"\w+", name.lower())
    return " ".join(t for t in tokens if t not in _STOPWORDS)


def _name_token_similarity(a: str, b: str) -> float:
    """Jaccard similarity over non-stopword tokens."""
    ta = set(re.findall(r"\w+", a.lower())) - _STOPWORDS
    tb = set(re.findall(r"\w+", b.lower())) - _STOPWORDS
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _action_signature(skill: Skill) -> tuple[str, ...]:
    """Ordered action-type tuple for sequence comparison."""
    return tuple(s.action_type for s in skill.steps)


def _action_similarity(sig_a: tuple[str, ...], sig_b: tuple[str, ...]) -> float:
    """Prefix-matching similarity between two action signatures."""
    if not sig_a and not sig_b:
        return 1.0
    max_len = max(len(sig_a), len(sig_b))
    if max_len == 0:
        return 1.0
    matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return matches / max_len


# ---------------------------------------------------------------------------
# Re-use BM25 / FAISS building blocks from memory.retrieval
# ---------------------------------------------------------------------------

def _lazy_bm25() -> _BM25Index:
    from opengui.memory.retrieval import _BM25Index
    return _BM25Index()


def _lazy_faiss() -> _FaissIndex:
    from opengui.memory.retrieval import _FaissIndex
    return _FaissIndex()


# ---------------------------------------------------------------------------
# Merge prompts
# ---------------------------------------------------------------------------

_MERGE_DECISION_PROMPT = """\
You are a GUI skill librarian. Two skills appear to overlap. Decide how to handle them.

## Existing Skill (OLD)
{old_skill_json}

## Incoming Skill (NEW)
{new_skill_json}

## Decision Rules
- **MERGE**: Same intent, combine into one skill. Prefer the longer/better step sequence.
- **KEEP_OLD**: Old skill is more complete or reliable; discard new.
- **KEEP_NEW**: New skill is clearly better; replace old.
- **ADD**: They are genuinely different skills; keep both.

Respond with ONLY a JSON object:
{{"decision": "MERGE|KEEP_OLD|KEEP_NEW|ADD", "reason": "one-line explanation"}}
"""


# ---------------------------------------------------------------------------
# SkillLibrary
# ---------------------------------------------------------------------------

@dataclass
class SkillLibrary:
    """Persistent JSON skill store organized by ``{platform}/{app}/skills.json``.

    Supports:
    - BM25 + optional FAISS hybrid retrieval
    - Multi-factor skill deduplication on add
    - LLM-based or heuristic merge decisions

    Parameters
    ----------
    store_dir:
        Root directory for skill JSON files.
    embedding_provider:
        Optional embedding API for hybrid search.
    merge_llm:
        Optional LLM for merge decisions. Falls back to heuristic if None.
    alpha:
        Blending weight (``1.0`` = pure embedding, ``0.0`` = pure BM25).
    merge_name_threshold:
        Minimum name token similarity to trigger merge consideration.
    merge_action_threshold:
        Minimum action sequence similarity to trigger merge consideration.
    """

    store_dir: Path
    embedding_provider: EmbeddingProvider | None = None
    merge_llm: LLMProvider | None = None
    alpha: float = 0.6
    merge_name_threshold: float = 0.50
    merge_action_threshold: float = 0.60

    _skills: dict[str, Skill] = field(default_factory=dict, repr=False)
    _bm25: _BM25Index = field(default_factory=_lazy_bm25, repr=False)
    _faiss: _FaissIndex = field(default_factory=_lazy_faiss, repr=False)
    _documents: list[str] = field(default_factory=list, repr=False)
    _ordered_ids: list[str] = field(default_factory=list, repr=False)
    _index_dirty: bool = field(default=True, repr=False)

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        self.load_all()

    # -- CRUD ----------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self._skills)

    async def add_or_merge(self, skill: Skill) -> tuple[str, str | None]:
        """Add a skill with deduplication. Returns ``(decision, skill_id)``.

        Decisions: ``"ADD"`` | ``"MERGE"`` | ``"KEEP_OLD"`` | ``"KEEP_NEW"``.
        """
        skill = self._normalize_skill(skill)
        conflict = self._find_best_conflict(skill)
        if conflict is None:
            self._upsert(skill)
            return "ADD", skill.skill_id

        decision = await self._decide_merge(conflict, skill)

        if decision == "MERGE":
            merged = self._merge_skills(conflict, skill)
            self._upsert(merged, replace_id=conflict.skill_id)
            return "MERGE", merged.skill_id
        elif decision == "KEEP_NEW":
            self._remove_internal(conflict.skill_id)
            self._upsert(skill)
            return "KEEP_NEW", skill.skill_id
        elif decision == "KEEP_OLD":
            return "KEEP_OLD", conflict.skill_id
        else:
            # ADD — genuinely different
            self._upsert(skill)
            return "ADD", skill.skill_id

    def add(self, skill: Skill) -> None:
        """Direct add without dedup (for bulk loading or trusted sources)."""
        self._upsert(self._normalize_skill(skill))

    def update(self, skill_id: str, updated_skill: Skill) -> bool:
        """Replace a skill by ID with an updated version.

        Used by the agent loop after each run to persist confidence updates
        (``success_count``, ``failure_count``, ``success_streak``,
        ``failure_streak``) without triggering deduplication logic.

        The ``updated_skill`` MUST carry the same ``skill_id`` as the one
        passed in ``skill_id``; callers are responsible for ensuring this.

        Args:
            skill_id: The ID of the skill to replace.
            updated_skill: The new Skill instance that replaces the old one.

        Returns:
            ``True`` if the skill was found and replaced; ``False`` if the
            ``skill_id`` was not present in the library.
        """
        if skill_id not in self._skills:
            return False
        updated_skill = self._normalize_skill(updated_skill)
        # Remove-then-upsert ensures the search index is rebuilt with any
        # changed fields (e.g. updated description or tags in addition to
        # stat counters).
        self._remove_internal(skill_id)
        self._upsert(updated_skill)
        return True

    def remove(self, skill_id: str) -> bool:
        return self._remove_internal(skill_id)

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def list_all(
        self,
        *,
        platform: str | None = None,
        app: str | None = None,
    ) -> list[Skill]:
        normalized_app = self._normalize_filter_app(platform, app)
        results: list[Skill] = []
        for skill in self._skills.values():
            if platform is not None and skill.platform != platform:
                continue
            if app is not None:
                candidate_app = normalized_app or normalize_app_identifier(skill.platform, app)
                if skill.app != candidate_app:
                    continue
            results.append(skill)
        return results

    @staticmethod
    def _normalize_skill(skill: Skill) -> Skill:
        return normalize_skill_app(skill)

    @staticmethod
    def _normalize_filter_app(platform: str | None, app: str | None) -> str | None:
        if app is None:
            return None
        if platform is None:
            return None
        return normalize_app_identifier(platform, app)

    # -- Conflict detection --------------------------------------------------

    def _find_best_conflict(self, incoming: Skill) -> Skill | None:
        """Multi-factor scoring to find the best matching existing skill."""
        incoming = self._normalize_skill(incoming)
        in_name = _normalize_name(incoming.name)
        in_sig = _action_signature(incoming)
        best: Skill | None = None
        best_score = 0.0

        for existing in self._skills.values():
            if existing.platform != incoming.platform:
                continue
            if existing.app != incoming.app:
                continue

            score = 0.0
            ex_name = _normalize_name(existing.name)

            # Factor 1: Exact normalized name match
            if ex_name == in_name:
                score += 1.0

            # Factor 2: Skill ID match (same origin)
            if existing.skill_id == incoming.skill_id:
                score += 0.6

            # Factor 3: Action sequence similarity
            action_sim = _action_similarity(_action_signature(existing), in_sig)
            score += 0.9 * action_sim

            # Factor 4: Name token similarity
            name_sim = _name_token_similarity(existing.name, incoming.name)
            score += 0.6 * name_sim

            if score > best_score:
                best = existing
                best_score = score

        if best is None:
            return None

        # Apply conflict gate thresholds
        best_name = _normalize_name(best.name)
        if best.skill_id == incoming.skill_id:
            return best
        if best_name == in_name:
            return best

        name_sim = _name_token_similarity(best.name, incoming.name)
        action_sim = _action_similarity(_action_signature(best), in_sig)

        if name_sim >= self.merge_name_threshold and action_sim >= self.merge_action_threshold:
            return best
        # Very high action similarity compensates for lower name similarity
        if name_sim >= 0.35 and action_sim >= 0.90:
            return best

        return None

    # -- Merge decision ------------------------------------------------------

    async def _decide_merge(self, old: Skill, new: Skill) -> str:
        """LLM or heuristic merge decision."""
        if self.merge_llm is not None:
            return await self._llm_merge_decision(old, new)
        return self._heuristic_merge_decision(old, new)

    async def _llm_merge_decision(self, old: Skill, new: Skill) -> str:
        prompt = _MERGE_DECISION_PROMPT.format(
            old_skill_json=json.dumps(old.to_dict(), ensure_ascii=False, indent=2),
            new_skill_json=json.dumps(new.to_dict(), ensure_ascii=False, indent=2),
        )
        response = await self.merge_llm.chat([{"role": "user", "content": prompt}])  # type: ignore[union-attr]
        return self._parse_llm_decision(response.content)

    @staticmethod
    def _parse_llm_decision(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            first_nl = text.index("\n")
            last_fence = text.rfind("```")
            text = text[first_nl + 1:last_fence].strip()
        try:
            data = json.loads(text)
            decision = data.get("decision", "ADD").upper()
            if decision in ("MERGE", "KEEP_OLD", "KEEP_NEW", "ADD"):
                return decision
        except (json.JSONDecodeError, AttributeError):
            pass
        logger.warning("Unparseable LLM merge decision, defaulting to ADD")
        return "ADD"

    @staticmethod
    def _heuristic_merge_decision(old: Skill, new: Skill) -> str:
        """Rule-based merge without LLM."""
        if old.skill_id == new.skill_id:
            return "KEEP_NEW"

        old_name = _normalize_name(old.name)
        new_name = _normalize_name(new.name)
        name_sim = _name_token_similarity(old.name, new.name)
        action_sim = _action_similarity(_action_signature(old), _action_signature(new))

        if old_name == new_name and action_sim >= 0.7:
            return "MERGE"
        if old_name == new_name:
            return "KEEP_OLD"
        if name_sim >= 0.72 and action_sim >= 0.55:
            return "MERGE"
        if name_sim >= 0.50 and action_sim >= 0.75:
            return "MERGE"
        if name_sim >= 0.30 and action_sim >= 0.93:
            return "KEEP_NEW"
        return "ADD"

    @staticmethod
    def _merge_skills(old: Skill, new: Skill) -> Skill:
        """Deterministic merge: aggregate stats, prefer longer step sequence."""
        old_sig = _action_signature(old)
        new_sig = _action_signature(new)

        # Steps: prefer longer (better coverage) if sequences are similar
        if _action_similarity(old_sig, new_sig) >= 0.8:
            steps = new.steps if len(new.steps) >= len(old.steps) else old.steps
        else:
            steps = new.steps or old.steps

        # Aggregate stats
        success = old.success_count + new.success_count
        failure = old.failure_count + new.failure_count

        # Union tags and parameters
        tags = tuple(sorted(set(old.tags) | set(new.tags)))
        params = tuple(sorted(set(old.parameters) | set(new.parameters)))
        preconditions = tuple(sorted(set(old.preconditions) | set(new.preconditions)))

        return Skill(
            skill_id=old.skill_id,  # Preserve old ID for stability
            name=new.name or old.name,
            description=new.description or old.description,
            app=new.app or old.app,
            platform=new.platform or old.platform,
            steps=steps,
            parameters=params,
            preconditions=preconditions,
            tags=tags,
            created_at=old.created_at,  # Keep original creation time
            success_count=success,
            failure_count=failure,
        )

    # -- Search --------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        platform: str | None = None,
        app: str | None = None,
        top_k: int = 5,
    ) -> list[tuple[Skill, float]]:
        """Hybrid BM25 + FAISS search. Falls back to pure BM25 if no embeddings."""
        if not self._skills:
            return []

        if self._index_dirty:
            await self._rebuild_index()

        mask = self._filter_mask(
            platform=platform,
            app=self._normalize_filter_app(platform, app),
        )
        if not any(mask):
            return []

        # BM25
        bm25_scores = np.array(self._bm25.score(query), dtype=np.float32)
        bm25_scores[~mask] = -1e9

        # Embedding (optional)
        if self.embedding_provider is not None:
            query_emb = await self.embedding_provider.embed([query])
            faiss_raw, faiss_idx = self._faiss.search(query_emb[0], len(self._ordered_ids))
            emb_scores = np.full(len(self._ordered_ids), -1e9, dtype=np.float32)
            for s, i in zip(faiss_raw, faiss_idx):
                if i >= 0:
                    emb_scores[i] = s
            emb_scores[~mask] = -1e9
        else:
            emb_scores = None

        # Normalize + blend
        bm25_norm = _min_max_norm(bm25_scores, mask)
        if emb_scores is not None:
            emb_norm = _min_max_norm(emb_scores, mask)
            hybrid = (1.0 - self.alpha) * bm25_norm + self.alpha * emb_norm
        else:
            hybrid = bm25_norm

        ranked = np.argsort(-hybrid)
        results: list[tuple[Skill, float]] = []
        for idx in ranked:
            if not mask[idx] or hybrid[idx] <= 0:
                break
            results.append((self._skills[self._ordered_ids[idx]], float(hybrid[idx])))
            if len(results) >= top_k:
                break
        return results

    # -- Persistence ---------------------------------------------------------

    def load_all(self) -> None:
        self._skills.clear()
        if not self.store_dir.exists():
            return
        for skills_file in self.store_dir.rglob("skills.json"):
            try:
                with open(skills_file, encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping invalid skill store %s: %s", skills_file, exc)
                continue
            if not isinstance(data, dict):
                logger.warning("Skipping malformed skill store %s: expected JSON object", skills_file)
                continue
            for skill_data in data.get("skills", []):
                skill = self._normalize_skill(Skill.from_dict(skill_data))
                self._skills[skill.skill_id] = skill
        self._index_dirty = True

    def _upsert(self, skill: Skill, *, replace_id: str | None = None) -> None:
        skill = self._normalize_skill(skill)
        if replace_id and replace_id in self._skills:
            del self._skills[replace_id]
        self._skills[skill.skill_id] = skill
        self._index_dirty = True
        self._save_platform_app(skill.platform, skill.app)

    def _remove_internal(self, skill_id: str) -> bool:
        skill = self._skills.pop(skill_id, None)
        if skill is None:
            return False
        self._index_dirty = True
        self._save_platform_app(skill.platform, skill.app)
        return True

    def _save_platform_app(self, platform: str, app: str) -> None:
        dir_path = self.store_dir / platform / app
        dir_path.mkdir(parents=True, exist_ok=True)
        target = dir_path / "skills.json"
        skills = [s for s in self._skills.values() if s.platform == platform and s.app == app]
        payload = {"skills": [s.to_dict() for s in skills]}
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=dir_path, suffix=".tmp", delete=False, encoding="utf-8",
        )
        try:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            Path(tmp.name).replace(target)
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    # -- Index management ----------------------------------------------------

    async def _rebuild_index(self) -> None:
        self._ordered_ids = list(self._skills.keys())
        self._documents = [self._skill_text(self._skills[sid]) for sid in self._ordered_ids]
        self._bm25.build(self._documents)
        if self.embedding_provider is not None and self._documents:
            embeddings = await self.embedding_provider.embed(self._documents)
            self._faiss.build(embeddings)
        self._index_dirty = False

    def _filter_mask(self, *, platform: str | None, app: str | None) -> np.ndarray:
        mask = np.ones(len(self._ordered_ids), dtype=bool)
        for i, sid in enumerate(self._ordered_ids):
            skill = self._skills[sid]
            if platform is not None and skill.platform != platform:
                mask[i] = False
            elif app is not None:
                normalized_app = app if platform is not None else normalize_app_identifier(skill.platform, app)
                if skill.app != normalized_app:
                    mask[i] = False
        return mask

    @staticmethod
    def _skill_text(skill: Skill) -> str:
        parts = [skill.name, skill.description, skill.app]
        parts.extend(skill.tags)
        if skill.preconditions:
            parts.extend(skill.preconditions)
        return " ".join(parts)


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
