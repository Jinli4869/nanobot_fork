---
phase: 01-p1-unit-tests
plan: 01
subsystem: testing
tags: [faiss-cpu, numpy, bm25, memory, pytest, unit-tests]

# Dependency graph
requires: []
provides:
  - faiss-cpu and numpy in pyproject.toml main dependencies (unblocks all memory module imports in tests)
  - 13 passing unit tests covering MemoryStore JSON persistence, MemoryEntry serialization, MemoryRetriever BM25+FAISS hybrid search
affects: [02-p1-skills-tests, 03-p1-trajectory-tests]

# Tech tracking
tech-stack:
  added: [faiss-cpu>=1.9.0, numpy>=1.26.0]
  patterns: [_FakeEmbedder deterministic unit-vector embedder pattern for FAISS test isolation]

key-files:
  created:
    - tests/test_opengui_p1_memory.py
  modified:
    - pyproject.toml

key-decisions:
  - "faiss-cpu and numpy added to main [project.dependencies], not dev-only — retrieval.py imports numpy at module top-level and calls faiss at runtime making them production requirements"
  - "_FakeEmbedder uses hash-to-slot unit vectors: each unique text maps to a distinct dimension so FAISS ranking is deterministic without a real embedding API"

patterns-established:
  - "FakeEmbedder pattern: async def embed(texts) -> np.ndarray returning hash-derived unit float32 vectors for deterministic FAISS testing"
  - "tmp_path isolation: every MemoryStore test uses pytest tmp_path fixture for independent JSON file paths"
  - "asyncio_mode=auto: async test functions need no decorator — pytest-asyncio picks them up automatically"

requirements-completed: [TEST-02]

# Metrics
duration: 12min
completed: 2026-03-17
---

# Phase 1 Plan 01: Memory Module Dependencies and Unit Tests Summary

**faiss-cpu and numpy added to production deps; 13 unit tests covering MemoryStore JSON persistence, MemoryEntry round-trip serialization, and MemoryRetriever hybrid BM25+FAISS search**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-03-17T00:00:00Z
- **Completed:** 2026-03-17
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `faiss-cpu>=1.9.0` and `numpy>=1.26.0` to main project dependencies (not dev-only) since `opengui.memory.retrieval` and `opengui.skills.library` import both at module load time
- Verified both packages are importable via `uv run python -c "import faiss; import numpy"` after `uv sync`
- All 8 pre-existing P0 tests continue to pass
- Created `tests/test_opengui_p1_memory.py` with 13 passing tests covering the full memory module API surface

## Task Commits

1. **Task 1: Add faiss-cpu and numpy to dependencies** - `d316fdc` (chore)
2. **Task 2: Write memory module unit tests (TEST-02)** - `46c062d` (test)

## Files Created/Modified

- `pyproject.toml` - Added faiss-cpu>=1.9.0 and numpy>=1.26.0 to [project.dependencies]
- `tests/test_opengui_p1_memory.py` - 13 unit tests: MemoryEntry round-trip, MemoryStore CRUD+persistence, MemoryRetriever hybrid/BM25-only/FAISS-only search, format_context

## Decisions Made

- **faiss-cpu in main deps not dev extras:** `retrieval.py` imports numpy at top-level and calls faiss at runtime — these are not test-only requirements. Adding to `[project.dependencies]` ensures production installs also work.
- **_FakeEmbedder design:** Uses `hash(text) % DIM` to map each unique text to a distinct unit-vector slot. This makes FAISS ranking deterministic without a real embedding API and avoids any network call.
- **faiss-cpu version pinned at >=1.9.0:** The plan specified >=1.13.0 but the latest available release on PyPI is 1.9.0.x; used >=1.9.0 to pick up the available package.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Version] faiss-cpu version spec adjusted from >=1.13.0 to >=1.9.0**
- **Found during:** Task 1 (dependency sync)
- **Issue:** Plan specified `faiss-cpu>=1.13.0` but PyPI only has releases up to 1.9.x; uv resolved to the latest available 1.9.x wheel
- **Fix:** Used `faiss-cpu>=1.9.0` constraint which matches available releases and installs correctly
- **Files modified:** pyproject.toml
- **Verification:** `uv run python -c "import faiss; import numpy; print('OK')"`
- **Committed in:** d316fdc (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (version spec adjustment)
**Impact on plan:** Necessary correction — no 1.13.x release exists on PyPI. The installed 1.9.x release satisfies all test requirements.

## Issues Encountered

- `uv sync --extra dev` failed to build `python-olm` (matrix-nio e2e extra) due to missing cmake/gmake on this machine. This is a pre-existing issue unrelated to this plan. faiss-cpu and numpy installed successfully; the failure came from an unrelated native build. Verified by running `uv run python -c "import faiss; import numpy"` directly.
- `tests/test_matrix_channel.py` collection fails when running `pytest tests/` due to the same missing matrix optional dep. Both issues are pre-existing and out of scope — deferred to `deferred-items.md`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- faiss-cpu and numpy are now in the environment, unblocking all subsequent test plans that import the memory module
- `tests/test_opengui_p1_memory.py` provides regression coverage for the memory subsystem
- Next plan (01-02) can proceed to skills module tests without re-verifying FAISS availability

---
*Phase: 01-p1-unit-tests*
*Completed: 2026-03-17*

## Self-Check: PASSED

- FOUND: tests/test_opengui_p1_memory.py
- FOUND: .planning/phases/01-p1-unit-tests/01-01-SUMMARY.md
- FOUND commit d316fdc (chore: faiss-cpu and numpy deps)
- FOUND commit 46c062d (test: memory module unit tests)
- 13 memory tests pass, 21 combined tests pass
- STATE.md updated (progress 33%, 2 decisions recorded)
- ROADMAP.md updated (phase 1: 1/3 summaries, In Progress)
- REQUIREMENTS.md: TEST-02 marked complete
