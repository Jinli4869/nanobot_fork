# Phase 11: Integration & Tests - Research

**Researched:** 2026-03-20
**Domain:** Python argparse / Pydantic v2 integration wiring + pytest-asyncio mocking
**Confidence:** HIGH

## Summary

Phase 11 is pure integration and test wiring work. No new backend or display logic is invented — the task is to connect `BackgroundDesktopBackend` + `XvfbDisplayManager` (built in Phases 9–10) into two entry points: the standalone CLI (`opengui/cli.py`) and nanobot's `GuiSubagentTool` (`nanobot/agent/tools/gui.py` + `nanobot/config/schema.py`). The fifth deliverable is a CI-safe test suite covering all new code paths.

The codebase is well-structured for this work. All integration points are already identified: `parse_args()` / `run_cli()` in cli.py, `GuiConfig` in schema.py, and `GuiSubagentTool._build_backend()` / `execute()` in gui.py. The Phase 10 test file (`test_opengui_p10_background.py`) establishes the mock helper and try/finally DISPLAY patterns that must be reused. The existing test suite runs 663 tests with 1 pre-existing unrelated failure; regressions in this suite are the acceptance gate.

**Primary recommendation:** Extend existing files rather than creating new ones — add to `test_opengui_p5_cli.py` for CLI, create `test_opengui_p11_integration.py` for nanobot/GuiConfig coverage. Use `NoOpDisplayManager` (already in `opengui.backends.virtual_display`) as the universal test mock; never use `XvfbDisplayManager` in tests.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**CLI flag design**
- `--background` flag added to argparse. Only valid with `--backend local` (or default backend); error via `parser.error()` if combined with `adb` or `dry-run`
- `--background` implies `--backend local` automatically — user doesn't need to specify both
- Additional flags: `--display-num`, `--width`, `--height` override config.yaml values
- Default resolution: 1280x720 when no explicit size given
- CLI flags take precedence over config.yaml values

**CLI build_backend wrapping**
- `build_backend()` returns raw `LocalDesktopBackend` as before
- `run_cli()` wraps it in `BackgroundDesktopBackend(inner, XvfbDisplayManager(...))` when `--background` is set
- Lifecycle managed via `async with` in `run_cli()` — display starts before agent.run(), shuts down after

**GuiConfig schema (nanobot)**
- Flat fields on existing `GuiConfig` Pydantic model: `background: bool = False`, `display_num: int | None = None`, `display_width: int = 1280`, `display_height: int = 720`
- Pydantic `model_validator` rejects `background=true` with `backend != 'local'` at config load time
- `_build_backend` in `GuiSubagentTool` creates raw `LocalDesktopBackend`; wrapping happens in `execute()` via `async with BackgroundDesktopBackend(...)` — one virtual display per run, clean lifecycle

**Platform compatibility**
- On non-Linux platforms (macOS, Windows), `--background` is accepted but logs a warning and falls back to foreground mode (no Xvfb available). Graceful degradation, not an error
- Same fallback behavior in nanobot path: if `background=true` and platform is not Linux, log warning and skip wrapping

**Test strategy**
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

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INTG-01 | CLI `--background` flag with `display_num`, `width`, `height` config | `parse_args()` needs 4 new args; `CliConfig` dataclass needs background fields; `run_cli()` wraps backend in `async with BackgroundDesktopBackend` |
| INTG-02 | `GuiConfig.background` fields in nanobot config schema | Flat Pydantic fields on `GuiConfig`; `model_validator` for backend=local constraint; camelCase aliases via existing `to_camel` alias_generator |
| INTG-03 | `build_backend` wraps `LocalDesktopBackend` when background=true (CLI path) | Wrapping happens in `run_cli()`, not `build_backend()`. `XvfbDisplayManager` instantiated from CLI args; `async with BackgroundDesktopBackend` manages lifecycle |
| INTG-04 | `_build_backend` wraps `LocalDesktopBackend` when background=true (nanobot path) | Wrapping in `execute()` via `async with BackgroundDesktopBackend`; `_build_backend()` still returns raw `LocalDesktopBackend`; platform guard with `sys.platform` |
| TEST-V11-01 | Full test suite with mocked subprocess (no real Xvfb in CI) | `NoOpDisplayManager` as universal mock; `monkeypatch` for `BackgroundDesktopBackend` and `XvfbDisplayManager`; 663 existing tests must stay green |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| argparse | stdlib | CLI flag parsing | Already used in `cli.py`; no new dependency |
| Pydantic v2 | `>=2.12.0` | Schema validation + model_validator | Already the project schema library; `GuiConfig` is a Pydantic `BaseModel` subclass |
| pytest-asyncio | `>=1.3.0` | Async test runner | Already configured with `asyncio_mode = "auto"` |
| unittest.mock | stdlib | AsyncMock, MagicMock, patch | Pattern established in Phase 9/10 tests |
| sys | stdlib | `sys.platform` check for Linux guard | Standard; no alternative needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| NoOpDisplayManager | project | Mock VirtualDisplayManager in tests | All background-related tests in Phase 11 |
| BackgroundDesktopBackend | project | The wrapper being integrated | Imported in `cli.py` and `gui.py` when `--background` is active |
| XvfbDisplayManager | project | Real Xvfb manager to instantiate in production code | Only in CLI/nanobot production paths; never in tests |

**No new external dependencies are required for this phase.**

## Architecture Patterns

### Recommended Project Structure
```
opengui/
├── cli.py                          # Add --background flags to parse_args(), CliConfig, run_cli()
├── backends/
│   ├── background.py               # Unchanged (Phase 10)
│   ├── virtual_display.py          # Unchanged (Phase 9)
│   └── displays/
│       └── xvfb.py                 # Unchanged (Phase 9)
nanobot/
├── config/
│   └── schema.py                   # Extend GuiConfig with 4 background fields + model_validator
└── agent/
    └── tools/
        └── gui.py                  # Extend execute() with background wrapping
tests/
├── test_opengui_p5_cli.py          # Extend with --background CLI tests
└── test_opengui_p11_integration.py # New file: GuiConfig schema + nanobot execute() tests
```

### Pattern 1: CLI argparse + CliConfig extension

**What:** Add 4 new argparse flags; add corresponding fields to `CliConfig` dataclass; in `run_cli()` construct `XvfbDisplayManager` from CLI args and wrap backend in `async with BackgroundDesktopBackend`.

**When to use:** The CLI path. `build_backend()` must remain unchanged (returns raw `LocalDesktopBackend`).

**Example:**
```python
# In parse_args():
parser.add_argument("--background", action="store_true", help="Run on virtual Xvfb display (Linux only)")
parser.add_argument("--display-num", type=int, default=None, help="Xvfb display number (default: 99)")
parser.add_argument("--width", type=int, default=None, help="Display width (default: 1280)")
parser.add_argument("--height", type=int, default=None, help="Display height (default: 720)")

# Post-parse validation (in parse_args() or resolve_backend_name()):
if args.background and args.backend in ("adb", "dry-run"):
    parser.error("--background requires --backend local (or omit --backend)")
# --background implies --backend local:
if args.background:
    args.backend = "local"
```

```python
# CliConfig additions (new fields in the dataclass):
@dataclass(slots=True)
class BackgroundConfig:
    display_num: int = 99
    width: int = 1280
    height: int = 720

@dataclass(slots=True)
class CliConfig:
    provider: ProviderConfig
    # ... existing fields ...
    background: bool = False
    background_config: BackgroundConfig = field(default_factory=BackgroundConfig)
```

```python
# run_cli() wrapping pattern:
async def run_cli(args: argparse.Namespace) -> AgentResult:
    # ... existing code ...
    backend = build_backend(resolve_backend_name(args), config)

    if getattr(args, "background", False):
        import sys
        if sys.platform != "linux":
            import logging
            logging.getLogger(__name__).warning(
                "Background mode (Xvfb) is Linux-only; running in foreground on %s", sys.platform
            )
        else:
            from opengui.backends.background import BackgroundDesktopBackend
            from opengui.backends.displays.xvfb import XvfbDisplayManager
            display_num = args.display_num or 99
            width = args.width or 1280
            height = args.height or 720
            mgr = XvfbDisplayManager(display_num=display_num, width=width, height=height)
            backend = BackgroundDesktopBackend(backend, mgr)
            async with backend:
                return await _run_agent(args, config, backend, provider, ...)
    return await _run_agent(args, config, backend, provider, ...)
```

**CRITICAL wrapping concern:** `run_cli()` currently calls `agent.run(task)` at the bottom after assembling all components. The `async with BackgroundDesktopBackend` context must wrap around the `agent.run()` call. The cleanest pattern is to restructure `run_cli()` to extract `_run_agent()` helper, OR inline the `async with` block where `agent.run()` is called. See "Anti-Patterns to Avoid" below.

### Pattern 2: Pydantic model_validator for GuiConfig

**What:** Add 4 flat fields to `GuiConfig` and a `model_validator(mode='after')` that enforces `background=True` requires `backend='local'`.

**When to use:** The nanobot config path. Validation runs at YAML-load time, not at `execute()` time.

**Example:**
```python
# Source: Pydantic v2 model_validator docs
from pydantic import model_validator

class GuiConfig(Base):
    """GUI subagent configuration."""
    backend: Literal["adb", "local", "dry-run"] = "adb"
    adb: AdbConfig = Field(default_factory=AdbConfig)
    artifacts_dir: str = "gui_runs"
    max_steps: int = 15
    skill_threshold: float = 0.6
    embedding_model: str | None = None
    # New Phase 11 fields:
    background: bool = False
    display_num: int | None = None
    display_width: int = 1280
    display_height: int = 720

    @model_validator(mode='after')
    def _validate_background_requires_local(self) -> "GuiConfig":
        if self.background and self.backend != "local":
            raise ValueError(
                f"background mode requires backend='local', got backend={self.backend!r}"
            )
        return self
```

**Key detail:** `GuiConfig` inherits from `Base` which has `alias_generator=to_camel`. The new fields (`display_num`, `display_width`, `display_height`) will automatically accept `displayNum`, `displayWidth`, `displayHeight` in YAML/JSON. No extra `Field(alias=...)` needed.

### Pattern 3: GuiSubagentTool.execute() wrapping

**What:** In `execute()`, after `active_backend = self._select_backend(backend)`, conditionally wrap in `BackgroundDesktopBackend` when `self._gui_config.background` is true and platform is Linux.

**When to use:** The nanobot path. One virtual display per `execute()` call; clean lifecycle via `async with`.

**Example:**
```python
async def execute(self, task: str, backend: str | None = None, **kwargs: Any) -> str:
    from opengui.agent import GuiAgent
    from opengui.trajectory.recorder import TrajectoryRecorder

    active_backend = self._select_backend(backend)

    # Background wrapping — one display per execute() call
    if self._gui_config.background:
        import sys
        if sys.platform != "linux":
            logger.warning(
                "GuiConfig.background=true but Xvfb is Linux-only; "
                "running in foreground on %s. Use Linux for background mode.",
                sys.platform,
            )
        else:
            from opengui.backends.background import BackgroundDesktopBackend
            from opengui.backends.displays.xvfb import XvfbDisplayManager
            display_num = self._gui_config.display_num or 99
            mgr = XvfbDisplayManager(
                display_num=display_num,
                width=self._gui_config.display_width,
                height=self._gui_config.display_height,
            )
            active_backend = BackgroundDesktopBackend(active_backend, mgr)
            async with active_backend:
                return await self._run_task(active_backend, task, **kwargs)
            # unreachable — async with returns

    return await self._run_task(active_backend, task, **kwargs)
```

**Implementation note:** `execute()` currently has all the agent assembly inline. Extracting a `_run_task()` helper avoids duplicating 20+ lines. The planner should include this refactor as part of the task.

### Pattern 4: Test structure for background CLI tests

**What:** Extend `test_opengui_p5_cli.py` with tests for `parse_args()` (new flags), `resolve_backend_name()` with `--background`, and `run_cli()` with `--background` using `monkeypatch` to replace `BackgroundDesktopBackend` and `XvfbDisplayManager`.

**Key mock approach (CONTEXT.md decision):** Mock `XvfbDisplayManager` with `NoOpDisplayManager` — do NOT mock at `asyncio.subprocess` boundary. This means tests patch `XvfbDisplayManager` in `cli` module namespace OR patch the constructor in `opengui.backends.displays.xvfb`.

```python
# In test_opengui_p5_cli.py — new test for --background parse
def test_cli_parses_background_flags() -> None:
    import opengui.cli as cli

    args = cli.parse_args(["--background", "--task", "Open Settings"])
    assert args.background is True
    assert cli.resolve_backend_name(args) == "local"  # --background implies local

    # Error case: --background with --backend adb
    with pytest.raises(SystemExit):
        cli.parse_args(["--background", "--backend", "adb", "--task", "Open Settings"])

    # Width/height/display-num accepted
    args2 = cli.parse_args(["--background", "--display-num", "42", "--width", "1920", "--height", "1080", "--task", "t"])
    assert args2.display_num == 42
    assert args2.width == 1920
    assert args2.height == 1080
```

```python
# In test_opengui_p11_integration.py — GuiConfig validation test
def test_guiconfig_background_requires_local_backend() -> None:
    from nanobot.config.schema import GuiConfig
    from pydantic import ValidationError

    # Valid
    cfg = GuiConfig(backend="local", background=True)
    assert cfg.background is True

    # Invalid
    with pytest.raises(ValidationError, match="background mode requires backend='local'"):
        GuiConfig(backend="adb", background=True)
```

### Anti-Patterns to Avoid

- **Wrapping in `build_backend()` instead of `run_cli()`:** The CONTEXT.md decision is explicit: `build_backend()` remains unchanged and returns raw `LocalDesktopBackend`. Wrapping happens one level up in `run_cli()`.
- **Using `XvfbDisplayManager` directly in tests:** Always substitute `NoOpDisplayManager` or an `AsyncMock` satisfying `VirtualDisplayManager`. Never let tests reach the subprocess boundary.
- **Double-wrapping on the nanobot path:** `_build_backend()` returns raw `LocalDesktopBackend`; `execute()` wraps it. If `_select_backend()` returns a cached `self._backend`, wrapping in `execute()` is correct. Do NOT wrap in `_build_backend()` — it would conflict with `__init__` caching.
- **Platform check on Windows/macOS causing test failures:** Tests run on macOS in CI. The platform guard (`sys.platform != "linux"`) must gracefully skip wrapping, not raise. The test must confirm the agent runs without wrapping on non-Linux.
- **Not using `async with` for BackgroundDesktopBackend lifecycle:** The backend's `preflight()`/`shutdown()` lifecycle requires `async with`. Plain `await backend.preflight()` without a `try/finally` risks display leak on agent error.
- **Forgetting `--background` implies `--backend local`:** The `resolve_backend_name()` function currently reads `args.dry_run` and `args.backend`. After adding `--background`, it must also check `args.background` and force `"local"`. The test `test_cli_parses_task_and_backend_flags` calls `resolve_backend_name()` and must still pass.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Virtual display lifecycle | Custom subprocess manager | `XvfbDisplayManager` (Phase 9) | Already handles socket polling, crash detection, retries |
| Backend decoration | Custom wrapping in `build_backend()` | `BackgroundDesktopBackend` (Phase 10) | Already handles DISPLAY env, coord offsets, idempotent shutdown |
| Display mock in tests | Mock `asyncio.create_subprocess_exec` | `NoOpDisplayManager` | Simpler, higher-level, matches CONTEXT.md decision |
| Pydantic cross-field validation | Manual `__init__` override | `@model_validator(mode='after')` | Pydantic v2 idiomatic; auto-runs on construction |

**Key insight:** Every hard problem in this phase was solved in Phases 9 and 10. Phase 11 is wiring and testing only.

## Common Pitfalls

### Pitfall 1: CliConfig dataclass with slots=True blocks field addition
**What goes wrong:** `CliConfig` uses `@dataclass(slots=True)`. Adding new fields with complex defaults (e.g. a nested dataclass) requires `field(default_factory=...)`. Missing this causes `TypeError: non-default argument follows default argument`.
**Why it happens:** Python dataclass `slots=True` is strict about default values in field order.
**How to avoid:** Use `field(default_factory=...)` for any nested config dataclass. For simple scalar fields (bool, int), plain `= False` / `= 99` defaults work fine.
**Warning signs:** `TypeError` at import time in test that imports `CliConfig`.

### Pitfall 2: Pydantic camelCase aliases in GuiConfig
**What goes wrong:** `GuiConfig` inherits from `Base` which has `alias_generator=to_camel, populate_by_name=True`. New fields named `display_num` will be aliased to `displayNum`. YAML config files using `display_num` (snake_case) still work because `populate_by_name=True` is set. No additional configuration needed.
**Why it happens:** Engineers unfamiliar with the Base class may add redundant `Field(alias=...)` or expect failures.
**How to avoid:** Trust the existing Base config. Test both `display_num` and `displayNum` keys in GuiConfig construction.

### Pitfall 3: run_cli() inline structure makes async with awkward
**What goes wrong:** `run_cli()` builds all components sequentially and calls `agent.run(task)` at line 352. Wrapping just `agent.run(task)` in `async with backend` works, but only if `backend` is reassigned to the wrapped `BackgroundDesktopBackend` before building the `GuiAgent` (which captures `backend` in its constructor).
**Why it happens:** The wrapping must happen before `GuiAgent(backend=backend, ...)` is called — not after.
**How to avoid:** The wrapping must occur between `build_backend(...)` and `GuiAgent(backend=backend, ...)` construction. The `async with` context must span both the `GuiAgent` construction and `agent.run()`.
**Warning signs:** Agent receives raw `LocalDesktopBackend` while `BackgroundDesktopBackend` was supposed to be the outer wrapper.

### Pitfall 4: Non-Linux platforms in existing CI
**What goes wrong:** If `--background` triggers `XvfbDisplayManager.start()` on macOS (CI), it will fail with `XvfbNotFoundError`. The platform guard must be applied before instantiating `XvfbDisplayManager`.
**Why it happens:** The guard was decided but must be coded correctly — the `XvfbDisplayManager` object must not even be constructed on non-Linux.
**How to avoid:** Check `sys.platform == "linux"` before importing/constructing `XvfbDisplayManager`. Tests that pass `--background` args on macOS CI must monkeypatch `BackgroundDesktopBackend` or test the non-Linux fallback path explicitly.
**Warning signs:** `XvfbNotFoundError` in CI test output.

### Pitfall 5: test_opengui_p5_cli.py monkeypatch scope for BackgroundDesktopBackend
**What goes wrong:** `BackgroundDesktopBackend` and `XvfbDisplayManager` are not currently imported at the module level in `cli.py` — they're lazy-imported inside `run_cli()`. `monkeypatch.setattr(cli, "BackgroundDesktopBackend", ...)` will fail if the name doesn't exist in the module namespace at patch time.
**Why it happens:** Lazy imports (inside function body) mean the name is not a module-level attribute.
**How to avoid:** Two options: (a) import `BackgroundDesktopBackend` at module level in `cli.py` (conditional behind `TYPE_CHECKING` or always); OR (b) patch at the source module: `monkeypatch.setattr("opengui.backends.background.BackgroundDesktopBackend", ...)`. Option (a) is simpler. Check how `LocalDesktopBackend` is handled — it's a module-level `None` that gets replaced by lazy import.
**Warning signs:** `AttributeError: <module 'opengui.cli'> does not have attribute 'BackgroundDesktopBackend'`.

## Code Examples

Verified patterns from project source code:

### Extending argparse in parse_args() — current pattern
```python
# Source: opengui/cli.py line 177
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m opengui.cli")
    # ... existing flags ...
    parser.add_argument("--dry-run", action="store_true", help="Shortcut for --backend dry-run")
    # New --background flag follows the same pattern as --dry-run
    args = parser.parse_args(argv)
    if not args.task_input and not args.task_flag:
        parser.error("task is required via positional input or --task")
    return args
```

### resolve_backend_name() — must be extended
```python
# Source: opengui/cli.py line 213
def resolve_backend_name(args: argparse.Namespace) -> str:
    return "dry-run" if args.dry_run else args.backend
    # Must become:
    # if args.dry_run: return "dry-run"
    # if getattr(args, "background", False): return "local"  # --background implies local
    # return args.backend
```

### Pydantic model_validator pattern (v2)
```python
# Source: Pydantic v2 docs — already used in project (pydantic>=2.12.0)
from pydantic import model_validator

@model_validator(mode='after')
def _validate_something(self) -> "GuiConfig":
    if self.background and self.backend != "local":
        raise ValueError(
            f"background mode requires backend='local', got backend={self.backend!r}"
        )
    return self
```

### NoOpDisplayManager as test replacement for XvfbDisplayManager
```python
# Source: opengui/backends/virtual_display.py
# NoOpDisplayManager satisfies VirtualDisplayManager protocol
# returns DisplayInfo(display_id="noop", width=1280, height=720)
from opengui.backends.virtual_display import NoOpDisplayManager

mgr = NoOpDisplayManager(width=1280, height=720)
backend = BackgroundDesktopBackend(inner, mgr)
async with backend:
    ...  # no subprocess, no Xvfb, CI-safe
```

### AsyncMock manager pattern from Phase 10
```python
# Source: tests/test_opengui_p10_background.py line 27
def _make_mock_manager(display_id: str = ":99", ...) -> AsyncMock:
    mgr = AsyncMock()
    mgr.start = AsyncMock(return_value=DisplayInfo(display_id=display_id, width=1920, height=1080))
    mgr.stop = AsyncMock()
    return mgr
```

### monkeypatch for module-level None replacement (cli.py pattern)
```python
# Source: tests/test_opengui_p5_cli.py line 114
monkeypatch.setattr(cli, "LocalDesktopBackend", FakeLocalDesktopBackend)
# BackgroundDesktopBackend needs the same treatment:
# In cli.py, add at module level: BackgroundDesktopBackend = None
# Then monkeypatch.setattr(cli, "BackgroundDesktopBackend", FakeBackgroundBackend)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `--dry-run` as standalone flag | `--dry-run` and `--backend` are separate but `--dry-run` wins | Phase 5 | `--background` follows same pattern: wins over `--backend` |
| `GuiConfig` flat Pydantic model | Unchanged; add flat fields | Phase 3 | No nested `BackgroundConfig` needed for GuiConfig — keep flat per decision |
| No cross-field validation in GuiConfig | Add `model_validator` | Phase 11 | Validates `background=true` requires `backend='local'` |

## Open Questions

1. **Exact CliConfig field naming for background settings**
   - What we know: CONTEXT.md says "Claude's Discretion" for this
   - What's unclear: Single `BackgroundConfig` nested dataclass vs flat fields on `CliConfig`
   - Recommendation: Use a nested `BackgroundConfig` dataclass (parallel to `AdbConfig`), accessed as `config.background_config.display_num` etc. This keeps `CliConfig` from growing unbounded and mirrors the nanobot `AdbConfig` pattern already in place.

2. **How to wire `async with BackgroundDesktopBackend` in run_cli() without duplication**
   - What we know: `run_cli()` assembles all components and calls `agent.run(task)` inline
   - What's unclear: Whether to extract a `_run_agent()` helper or use an inner function
   - Recommendation: Extract a private `_execute_agent(task, config, backend, ...)` coroutine. This avoids repeating 20+ lines of agent assembly for the background vs non-background paths, and makes tests easier to target.

3. **Test file for nanobot GuiConfig + execute() tests**
   - What we know: CONTEXT.md says "extend existing nanobot GUI test files"; the existing file is `test_opengui_p3_nanobot.py`
   - What's unclear: Whether to extend p3 or create a new p11 file
   - Recommendation: Create `test_opengui_p11_integration.py` — it keeps Phase 11 coverage isolated and avoids making the already-large p3 file harder to read. The Phase 3 file tests protocol adapters; Phase 11 tests background wiring — different concerns.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio 1.3+ |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `asyncio_mode = "auto"` |
| Quick run command | `.venv/bin/pytest tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -x -q` |
| Full suite command | `.venv/bin/pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INTG-01 | `parse_args()` accepts `--background`, `--display-num`, `--width`, `--height`; errors on `--backend adb` | unit | `.venv/bin/pytest tests/test_opengui_p5_cli.py::test_cli_parses_background_flags -x` | Wave 0 |
| INTG-01 | `resolve_backend_name()` returns `"local"` when `--background` set | unit | `.venv/bin/pytest tests/test_opengui_p5_cli.py::test_background_implies_local_backend -x` | Wave 0 |
| INTG-02 | `GuiConfig` accepts `background`, `display_num`, `display_width`, `display_height` | unit | `.venv/bin/pytest tests/test_opengui_p11_integration.py::test_guiconfig_background_fields -x` | Wave 0 |
| INTG-02 | `GuiConfig` model_validator rejects `background=True` with non-local backend | unit | `.venv/bin/pytest tests/test_opengui_p11_integration.py::test_guiconfig_background_requires_local -x` | Wave 0 |
| INTG-03 | `run_cli()` wraps backend in `BackgroundDesktopBackend` when `--background` set (Linux) | integration | `.venv/bin/pytest tests/test_opengui_p5_cli.py::test_run_cli_background_wraps_backend -x` | Wave 0 |
| INTG-03 | `run_cli()` falls back to foreground on non-Linux with warning | unit | `.venv/bin/pytest tests/test_opengui_p5_cli.py::test_run_cli_background_nonlinux_fallback -x` | Wave 0 |
| INTG-04 | `GuiSubagentTool.execute()` wraps backend in `BackgroundDesktopBackend` when `background=True` | integration | `.venv/bin/pytest tests/test_opengui_p11_integration.py::test_gui_tool_execute_background_wraps_backend -x` | Wave 0 |
| INTG-04 | `GuiSubagentTool.execute()` skips wrapping on non-Linux with warning | unit | `.venv/bin/pytest tests/test_opengui_p11_integration.py::test_gui_tool_execute_background_nonlinux_fallback -x` | Wave 0 |
| TEST-V11-01 | All new tests pass without real Xvfb binary | suite | `.venv/bin/pytest tests/ -q` | Wave 0 gaps below |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/ -q`
- **Phase gate:** Full suite green (max 1 pre-existing failure in `test_tool_validation.py`) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p11_integration.py` — covers INTG-02 (GuiConfig schema), INTG-04 (nanobot execute wrapping)
- [ ] `tests/test_opengui_p5_cli.py` additions — covers INTG-01 (parse_args), INTG-03 (run_cli wrapping)
- [ ] Framework install: already present — pytest and pytest-asyncio in `pyproject.toml`

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `opengui/cli.py`, `nanobot/agent/tools/gui.py`, `nanobot/config/schema.py` — exact signatures, current state, integration points
- Direct code inspection: `opengui/backends/background.py`, `opengui/backends/virtual_display.py`, `opengui/backends/displays/xvfb.py` — Phase 9/10 implementation
- Direct code inspection: `tests/test_opengui_p10_background.py`, `tests/test_opengui_p5_cli.py` — established mock patterns
- `pyproject.toml` — verified pytest-asyncio `asyncio_mode = "auto"`, dependency versions
- `.planning/phases/11-integration-tests/11-CONTEXT.md` — locked decisions, constraints

### Secondary (MEDIUM confidence)
- Pydantic v2 `model_validator(mode='after')` — standard Pydantic v2 API; version `>=2.12.0` confirmed in `pyproject.toml`

### Tertiary (LOW confidence)
- None — all findings are directly verifiable from source files

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in pyproject.toml, exact versions known
- Architecture: HIGH — integration points exactly identified with file/line references
- Pitfalls: HIGH — derived from direct code inspection of the files being modified
- Test patterns: HIGH — Phase 10 test file provides directly reusable patterns

**Research date:** 2026-03-20
**Valid until:** 2026-04-19 (stable domain; code doesn't change unless modified)
