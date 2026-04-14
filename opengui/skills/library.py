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
    """Persistent JSON skill store organized by ``{platform}/skills.json``.

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
    _loaded_mtime_ns: int = field(default=0, repr=False)

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
        logger.info(
            "Skill conflict found: new=%s [%s] vs existing=%s [%s]  "
            "name_sim=%.3f action_sim=%.3f",
            skill.name, skill.skill_id[:8],
            conflict.name, conflict.skill_id[:8],
            name_sim, action_sim,
        )

        decision = await self._decide_merge(conflict, skill)

        if decision == "MERGE":
            merged = self._merge_skills(conflict, skill)
            self._upsert(merged, replace_id=conflict.skill_id)
            logger.info(
                "Skill dedup decision=MERGE  merged=%s [%s]  "
                "(kept existing id, aggregated stats)",
                merged.name, merged.skill_id[:8],
            )
            self._cleanup_superseded_prefixes(skill.platform, skill.app)
            return "MERGE", merged.skill_id
        elif decision == "KEEP_NEW":
            self._remove_internal(conflict.skill_id)
            self._upsert(skill)
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
            self._upsert(skill)
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

        # Normalize BM25 to [0, 1] so it blends properly with cosine similarity
        valid_bm25 = bm25_scores[mask]
        bm25_max = float(valid_bm25.max()) if valid_bm25.size > 0 else 0.0
        if bm25_max > 0:
            bm25_scores = np.where(mask, bm25_scores / bm25_max, bm25_scores)

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

        # Blend normalized scores
        if emb_scores is not None:
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
            for skill_data in data.get("skills", []):
                skill = self._normalize_skill(Skill.from_dict(skill_data))
                self._skills[skill.skill_id] = skill
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

    def _upsert(self, skill: Skill, *, replace_id: str | None = None) -> None:
        skill = self._normalize_skill(skill)
        if replace_id and replace_id in self._skills:
            del self._skills[replace_id]
        self._skills[skill.skill_id] = skill
        self._index_dirty = True
        self._save_platform(skill.platform)

    def _remove_internal(self, skill_id: str) -> bool:
        skill = self._skills.pop(skill_id, None)
        if skill is None:
            return False
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
            self._cleanup_legacy_platform_files(platform)
            return
        payload = {"skills": [s.to_dict() for s in skills]}
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
        for step in skill.steps:
            # Strip {{param}} placeholders, keep semantic words
            target_clean = re.sub(r"\{\{[^}]+\}\}", "", step.target).strip()
            if target_clean:
                parts.append(target_clean)
            parts.append(step.action_type)
            if step.valid_state and step.valid_state.lower() != "no need to verify":
                parts.append(step.valid_state)
        return " ".join(p for p in parts if p)

