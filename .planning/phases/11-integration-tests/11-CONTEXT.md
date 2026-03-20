# Phase 11: Integration & Tests - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire `--background` flag into the standalone CLI and nanobot's `GuiConfig`, plus a full CI-safe test suite with mocked display managers. This phase connects the Phase 9 virtual display protocol and Phase 10 background backend wrapper to both entry points (CLI and nanobot). No new backend or display logic is created — only integration wiring and tests.

</domain>

<decisions>
## Implementation Decisions

### CLI flag design
- `--background` flag added to argparse. Only valid with `--backend local` (or default backend); error via `parser.error()` if combined with `adb` or `dry-run`
- `--background` implies `--backend local` automatically — user doesn't need to specify both
- Additional flags: `--display-num`, `--width`, `--height` override config.yaml values
- Default resolution: 1280x720 when no explicit size given
- CLI flags take precedence over config.yaml values

### CLI build_backend wrapping
- `build_backend()` returns raw `LocalDesktopBackend` as before
- `run_cli()` wraps it in `BackgroundDesktopBackend(inner, XvfbDisplayManager(...))` when `--background` is set
- Lifecycle managed via `async with` in `run_cli()` — display starts before agent.run(), shuts down after

### GuiConfig schema (nanobot)
- Flat fields on existing `GuiConfig` Pydantic model: `background: bool = False`, `display_num: int | None = None`, `display_width: int = 1280`, `display_height: int = 720`
- Pydantic `model_validator` rejects `background=true` with `backend != 'local'` at config load time
- `_build_backend` in `GuiSubagentTool` creates raw `LocalDesktopBackend`; wrapping happens in `execute()` via `async with BackgroundDesktopBackend(...)` — one virtual display per run, clean lifecycle

### Platform compatibility
- On non-Linux platforms (macOS, Windows), `--background` is accepted but logs a warning and falls back to foreground mode (no Xvfb available). Graceful degradation, not an error
- Same fallback behavior in nanobot path: if `background=true` and platform is not Linux, log warning and skip wrapping

### Test strategy
- CLI background tests extend `tests/test_opengui_p5_cli.py`
- Nanobot background tests extend existing nanobot GUI test files
- Mock `XvfbDisplayManager` with `NoOpDisplayManager` or a mock — do NOT mock at `asyncio.subprocess` boundary
- Both unit tests (build_backend wrapping logic, config parsing, validation) and integration tests (full `run_cli` path with `--background` and mock agent)
- All tests must pass in CI without a real Xvfb binary
- Existing v1.0 and v1.1 test suite must not regress

### Claude's Discretion
- Exact CliConfig dataclass field naming for background settings (background_display_num vs display_num etc.)
- How config.yaml background section is structured
- Integration test mock patterns for GuiAgent (DryRunBackend + mock LLM)
- Log message wording for platform fallback warning

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — INTG-01 through INTG-04 and TEST-V11-01 define the five deliverables for this phase

### Roadmap
- `.planning/ROADMAP.md` — Phase 11 success criteria (4 items), dependency on Phase 10

### Phase 9 & 10 context (predecessors)
- `.planning/phases/09-virtual-display-protocol/09-CONTEXT.md` — VirtualDisplayManager protocol decisions, DisplayInfo fields, XvfbDisplayManager error handling
- `.planning/phases/10-background-backend-wrapper/10-CONTEXT.md` — BackgroundDesktopBackend lifecycle, DISPLAY env isolation, idempotent shutdown, async context manager

### Existing code (integration targets)
- `opengui/cli.py` — Standalone CLI entry point: `parse_args()`, `build_backend()`, `run_cli()`, `CliConfig` dataclass
- `nanobot/agent/tools/gui.py` — `GuiSubagentTool`: `_build_backend()`, `execute()`, constructor
- `nanobot/config/schema.py` — `GuiConfig` Pydantic model (line 160): current fields to extend
- `opengui/backends/background.py` — `BackgroundDesktopBackend` implementation to wire into both paths
- `opengui/backends/virtual_display.py` — `VirtualDisplayManager`, `DisplayInfo`, `NoOpDisplayManager`
- `opengui/backends/displays/xvfb.py` — `XvfbDisplayManager` to instantiate from CLI/nanobot config

### Existing tests (extend these)
- `tests/test_opengui_p5_cli.py` — CLI test file to extend with --background tests
- `tests/test_opengui_p4_desktop.py` — Desktop backend tests (reference for mock patterns)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `NoOpDisplayManager` from `opengui.backends.virtual_display`: Perfect mock replacement for `XvfbDisplayManager` in tests
- `DryRunBackend` from `opengui.backends.dry_run`: Usable as inner backend for integration tests
- `OpenAICompatibleLLMProvider` / `OpenAICompatibleEmbeddingProvider` in `cli.py`: Already handles provider bridging
- `BackgroundDesktopBackend` supports `async with` — cleanest pattern for both CLI and nanobot wrapping

### Established Patterns
- `GuiConfig` uses Pydantic `BaseModel` with `Field(default_factory=...)` for nested configs
- `_build_backend()` in `gui.py` uses lazy imports per backend type
- `build_backend()` in `cli.py` uses conditional imports (LocalDesktopBackend lazy-loaded)
- CLI tests in `test_opengui_p5_cli.py` test `parse_args()` and `build_backend()` as separate units
- Phase 10 tests use `try/finally` with original-value save for DISPLAY env

### Integration Points
- `run_cli()` in `cli.py` (line 308): After `build_backend()`, wrap result when `--background` active
- `GuiSubagentTool.execute()` in `gui.py` (line 81): Wrap active_backend in `async with BackgroundDesktopBackend(...)` when background config is set
- `GuiConfig` in `schema.py` (line 160): Add background fields + model_validator
- `parse_args()` in `cli.py` (line 177): Add `--background`, `--display-num`, `--width`, `--height` flags + validation

</code_context>

<specifics>
## Specific Ideas

- `--background` alone should "just work" — `python -m opengui.cli --background --task "Open Settings"` with zero additional config
- Platform fallback: log message should mention that Xvfb is Linux-only and suggest running on Linux for background mode
- Pydantic validation error should clearly say "background mode requires backend='local'" — not a generic validation failure

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 11-integration-tests*
*Context gathered: 2026-03-20*
