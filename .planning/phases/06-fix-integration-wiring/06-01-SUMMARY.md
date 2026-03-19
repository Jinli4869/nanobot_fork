---
phase: 06-fix-integration-wiring
plan: "01"
subsystem: nanobot-gui-wiring
tags: [embedding, config, packaging, tdd]
dependency_graph:
  requires:
    - "03-01: GuiSubagentTool, NanobotLLMAdapter, NanobotEmbeddingAdapter"
    - "04-01: LocalDesktopBackend (Pillow dependency identified)"
    - "05-01: opengui CLI (entry point identified)"
  provides:
    - "GuiConfig.embedding_model field (NANO-03, BACK-03, CLI-01)"
    - "NanobotEmbeddingAdapter wiring in GuiSubagentTool via litellm.aembedding"
    - "Pillow>=10.0 in desktop and dev extras"
    - "opengui = opengui.cli:main console script"
  affects:
    - "nanobot/config/schema.py"
    - "nanobot/agent/tools/gui.py"
    - "pyproject.toml"
tech_stack:
  added: []
  patterns:
    - "litellm.aembedding for embedding calls with provider credential forwarding"
    - "TDD RED/GREEN with self-contained Phase 6 regression test file"
    - "Conditional adapter construction: embedding_adapter = build() if config.embedding_model else None"
key_files:
  created:
    - tests/test_opengui_p6_wiring.py
  modified:
    - nanobot/config/schema.py
    - nanobot/agent/tools/gui.py
    - pyproject.toml
decisions:
  - "litellm.aembedding called with provider credentials forwarded (api_key, api_base, extra_headers) only when truthy — avoids sending empty strings that some backends reject"
  - "Model name resolved via provider._resolve_model() when present and callable; falls back to raw model string for simpler provider stubs"
  - "embedding_adapter is built at __init__ time, not lazily — deterministic ownership and no race conditions in async execute() calls"
metrics:
  duration: "~3 min"
  completed: "2026-03-19"
  tasks: 2
  files: 4
---

# Phase 6 Plan 1: Fix Integration Wiring Summary

**One-liner:** Closed three broken cross-phase wiring seams — GuiConfig.embedding_model field, NanobotEmbeddingAdapter→SkillLibrary wiring via litellm.aembedding, and pyproject.toml metadata (Pillow + opengui script).

## Objective

Close integration gaps left after Phases 3-5 without reopening prior scope:
1. Expose `GuiConfig.embedding_model` with camelCase alias support
2. Wire `NanobotEmbeddingAdapter` in `GuiSubagentTool` for embedding-backed skill search
3. Declare `Pillow>=10.0` in `desktop` and `dev` extras
4. Add `opengui = "opengui.cli:main"` console script

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add Phase 6 regression coverage (TDD RED) | 36a24a3 | tests/test_opengui_p6_wiring.py |
| 2 | Implement wiring and metadata fixes (TDD GREEN) | 4575db8 | nanobot/config/schema.py, nanobot/agent/tools/gui.py, pyproject.toml |

## Key Changes

### nanobot/config/schema.py
Added `embedding_model: str | None = None` to `GuiConfig`. The existing `Base` model alias generator (`to_camel`) automatically provides the `embeddingModel` camelCase alias so both naming conventions work transparently.

### nanobot/agent/tools/gui.py
- Added imports: `litellm`, `numpy as np`, `NanobotEmbeddingAdapter`, `Callable`, `Awaitable`
- Replaced unconditional `self._embedding_adapter = None` with conditional instantiation via `_build_embedding_adapter()`
- `_build_embedding_adapter()` creates an async `_embed` closure that:
  - Returns `np.zeros((0, 0), dtype=np.float32)` for empty input
  - Resolves model name via `provider._resolve_model()` when available
  - Calls `litellm.aembedding()` with provider credentials forwarded
  - Normalises response into `np.array(vectors, dtype=np.float32)`
  - Wraps the closure with `NanobotEmbeddingAdapter`
- When `embedding_model` is absent, `_embedding_adapter` stays `None` — `SkillLibrary` still creates successfully with `embedding_provider=None`

### pyproject.toml
- `Pillow>=10.0` added to both `[project.optional-dependencies].desktop` and `dev`
- `opengui = "opengui.cli:main"` added to `[project.scripts]`

## Verification

```
599 passed, 7 warnings in 17.69s
```

All 599 tests pass including the 5 new Phase 6 regression tests.

## Deviations from Plan

None — plan executed exactly as written. The `_resolve_model` guard (`callable(resolve)`) was an implementation detail within discretionary scope noted in CONTEXT.md.

## Self-Check: PASSED

- `tests/test_opengui_p6_wiring.py` exists: FOUND
- `nanobot/config/schema.py` has `embedding_model: str | None = None`: FOUND (line 168)
- `nanobot/agent/tools/gui.py` imports and uses `NanobotEmbeddingAdapter`: FOUND
- `pyproject.toml` has 2x `Pillow>=10.0` and `opengui` script: FOUND
- Commits `36a24a3` and `4575db8`: FOUND in git log
