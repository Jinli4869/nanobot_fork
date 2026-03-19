# Phase 6: Fix Integration Wiring - Research

**Researched:** 2026-03-19
**Domain:** Nanobot GUI embedding wiring, desktop packaging metadata, CLI console script packaging
**Confidence:** HIGH (current codebase inspected directly; installed LiteLLM behavior verified locally from `.venv`)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- Do **not** wire `skill_context` into the system prompt; that idea is intentionally dropped
- `GuiSubagentTool` should instantiate `NanobotEmbeddingAdapter` only when `gui.embedding_model` is configured
- The embedding path should reuse nanobot's existing provider chain via `litellm.aembedding(...)`
- If `gui.embedding_model` is not configured, nanobot GUI skill search should degrade gracefully to the current no-embedding behavior
- `pyproject.toml` must add `Pillow>=10.0` to the `desktop` extra and the `dev` extra
- `pyproject.toml` must add `opengui = "opengui.cli:main"` under `[project.scripts]`

### Claude's Discretion

- Exact `litellm.aembedding()` wrapper shape and response normalization
- Whether to log when embeddings are disabled because `gui.embedding_model` is unset
- Whether regression coverage should extend an existing phase test file or live in a dedicated Phase 6 test file

### Deferred / Out of Scope

- New agent-loop behavior beyond the missing wiring
- Any `skill_context` prompt changes
- New GUI capabilities or deeper CLI redesign

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| NANO-03 | Nanobot GUI path supports backend-selected skill search correctly | `GuiSubagentTool` already builds per-platform `SkillLibrary`, but it never instantiates `NanobotEmbeddingAdapter`, so FAISS search is currently unavailable in nanobot runs |
| BACK-03 | Desktop backend imports work after install | `opengui/backends/desktop.py` imports `from PIL import Image` at module import time, but `Pillow` is missing from both `desktop` and `dev` extras in current `pyproject.toml` |
| CLI-01 | CLI has an installable entry point | `opengui/cli.py` and `opengui/__main__.py` already exist, but `[project.scripts]` still only declares `nanobot` |

</phase_requirements>

---

## Summary

Phase 6 is a narrow gap-closure phase, not a new feature phase. All three missing pieces already have nearby implementations:

- `NanobotEmbeddingAdapter` already exists in `nanobot/agent/gui_adapter.py`
- the standalone CLI already exists in `opengui/cli.py`
- the desktop backend already imports and uses `PIL.Image`

The actual gaps are all wiring or packaging metadata:

1. `nanobot/agent/tools/gui.py` sets `self._embedding_adapter = None` unconditionally, so `SkillLibrary(..., embedding_provider=self._embedding_adapter)` always runs BM25-only in the nanobot path
2. `pyproject.toml` does not declare `Pillow` in the `desktop` extra or `dev` extra even though `opengui/backends/desktop.py` imports `PIL` at module import time
3. `pyproject.toml` does not declare `opengui = "opengui.cli:main"` even though the CLI entry point code already exists

The cleanest execution split is a single plan with:

- Wave 0 / Task 1: add regression coverage for the three missing seams
- Wave 1 / Task 2: wire the embedding adapter, extend `GuiConfig`, and fix package metadata in `pyproject.toml`

---

## Current Code Reality

### Embedding Wiring Gap

Direct inspection of `nanobot/agent/tools/gui.py` shows:

- `GuiSubagentTool.__init__()` creates `NanobotLLMAdapter`
- `self._embedding_adapter` is always set to `None`
- `_get_skill_library()` already passes `embedding_provider=self._embedding_adapter`

That means the nanobot path already has the correct constructor seam, but never supplies a real embedding provider.

### Config Gap

`nanobot/config/schema.py` defines:

- `GuiConfig.backend`
- `GuiConfig.adb`
- `GuiConfig.artifacts_dir`
- `GuiConfig.max_steps`
- `GuiConfig.skill_threshold`

There is no `embedding_model` field yet, so the phase's intended configuration knob does not exist.

### Packaging Gaps

Direct inspection of `pyproject.toml` shows:

- `[project.optional-dependencies].desktop` contains `mss`, `pyautogui`, and `pyperclip`, but **not** `Pillow`
- `[project.optional-dependencies].dev` also lacks `Pillow`
- `[project.scripts]` contains only `nanobot = "nanobot.cli.commands:app"`

### Existing CLI / Backend State

- `opengui/cli.py` already exports `main(argv: list[str] | None = None) -> int`
- `opengui/__main__.py` already delegates to that CLI
- `opengui/backends/desktop.py` imports `from PIL import Image` at module import time, so packaging must guarantee `Pillow` is installed when the desktop extra is used

---

## LiteLLM Findings

The installed environment currently has LiteLLM `1.82.4` (verified locally from `.venv`).

Relevant findings from the installed package:

- `litellm.aembedding(*args, **kwargs)` returns `litellm.types.utils.EmbeddingResponse`
- that response has a required `data` field
- each response row exposes an embedding vector that should be normalized into `numpy.ndarray(dtype=numpy.float32)`

**Practical implication:** the embed wrapper in `GuiSubagentTool` should not assume a raw list is returned. It should:

1. await `litellm.aembedding(...)`
2. read `response.data`
3. extract each row's `embedding`
4. return `np.array(vectors, dtype=np.float32)`

For empty `texts`, returning `np.zeros((0, 0), dtype=np.float32)` matches the existing CLI embedding provider pattern and avoids unnecessary network calls.

---

## Provider Reuse Pattern

The nanobot provider passed into `GuiSubagentTool` is not always the same concrete class:

- `LiteLLMProvider` carries `api_key`, `api_base`, `extra_headers`, and internal model resolution helpers
- direct OpenAI-compatible providers such as `CustomProvider` also carry `api_key` / `api_base`

That creates one planning-sensitive nuance:

- chat model resolution in `LiteLLMProvider` may prefix or canonicalize model names before calling LiteLLM

**Recommendation:** the embedding wrapper should read the configured `gui.embedding_model` and:

- pass `api_key` and `api_base` through when available
- pass `extra_headers` when the provider exposes them
- use provider-specific model resolution when available, otherwise pass the configured model verbatim

This keeps the implementation narrow while still respecting gateway/custom endpoint configuration.

If the planner decides not to reuse provider-side model normalization, then `06-CONTEXT.md`'s "embedding model comes from GuiConfig" should be interpreted strictly: users must provide a LiteLLM-ready embedding model string in config.

---

## Recommended Test Shape

The three gaps are small and cross phase boundaries. A dedicated regression file is the cleanest option:

- `tests/test_opengui_p6_wiring.py`

That file should cover:

1. `GuiConfig` accepts `embedding_model` (including camelCase alias behavior)
2. `GuiSubagentTool` instantiates `NanobotEmbeddingAdapter` when `embedding_model` is configured
3. `GuiSubagentTool` leaves `_embedding_adapter` as `None` when `embedding_model` is absent
4. `SkillLibrary` receives the embedding adapter instance when configured
5. `pyproject.toml` declares `Pillow>=10.0` in both `desktop` and `dev`
6. `pyproject.toml` declares `opengui = "opengui.cli:main"` in `[project.scripts]`

This is better than scattering assertions across existing Phase 3 / 4 / 5 files because Phase 6 is explicitly a gap-closure pass across those earlier deliverables.

Still, the implementation task should read the existing tests for patterns:

- `tests/test_opengui_p3_nanobot.py`
- `tests/test_opengui_p4_desktop.py`
- `tests/test_opengui_p5_cli.py`

---

## Architecture Patterns

### Pattern 1: Keep the Fix Local to Nanobot Wiring

`NanobotEmbeddingAdapter` already exists. The phase should instantiate it inside `GuiSubagentTool` instead of introducing a new shared adapter layer.

### Pattern 2: Preserve Graceful Fallback

If `gui.embedding_model` is missing, nanobot GUI runs should keep the current behavior:

- `self._embedding_adapter = None`
- `SkillLibrary(..., embedding_provider=None, ...)`

That keeps FAISS search opt-in and avoids breaking existing configurations.

### Pattern 3: Match Existing `numpy.float32` Behavior

`opengui/cli.py` already normalizes embedding vectors into `np.ndarray(dtype=np.float32)`. The nanobot embedding wrapper should match that representation so `MemoryRetriever` / `SkillLibrary` work consistently.

### Pattern 4: Treat Packaging Metadata as Product Code

Both packaging fixes are user-visible behavior:

- missing `Pillow` breaks `pip install .[desktop]`
- missing `opengui` script prevents the CLI from being invoked as an installed command

They need automated regression coverage instead of a one-off manual edit.

---

## Common Pitfalls

### Pitfall 1: Forgetting `extra_headers`

Some gateway configurations rely on provider-specific headers. If the embedding wrapper calls LiteLLM with only `api_key` and `api_base`, those requests can diverge from the chat path.

### Pitfall 2: Assuming `aembedding()` Returns a Raw List

The installed LiteLLM version returns an `EmbeddingResponse` object, not a bare list. The wrapper must extract `response.data[*].embedding`.

### Pitfall 3: Scattering Regressions Across Old Phase Test Files

That makes the gap-closure intent harder to verify. A focused Phase 6 regression file keeps the contract visible and makes the quick verification command obvious.

### Pitfall 4: Treating `Pillow` as Transitive

Current code imports `PIL` directly. Depending on some other package to happen to install `Pillow` is not acceptable for this phase.

---

## Recommended Plan Split

### Plan 06-01

Ship the full Phase 6 gap-closure in one execute plan with two tasks:

- Task 1: add Phase 6 regression coverage (`tests/test_opengui_p6_wiring.py`)
- Task 2: implement `GuiConfig.embedding_model`, wire `NanobotEmbeddingAdapter`, and update `pyproject.toml`

This phase is too small to benefit from multiple plans or multiple waves beyond RED/GREEN.

---

## Validation Architecture

### Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py -x -q` |
| Full suite command | `PATH="$(pwd)/.venv/bin:$PATH" ./.venv/bin/python -m pytest tests/ -x -q` |
| Estimated runtime | ~10 seconds |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NANO-03 | `GuiConfig` exposes `embedding_model` with alias support | unit | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_gui_config_accepts_embedding_model_alias -x -q` | ❌ Wave 0 |
| NANO-03 | `GuiSubagentTool` creates `NanobotEmbeddingAdapter` when embedding config is present | unit | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_gui_tool_wires_embedding_adapter_when_configured -x -q` | ❌ Wave 0 |
| NANO-03 | `GuiSubagentTool` keeps `embedding_provider=None` when embedding config is absent | unit | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_gui_tool_skips_embedding_adapter_without_config -x -q` | ❌ Wave 0 |
| BACK-03 | `pyproject.toml` declares `Pillow>=10.0` in desktop and dev extras | packaging | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_pyproject_declares_pillow_for_desktop_and_dev -x -q` | ❌ Wave 0 |
| CLI-01 | `pyproject.toml` declares `opengui = "opengui.cli:main"` | packaging | `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py::test_pyproject_declares_opengui_console_script -x -q` | ❌ Wave 0 |

### Manual-Only Verifications

| Behavior | Requirement | Why manual | Test instructions |
|----------|-------------|------------|-------------------|
| `pip install .[desktop]` succeeds and `python -c "from PIL import Image"` exits 0 | BACK-03 | Requires an actual install transaction in the target environment | Create a clean virtualenv, run `pip install .[desktop]`, then run the import check |
| installed `opengui --help` resolves the console script entry point | CLI-01 | Requires package installation to validate generated wrapper scripts | Install the package into a clean virtualenv and run `opengui --help` |

### Sampling Rate

- After every task commit: `./.venv/bin/python -m pytest tests/test_opengui_p6_wiring.py -x -q`
- After the plan wave: `PATH="$(pwd)/.venv/bin:$PATH" ./.venv/bin/python -m pytest tests/ -x -q`
- Before verification: the full suite must be green

### Wave 0 Gaps

- [ ] `tests/test_opengui_p6_wiring.py` for config, embedding wiring, and packaging metadata
- [ ] `GuiConfig.embedding_model` field
- [ ] `GuiSubagentTool` embedding wrapper around `litellm.aembedding`
- [ ] `pyproject.toml` desktop/dev/script metadata fixes

---

## Sources

Local code and installed-package sources inspected:

- `nanobot/agent/tools/gui.py`
- `nanobot/agent/gui_adapter.py`
- `nanobot/config/schema.py`
- `nanobot/providers/base.py`
- `nanobot/providers/litellm_provider.py`
- `nanobot/providers/custom_provider.py`
- `opengui/backends/desktop.py`
- `opengui/cli.py`
- `pyproject.toml`
- `tests/test_opengui_p3_nanobot.py`
- `tests/test_opengui_p4_desktop.py`
- `tests/test_opengui_p5_cli.py`
- `.venv/lib/python3.12/site-packages/litellm/utils.py` (`aembedding`)
- `.venv` installed package metadata for LiteLLM version `1.82.4`
