"""
opengui.skills.library
~~~~~~~~~~~~~~~~~~~~~~
Persistent skill storage with BM25 + optional FAISS hybrid retrieval,
and LLM-based or heuristic skill deduplication/merge.

Inspired by KnowAct's four-bucket model, simplified for opengui's scope:
- Single primary bucket per (platform, app)
- Embedding-dominant conflict detection (embedding + action sequence + name token)
- LLM or heuristic merge decision
- Description embeddings persisted to ``{platform}/embeddings.npy`` alongside
  ``skills.json``; ``skills.json`` groups skills by app for readability
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import typing
import hashlib
import time
from dataclasses import dataclass, field
from collections import OrderedDict
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
    """Prefix-aware similarity between two action signatures.

    When the shorter sequence is a perfect prefix of the longer one, the
    score reflects that all overlapping actions match, with only a mild
    penalty for the extra tail in the longer sequence.  This prevents
    short navigational-prefix skills from being scored as dissimilar to
    their longer counterparts.

    Formula:
        score = prefix_matches / min_len            (overlap quality, 0-1)
              * (1 - 0.3 * tail_len / max_len)      (length penalty, 0.7-1)
    """
    if not sig_a and not sig_b:
        return 1.0
    min_len = min(len(sig_a), len(sig_b))
    max_len = max(len(sig_a), len(sig_b))
    if max_len == 0:
        return 1.0
    # Count contiguous prefix matches (stricter than zip-anywhere).
    prefix_matches = 0
    for a, b in zip(sig_a, sig_b):
        if a == b:
            prefix_matches += 1
        else:
            break
    if min_len == 0:
        return 0.0
    overlap_quality = prefix_matches / min_len
    tail_len = max_len - min_len
    length_penalty = 1.0 - 0.3 * (tail_len / max_len)
    return overlap_quality * length_penalty


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors; returns 0 for zero-norm inputs."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


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

  Use `success_count`, `failure_count`, and `failure_streak` as reliability signals.
  **MERGE will keep the SHORTER step sequence** as a reusable navigational prefix.

  - **MERGE**: Same intent AND the shorter sequence is a genuine navigational prefix
    (it reaches the correct app/screen state; remaining steps are task-specific).
    Do NOT choose MERGE if the shorter skill has never succeeded — it may be a
    partial/failed recording, not a valid prefix.

  - **KEEP_OLD**: Old is more reliable (more executions, higher success rate) and new
    offers no structural improvement. Prefer when new has < 3 total executions vs
    old's >= 5, unless new's steps fix a clear error in old.

  - **KEEP_NEW**: New has a demonstrably better step sequence (corrects wrong actions,
    fewer redundant steps) even with fewer executions. Also prefer when old has
    failure_streak >= 3 and new has recent successes.

  - **ADD**: Different target screens or intents, or structurally incompatible paths
    that serve distinct use cases despite surface similarity.

  Respond with ONLY a JSON object:
  {{"decision": "MERGE|KEEP_OLD|KEEP_NEW|ADD", "reason": "one-line explanation"}}
  """


# ---------------------------------------------------------------------------
# SkillLibrary
# ---------------------------------------------------------------------------

@dataclass
class SkillLibrary:
    """Persistent JSON skill store organized by ``{platform}/skills.json``.

    Supports:
    - BM25 + optional FAISS hybrid retrieval
    - Embedding-dominant conflict detection on add
    - LLM-based or heuristic merge decisions
    - Description embeddings persisted to ``{platform}/embeddings.npy``

    Storage layout::

        {store_dir}/
          android/
            skills.json      # app-grouped: {"apps": {"com.x": [skill, ...]}}
            embeddings.npy   # numpy dict: {skill_id: np.ndarray}
          ios/
            skills.json
            embeddings.npy

    Parameters
    ----------
    store_dir:
        Root directory for skill JSON files.
    embedding_provider:
        Optional embedding API for hybrid search and conflict detection.
    merge_llm:
        Optional LLM for merge decisions. Falls back to heuristic if None.
    alpha:
        Blending weight (``1.0`` = pure embedding, ``0.0`` = pure BM25).
    merge_conflict_threshold:
        Combined-score threshold to trigger merge consideration.
        Score = 0.65 * embedding_sim + 0.25 * action_sim + 0.10 * name_token_sim.
        When no embedding provider is configured, falls back to a stricter
        action + name gate.
    search_mode:
        Retrieval strategy for :meth:`search`. One of:

        - ``"hybrid"`` (default): weighted blend of BM25 + embedding scores.
          Backward-compatible with the original behaviour.
        - ``"rrf"``: Reciprocal Rank Fusion — combines BM25 and embedding
          *rankings* without score normalization artifacts. More robust when
          score distributions differ across queries.
        - ``"hybrid_comprehensive"``: two-phase retrieval. Phase 1 selects
          ``top_k * 2`` candidates via hybrid scoring; Phase 2 re-ranks using
          a comprehensive similarity combining name-token Jaccard similarity and
          description embedding cosine.

        Falls back to ``"hybrid"`` for unrecognized values.
    """

    store_dir: Path
    embedding_provider: EmbeddingProvider | None = None
    merge_llm: LLMProvider | None = None
    alpha: float = 0.7
    merge_conflict_threshold: float = 0.45
    search_mode: str = "rrf"  # "hybrid" | "rrf" | "hybrid_comprehensive"
    query_embedding_cache_size: int = 512
    query_embedding_cache_ttl_hours: int = 24
    embedding_signature: str | None = None

    _skills: dict[str, Skill] = field(default_factory=dict, repr=False)
    _embeddings: dict[str, np.ndarray] = field(default_factory=dict, repr=False)
    _query_embedding_cache: dict[str, OrderedDict[str, dict[str, typing.Any]]] = field(
        default_factory=dict, repr=False
    )
    _query_cache_loaded_platforms: set[str] = field(default_factory=set, repr=False)
    _query_cache_meta: dict[str, dict[str, typing.Any]] = field(
        default_factory=dict, repr=False
    )
    _bm25: _BM25Index = field(default_factory=_lazy_bm25, repr=False)
    _faiss: _FaissIndex = field(default_factory=_lazy_faiss, repr=False)
    _documents: list[str] = field(default_factory=list, repr=False)
    _ordered_ids: list[str] = field(default_factory=list, repr=False)
    _index_dirty: bool = field(default=True, repr=False)
    _loaded_mtime_ns: int = field(default=0, repr=False)

    _VALID_SEARCH_MODES: typing.ClassVar[frozenset[str]] = frozenset(
        {"hybrid", "rrf", "hybrid_comprehensive"}
    )

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        if self.search_mode not in self._VALID_SEARCH_MODES:
            logger.warning(
                "Unknown search_mode %r; falling back to 'hybrid'. "
                "Valid options: %s",
                self.search_mode,
                sorted(self._VALID_SEARCH_MODES),
            )
        self.load_all()

    # -- Query embedding cache -------------------------------------------------

    @staticmethod
    def _query_cache_key(platform: str | None) -> str:
        return platform or "_global"

    def _query_cache_file(self, platform: str | None) -> Path:
        base_dir = self.store_dir if platform is None else self.store_dir / platform
        return base_dir / "query_embeddings_cache.json"

    def _clear_query_cache(self, platform: str | None) -> None:
        cache_key = self._query_cache_key(platform)
        self._query_embedding_cache.pop(cache_key, None)
        self._query_cache_meta.pop(cache_key, None)
        self._query_cache_loaded_platforms.discard(cache_key)
        target = self._query_cache_file(platform)
        if target.is_file():
            try:
                target.unlink()
            except OSError:
                logger.warning("Failed to remove query cache file %s", target)

    def _load_query_cache_if_needed(self, platform: str | None) -> None:
        cache_key = self._query_cache_key(platform)
        if cache_key in self._query_cache_loaded_platforms:
            return
        self._query_cache_loaded_platforms.add(cache_key)

        path = self._query_cache_file(platform)
        if not path.is_file():
            self._query_embedding_cache.setdefault(cache_key, OrderedDict())
            self._query_cache_meta.pop(cache_key, None)
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("query cache payload is malformed")
            stored_signature = payload.get("embedding_signature")
            if not isinstance(stored_signature, str):
                raise ValueError("query cache signature is missing")
            if stored_signature != self.embedding_signature:
                raise ValueError("query cache signature mismatch")

            dim = payload.get("dimension")
            if not isinstance(dim, int) or dim <= 0:
                raise ValueError("query cache dimension is invalid")

            raw_entries = payload.get("entries")
            if not isinstance(raw_entries, dict):
                raise ValueError("query cache entries are invalid")

            cache: OrderedDict[str, dict[str, typing.Any]] = OrderedDict()
            for hash_key, raw_entry in raw_entries.items():
                if not isinstance(raw_entry, dict):
                    continue
                vec = raw_entry.get("vec")
                ts = raw_entry.get("ts")
                dim_entry = raw_entry.get("dim")
                if (
                    not isinstance(vec, list)
                    or not vec
                    or not isinstance(ts, (int, float))
                    or not isinstance(dim_entry, int)
                    or dim_entry <= 0
                ):
                    continue
                if dim_entry != dim or len(vec) != dim:
                    raise ValueError("query cache dimension mismatch")
                vec_arr = np.array(vec, dtype=np.float32)
                if vec_arr.ndim != 1:
                    continue
                cache[str(hash_key)] = {
                    "vec": vec_arr,
                    "ts": float(ts),
                    "dim": int(dim_entry),
                }

            self._query_embedding_cache[cache_key] = cache
            self._query_cache_meta[cache_key] = {
                "embedding_signature": stored_signature,
                "dimension": dim,
            }
        except (OSError, ValueError, json.JSONDecodeError):
            self._clear_query_cache(platform)

    def _prune_expired_query_cache_entries(self, cache_key: str) -> None:
        cache = self._query_embedding_cache.get(cache_key)
        if not cache:
            return
        ttl_seconds = self.query_embedding_cache_ttl_hours * 3600
        now = time.time()
        expired = [
            key
            for key, value in cache.items()
            if now - float(value.get("ts", 0.0)) > ttl_seconds
        ]
        for key in expired:
            cache.pop(key, None)

    def _enforce_query_cache_size(self, cache_key: str) -> None:
        cache = self._query_embedding_cache.get(cache_key)
        if cache is None:
            return
        while len(cache) > self.query_embedding_cache_size:
            cache.popitem(last=False)

    def _save_query_cache(self, platform: str | None) -> None:
        cache_key = self._query_cache_key(platform)
        cache = self._query_embedding_cache.get(cache_key)
        if cache is None:
            return
        if not cache:
            self._query_cache_file(platform).unlink(missing_ok=True)
            return

        entries: dict[str, dict[str, typing.Any]] = {}
        dimension: int | None = None
        for key, value in cache.items():
            vec = value.get("vec")
            if not isinstance(vec, np.ndarray):
                continue
            dim = int(value.get("dim", 0))
            if dim <= 0:
                continue
            dimension = dim
            entries[key] = {
                "vec": vec.tolist(),
                "ts": float(value.get("ts", 0.0)),
                "dim": dim,
            }

        if not entries:
            self._query_cache_file(platform).unlink(missing_ok=True)
            return

        target = self._query_cache_file(platform)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "embedding_signature": self.embedding_signature,
            "dimension": dimension,
            "entries": entries,
        }
        tmp = target.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            tmp.replace(target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _query_cache_candidate_k(self, top_k: int) -> int:
        return max(1, min(len(self._ordered_ids), top_k * 2))

    async def _get_query_embedding(self, query: str, platform: str | None) -> np.ndarray | None:
        if self.embedding_provider is None:
            return None

        self._load_query_cache_if_needed(platform)
        cache_key = self._query_cache_key(platform)
        cache = self._query_embedding_cache.setdefault(cache_key, OrderedDict())
        self._prune_expired_query_cache_entries(cache_key)
        self._enforce_query_cache_size(cache_key)

        normalized_query = query.strip().lower()
        query_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
        cached = cache.get(query_hash)
        if cached is not None and isinstance(cached.get("vec"), np.ndarray):
            cache.pop(query_hash, None)
            cache[query_hash] = cached
            return cached["vec"]

        vec = (await self.embedding_provider.embed([normalized_query]))[0]
        vec = np.asarray(vec, dtype=np.float32)
        cache[query_hash] = {"vec": vec, "ts": time.time(), "dim": int(vec.size)}
        self._enforce_query_cache_size(cache_key)
        self._save_query_cache(platform)
        return vec

    # -- CRUD ----------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self._skills)

    async def add_or_merge(self, skill: Skill) -> tuple[str, str | None]:
        """Add a skill with deduplication. Returns ``(decision, skill_id)``.

        Decisions: ``"ADD"`` | ``"MERGE"`` | ``"KEEP_OLD"`` | ``"KEEP_NEW"``.
        """
        skill = self._normalize_skill(skill)

        # Compute embedding for the incoming skill description up front so it
        # can be used both in conflict detection and persisted on upsert.
        incoming_emb: np.ndarray | None = None
        if self.embedding_provider is not None:
            try:
                vecs = await self.embedding_provider.embed([skill.description])
                incoming_emb = vecs[0]
            except Exception as exc:
                logger.warning("Failed to embed incoming skill %r: %s", skill.name, exc)

        conflict = self._find_best_conflict(skill, incoming_emb)
        if conflict is None:
            self._upsert(skill, embedding=incoming_emb)
            logger.info(
                "Skill dedup decision=ADD  new=%s [%s] app=%s  (no conflict found)",
                skill.name, skill.skill_id[:8], skill.app,
            )
            self._cleanup_superseded_prefixes(skill.platform, skill.app)
            return "ADD", skill.skill_id

        # Log conflict details with similarity scores for diagnostics.
        name_sim = _name_token_similarity(conflict.name, skill.name)
        action_sim = _action_similarity(
            _action_signature(conflict), _action_signature(skill),
        )
        emb_sim: float | None = None
        if incoming_emb is not None and conflict.skill_id in self._embeddings:
            emb_sim = _cosine_similarity(incoming_emb, self._embeddings[conflict.skill_id])
        logger.info(
            "Skill conflict found: new=%s [%s] vs existing=%s [%s]  "
            "name_sim=%.3f action_sim=%.3f emb_sim=%s",
            skill.name, skill.skill_id[:8],
            conflict.name, conflict.skill_id[:8],
            name_sim, action_sim,
            f"{emb_sim:.3f}" if emb_sim is not None else "n/a",
        )

        decision = await self._decide_merge(conflict, skill)

        if decision == "MERGE":
            merged = self._merge_skills(conflict, skill)
            self._upsert(merged, replace_id=conflict.skill_id, embedding=incoming_emb)
            logger.info(
                "Skill dedup decision=MERGE  merged=%s [%s]  "
                "(kept existing id, aggregated stats)",
                merged.name, merged.skill_id[:8],
            )
            self._cleanup_superseded_prefixes(skill.platform, skill.app)
            return "MERGE", merged.skill_id
        elif decision == "KEEP_NEW":
            self._remove_internal(conflict.skill_id)
            self._upsert(skill, embedding=incoming_emb)
            logger.info(
                "Skill dedup decision=KEEP_NEW  new=%s [%s]  "
                "replaced=%s [%s]",
                skill.name, skill.skill_id[:8],
                conflict.name, conflict.skill_id[:8],
            )
            self._cleanup_superseded_prefixes(skill.platform, skill.app)
            return "KEEP_NEW", skill.skill_id
        elif decision == "KEEP_OLD":
            logger.info(
                "Skill dedup decision=KEEP_OLD  kept=%s [%s]  "
                "discarded=%s [%s]",
                conflict.name, conflict.skill_id[:8],
                skill.name, skill.skill_id[:8],
            )
            return "KEEP_OLD", conflict.skill_id
        else:
            # ADD — genuinely different
            self._upsert(skill, embedding=incoming_emb)
            logger.info(
                "Skill dedup decision=ADD  new=%s [%s] app=%s  "
                "(conflict found but decision=ADD)",
                skill.name, skill.skill_id[:8], skill.app,
            )
            self._cleanup_superseded_prefixes(skill.platform, skill.app)
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
        # Preserve existing embedding — stat-only updates don't change description.
        existing_emb = self._embeddings.get(skill_id)
        self._remove_internal(skill_id)
        self._upsert(updated_skill, embedding=existing_emb)
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

    def _find_best_conflict(
        self,
        incoming: Skill,
        incoming_emb: np.ndarray | None = None,
    ) -> Skill | None:
        """Embedding-dominant multi-factor scoring to find the best matching skill.

        Scoring weights:
        - Embedding cosine similarity: 0.65  (dominant — semantic intent)
        - Action sequence similarity:  0.25  (structural)
        - Name token (Jaccard) similarity: 0.10  (weak signal, easily gamed)

        When no embedding provider is available, falls back to a pure
        action-sequence + name-token gate (no embedding term).
        """
        incoming = self._normalize_skill(incoming)
        in_sig = _action_signature(incoming)
        best: Skill | None = None
        best_score = 0.0

        for existing in self._skills.values():
            if existing.platform != incoming.platform:
                continue
            if existing.app != incoming.app:
                continue

            score = 0.0

            # Factor 1 — embedding cosine similarity (dominant)
            if incoming_emb is not None and existing.skill_id in self._embeddings:
                ex_emb = self._embeddings[existing.skill_id]
                score += 0.65 * _cosine_similarity(incoming_emb, ex_emb)

            # Factor 2 — action sequence similarity
            action_sim = _action_similarity(_action_signature(existing), in_sig)
            score += 0.25 * action_sim

            # Factor 3 — name token (Jaccard) similarity, low weight
            name_sim = _name_token_similarity(existing.name, incoming.name)
            score += 0.10 * name_sim

            if score > best_score:
                best = existing
                best_score = score

        if best is None:
            return None

        # Gate: combined score must exceed threshold when embeddings are available.
        if incoming_emb is not None and best.skill_id in self._embeddings:
            if best_score >= self.merge_conflict_threshold:
                return best
            return None

        # Fallback gate (no embedding): require both action and name similarity.
        action_sim = _action_similarity(_action_signature(best), in_sig)
        name_sim = _name_token_similarity(best.name, incoming.name)
        if action_sim >= 0.60 and name_sim >= 0.50:
            return best
        if action_sim >= 0.90 and name_sim >= 0.35:
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
        """Deterministic merge: aggregate stats, prefer shorter step sequence.

        Shorter skills are more generic navigational prefixes — the agent
        handles remaining steps dynamically based on the specific task.
        """
        old_sig = _action_signature(old)
        new_sig = _action_signature(new)

        # Steps: prefer shorter (more generic prefix) if sequences are similar
        if _action_similarity(old_sig, new_sig) >= 0.8:
            steps = new.steps if len(new.steps) <= len(old.steps) else old.steps
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

    async def _search_rrf(
        self,
        query: str,
        *,
        mask: np.ndarray,
        bm25_scores: np.ndarray,
        query_emb: np.ndarray | None,
        top_k: int,
        rrf_k: int = 60,
        min_emb_similarity: float = 0.3,
        faiss_k: int | None = None,
    ) -> list[tuple[Skill, float]]:
        """Reciprocal Rank Fusion retrieval.

        Combines BM25 and embedding *rankings* (not scores) via the RRF formula::

            RRF(item) = 1 / (rrf_k + rank_bm25) + 1 / (rrf_k + rank_emb)

        where ranks are 1-based. This avoids normalization artifacts that arise
        when blending raw BM25 and cosine scores with different distributions.

        Falls back to BM25-only RRF when ``query_emb`` is None.

        After ranking, the normalized RRF score [0, 1] is scaled by the raw
        embedding cosine similarity so that the final score reflects actual
        semantic relevance — preventing the top-ranked item from always
        receiving score=1.0 regardless of how relevant it actually is.
        When ``query_emb`` is None, results with BM25-only scores are returned
        unchanged (no embedding gate is applied).

        Parameters
        ----------
        min_emb_similarity:
            Hard floor on embedding cosine similarity.  Results whose
            embedding cosine falls below this value are excluded from the
            output even if they rank first by RRF.  Only applied when an
            embedding provider is available.
        """
        n = len(self._ordered_ids)

        # BM25 ranking: masked-out items sorted to the bottom, then assigned inf rank.
        bm25_valid = np.where(mask, bm25_scores, -1e9)
        bm25_ordering = np.argsort(-bm25_valid)  # descending
        bm25_rank = np.empty(n, dtype=np.float64)
        for rank, idx in enumerate(bm25_ordering):
            bm25_rank[idx] = rank
        bm25_rank[~mask] = np.inf

        emb_scores: np.ndarray | None = None
        if query_emb is not None:
            if faiss_k is None:
                faiss_k = n
            faiss_raw, faiss_idx = self._faiss.search(query_emb, faiss_k)
            emb_scores = np.full(n, -1e9, dtype=np.float32)
            emb_rank = np.full(n, np.inf, dtype=np.float64)
            for rank, (s, i) in enumerate(zip(faiss_raw, faiss_idx)):
                if i >= 0:
                    emb_scores[i] = s
                    emb_rank[i] = float(rank)
            emb_scores[~mask] = -1e9
            emb_rank[~mask] = np.inf

            # RRF score using 1-based ranks (0-based rank + 1).
            rrf_scores = (
                1.0 / (rrf_k + bm25_rank + 1.0)
                + 1.0 / (rrf_k + emb_rank + 1.0)
            )
        else:
            rrf_scores = 1.0 / (rrf_k + bm25_rank + 1.0)

        rrf_scores[~mask] = 0.0

        # Normalize RRF ranks to [0, 1].
        rrf_max = float(rrf_scores.max())
        if rrf_max > 0:
            rrf_scores = rrf_scores / rrf_max

        # Scale normalized RRF score by the raw embedding cosine similarity so
        # that the final score reflects actual semantic relevance.  Without this,
        # the top-ranked item always receives 1.0 regardless of relevance, making
        # the caller's threshold check meaningless.
        if emb_scores is not None:
            emb_clipped = np.clip(emb_scores, 0.0, 1.0)
            rrf_scores = rrf_scores * emb_clipped

        ranked = np.argsort(-rrf_scores)
        results: list[tuple[Skill, float]] = []
        for idx in ranked:
            if not mask[idx] or rrf_scores[idx] <= 0:
                break
            # Hard gate: exclude results whose raw embedding cosine is too low.
            if emb_scores is not None and float(emb_scores[idx]) < min_emb_similarity:
                continue
            results.append((self._skills[self._ordered_ids[idx]], float(rrf_scores[idx])))
            if len(results) >= top_k:
                break
        return results

    async def _search_hybrid_comprehensive(
        self,
        query: str,
        *,
        mask: np.ndarray,
        bm25_scores: np.ndarray,
        query_emb: np.ndarray | None,
        top_k: int,
        faiss_k: int | None = None,
    ) -> list[tuple[Skill, float]]:
        """Two-phase retrieval: hybrid candidate selection + comprehensive re-ranking.

        **Phase 1** — retrieve ``top_k * 2`` candidates using standard hybrid
        BM25 + embedding scoring (same as the ``"hybrid"`` mode).

        **Phase 2** — re-rank each candidate with a comprehensive score that
        combines name-token Jaccard similarity (query vs. skill name) and
        description embedding cosine::

            comp_score  = 0.30 * name_sim + 0.70 * desc_sim
            final_score = 0.60 * hybrid_score + 0.40 * comp_score

        Note: action-sequence similarity is intentionally excluded from
        retrieval.  It applies to skill-vs-skill deduplication (both sides have
        action sequences) but not to query-vs-skill retrieval where the query
        has no action sequence.
        """
        n = len(self._ordered_ids)
        candidate_k = min(top_k * 2, n)

        # --- Phase 1: hybrid scoring ---
        bm25_copy = bm25_scores.copy()
        bm25_max = float(bm25_copy[mask].max()) if mask.any() else 0.0
        if bm25_max > 0:
            bm25_norm = np.where(mask, bm25_copy / bm25_max, bm25_copy)
        else:
            bm25_norm = bm25_copy

        emb_scores: np.ndarray | None = None
        if query_emb is not None:
            if faiss_k is None:
                faiss_k = n
            faiss_raw, faiss_idx = self._faiss.search(query_emb, faiss_k)
            emb_scores = np.full(n, -1e9, dtype=np.float32)
            for s, i in zip(faiss_raw, faiss_idx):
                if i >= 0:
                    emb_scores[i] = s
            emb_scores[~mask] = -1e9
            hybrid = (1.0 - self.alpha) * bm25_norm + self.alpha * emb_scores
        else:
            hybrid = bm25_norm.copy()

        # Select top candidates by hybrid score.
        ranked_all = np.argsort(-hybrid)
        candidate_indices: list[int] = []
        for idx in ranked_all:
            if not mask[idx] or hybrid[idx] <= 0:
                break
            candidate_indices.append(int(idx))
            if len(candidate_indices) >= candidate_k:
                break

        if not candidate_indices:
            return []

        # --- Phase 2: comprehensive re-ranking ---
        scored: list[tuple[Skill, float]] = []
        for idx in candidate_indices:
            sid = self._ordered_ids[idx]
            skill = self._skills[sid]
            hybrid_score = float(hybrid[idx])

            # name_sim: Jaccard between query tokens and skill name tokens.
            name_sim = _name_token_similarity(query, skill.name)

            # desc_sim: embedding cosine; prefer the already-computed FAISS score.
            if emb_scores is not None and emb_scores[idx] > -1e8:
                desc_sim = float(emb_scores[idx])
            elif sid in self._embeddings and query_emb is not None:
                desc_sim = _cosine_similarity(query_emb, self._embeddings[sid])
            else:
                desc_sim = 0.0

            comp_score = 0.30 * name_sim + 0.70 * desc_sim
            final_score = 0.60 * hybrid_score + 0.40 * comp_score
            scored.append((skill, final_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [(skill, score) for skill, score in scored[:top_k] if score > 0]

    async def search(
        self,
        query: str,
        *,
        platform: str | None = None,
        app: str | None = None,
        top_k: int = 5,
    ) -> list[tuple[Skill, float]]:
        """Search the skill library using the configured ``search_mode``.

        Supports three modes (controlled by :attr:`search_mode`):

        - ``"hybrid"`` (default): weighted BM25 + embedding blend.
        - ``"rrf"``: Reciprocal Rank Fusion of BM25 and embedding rankings.
        - ``"hybrid_comprehensive"``: two-phase hybrid filter + name/embedding
          re-ranking.

        Falls back to pure BM25 when no embedding provider is configured.
        Unrecognized ``search_mode`` values fall back to ``"hybrid"``.
        """
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

        query = query.strip().lower()

        # Shared: raw BM25 scores with masked-out items suppressed.
        bm25_scores = np.array(self._bm25.score(query), dtype=np.float32)
        bm25_scores[~mask] = -1e9

        # Shared: query embedding — normalized + cached across calls and restarts.
        query_emb = await self._get_query_embedding(query, platform=platform)
        faiss_k = self._query_cache_candidate_k(top_k)

        if self.search_mode == "rrf":
            return await self._search_rrf(
                query,
                mask=mask,
                bm25_scores=bm25_scores,
                query_emb=query_emb,
                top_k=top_k,
                faiss_k=faiss_k,
            )

        if self.search_mode == "hybrid_comprehensive":
            return await self._search_hybrid_comprehensive(
                query,
                mask=mask,
                bm25_scores=bm25_scores,
                query_emb=query_emb,
                top_k=top_k,
                faiss_k=faiss_k,
            )

        # Default "hybrid" mode — backward-compatible weighted blend.
        # Normalize BM25 to [0, 1] before blending with cosine similarity.
        valid_bm25 = bm25_scores[mask]
        bm25_max = float(valid_bm25.max()) if valid_bm25.size > 0 else 0.0
        if bm25_max > 0:
            bm25_scores = np.where(mask, bm25_scores / bm25_max, bm25_scores)

        if query_emb is not None:
            faiss_raw, faiss_idx = self._faiss.search(query_emb, faiss_k)
            emb_scores = np.full(len(self._ordered_ids), -1e9, dtype=np.float32)
            for s, i in zip(faiss_raw, faiss_idx):
                if i >= 0:
                    emb_scores[i] = s
            emb_scores[~mask] = -1e9
            hybrid = (1.0 - self.alpha) * bm25_scores + self.alpha * emb_scores
        else:
            hybrid = bm25_scores.copy()

        ranked = np.argsort(-hybrid)
        results: list[tuple[Skill, float]] = []
        for idx in ranked:
            if not mask[idx] or hybrid[idx] <= 0:
                break
            results.append((self._skills[self._ordered_ids[idx]], float(hybrid[idx])))
            if len(results) >= top_k:
                break
        return results

    # -- Redundancy cleanup ---------------------------------------------------

    def _cleanup_superseded_prefixes(self, platform: str, app: str) -> None:
        """Remove zero-success skills whose step sequence is a strict prefix of a
        higher-confidence sibling in the same (platform, app) bucket.

        Called automatically at the end of every ADD / MERGE / KEEP_NEW branch
        in :meth:`add_or_merge` so callers don't need to orchestrate cleanup.
        """
        from opengui.skills.data import compute_confidence

        normalized_app = self._normalize_filter_app(platform, app) or app
        candidates = [
            s for s in self._skills.values()
            if s.platform == platform and s.app == normalized_app
        ]
        for skill in list(candidates):
            if skill.success_count > 0:
                continue
            sig = _action_signature(skill)
            for other in candidates:
                if other.skill_id == skill.skill_id:
                    continue
                other_sig = _action_signature(other)
                if (
                    len(sig) < len(other_sig)
                    and other_sig[: len(sig)] == sig
                    and compute_confidence(other) > compute_confidence(skill)
                ):
                    self._remove_internal(skill.skill_id)
                    candidates = [c for c in candidates if c.skill_id != skill.skill_id]
                    logger.info(
                        "Cleanup: removed superseded prefix skill %s [%s] "
                        "(prefix of %s [%s])",
                        skill.name, skill.skill_id[:8],
                        other.name, other.skill_id[:8],
                    )
                    break

    def cleanup_app_skills(
        self, platform: str, app: str, *, min_count: int = 3
    ) -> list[str]:
        """Remove redundant skills for a given *platform*/*app* pair.

        Triggered after ``add_or_merge`` when the per-app skill count reaches
        *min_count*.  Returns the list of removed skill IDs.

        Cleanup rules (applied in order):
        1. Remove zero-success skills whose steps are a prefix of a
           higher-confidence sibling (superseded).
        2. Remove skills with ``failure_streak >= 3`` and zero successes
           (persistently failing, not worth waiting for 5 attempts).
        """
        from opengui.skills.data import compute_confidence

        normalized_app = self._normalize_filter_app(platform, app) or app
        candidates = [
            s for s in self._skills.values()
            if s.platform == platform and s.app == normalized_app
        ]
        if len(candidates) < min_count:
            return []

        removed: list[str] = []

        # Rule 1: superseded prefix skills with zero success
        for skill in list(candidates):
            if skill.success_count > 0:
                continue
            sig = _action_signature(skill)
            for other in candidates:
                if other.skill_id == skill.skill_id:
                    continue
                other_sig = _action_signature(other)
                # Check if skill is a strict prefix of other
                if (
                    len(sig) < len(other_sig)
                    and other_sig[: len(sig)] == sig
                    and compute_confidence(other) > compute_confidence(skill)
                ):
                    self._remove_internal(skill.skill_id)
                    removed.append(skill.skill_id)
                    candidates = [c for c in candidates if c.skill_id != skill.skill_id]
                    logger.info(
                        "Cleanup: removed superseded skill %s [%s] "
                        "(prefix of %s [%s])",
                        skill.name, skill.skill_id[:8],
                        other.name, other.skill_id[:8],
                    )
                    break

        # Rule 2: persistently failing skills (failure_streak >= 3, zero success)
        for skill in list(candidates):
            if skill.skill_id in removed:
                continue
            if skill.failure_streak >= 3 and skill.success_count == 0:
                self._remove_internal(skill.skill_id)
                removed.append(skill.skill_id)
                logger.info(
                    "Cleanup: removed persistently failing skill %s [%s] "
                    "(failure_streak=%d, success=0)",
                    skill.name, skill.skill_id[:8], skill.failure_streak,
                )

        return removed

    # -- Persistence ---------------------------------------------------------

    def load_all(self) -> None:
        self._skills.clear()
        self._embeddings.clear()
        if not self.store_dir.exists():
            self._loaded_mtime_ns = 0
            self._index_dirty = True
            return
        for skills_file in self._iter_skill_files():
            try:
                with open(skills_file, encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping invalid skill store %s: %s", skills_file, exc)
                continue
            if not isinstance(data, dict):
                logger.warning("Skipping malformed skill store %s: expected JSON object", skills_file)
                continue

            # Support both new app-grouped format and legacy flat list.
            apps_section = data.get("apps")
            if isinstance(apps_section, dict):
                # New format: {"apps": {"app_name": [skill_dict, ...]}}
                for skill_list in apps_section.values():
                    if not isinstance(skill_list, list):
                        continue
                    for skill_data in skill_list:
                        skill = self._normalize_skill(Skill.from_dict(skill_data))
                        self._skills[skill.skill_id] = skill
            else:
                # Legacy format: {"skills": [skill_dict, ...]}
                for skill_data in data.get("skills", []):
                    skill = self._normalize_skill(Skill.from_dict(skill_data))
                    self._skills[skill.skill_id] = skill

            # Load companion embeddings.npy if present.
            emb_path = skills_file.parent / "embeddings.npy"
            if emb_path.is_file():
                try:
                    raw = np.load(str(emb_path), allow_pickle=True).item()
                    if isinstance(raw, dict):
                        for sid, vec in raw.items():
                            self._embeddings[sid] = np.asarray(vec, dtype=np.float32)
                except Exception as exc:
                    logger.warning("Failed to load embeddings from %s: %s", emb_path, exc)

        self._loaded_mtime_ns = self._snapshot_mtime_ns()
        self._index_dirty = True

    def refresh_if_stale(self) -> bool:
        current_mtime_ns = self._snapshot_mtime_ns()
        if current_mtime_ns == self._loaded_mtime_ns:
            return False
        self.load_all()
        return True

    def _iter_skill_files(self) -> list[Path]:
        files: list[Path] = []
        flat_platforms: set[str] = set()

        if not self.store_dir.exists():
            return files

        for platform_dir in sorted(path for path in self.store_dir.iterdir() if path.is_dir()):
            flat_file = platform_dir / "skills.json"
            if flat_file.is_file():
                files.append(flat_file)
                flat_platforms.add(platform_dir.name)

        for skills_file in sorted(self.store_dir.rglob("skills.json")):
            relative_parts = skills_file.relative_to(self.store_dir).parts
            if len(relative_parts) <= 2:
                continue
            if relative_parts[0] in flat_platforms:
                continue
            files.append(skills_file)

        return files

    def _snapshot_mtime_ns(self) -> int:
        max_mtime_ns = 0
        for skills_file in self._iter_skill_files():
            try:
                max_mtime_ns = max(max_mtime_ns, skills_file.stat().st_mtime_ns)
            except FileNotFoundError:
                continue
        return max_mtime_ns

    def _upsert(
        self,
        skill: Skill,
        *,
        replace_id: str | None = None,
        embedding: np.ndarray | None = None,
    ) -> None:
        skill = self._normalize_skill(skill)
        if replace_id and replace_id in self._skills:
            del self._skills[replace_id]
            if replace_id != skill.skill_id:
                self._embeddings.pop(replace_id, None)
        self._skills[skill.skill_id] = skill
        if embedding is not None:
            self._embeddings[skill.skill_id] = embedding
        self._index_dirty = True
        self._save_platform(skill.platform)

    def _remove_internal(self, skill_id: str) -> bool:
        skill = self._skills.pop(skill_id, None)
        if skill is None:
            return False
        self._embeddings.pop(skill_id, None)
        self._index_dirty = True
        self._save_platform(skill.platform)
        return True

    def _save_platform(self, platform: str) -> None:
        dir_path = self.store_dir / platform
        dir_path.mkdir(parents=True, exist_ok=True)
        target = dir_path / "skills.json"
        skills = [s for s in self._skills.values() if s.platform == platform]
        if not skills:
            target.unlink(missing_ok=True)
            (dir_path / "embeddings.npy").unlink(missing_ok=True)
            self._cleanup_legacy_platform_files(platform)
            return

        # Group skills by app for readability.
        apps: dict[str, list[dict]] = {}
        for s in skills:
            apps.setdefault(s.app, []).append(s.to_dict())
        payload = {"apps": apps}

        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=dir_path, suffix=".tmp", delete=False, encoding="utf-8",
        )
        try:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            Path(tmp.name).replace(target)
            self._cleanup_legacy_platform_files(platform)
            self._loaded_mtime_ns = self._snapshot_mtime_ns()
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise

        self._save_embeddings(platform)

    def _save_embeddings(self, platform: str) -> None:
        """Atomically persist the embedding cache for *platform* to a .npy file."""
        dir_path = self.store_dir / platform
        dir_path.mkdir(parents=True, exist_ok=True)
        target = dir_path / "embeddings.npy"

        # Collect embeddings for skills belonging to this platform only.
        platform_ids = {s.skill_id for s in self._skills.values() if s.platform == platform}
        emb_dict = {
            sid: emb
            for sid, emb in self._embeddings.items()
            if sid in platform_ids
        }
        if not emb_dict:
            target.unlink(missing_ok=True)
            return

        tmp_path = dir_path / "embeddings.tmp.npy"
        try:
            np.save(str(tmp_path), emb_dict)
            tmp_path.replace(target)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    def _embeddings_path(self, platform: str) -> Path:
        """Return the path to the embeddings file for *platform*."""
        return self.store_dir / platform / "embeddings.npy"

    def _cleanup_legacy_platform_files(self, platform: str) -> None:
        platform_dir = self.store_dir / platform
        if not platform_dir.exists():
            return
        for legacy_file in sorted(platform_dir.glob("*/skills.json")):
            legacy_file.unlink(missing_ok=True)
            try:
                legacy_file.parent.rmdir()
            except OSError:
                continue

    # -- Index management ----------------------------------------------------

    async def _rebuild_index(self) -> None:
        self._ordered_ids = list(self._skills.keys())
        self._documents = [self._skill_text(self._skills[sid]) for sid in self._ordered_ids]
        self._bm25.build(self._documents)

        if self.embedding_provider is not None and self._documents:
            # Only embed skills that don't already have a cached embedding.
            missing_indices = [
                i for i, sid in enumerate(self._ordered_ids)
                if sid not in self._embeddings
            ]
            if missing_indices:
                missing_texts = [self._documents[i] for i in missing_indices]
                changed_platforms: set[str] = set()
                try:
                    new_vecs = await self.embedding_provider.embed(missing_texts)
                    for idx, vec in zip(missing_indices, new_vecs):
                        sid = self._ordered_ids[idx]
                        self._embeddings[sid] = vec
                        # Persist new embeddings by platform.
                        platform = self._skills[sid].platform
                        changed_platforms.add(platform)
                except Exception as exc:
                    logger.warning("Failed to embed %d skills during index rebuild: %s",
                                   len(missing_indices), exc)
                    changed_platforms.clear()

                for platform in changed_platforms:
                    self._save_embeddings(platform)

            # Build FAISS from the full (now-populated) embedding cache.
            vecs = [
                self._embeddings[sid]
                for sid in self._ordered_ids
                if sid in self._embeddings
            ]
            if vecs:
                self._faiss.build(np.stack(vecs).astype(np.float32))

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
        for step in skill.steps:
            # Strip {{param}} placeholders, keep semantic words
            target_clean = re.sub(r"\{\{[^}]+\}\}", "", step.target).strip()
            if target_clean:
                parts.append(target_clean)
            parts.append(step.action_type)
            if step.valid_state and step.valid_state.lower() != "no need to verify":
                parts.append(step.valid_state)
        return " ".join(p for p in parts if p)
