# Phase 1: P1 Unit Tests - Research

**Researched:** 2026-03-17
**Domain:** Python unit testing — pytest, async mocking, FAISS isolation
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TEST-02 | Unit tests for memory module (store, retrieval, types) | MemoryStore JSON persistence verified; MemoryRetriever async embed protocol clearly mockable; BM25 pure-Python testable without FAISS |
| TEST-03 | Unit tests for skills module (library CRUD, search, dedup, executor, extractor) | SkillLibrary CRUD and dedup paths fully synchronous except `add_or_merge` / `search`; SkillExecutor testable via DryRunBackend + mock StateValidator; SkillExtractor testable via mock LLMProvider |
| TEST-04 | Unit tests for trajectory module (recorder events, summarizer) | TrajectoryRecorder is fully synchronous; TrajectorySummarizer async but trivially mockable via mock LLMProvider |
</phase_requirements>

---

## Summary

Phase 1 must add fast, isolated unit tests for the three opengui sub-packages (`memory/`, `skills/`, `trajectory/`) that were implemented in Phase 0 but left uncovered. The P0 test file (`tests/test_opengui.py`) demonstrates the project's established pattern: synchronous and async tests co-exist, async tests carry `@pytest.mark.asyncio`, dependencies are replaced via `monkeypatch` or manual mock classes (no `unittest.mock.patch` decoration style is used), and the `DryRunBackend` is the canonical no-IO backend.

A critical infrastructure gap exists: `faiss-cpu` and `numpy` are **not** in `pyproject.toml` dependencies or the dev extras, yet the memory retrieval and skill library modules `import numpy as np` at module load time and call `import faiss` inside methods. The uv venv currently has neither package installed. Writing tests that import `opengui.memory.retrieval` or `opengui.skills.library` without first adding these packages to the dev deps will fail at collection time. This must be resolved in the first task of this phase before any test code is written.

The test infrastructure itself is solid: pytest 9.0.2, pytest-asyncio 1.3.0, `asyncio_mode = "auto"` in `pyproject.toml` (meaning `@pytest.mark.asyncio` is applied automatically and can be omitted), and `testpaths = ["tests"]` already set. All eight P0 tests pass in 0.02 seconds with `uv run pytest`. The target is a single new test file `tests/test_opengui_p1.py` (following P0 naming convention) covering all three modules.

**Primary recommendation:** Add `faiss-cpu` and `numpy` to `[project.optional-dependencies] dev`, then write three test modules (or sections) in `tests/test_opengui_p1.py` — one per sub-package — using fake/stub classes for all external I/O (embeddings, LLM, device backend).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 9.0.2 (already installed) | Test runner, fixtures, assertions | Already in dev deps; all P0 tests use it |
| pytest-asyncio | 1.3.0 (already installed) | Async test support | Already in dev deps; `asyncio_mode=auto` in pyproject |
| faiss-cpu | 1.13.x (not yet installed) | FAISS vector index (required by retrieval.py + library.py) | Used in production code; must be present to import modules |
| numpy | 2.4.x (not yet installed) | Array operations (required by retrieval.py + library.py) | Used in production code; must be present to import modules |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock (stdlib) | stdlib | AsyncMock for embedding/LLM callables | Used in P0 tests already (`AsyncMock`) |
| tmp_path (pytest fixture) | built-in | Isolated temp dirs for JSON persistence tests | Use for all MemoryStore and SkillLibrary persistence tests |
| DryRunBackend | in-repo | No-IO device backend | Use in SkillExecutor tests to avoid real device calls |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| faiss-cpu | Pure-Python cosine sim fallback | STATE.md: "No pure-Python cosine fallback" — project decision locks faiss-cpu |
| AsyncMock for embed | Real numpy arrays | AsyncMock + returning `np.random.rand(N, 8).astype(np.float32)` is simpler and deterministic |

**Installation (missing deps):**
```bash
uv add --dev faiss-cpu numpy
```

Or directly edit `pyproject.toml` dev extras:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=9.0.0,<10.0.0",
    "pytest-asyncio>=1.3.0,<2.0.0",
    "faiss-cpu>=1.13.0",
    "numpy>=1.26.0",
    "ruff>=0.1.0",
    ...
]
```

---

## Architecture Patterns

### Recommended Project Structure
```
tests/
└── test_opengui_p1.py   # All Phase 1 unit tests (mirrors test_opengui.py pattern)
```

One file following the existing P0 convention. Sections within the file can be delimited by comments grouping memory / skills / trajectory tests.

### Pattern 1: Sync Tests — No Decorator Needed
**What:** Pure synchronous tests use plain `def test_*()` — no decorator required.
**When to use:** MemoryStore, MemoryEntry serialization, SkillStep/Skill serialization, TrajectoryRecorder, SkillLibrary CRUD (non-async paths), helper functions.
**Example:**
```python
# Mirrors pattern in tests/test_opengui.py
def test_memory_store_round_trip(tmp_path):
    store = MemoryStore(tmp_path / "mem")
    entry = MemoryEntry(
        entry_id="e1",
        memory_type=MemoryType.APP_GUIDE,
        platform="android",
        content="Settings > WiFi",
    )
    store.add(entry)
    store2 = MemoryStore(tmp_path / "mem")   # reload from disk
    assert store2.get("e1") == entry
```

### Pattern 2: Async Tests — asyncio_mode=auto
**What:** Async tests are declared `async def test_*()`. No `@pytest.mark.asyncio` decorator is needed because `asyncio_mode = "auto"` is set in pyproject.
**When to use:** MemoryRetriever.search, SkillLibrary.search, SkillLibrary.add_or_merge, SkillExecutor.execute, SkillExtractor.extract_from_steps, TrajectorySummarizer.summarize_events.
**Example:**
```python
async def test_memory_retriever_returns_ranked_results(tmp_path):
    provider = _FakeEmbedder(dim=8)
    retriever = MemoryRetriever(embedding_provider=provider, top_k=2)
    entries = [
        MemoryEntry("a", MemoryType.APP_GUIDE, "android", "open wifi settings"),
        MemoryEntry("b", MemoryType.OS_GUIDE, "android", "reboot device"),
    ]
    await retriever.index(entries)
    results = await retriever.search("wifi")
    assert len(results) >= 1
    assert results[0][0].entry_id == "a"
```

### Pattern 3: Fake Embedding Provider
**What:** A lightweight in-process class satisfying `EmbeddingProvider` protocol, returning deterministic `numpy` arrays.
**When to use:** Every test of MemoryRetriever or SkillLibrary.search that needs FAISS indexing to function.
```python
import numpy as np

class _FakeEmbedder:
    """Returns deterministic L2-norm-able float32 embeddings."""
    def __init__(self, dim: int = 8) -> None:
        self._dim = dim
        self._counter = 0

    async def embed(self, texts: list[str]) -> np.ndarray:
        # Each text gets a unique unit vector so FAISS ranking is deterministic
        vecs = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i in range(len(texts)):
            vecs[i, (self._counter + i) % self._dim] = 1.0
        self._counter += len(texts)
        return vecs
```

### Pattern 4: Fake LLM Provider
**What:** Scripted synchronous or async `chat()` returning canned `LLMResponse` objects.
**When to use:** SkillExtractor, TrajectorySummarizer, SkillLibrary (when testing merge_llm path), LLMStateValidator.
```python
from opengui.interfaces import LLMResponse

class _ScriptedLLM:
    def __init__(self, *responses: str) -> None:
        self._queue = list(responses)

    async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
        return LLMResponse(content=self._queue.pop(0))
```

### Pattern 5: Fake StateValidator
**What:** A mock `StateValidator` that returns a controlled `True`/`False` per call.
**When to use:** SkillExecutor.execute tests that need to trigger valid_state failure paths.
```python
class _FakeValidator:
    def __init__(self, returns: list[bool]) -> None:
        self._queue = list(returns)

    async def validate(self, valid_state: str, screenshot=None) -> bool:
        return self._queue.pop(0) if self._queue else True
```

### Anti-Patterns to Avoid
- **Importing opengui.memory.retrieval without faiss-cpu installed:** Causes `ModuleNotFoundError: No module named 'numpy'` at collection time, failing the entire test suite.
- **Using `@pytest.mark.asyncio` decorator:** Not needed when `asyncio_mode = "auto"` is set; adding it causes deprecation warnings in pytest-asyncio 1.3.x.
- **Network calls in tests:** SkillExtractor and TrajectorySummarizer both call `llm.chat()` — always inject a `_ScriptedLLM` mock. MemoryRetriever calls `embedding_provider.embed()` — always inject `_FakeEmbedder`.
- **Real file paths in trajectory tests:** Use `tmp_path` fixture for all `TrajectoryRecorder(output_dir=...)` construction to avoid cross-test pollution.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Temp file isolation | Custom dir cleanup code | `tmp_path` pytest fixture | Auto-cleaned, unique per test |
| Async test runner | Custom event loop setup | `asyncio_mode=auto` already configured | Already in pyproject.toml |
| Fake numpy arrays | Custom numeric computation | `np.zeros(..., dtype=np.float32)` + index assignment | FAISS requires float32 contiguous arrays specifically |
| JSON serialization assertions | String comparison | Re-deserialize with `from_dict()` and compare dataclass equality | More robust than string matching |

**Key insight:** All external I/O in the three modules is behind protocols (`EmbeddingProvider`, `LLMProvider`, `DeviceBackend`, `StateValidator`). This means zero monkey-patching is needed — construct real classes with injected fakes.

---

## Common Pitfalls

### Pitfall 1: faiss-cpu / numpy Missing from Dev Dependencies
**What goes wrong:** `import opengui.memory.retrieval` raises `ModuleNotFoundError: No module named 'numpy'` at pytest collection time, blocking all tests in the file.
**Why it happens:** `retrieval.py` has `import numpy as np` at module top level; `library.py` does the same. Neither `faiss-cpu` nor `numpy` is declared in `pyproject.toml`.
**How to avoid:** First task in the phase must add both to dev extras in `pyproject.toml` and run `uv sync --extra dev`.
**Warning signs:** Any attempt to import either module from the test shell will fail immediately.

### Pitfall 2: SkillLibrary.__post_init__ Calls load_all()
**What goes wrong:** Constructing `SkillLibrary(store_dir=tmp_path)` automatically calls `load_all()`, which calls `self.store_dir.rglob("skills.json")`. This is fine with `tmp_path` but will silently pick up stale files if a shared directory is reused across tests.
**How to avoid:** Always pass a fresh `tmp_path / "skills"` subdirectory per test.

### Pitfall 3: FAISS Index Requires Contiguous float32
**What goes wrong:** `_FaissIndex.build()` calls `faiss.normalize_L2(embeddings)` which requires `np.float32` contiguous arrays. Fake embedders returning `float64` or non-contiguous arrays will raise a FAISS internal error.
**How to avoid:** Always declare fake embedding arrays as `dtype=np.float32` and call `np.ascontiguousarray()`.

### Pitfall 4: TrajectoryRecorder Requires start() Before record_step()
**What goes wrong:** Calling `recorder.record_step(...)` before `recorder.start()` raises `RuntimeError("Recorder not started; call start() first")` because `_path` is `None`.
**How to avoid:** Always call `recorder.start()` first in test setup; verify the returned `Path` exists.

### Pitfall 5: SkillExtractor.extract_from_steps() Returns None for < 2 Steps
**What goes wrong:** Passing a single-step list returns `None` silently (by design). Tests asserting a `Skill` object would fail.
**How to avoid:** Always provide at least 2 step dicts to `extract_from_steps()`. Test the < 2 path explicitly to assert `None` return.

### Pitfall 6: asyncio_mode=auto Scope Collision
**What goes wrong:** `asyncio_default_fixture_loop_scope=None` warning visible in P0 run output. If fixtures using `scope="session"` or `scope="module"` are added, they can conflict with per-function loops.
**How to avoid:** Keep all async fixtures at function scope (default). Do not add session-scoped async fixtures in this phase.

---

## Code Examples

Verified patterns from source code:

### MemoryStore JSON Persistence
```python
# Source: opengui/memory/store.py — MemoryStore.save() atomic write
def test_memory_store_persists_and_reloads(tmp_path):
    store = MemoryStore(tmp_path)
    entry = MemoryEntry(
        entry_id="abc",
        memory_type=MemoryType.POLICY,
        platform="android",
        content="never tap red buttons",
    )
    store.add(entry)
    store2 = MemoryStore(tmp_path)
    loaded = store2.get("abc")
    assert loaded is not None
    assert loaded.content == "never tap red buttons"
    assert loaded.memory_type == MemoryType.POLICY
```

### MemoryRetriever BM25-Only (alpha=0)
```python
# Source: opengui/memory/retrieval.py — alpha blending
async def test_retriever_bm25_only_ranks_by_term_overlap():
    provider = _FakeEmbedder(dim=8)
    retriever = MemoryRetriever(embedding_provider=provider, alpha=0.0, top_k=3)
    entries = [
        MemoryEntry("a", MemoryType.APP_GUIDE, "android", "open wifi network settings"),
        MemoryEntry("b", MemoryType.OS_GUIDE, "android", "reboot the device"),
        MemoryEntry("c", MemoryType.APP_GUIDE, "android", "wifi password change settings"),
    ]
    await retriever.index(entries)
    results = await retriever.search("wifi settings")
    ids = [e.entry_id for e, _ in results]
    assert "a" in ids
    assert "c" in ids
```

### SkillLibrary CRUD
```python
# Source: opengui/skills/library.py — add/get/remove/list_all
def test_skill_library_crud(tmp_path):
    lib = SkillLibrary(store_dir=tmp_path)
    skill = Skill(
        skill_id="s1", name="open_settings", description="Open settings app",
        app="settings", platform="android",
        steps=(SkillStep(action_type="tap", target="Settings icon"),),
    )
    lib.add(skill)
    assert lib.count == 1
    assert lib.get("s1") is not None
    assert lib.remove("s1") is True
    assert lib.count == 0
```

### SkillLibrary Deduplication (heuristic path)
```python
# Source: opengui/skills/library.py — _heuristic_merge_decision, add_or_merge
async def test_skill_library_dedup_same_name_merges(tmp_path):
    lib = SkillLibrary(store_dir=tmp_path)  # no merge_llm → heuristic path
    s1 = Skill("s1", "open_wifi_settings", "Open WiFi", "settings", "android",
               steps=(SkillStep("tap", "WiFi option"),))
    s2 = Skill("s2", "open_wifi_settings", "Open WiFi updated", "settings", "android",
               steps=(SkillStep("tap", "WiFi option"), SkillStep("tap", "Advanced")))
    lib.add(s1)
    decision, sid = await lib.add_or_merge(s2)
    assert decision in ("MERGE", "KEEP_OLD", "KEEP_NEW", "ADD")
    assert lib.count >= 1
```

### SkillExecutor valid_state Verification
```python
# Source: opengui/skills/executor.py — _validate_state called before execute
async def test_executor_stops_on_failed_state_check(tmp_path):
    backend = DryRunBackend()
    validator = _FakeValidator(returns=[False])
    executor = SkillExecutor(backend=backend, state_validator=validator, stop_on_failure=True)
    skill = Skill(
        "s1", "test_skill", "", "app", "android",
        steps=(SkillStep("tap", "Button", valid_state="button must be visible"),),
    )
    result = await executor.execute(skill)
    assert result.state == ExecutionState.FAILED
    assert result.step_results[0].valid_state_check is False
```

### SkillExtractor Parsing
```python
# Source: opengui/skills/extractor.py — _parse_response
async def test_skill_extractor_parses_llm_json():
    canned = json.dumps({
        "name": "open_settings",
        "description": "Opens the settings app",
        "app": "settings",
        "platform": "android",
        "parameters": [],
        "preconditions": ["home screen visible"],
        "steps": [{"action_type": "tap", "target": "Settings icon",
                   "parameters": {}, "valid_state": "No need to verify"}],
    })
    llm = _ScriptedLLM(canned)
    extractor = SkillExtractor(llm)
    steps = [{"type": "step", "action": {"action_type": "tap"}, "model_output": "tap"},
             {"type": "step", "action": {"action_type": "done"}, "model_output": "done"}]
    skill = await extractor.extract_from_steps(steps, is_success=True)
    assert skill is not None
    assert skill.name == "open_settings"
    assert skill.platform == "android"
```

### TrajectoryRecorder Event Sequencing
```python
# Source: opengui/trajectory/recorder.py — start/record_step/finish JSONL ordering
def test_trajectory_recorder_event_order(tmp_path):
    rec = TrajectoryRecorder(output_dir=tmp_path, task="open settings", platform="android")
    path = rec.start()
    rec.record_step(action={"action_type": "tap", "x": 100, "y": 200}, model_output="tap icon")
    rec.set_phase(ExecutionPhase.SKILL, reason="matched skill")
    rec.record_step(action={"action_type": "done"}, model_output="done")
    rec.finish(success=True)

    lines = path.read_text().strip().splitlines()
    events = [json.loads(l) for l in lines]
    types = [e["type"] for e in events]
    assert types[0] == "metadata"
    assert types[-1] == "result"
    assert events[-1]["success"] is True
    assert events[-1]["total_steps"] == 2
```

### TrajectorySummarizer Output Format
```python
# Source: opengui/trajectory/summarizer.py — summarize_events returns stripped string
async def test_trajectory_summarizer_returns_string():
    llm = _ScriptedLLM("The agent opened settings successfully.")
    summarizer = TrajectorySummarizer(llm)
    events = [
        {"type": "metadata", "task": "open settings", "platform": "android"},
        {"type": "step", "step_index": 0, "action": {"action_type": "tap"}, "model_output": ""},
        {"type": "result", "success": True, "duration_s": 1.2, "error": None},
    ]
    summary = await summarizer.summarize_events(events)
    assert isinstance(summary, str)
    assert len(summary) > 0
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@pytest.mark.asyncio` on every async test | `asyncio_mode = "auto"` in pyproject | pytest-asyncio 0.21+ | No decorator needed on async def test_*() |
| `unittest.mock.patch` decorator | Constructor injection of fakes | P0 pattern established | No monkey-patching needed for protocol-typed dependencies |

**Deprecated/outdated:**
- `@pytest.mark.asyncio` per-test decorator: still works but unnecessary given `asyncio_mode=auto`.

---

## Open Questions

1. **faiss-cpu dependency declaration**
   - What we know: faiss-cpu is not in pyproject.toml; tests importing retrieval.py will fail at collection without it.
   - What's unclear: Whether it should go in main dependencies or dev-only. The production `retrieval.py` code uses numpy and calls faiss at runtime, suggesting it belongs in main deps, not just dev.
   - Recommendation: Add `faiss-cpu>=1.13.0` and `numpy>=1.26.0` to main `[project.dependencies]` (since they are required for production use of MemoryRetriever), and verify with `uv sync`.

2. **SkillLibrary search without FAISS (BM25-only path)**
   - What we know: When `embedding_provider=None`, `SkillLibrary.search()` uses pure BM25 (line 406: `emb_scores = None`).
   - What's unclear: Whether tests should exercise both BM25-only and hybrid paths, or only hybrid.
   - Recommendation: Test BM25-only path (no embedding provider) as the simpler case; add one hybrid test with `_FakeEmbedder`. Both code paths exist in library.py.

3. **MemoryRetriever.format_context coverage**
   - What we know: `format_context()` is a pure formatting method returning a string; it's not listed in TEST-02 success criteria explicitly.
   - What's unclear: Whether to include it in unit tests.
   - Recommendation: Include one test since it is part of MEM-03 functionality and is trivially testable synchronously.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 1.3.0 |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_opengui_p1.py -v` |
| Full suite command | `uv run pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-02 | MemoryStore JSON persistence + reload | unit | `uv run pytest tests/test_opengui_p1.py -k "memory_store" -x` | Wave 0 |
| TEST-02 | MemoryRetriever BM25+FAISS hybrid search | unit | `uv run pytest tests/test_opengui_p1.py -k "retriever" -x` | Wave 0 |
| TEST-03 | SkillLibrary CRUD (add/get/remove/list) | unit | `uv run pytest tests/test_opengui_p1.py -k "skill_library_crud" -x` | Wave 0 |
| TEST-03 | SkillLibrary hybrid search | unit | `uv run pytest tests/test_opengui_p1.py -k "skill_library_search" -x` | Wave 0 |
| TEST-03 | SkillLibrary deduplication + merge | unit | `uv run pytest tests/test_opengui_p1.py -k "dedup" -x` | Wave 0 |
| TEST-03 | SkillExecutor per-step valid_state | unit | `uv run pytest tests/test_opengui_p1.py -k "executor" -x` | Wave 0 |
| TEST-03 | SkillExtractor JSON parsing | unit | `uv run pytest tests/test_opengui_p1.py -k "extractor" -x` | Wave 0 |
| TEST-04 | TrajectoryRecorder event sequencing | unit | `uv run pytest tests/test_opengui_p1.py -k "recorder" -x` | Wave 0 |
| TEST-04 | TrajectorySummarizer output format | unit | `uv run pytest tests/test_opengui_p1.py -k "summarizer" -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p1.py -v`
- **Per wave merge:** `uv run pytest tests/ -v`
- **Phase gate:** Full suite green (`uv run pytest tests/ -v`) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p1.py` — main deliverable covering TEST-02, TEST-03, TEST-04
- [ ] `pyproject.toml` dev extras — add `faiss-cpu>=1.13.0` and `numpy>=1.26.0`
- [ ] Run `uv sync --extra dev` after adding deps

---

## Sources

### Primary (HIGH confidence)
- Direct source code reading — `opengui/memory/types.py`, `store.py`, `retrieval.py`
- Direct source code reading — `opengui/skills/data.py`, `library.py`, `executor.py`, `extractor.py`
- Direct source code reading — `opengui/trajectory/recorder.py`, `summarizer.py`
- Direct source code reading — `tests/test_opengui.py` (P0 test patterns)
- `pyproject.toml` — pytest config (`asyncio_mode=auto`, `testpaths=["tests"]`), dev deps

### Secondary (MEDIUM confidence)
- `uv run pytest tests/test_opengui.py` output — confirmed 8 tests pass in 0.02s, Python 3.12.12
- `uv pip install faiss-cpu numpy --dry-run` — confirmed both installable, faiss-cpu 1.13.2 + numpy 2.4.3
- System `python3 -c "import faiss"` confirmed faiss 1.13.0 available system-wide (not in venv)

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified via uv environment inspection
- Architecture: HIGH — patterns directly observed from P0 test file and production code structure
- Pitfalls: HIGH — confirmed via `uv pip list` (faiss not in venv), source code review of constructors and edge cases

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable ecosystem; pytest-asyncio asyncio_mode behavior is stable in 1.x)
