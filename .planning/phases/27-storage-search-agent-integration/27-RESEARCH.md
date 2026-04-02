# Phase 27: Storage, Search, and Agent Integration - Research

**Researched:** 2026-04-02
**Domain:** Versioned skill persistence, layer-aware unified search, and GuiAgent two-layer wiring
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| STOR-01 | Shortcut skills and task-level skills are persisted in separate, versioned JSON stores | `SkillLibrary` already implements the JSON-persistence pattern for legacy `Skill` objects (`_save_platform` + atomic temp-file write). Phase 27 creates two analogous store classes: `ShortcutSkillStore` and `TaskSkillStore`, each with `to_dict/from_dict` for their respective schema types. |
| STOR-02 | Unified skill search covers both layers with layer-aware relevance scoring | `SkillLibrary` already uses BM25 + optional FAISS hybrid via `_BM25Index` and `_FaissIndex` from `opengui.memory.retrieval`. `UnifiedSkillSearch` wraps both stores, runs search on each, and blends results with a layer-weight factor before returning a ranked `list[SkillSearchResult]`. |
| INTEG-01 | GuiAgent searches both skill layers during pre-task skill lookup and selects the most appropriate match | `GuiAgent._search_skill()` currently searches only legacy `SkillLibrary`. Phase 27 replaces this with a call to `UnifiedSkillSearch.search()` and selects the top result when above `skill_threshold`. The log entry must record which layer was selected. |
| INTEG-02 | GuiAgent injects the app memory context referenced by a task-level skill into the execution context before running | `TaskSkill.memory_context_id` is the opaque pointer. Before the first skill step runs, the agent calls `MemoryStore.get(memory_context_id)` and, if found, prepends the entry's `content` to `memory_context` (the same string passed to `_run_once`). |
</phase_requirements>

## Summary

Phase 27 is the capstone of the v1.5 architecture. It connects the output of Phase 26 (quality-gated `ShortcutSkill` candidates) to disk storage, and then wires `GuiAgent` to search both storage layers and inject memory context when a `TaskSkill` carries a pointer.

The work divides cleanly into three independent sub-problems that can be planned as separate waves:
1. **Storage layer** — `ShortcutSkillStore` and `TaskSkillStore` as two flat-file JSON stores following the atomic-write pattern already proven in `SkillLibrary`.
2. **Search layer** — `UnifiedSkillSearch` that queries both stores independently, applies per-layer weights to the relevance scores, and returns a ranked union. The BM25 and FAISS index building blocks already exist in `opengui.memory.retrieval`; the stores just need to own their own indices.
3. **Agent wiring** — `GuiAgent._search_skill()` is replaced by a call to `UnifiedSkillSearch`; a new `_inject_skill_memory_context()` helper injects `MemoryStore` content before the first execution step when a `TaskSkill` result carries `memory_context_id`.

All three sub-problems are self-contained and traceable to existing patterns in the codebase. No new external dependencies are required.

**Primary recommendation:** Model `ShortcutSkillStore` and `TaskSkillStore` directly on `SkillLibrary`'s persistence pattern — atomic temp-file write, `to_dict/from_dict` round-trip, per-platform file layout — then build `UnifiedSkillSearch` as a thin orchestrator over both stores using the shared `_BM25Index` building block.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `dataclasses`, `typing`, `pathlib`, `json`, `tempfile` | `>=3.11` | Store dataclasses, atomic writes, serialization | Matches every existing store in the codebase |
| `opengui.skills.shortcut` | workspace current | `ShortcutSkill`, `StateDescriptor`, `ParameterSlot` — the type `ShortcutSkillStore` persists | Phase 24 output, already has `to_dict/from_dict` |
| `opengui.skills.task_skill` | workspace current | `TaskSkill`, `TaskNode` — the type `TaskSkillStore` persists | Phase 24 output, already has `to_dict/from_dict` |
| `opengui.memory.retrieval._BM25Index` | workspace current | BM25 full-text index for search within each store | Shared module already used by `SkillLibrary` |
| `opengui.memory.retrieval._FaissIndex` | workspace current | Optional FAISS embedding index (hybrid search) | Same lazy-import pattern already used by `SkillLibrary` |
| `opengui.memory.retrieval.EmbeddingProvider` | workspace current | Optional async embedding protocol for FAISS | Already used by `SkillLibrary`; `GuiSubagentTool` already constructs a `NanobotEmbeddingAdapter` |
| `opengui.memory.store.MemoryStore` | workspace current | Memory entry lookup by `entry_id` for INTEG-02 | Existing production class; `MemoryStore.get(entry_id)` returns `MemoryEntry | None` |
| `opengui.agent.GuiAgent` | workspace current | The agent being wired — `_search_skill()` updated, `_inject_skill_memory_context()` added | The primary integration point |
| `numpy>=1.26.0` | `>=1.26.0` | Score arrays and min-max normalization | Already in `pyproject.toml`; same pattern in `SkillLibrary.search()` |
| `faiss-cpu>=1.9.0` | `>=1.9.0` | Vector similarity search (optional) | Already in `pyproject.toml` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest>=9.0.0` + `pytest-asyncio>=1.3.0` | workspace locked | Unit tests for async store/search/agent methods | All Phase 27 tests; `asyncio_mode = "auto"` already in `pyproject.toml` |
| `opengui.skills.normalization.normalize_app_identifier` | workspace current | App identifier normalization during skill storage | Same hook used by `SkillLibrary._normalize_skill()` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Per-store BM25 indices | Single shared index over all skills | Shared index conflates layer scores and loses layer-aware ranking; per-store is simpler and matches existing `SkillLibrary` design |
| Extending `SkillLibrary` to accept `ShortcutSkill` | New dedicated store classes | `SkillLibrary` is coupled to the legacy `Skill` schema and the merge/dedup logic; adding two-layer support would add complexity and risk regressions in the legacy path |
| `sqlite3` for skill persistence | Flat JSON files | JSON files match the existing system-wide pattern (`SkillLibrary`, `MemoryStore`); SQLite would add migration complexity with no benefit at current scale |

**Installation:**
```bash
uv sync --extra dev
```

No new packages are needed. All dependencies are already declared in `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure

```text
opengui/
└── skills/
    ├── library.py                   # existing SkillLibrary (legacy Skill, do not touch)
    ├── shortcut_store.py            # NEW: ShortcutSkillStore + UnifiedSkillSearch
    ├── shortcut.py                  # existing ShortcutSkill / StateDescriptor / ParameterSlot
    ├── task_skill.py                # existing TaskSkill / TaskNode
    └── __init__.py                  # add new Phase 27 public symbols

tests/
└── test_opengui_p27_storage_search_agent.py  # NEW: Phase 27 coverage
```

A single new file `shortcut_store.py` is preferred over multiple files to keep the flat layout consistent with the existing module structure. Both `ShortcutSkillStore` and `TaskSkillStore` are functionally similar enough to live alongside `UnifiedSkillSearch` in one module.

### Pattern 1: Versioned JSON Store With Atomic Write
**What:** Each store writes a single JSON file per platform to `{store_dir}/{platform}/{type}_skills.json` using a temp-file + `Path.replace()` pattern so writes are atomic. The store loads on `__post_init__` (same as `SkillLibrary`).
**When to use:** `ShortcutSkillStore.save()` and `TaskSkillStore.save()`.
**Example:**
```python
# Source: opengui/skills/library.py SkillLibrary._save_platform()
def _save_platform(self, platform: str) -> None:
    dir_path = self._store_dir / platform
    dir_path.mkdir(parents=True, exist_ok=True)
    target = dir_path / "shortcut_skills.json"
    skills = [s for s in self._skills.values() if s.platform == platform]
    if not skills:
        target.unlink(missing_ok=True)
        return
    payload = {"version": 1, "skills": [s.to_dict() for s in skills]}
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
```

The `"version": 1` field on the JSON envelope is what makes the store "versioned" — a future format change bumps this integer, and the reader checks it before attempting deserialization.

### Pattern 2: Per-Store BM25 + Optional FAISS Hybrid Search
**What:** Each store owns its own `_BM25Index` and `_FaissIndex`. When `search()` is called, it rebuilds dirty indices, scores documents with BM25, optionally blends with FAISS embeddings (min-max normalized), and returns ranked `(skill, score)` tuples.
**When to use:** `ShortcutSkillStore.search()` and `TaskSkillStore.search()`.
**Example:**
```python
# Source: opengui/skills/library.py SkillLibrary.search() and _rebuild_index()
async def search(self, query: str, *, top_k: int = 5) -> list[tuple[ShortcutSkill, float]]:
    if not self._skills:
        return []
    if self._index_dirty:
        await self._rebuild_index()
    bm25_scores = np.array(self._bm25.score(query), dtype=np.float32)
    if self._embedding_provider is not None:
        query_emb = await self._embedding_provider.embed([query])
        faiss_raw, faiss_idx = self._faiss.search(query_emb[0], len(self._ordered_ids))
        emb_scores = np.full(len(self._ordered_ids), -1e9, dtype=np.float32)
        for s, i in zip(faiss_raw, faiss_idx):
            if i >= 0:
                emb_scores[i] = s
        hybrid = (1.0 - self.alpha) * _min_max_norm(bm25_scores, mask) + self.alpha * _min_max_norm(emb_scores, mask)
    else:
        hybrid = _min_max_norm(bm25_scores, mask)
    ranked = np.argsort(-hybrid)
    ...
```

### Pattern 3: Layer-Aware Unified Search Result
**What:** `UnifiedSkillSearch.search()` queries both stores, annotates each result with its layer label, applies a `layer_weight` multiplier, and returns a single sorted list of `SkillSearchResult` objects.
**When to use:** `GuiAgent._search_skill()` calls only this method.
**Example:**
```python
# Source: design pattern — no existing analog; modeled on SkillLibrary.search() return shape
from dataclasses import dataclass
from typing import Literal

LayerLabel = Literal["shortcut", "task"]

@dataclass(frozen=True)
class SkillSearchResult:
    skill: ShortcutSkill | TaskSkill
    layer: LayerLabel
    score: float        # final blended score (layer-weighted)
    raw_score: float    # score before layer weighting

async def search(
    self,
    query: str,
    *,
    top_k: int = 5,
    shortcut_layer_weight: float = 1.0,
    task_layer_weight: float = 1.0,
) -> list[SkillSearchResult]:
    shortcut_hits = await self._shortcut_store.search(query, top_k=top_k)
    task_hits = await self._task_store.search(query, top_k=top_k)
    results: list[SkillSearchResult] = []
    for skill, score in shortcut_hits:
        results.append(SkillSearchResult(skill=skill, layer="shortcut",
                                          score=score * shortcut_layer_weight,
                                          raw_score=score))
    for skill, score in task_hits:
        results.append(SkillSearchResult(skill=skill, layer="task",
                                          score=score * task_layer_weight,
                                          raw_score=score))
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
```

### Pattern 4: GuiAgent Memory Context Injection Before Skill Execution
**What:** When `_search_skill()` returns a `TaskSkill` with `memory_context_id`, the agent calls `MemoryStore.get(memory_context_id)` and prepends the entry's `content` to `memory_context` before passing it to `_run_once`. This must happen before the first skill step runs.
**When to use:** In `GuiAgent.run()` between skill lookup (step 3) and skill execution (step 4).
**Example:**
```python
# Source: GuiAgent.run() structure from opengui/agent.py, MemoryStore.get() from opengui/memory/store.py
async def run(self, task: str, ...) -> AgentResult:
    ...
    skill_match = await self._search_skill(task)         # returns SkillSearchResult | None
    memory_context = await self._retrieve_memory(task)

    # INTEG-02: inject referenced app memory context when task-level skill has a pointer
    if skill_match is not None:
        memory_context = await self._inject_skill_memory_context(
            skill_match.skill, memory_context
        )
    ...

async def _inject_skill_memory_context(
    self,
    skill: ShortcutSkill | TaskSkill,
    existing_context: str | None,
) -> str | None:
    from opengui.skills.task_skill import TaskSkill as _TaskSkill
    if not isinstance(skill, _TaskSkill) or skill.memory_context_id is None:
        return existing_context
    if self._memory_store is None:
        return existing_context
    entry = self._memory_store.get(skill.memory_context_id)
    if entry is None:
        logger.warning("Skill %s references missing memory context %s", skill.skill_id, skill.memory_context_id)
        return existing_context
    injected = f"[Skill memory context]\n{entry.content}"
    return f"{injected}\n\n{existing_context}" if existing_context else injected
```

### Pattern 5: Skill Text Document for BM25/FAISS Indexing
**What:** Both stores need a `_skill_text()` helper that flattens a skill's searchable fields to a single string for BM25 tokenization. The shortcut store includes `parameter_slot` names and condition values; the task store includes the `name`, `description`, `app`, and `tags`.
**When to use:** Inside `_rebuild_index()` for each store.
**Example:**
```python
# Source: opengui/skills/library.py SkillLibrary._skill_text()
@staticmethod
def _shortcut_skill_text(skill: ShortcutSkill) -> str:
    parts = [skill.name, skill.description, skill.app, skill.platform]
    parts.extend(skill.tags)
    parts.extend(slot.name for slot in skill.parameter_slots)
    parts.extend(c.value for c in skill.preconditions)
    parts.extend(c.value for c in skill.postconditions)
    return " ".join(p for p in parts if p)

@staticmethod
def _task_skill_text(skill: TaskSkill) -> str:
    parts = [skill.name, skill.description, skill.app, skill.platform]
    parts.extend(skill.tags)
    return " ".join(p for p in parts if p)
```

### Anti-Patterns to Avoid

- **Reusing `SkillLibrary` for the new schema types:** `SkillLibrary` is tightly coupled to the legacy `Skill` dataclass and its merge/dedup logic. Creating new store classes avoids coupling and keeps the legacy path untouched.
- **Building a single merged JSON file for both layers:** STOR-01 explicitly requires separate stores. A single file would lose layer identity during deserialization.
- **Importing `MemoryStore` at module level in `shortcut_store.py`:** Use a lazy import pattern (identical to `SkillLibrary`'s `TYPE_CHECKING`-only import of `LLMProvider`) to avoid circular dependencies.
- **Searching both stores with the same `top_k` and then truncating:** When `top_k=5` and both stores return 5 results each, the final merged list has 10 before ranking. The stores should be queried with `top_k * 2` to ensure the merge step has enough candidates from each layer before final top-k selection.
- **Injecting `MemoryStore` as a constructor argument to `GuiAgent` with a new named field in `__init__`:** The current `GuiAgent.__init__` already has 14 parameters. The `_memory_store` dependency should be added as an optional `Any`-typed parameter with `None` default, consistent with how `skill_library`, `skill_executor`, and `memory_retriever` are currently injected.
- **Logging the skill lookup result without including the layer label:** INTEG-01 requires the lookup log entry to show which layer was selected. Always log `layer` from `SkillSearchResult` in the existing `_log_memory_retrieval`-style helper.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic file write | Custom file write | `tempfile.NamedTemporaryFile` + `Path.replace()` | Already proven in `SkillLibrary._save_platform()` and `MemoryStore._atomic_write()` — handles crash-safety and cross-platform path replacement |
| BM25 text index | Custom inverted index | `opengui.memory.retrieval._BM25Index` | CJK-aware (jieba), battle-tested, shared across `SkillLibrary` and `MemoryRetriever` |
| FAISS embedding index | Custom vector store | `opengui.memory.retrieval._FaissIndex` | Already wrapped for lazy-import; in-session rebuild is acceptable at current scale (deferred persistent FAISS per REQUIREMENTS.md Out of Scope) |
| Min-max score normalization | Custom normalization | `_min_max_norm()` from `opengui/skills/library.py` — either copy the 10-line function or factor it to `opengui/memory/retrieval.py` | Already handles edge cases (empty mask, zero-range normalization) |
| Memory entry lookup | Custom lookup | `MemoryStore.get(entry_id)` | Returns `MemoryEntry | None` directly by `entry_id`; no search needed since `memory_context_id` is an exact pointer |

**Key insight:** Phase 27 is pure wiring and thin orchestration. Every primitive it needs — JSON persistence, atomic writes, BM25 search, FAISS blending, memory lookup — already exists in the codebase. The task is to assemble these building blocks into two store classes, one search class, and two agent methods.

---

## Common Pitfalls

### Pitfall 1: Version Field Missing From JSON Envelope
**What goes wrong:** The JSON file lacks a `"version"` field, making STOR-01's "versioned" requirement unverifiable. Future format changes have no upgrade path.
**Why it happens:** The existing `SkillLibrary` stores do not carry a version field — it is easy to copy the pattern and omit the new requirement.
**How to avoid:** Always write `{"version": 1, "skills": [...]}` at the top level for both `shortcut_skills.json` and `task_skills.json`. During load, check `data.get("version", 0)` and log a warning for unknown versions rather than raising.
**Warning signs:** Test for round-trip fidelity passes but version field is absent in the written file.

### Pitfall 2: Layer Scores Are Not Normalized Before Blending
**What goes wrong:** Shortcut layer and task layer may have very different score distributions (e.g., shortcut store has 1 skill, task store has 50). Without per-layer normalization, the larger store always dominates.
**Why it happens:** It is tempting to concatenate the two result lists and sort directly.
**How to avoid:** Apply min-max normalization to shortcut scores and task scores independently before applying `layer_weight` multipliers. This mirrors what `SkillLibrary.search()` does within one store.
**Warning signs:** Unified search always returns results from the larger store, never from the smaller one.

### Pitfall 3: Memory Context Injection Happens After Skill Execution Starts
**What goes wrong:** `_inject_skill_memory_context()` is called inside `_run_once()` or at the wrong point in `run()`, so the injected context is not in the first step's messages.
**Why it happens:** `run()` has a complex step ordering (memory retrieval → skill search → skill execution → retry loop). The injection must happen after skill lookup but before the first call to `_run_once()`.
**How to avoid:** Call `_inject_skill_memory_context()` immediately after `_search_skill()` in `run()`, merging its result into `memory_context` before passing it to `_run_once`. Add a test that captures the messages passed to `_run_once` and asserts the injected content appears.
**Warning signs:** Integration test fails because injected text is absent from the first-step system prompt.

### Pitfall 4: `GuiSubagentTool` Still Passes Legacy `SkillLibrary` To `GuiAgent`
**What goes wrong:** `GuiSubagentTool._get_skill_library()` continues to construct a `SkillLibrary` and pass it as `skill_library=` to `GuiAgent`. The new `UnifiedSkillSearch` is never used.
**Why it happens:** `GuiSubagentTool` builds and wires `GuiAgent` directly; updating only `GuiAgent` internals is not sufficient.
**How to avoid:** Phase 27 must also update `GuiSubagentTool._get_skill_library()` (or add a separate `_get_unified_search()` method) and pass `unified_skill_search=` (or an equivalent parameter) to `GuiAgent`. The new `GuiAgent` parameter must replace (or supplement) `skill_library=`.
**Warning signs:** Integration smoke test using `GuiSubagentTool` still searches only the legacy store.

### Pitfall 5: `_inject_skill_memory_context` Raises When `memory_context_id` Points to a Deleted Entry
**What goes wrong:** A `TaskSkill` carries a `memory_context_id` that was deleted from the `MemoryStore`. The agent raises `KeyError` or `AttributeError` instead of degrading gracefully.
**Why it happens:** `MemoryStore.get()` returns `None` for missing entries — forgetting to check for `None` causes attribute access errors.
**How to avoid:** Guard with `if entry is None: logger.warning(...); return existing_context`. Missing memory is a warning, not an error. Test this case explicitly.
**Warning signs:** Test with a `memory_context_id` that does not exist in the `MemoryStore` raises instead of returning `existing_context`.

---

## Code Examples

### ShortcutSkillStore Persistence Round-Trip
```python
# Source: opengui/skills/library.py _save_platform / load_all pattern
# Combined with ShortcutSkill.to_dict() / from_dict() from opengui/skills/shortcut.py

# Saving
payload = {"version": 1, "skills": [skill.to_dict() for skill in skills]}
json.dump(payload, tmp, ensure_ascii=False, indent=2)

# Loading
data = json.load(f)
version = data.get("version", 0)
if version != 1:
    logger.warning("Unexpected store version %d in %s", version, skills_file)
for skill_data in data.get("skills", []):
    skill = ShortcutSkill.from_dict(skill_data)
    self._skills[skill.skill_id] = skill
```

### UnifiedSkillSearch Result Shape
```python
# Source: design pattern; SkillSearchResult is new for Phase 27
@dataclass(frozen=True)
class SkillSearchResult:
    skill: ShortcutSkill | TaskSkill
    layer: Literal["shortcut", "task"]
    score: float      # final score after layer weighting
    raw_score: float  # score before layer weighting
```

### GuiAgent._search_skill() With Unified Search
```python
# Source: opengui/agent.py GuiAgent._search_skill() — to be replaced in Phase 27
async def _search_skill(self, task: str) -> SkillSearchResult | None:
    if self._unified_skill_search is None:
        return None
    results = await self._unified_skill_search.search(task, top_k=1)
    if not results:
        return None
    best = results[0]
    if best.score >= self._skill_threshold:
        logger.info(
            "Skill match: %s (layer=%s, score=%.2f)",
            best.skill.name, best.layer, best.score,
        )
        return best
    return None
```

### GuiAgent Constructor Parameter Addition
```python
# Source: opengui/agent.py GuiAgent.__init__() — add these two parameters
def __init__(
    self,
    ...
    unified_skill_search: Any = None,   # replaces skill_library for two-layer search
    memory_store: Any = None,           # for INTEG-02 memory context injection
    ...
) -> None:
    ...
    self._unified_skill_search = unified_skill_search
    self._memory_store = memory_store
```

### MemoryEntry Injection Into Execution Context
```python
# Source: opengui/memory/store.py MemoryStore.get() — returns MemoryEntry | None
entry = self._memory_store.get(skill.memory_context_id)
if entry is not None:
    prefix = f"[Skill memory context]\n{entry.content}"
    memory_context = f"{prefix}\n\n{memory_context}" if memory_context else prefix
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single `skills.json` flat file per platform | Separate `shortcut_skills.json` + `task_skills.json` per platform with version envelope | Phase 27 | Layer-aware persistence; forward-compatible versioning |
| `GuiAgent` searches only legacy `SkillLibrary` (`Skill` type) | `GuiAgent` searches both `ShortcutSkillStore` and `TaskSkillStore` via `UnifiedSkillSearch` | Phase 27 | Agent can reuse two-layer v1.5 skills; legacy search path deprecated for the two-layer path |
| `GuiAgent` receives memory context only from `_retrieve_memory()` | `GuiAgent` also injects memory context referenced by a `TaskSkill.memory_context_id` | Phase 27 | App-specific memory tied to a skill is automatically available for the task without requiring the user to configure it |
| No versioning on skill JSON files | `"version": 1` in the JSON envelope | Phase 27 | Enables future schema migrations without breaking existing stores |

**Deprecated/outdated:**
- `GuiAgent.skill_library` parameter: will be superseded by `unified_skill_search` for the two-layer path. The legacy `skill_library` parameter should be kept as a backward-compatibility shim (not removed) to avoid breaking existing `GuiSubagentTool` wiring until a single cut-over commit updates both.
- `SkillLibrary` is NOT deprecated — it continues to serve the legacy `Skill` extraction and dedup pipeline used by `GuiSubagentTool._extract_skill()`. Only the skill search path in `GuiAgent` moves to `UnifiedSkillSearch`.

---

## Open Questions

1. **Should `ShortcutSkillStore` expose `add_or_merge()` like `SkillLibrary`, or just `add()`?**
   - What we know: STOR-01 only requires persistence and typed round-trip. The dedup/merge logic lives in `SkillLibrary` and is coupled to the legacy `Skill` schema.
   - What's unclear: Whether Phase 27 needs conflict detection for `ShortcutSkill` or if that is deferred.
   - Recommendation: Phase 27 implements only `add()`, `remove()`, `get()`, and `search()` on both stores. Conflict detection for the two-layer stores is not in scope for STOR-01 and can be addressed in a future phase. This keeps Phase 27 focused and avoids re-implementing the complex merge decision logic from `SkillLibrary`.

2. **Does `GuiAgent` keep both `skill_library` and `unified_skill_search` as separate parameters, or is there a single cut-over?**
   - What we know: `GuiSubagentTool` constructs `GuiAgent` with `skill_library=`. Both parameters being `Any`-typed makes coexistence straightforward.
   - What's unclear: Whether the planner wants a clean cut-over (remove `skill_library` path) or a backward-compatible shim.
   - Recommendation: Add `unified_skill_search` as a new optional parameter. In `_search_skill()`, prefer `unified_skill_search` when present, fall back to `skill_library` when not. This avoids a breaking change to `GuiSubagentTool` in the same phase. A follow-up cleanup task can remove the legacy parameter once `GuiSubagentTool` is updated.

3. **Where should `_min_max_norm()` live to be shared between `SkillLibrary` and `ShortcutSkillStore`/`TaskSkillStore`?**
   - What we know: It is currently a module-level function in `opengui/skills/library.py`. Both new stores will need it.
   - What's unclear: Whether to duplicate it (simple but fragile) or move it to a shared location.
   - Recommendation: Copy the 10-line function into `shortcut_store.py` to avoid coupling to `library.py`. If it grows beyond that, factor it to `opengui/memory/retrieval.py` as a proper utility. Premature factoring is not worth the refactoring risk here.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest >=9.0.0,<10.0.0` + `pytest-asyncio >=1.3.0,<2.0.0` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STOR-01a | `ShortcutSkillStore.add()` then reload from disk produces identical `ShortcutSkill` objects | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k shortcut_store_round_trip` | ❌ Wave 0 |
| STOR-01b | `TaskSkillStore.add()` then reload from disk produces identical `TaskSkill` objects | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k task_store_round_trip` | ❌ Wave 0 |
| STOR-01c | JSON file carries `"version": 1` envelope field | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k version_field` | ❌ Wave 0 |
| STOR-02 | `UnifiedSkillSearch.search()` returns results from both layers ranked by score with layer label | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k unified_search` | ❌ Wave 0 |
| INTEG-01 | `GuiAgent._search_skill()` returns `SkillSearchResult` with `layer` field; log entry includes layer | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k agent_skill_lookup` | ❌ Wave 0 |
| INTEG-02 | When selected skill is `TaskSkill` with `memory_context_id`, injected content appears in `memory_context` before `_run_once` | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k memory_context_injection` | ❌ Wave 0 |
| INTEG-02 guard | Missing `memory_context_id` in `MemoryStore` logs a warning and returns `existing_context` unchanged | unit | `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q -k missing_memory_context` | ❌ Wave 0 |
| Phase 27 import safety | New module imports and compiles without circular imports | smoke | `uv run python -m py_compile opengui/skills/shortcut_store.py` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p24_schema_grounding.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p25_multi_layer_execution.py tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p24_schema_grounding.py -q`
- **Phase gate:** `uv run pytest -q`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p27_storage_search_agent.py` — covers STOR-01, STOR-02, INTEG-01, INTEG-02, and import safety
- [ ] `opengui/skills/shortcut_store.py` — new module with `ShortcutSkillStore`, `TaskSkillStore`, `UnifiedSkillSearch`, `SkillSearchResult`
- [ ] Export `ShortcutSkillStore`, `TaskSkillStore`, `UnifiedSkillSearch`, `SkillSearchResult` from `opengui/skills/__init__.py`

---

## Sources

### Primary (HIGH confidence)
- `opengui/skills/library.py` — `SkillLibrary` persistence pattern (atomic write, BM25/FAISS hybrid, load_all); the definitive template for both new store classes
- `opengui/skills/shortcut.py` — `ShortcutSkill`, `StateDescriptor`, `ParameterSlot` schemas with `to_dict/from_dict` — confirmed round-trip contracts
- `opengui/skills/task_skill.py` — `TaskSkill`, `TaskNode` schemas with `to_dict/from_dict` — confirmed round-trip contracts, `memory_context_id` opaque pointer
- `opengui/memory/retrieval.py` — `_BM25Index`, `_FaissIndex`, `EmbeddingProvider` — shared search building blocks
- `opengui/memory/store.py` — `MemoryStore.get(entry_id)` — INTEG-02 entry lookup mechanism; atomic write pattern
- `opengui/memory/types.py` — `MemoryEntry.content` field — the text injected as memory context
- `opengui/agent.py` — `GuiAgent.__init__()` parameter list, `run()` step ordering, `_search_skill()`, `_retrieve_memory()`, `_skill_maintenance()` — full agent wiring context
- `nanobot/agent/tools/gui.py` — `GuiSubagentTool._get_skill_library()`, `GuiAgent` constructor call — the nanobot-side wiring that must also be updated
- `nanobot/config/schema.py` — `GuiConfig` fields — confirmed no `unified_skill_search` or `memory_store` config exists yet
- `.planning/REQUIREMENTS.md` — STOR-01, STOR-02, INTEG-01, INTEG-02 requirement text
- `.planning/STATE.md` — Phase 24 decision: `TaskSkill.memory_context_id` is opaque string pointer; Phase 27 capstone design intent

### Secondary (MEDIUM confidence)
- `opengui/skills/__init__.py` — current `__all__` export list; reference for adding Phase 27 symbols
- `opengui/skills/shortcut_extractor.py` — Phase 26 output confirming `ShortcutSkill` is the store's input type
- `tests/test_opengui_p25_multi_layer_execution.py` — test stub style (`_FakeBackend`, `_StubGrounder`) confirms the fake-dependency test pattern for Phase 27 tests
- `pyproject.toml` — confirmed `numpy>=1.26.0`, `faiss-cpu>=1.9.0`, `pytest asyncio_mode = "auto"`

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — All packages already in `pyproject.toml`; all types and patterns confirmed in local repo files
- Architecture: HIGH — Store and search patterns are direct analogs of `SkillLibrary`; agent wiring changes are minimal and localized to `_search_skill()` and one new helper
- Pitfalls: HIGH — Derived from concrete code inspection of `SkillLibrary`, `GuiAgent`, `MemoryStore`, and the `GuiSubagentTool` wiring

**Research date:** 2026-04-02
**Valid until:** 2026-05-02
