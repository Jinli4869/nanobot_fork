# Phase 6: Fix Integration Wiring - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Close 3 broken cross-phase wiring issues identified in the milestone audit: instantiate NanobotEmbeddingAdapter so FAISS skill search works, declare missing Pillow dependency in desktop extras, and add opengui CLI console script entry point to pyproject.toml.

**Not in scope:** New agent capabilities, skill_context in system prompt (discussed and dropped — LLM only needs per-step valid_state checks and parameter grounding, not a global skills overview), agent loop changes.

</domain>

<decisions>
## Implementation Decisions

### Dropped: skill_context in system prompt
- `build_system_prompt()` already accepts `skill_context` param but it will NOT be wired
- Reasoning: skill execution is code-driven (SkillLibrary search → threshold check → SkillExecutor), the LLM's role is limited to per-step valid_state verification and dynamic coordinate grounding — neither requires knowing the full available skills list
- The `skill_context` param stays in `build_system_prompt()` as a dormant hook; no code changes needed
- AGENT-05 and SKILL-08 are satisfied by the existing code-level skill matching in `agent.py:run()`

### Embedding adapter wiring
- Use nanobot's existing LLM provider chain via `litellm.aembedding()` to create the embed function
- Embedding model name comes from GuiConfig (e.g. `gui.embedding_model` field)
- `GuiSubagentTool.__init__` creates `NanobotEmbeddingAdapter(embed_fn)` where `embed_fn` wraps `litellm.aembedding(model=config_model, input=texts)` and returns `np.ndarray`
- **Optional with graceful fallback**: if `gui.embedding_model` is not set in config, `self._embedding_adapter` stays `None` — SkillLibrary is still created but without FAISS embedding search (BM25-only or disabled). Consistent with Phase 5 CLI pattern where embedding is opt-in
- When embedding IS configured, `_get_skill_library()` passes the adapter as `embedding_provider`

### Pillow dependency
- Add `"Pillow>=10.0"` to `[project.optional-dependencies] desktop` in pyproject.toml
- Also add to the `dev` extras so CI tests can import PIL
- Desktop backend (`opengui/backends/desktop.py`) uses PIL for screenshot processing via mss

### CLI console script entry point
- Add `opengui = "opengui.cli:main"` to `[project.scripts]` in pyproject.toml
- Enables `opengui "Open Settings"` after `pip install` instead of `python -m opengui.cli`

### Claude's Discretion
- Exact `litellm.aembedding()` wrapper implementation details (error handling, dimension validation)
- GuiConfig field naming for embedding model (`embedding_model` recommended)
- Pillow version pin (>=10.0 recommended, match mss version era)
- Whether to add a log message when embedding is unavailable

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Embedding adapter
- `nanobot/agent/gui_adapter.py` — NanobotEmbeddingAdapter class (takes `embed_fn: Callable[[list[str]], Awaitable[np.ndarray]]`)
- `nanobot/agent/tools/gui.py` — GuiSubagentTool with `self._embedding_adapter = None` at line 41 (the fix target)
- `nanobot/config/schema.py` — GuiConfig Pydantic model (add embedding_model field here)
- `opengui/interfaces.py` — EmbeddingProvider protocol definition

### Skill library wiring
- `opengui/skills/library.py` — SkillLibrary constructor takes `embedding_provider` param
- `opengui/memory/retriever.py` — MemoryRetriever also takes embedding_provider (same pattern)

### Dependencies and entry point
- `pyproject.toml` — `[project.optional-dependencies] desktop` (line 67-71) and `[project.scripts]` (line 84-85)
- `opengui/cli.py` — CLI module with `main()` function
- `opengui/backends/desktop.py` — Uses `from PIL import Image` for screenshots

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `NanobotEmbeddingAdapter` in `gui_adapter.py`: Already implemented, just needs to be instantiated with a real embed_fn
- `litellm.aembedding()`: Available in nanobot's dependency chain, returns embedding vectors
- `GuiConfig` Pydantic model: Existing schema for GUI configuration, just needs embedding_model field

### Established Patterns
- Phase 5 CLI: embedding is opt-in via config — if embedding config present, enable FAISS features; if absent, run without
- GuiSubagentTool already builds NanobotLLMAdapter in `__init__` — embedding adapter follows same pattern
- Protocol-based interfaces: EmbeddingProvider protocol with `async embed(texts) -> np.ndarray`

### Integration Points
- `GuiSubagentTool.__init__()`: Create NanobotEmbeddingAdapter when embedding_model configured
- `GuiConfig`: Add `embedding_model: str | None = None` field
- `_get_skill_library()`: Already passes `self._embedding_adapter` — just needs it to be non-None
- `pyproject.toml`: Two edits — desktop extras + scripts section

</code_context>

<specifics>
## Specific Ideas

- The embed_fn wrapper should normalize litellm's response format to a plain np.ndarray since different embedding APIs return different shapes
- Graceful fallback matches the project philosophy: "opengui as zero-dependency GUI engine" — embedding is a power feature, not a requirement

</specifics>

<deferred>
## Deferred Ideas

- skill_context in system prompt — intentionally dropped, not deferred. Could revisit if a use case emerges where LLM awareness of available skills improves free exploration quality
- Embedding model auto-detection from nanobot's main LLM config — keep explicit for now

</deferred>

---

*Phase: 06-fix-integration-wiring*
*Context gathered: 2026-03-19*
