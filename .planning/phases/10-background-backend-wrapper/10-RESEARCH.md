# Phase 10: Background Backend Wrapper - Research

**Researched:** 2026-03-20
**Domain:** Python decorator/wrapper pattern, async context managers, process-global environment variable management, structural protocol conformance
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Display lifecycle**
- Virtual display starts in `preflight()` — calls `display_manager.start()`, sets DISPLAY env, then delegates to `inner.preflight()`
- Support async context manager (`__aenter__` / `__aexit__`) for automatic cleanup — `__aenter__` calls `preflight()`, `__aexit__` calls `shutdown()`
- If `observe()` or `execute()` is called before `preflight()`, raise `RuntimeError` with a clear message ("call preflight() or use async with before observe/execute")

**Environment isolation**
- Use process-global `os.environ["DISPLAY"]` — pyautogui and mss read os.environ directly, subprocess env passthrough is not feasible
- One BackgroundDesktopBackend per process is the expected usage
- Save original `os.environ.get("DISPLAY")` at preflight time; restore (or delete) it at shutdown for clean teardown

**Idempotent shutdown**
- Track `_stopped: bool` guard flag
- First `shutdown()` call: run `display_manager.stop()`, restore DISPLAY env, set `_stopped = True`
- Subsequent `shutdown()` calls: log a warning, return immediately (no-op)
- If `display_manager.stop()` raises: log the error and suppress — still restore env and set `_stopped = True`. Shutdown never propagates exceptions (best-effort cleanup)

**Type safety & protocol conformance**
- BackgroundDesktopBackend satisfies the `DeviceBackend` protocol — implements `observe()`, `execute()`, `preflight()`, `list_apps()` with correct signatures
- Inner backend typed as `DeviceBackend` (not `object`) using `TYPE_CHECKING` import from `opengui.interfaces`
- Expose `platform` property delegating to `inner.platform` — GuiAgent and prompts read this for OS identification
- No explicit `class BackgroundDesktopBackend(DeviceBackend)` subclassing — structural conformance via duck typing (consistent with other backends)

### Claude's Discretion
- Logging format and verbosity for lifecycle events
- Whether to add a `started` property for external inspection
- Internal method naming and organization
- Test structure and mock patterns

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BGND-01 | BackgroundDesktopBackend wraps any DeviceBackend via decorator pattern | Draft `background.py` exists; refine with lifecycle guard, context manager, and type-safe inner |
| BGND-02 | Wrapper sets DISPLAY env var for X11-based virtual displays | `_apply_display_env()` logic in draft is correct; add save/restore at preflight/shutdown |
| BGND-03 | Wrapper applies coordinate offsets for non-Xvfb platforms (macOS prep) | `_apply_offset()` with `dataclasses.replace()` is correct in draft; guard for relative coords already present |
| BGND-04 | Wrapper shutdown stops virtual display (idempotent) | Draft `shutdown()` calls `stop()` once but lacks `_stopped` guard; add flag + warning log + exception suppression |
</phase_requirements>

---

## Summary

Phase 10 delivers `BackgroundDesktopBackend` — a thin decorator that wraps any `DeviceBackend` to route GUI actions through a virtual display. A near-complete draft exists in `opengui/backends/background.py` (untracked). The draft correctly implements DISPLAY injection and coordinate offset logic but is missing four key pieces locked by CONTEXT.md decisions: (1) lifecycle guard (`_started`/`_stopped` flags that gate `observe()`/`execute()` with a clear error), (2) async context manager (`__aenter__`/`__aexit__`), (3) save/restore of the original DISPLAY env at preflight/shutdown, and (4) idempotent shutdown with warning log and exception suppression.

The implementation is entirely in stdlib + existing opengui internals — no new dependencies are required. The `DeviceBackend` protocol in `opengui/interfaces.py` uses `@typing.runtime_checkable` + `typing.Protocol`; BackgroundDesktopBackend must structurally match it without subclassing. `Action` is a frozen dataclass so `dataclasses.replace()` is the correct and only way to produce offset copies.

All four test scenarios (BGND-01 through BGND-04) can be verified with fast unit tests using `AsyncMock` and `unittest.mock` — no real subprocess, no real Xvfb, no real display needed. The Phase 9 tests (`test_opengui_p9_xvfb.py`, `test_opengui_p9_virtual_display.py`) set the template for mock patterns and test file naming.

**Primary recommendation:** Refine the existing draft to add the four missing pieces, then write `tests/test_opengui_p10_background.py` following the Phase 9 test style.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `os` | 3.11+ | `os.environ` manipulation for DISPLAY | Only option for process-global env vars pyautogui/mss read |
| Python stdlib `dataclasses` | 3.11+ | `dataclasses.replace()` for frozen Action copies | Action is frozen; this is the only correct mutation path |
| Python stdlib `logging` | 3.11+ | Lifecycle event and warning logs | Consistent with project — loguru used by nanobot but opengui uses stdlib logging |
| `typing.TYPE_CHECKING` | 3.11+ | Conditional import of `DeviceBackend` for type annotations | Avoids circular imports at runtime; project pattern in interfaces.py and desktop.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `unittest.mock.AsyncMock` | 3.8+ | Mock `VirtualDisplayManager` and inner `DeviceBackend` in tests | Every test — no real display or backend needed |
| `pytest-asyncio` | 1.3.x | Async test execution (`asyncio_mode = "auto"` in pyproject.toml) | All test functions are async coroutines per project pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `os.environ["DISPLAY"]` | `subprocess.Popen(env=...)` per call | Subprocess env passthrough is not feasible — pyautogui and mss read `os.environ` directly, not subprocess env |
| `_stopped: bool` flag | `contextlib.AsyncExitStack` | Flag is simpler and explicit; ExitStack adds complexity without benefit here |
| stdlib `logging` | `loguru` | loguru is used by nanobot but opengui uses stdlib logging for its backend modules; stay consistent |

**Installation:** No new packages required — all dependencies are stdlib or already present.

---

## Architecture Patterns

### Recommended Project Structure
```
opengui/
├── backends/
│   ├── background.py        # BackgroundDesktopBackend (this phase)
│   ├── virtual_display.py   # VirtualDisplayManager protocol, DisplayInfo, NoOpDisplayManager (Phase 9)
│   └── displays/
│       └── xvfb.py          # XvfbDisplayManager (Phase 9)
tests/
└── test_opengui_p10_background.py   # New test file this phase
```

### Pattern 1: Decorator / Wrapper with Lifecycle Guard
**What:** Class that holds a reference to an inner `DeviceBackend` and a `VirtualDisplayManager`, delegates all protocol calls, but gates them behind a lifecycle check.
**When to use:** Whenever you need to inject cross-cutting setup/teardown around an existing interface without modifying implementations.

```python
# Source: opengui/interfaces.py + locked CONTEXT.md decisions
from __future__ import annotations

import dataclasses
import logging
import os
import pathlib
from typing import TYPE_CHECKING

from opengui.backends.virtual_display import DisplayInfo, VirtualDisplayManager

if TYPE_CHECKING:
    from opengui.action import Action
    from opengui.interfaces import DeviceBackend
    from opengui.observation import Observation

logger = logging.getLogger(__name__)

_NOT_STARTED_MSG = "call preflight() or use async with before observe/execute"


class BackgroundDesktopBackend:
    def __init__(self, inner: DeviceBackend, display_manager: VirtualDisplayManager) -> None:
        self._inner = inner
        self._display_manager = display_manager
        self._display_info: DisplayInfo | None = None
        self._original_display: str | None | object = _SENTINEL  # sentinel = not yet saved
        self._stopped: bool = False

    # Async context manager
    async def __aenter__(self) -> BackgroundDesktopBackend:
        await self.preflight()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.shutdown()

    @property
    def platform(self) -> str:
        return self._inner.platform  # type: ignore[union-attr]

    async def preflight(self) -> None:
        self._display_info = await self._display_manager.start()
        # Save original DISPLAY before mutation
        self._original_display = os.environ.get("DISPLAY")
        self._apply_display_env()
        await self._inner.preflight()  # type: ignore[union-attr]

    async def observe(self, screenshot_path: pathlib.Path, timeout: float = 5.0) -> Observation:
        self._assert_started()
        self._apply_display_env()
        return await self._inner.observe(screenshot_path, timeout)  # type: ignore[union-attr]

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        self._assert_started()
        self._apply_display_env()
        return await self._inner.execute(self._apply_offset(action), timeout)  # type: ignore[union-attr]

    async def list_apps(self) -> list[str]:
        return await self._inner.list_apps()  # type: ignore[union-attr]

    async def shutdown(self) -> None:
        if self._stopped:
            logger.warning("BackgroundDesktopBackend.shutdown() called more than once — ignoring")
            return
        try:
            await self._display_manager.stop()
        except Exception:
            logger.exception("Error stopping display manager — continuing shutdown")
        self._restore_display_env()
        self._stopped = True

    # Internal helpers
    def _assert_started(self) -> None:
        if self._display_info is None:
            raise RuntimeError(_NOT_STARTED_MSG)

    def _apply_display_env(self) -> None:
        if self._display_info and self._display_info.display_id.startswith(":"):
            os.environ["DISPLAY"] = self._display_info.display_id

    def _restore_display_env(self) -> None:
        if isinstance(self._original_display, str):
            os.environ["DISPLAY"] = self._original_display
        elif "DISPLAY" in os.environ:
            del os.environ["DISPLAY"]

    def _apply_offset(self, action: Action) -> Action:
        info = self._display_info
        if not info or (info.offset_x == 0 and info.offset_y == 0):
            return action
        if action.x is None or action.relative:
            return action
        return dataclasses.replace(
            action,
            x=action.x + info.offset_x,
            y=action.y + info.offset_y,
            x2=(action.x2 + info.offset_x) if action.x2 is not None else None,
            y2=(action.y2 + info.offset_y) if action.y2 is not None else None,
        )
```

### Pattern 2: Sentinel for "not yet called" vs "called with None"
**What:** Use a module-level sentinel object to distinguish "preflight never called" from "preflight was called and DISPLAY was None at that time".
**When to use:** Saving optional values where `None` is a valid stored value.

```python
# Sentinel distinguishes "not saved yet" from "saved None"
_SENTINEL = object()
# At class level:
self._original_display: str | None | object = _SENTINEL

# In _restore_display_env:
if self._original_display is _SENTINEL:
    return  # preflight never ran, nothing to restore
if isinstance(self._original_display, str):
    os.environ["DISPLAY"] = self._original_display
elif "DISPLAY" in os.environ:
    del os.environ["DISPLAY"]
```

### Pattern 3: Frozen Dataclass Field Copy
**What:** Use `dataclasses.replace()` to produce a modified copy of a frozen dataclass.
**When to use:** Any time you need to adjust fields on `Action` or `DisplayInfo` — direct assignment raises `FrozenInstanceError`.

```python
# Source: opengui/action.py (Action is frozen=True)
import dataclasses
adjusted = dataclasses.replace(
    action,
    x=action.x + offset_x,
    y=action.y + offset_y,
    x2=(action.x2 + offset_x) if action.x2 is not None else None,
    y2=(action.y2 + offset_y) if action.y2 is not None else None,
)
```

### Pattern 4: AsyncMock for Protocol Objects in Tests
**What:** Build mock inner backends and display managers using `AsyncMock` and `MagicMock` from `unittest.mock`.
**When to use:** Every test — avoids real subprocess, real display, real pyautogui calls.

```python
# Source: tests/test_opengui_p9_virtual_display.py pattern
from unittest.mock import AsyncMock, MagicMock
from opengui.backends.virtual_display import DisplayInfo, NoOpDisplayManager

def _make_mock_manager(display_id: str = ":99", offset_x: int = 0, offset_y: int = 0):
    mgr = AsyncMock()
    mgr.start = AsyncMock(return_value=DisplayInfo(
        display_id=display_id, width=1920, height=1080,
        offset_x=offset_x, offset_y=offset_y,
    ))
    mgr.stop = AsyncMock()
    return mgr

def _make_mock_inner(platform: str = "linux"):
    inner = AsyncMock()
    type(inner).platform = PropertyMock(return_value=platform)
    inner.observe = AsyncMock(return_value=...)
    inner.execute = AsyncMock(return_value="ok")
    inner.preflight = AsyncMock()
    inner.list_apps = AsyncMock(return_value=[])
    return inner
```

### Anti-Patterns to Avoid
- **Subclassing DeviceBackend:** `class BackgroundDesktopBackend(DeviceBackend)` — protocols are not subclassed in this project. Use structural conformance only.
- **Setting DISPLAY every call without guard:** Re-setting `os.environ["DISPLAY"]` on each `observe()`/`execute()` call is correct (locked decision), but forgetting the preflight guard means it can set DISPLAY with a stale `_display_info` from a previous run.
- **Swallowing shutdown exceptions silently:** The locked decision says "log the error and suppress" — use `logger.exception()` not a bare `except: pass` so the error appears in logs.
- **Restoring DISPLAY before setting `_stopped = True`:** Order matters — restore first, set flag last. This way a second shutdown call (from `__aexit__` after explicit `shutdown()`) correctly sees `_stopped=True` and no-ops.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async context manager protocol | Custom `start()`/`stop()` wiring | `__aenter__`/`__aexit__` calling `preflight()`/`shutdown()` | Standard Python async context manager; ensures cleanup even on exception |
| Frozen dataclass mutation | Re-create `Action(...)` manually | `dataclasses.replace(action, x=..., y=...)` | Correctly copies all unspecified fields; safe even if Action gains new fields |
| Process-global env var save/restore | Thread-local storage, context vars | `os.environ.get("DISPLAY")` save + restore/delete | pyautogui and mss read `os.environ` directly; no other mechanism works |
| Protocol isinstance check | Manual duck-type inspection | `isinstance(obj, DeviceBackend)` with `@runtime_checkable` | Protocol already has `@typing.runtime_checkable`; this is free |

**Key insight:** The wrapper pattern is deliberately thin. Every complexity concern (subprocess management, socket polling, crash detection) lives in `XvfbDisplayManager`, not in `BackgroundDesktopBackend`. The wrapper only does: set env, offset coords, delegate, guard lifecycle.

---

## Common Pitfalls

### Pitfall 1: DISPLAY Restoration When preflight() Was Never Called
**What goes wrong:** `_restore_display_env()` runs during shutdown even if `preflight()` never ran (e.g., early error), potentially deleting a DISPLAY that was already set by the user's environment.
**Why it happens:** `_original_display` is initialized to `None` which is indistinguishable from "DISPLAY was unset at preflight time" — so restoration incorrectly deletes `DISPLAY`.
**How to avoid:** Initialize `_original_display` to a sentinel object (`_SENTINEL = object()`). In `_restore_display_env()`, check `if self._original_display is _SENTINEL: return` before doing anything.
**Warning signs:** Tests that call `shutdown()` without a preceding `preflight()` see unexpected `KeyError` or missing `DISPLAY`.

### Pitfall 2: Double Shutdown from Explicit Call + __aexit__
**What goes wrong:** Caller does `await backend.shutdown()` then the `async with` block exits calling `__aexit__` → `shutdown()` again. Without an idempotent guard this calls `display_manager.stop()` twice.
**Why it happens:** `__aexit__` always calls `shutdown()` regardless of whether it was already called.
**How to avoid:** `_stopped = True` flag checked at top of `shutdown()`. Second call logs a warning and returns immediately.
**Warning signs:** `VirtualDisplayManager.stop()` called twice in tests; race conditions or double-terminate in CI.

### Pitfall 3: Coordinate Offset Applied to Relative Coordinates
**What goes wrong:** Relative coordinates (action.relative=True) store values in [0, 999] grid space — applying pixel offsets to them produces wildly wrong results.
**Why it happens:** `_apply_offset()` guards `if action.x is None or action.relative: return action` — if this guard is omitted, relative coords get pixel-space offsets added.
**How to avoid:** Keep the `action.relative` guard in `_apply_offset()`. The draft already has this; do not remove it.
**Warning signs:** Tests with `relative=True` actions see coordinates outside [0, 999] after offset.

### Pitfall 4: TYPE_CHECKING Import Creates Runtime AttributeError
**What goes wrong:** `DeviceBackend` is imported under `TYPE_CHECKING` for type annotations, but if the annotation `inner: DeviceBackend` is used in a runtime expression (e.g., `isinstance(self._inner, DeviceBackend)`) it fails because the name doesn't exist at runtime.
**Why it happens:** `TYPE_CHECKING` is `False` at runtime — the import block is skipped.
**How to avoid:** Use `DeviceBackend` only in type annotations (string form or in `if TYPE_CHECKING:` block). Do not call `isinstance(x, DeviceBackend)` inside `BackgroundDesktopBackend` itself. Protocol isinstance checks belong in tests.
**Warning signs:** `NameError: name 'DeviceBackend' is not defined` at runtime.

### Pitfall 5: Draft Uses `inner: object` — Protocol Annotations Lost
**What goes wrong:** The draft types `inner` as `object` and adds `# type: ignore[union-attr]` comments on every delegation call. This makes mypy and IDEs blind to mismatches.
**Why it happens:** Circular import avoidance done incorrectly — `DeviceBackend` is in `opengui.interfaces` which imports from `opengui.backends.virtual_display`.
**How to avoid:** Use the `TYPE_CHECKING` guard: `if TYPE_CHECKING: from opengui.interfaces import DeviceBackend`. Annotate `self._inner: DeviceBackend`. The `# type: ignore` comments can then be dropped.
**Warning signs:** `type: ignore[union-attr]` on delegation lines in the production code.

---

## Code Examples

Verified patterns from the existing codebase:

### DeviceBackend Protocol (the interface BackgroundDesktopBackend must match)
```python
# Source: opengui/interfaces.py
@typing.runtime_checkable
class DeviceBackend(typing.Protocol):
    async def observe(self, screenshot_path: pathlib.Path, timeout: float = 5.0) -> Observation: ...
    async def execute(self, action: Action, timeout: float = 5.0) -> str: ...
    async def preflight(self) -> None: ...
    async def list_apps(self) -> list[str]: ...
    @property
    def platform(self) -> str: ...
```

### VirtualDisplayManager Protocol and DisplayInfo
```python
# Source: opengui/backends/virtual_display.py
@dataclasses.dataclass(frozen=True)
class DisplayInfo:
    display_id: str   # e.g. ":99"
    width: int
    height: int
    offset_x: int = 0
    offset_y: int = 0
    monitor_index: int = 1

@typing.runtime_checkable
class VirtualDisplayManager(typing.Protocol):
    async def start(self) -> DisplayInfo: ...
    async def stop(self) -> None: ...
```

### Idempotent Shutdown with Logging
```python
# Pattern: log warning on duplicate shutdown, suppress display_manager errors
async def shutdown(self) -> None:
    if self._stopped:
        logger.warning("BackgroundDesktopBackend.shutdown() called more than once — ignoring")
        return
    try:
        await self._display_manager.stop()
    except Exception:
        logger.exception("Error stopping display manager during shutdown")
    self._restore_display_env()
    self._stopped = True
```

### DISPLAY Save/Restore Pattern
```python
# Preflight: save before mutation
self._original_display = os.environ.get("DISPLAY")  # None if unset

# Shutdown: restore or delete
if isinstance(self._original_display, str):
    os.environ["DISPLAY"] = self._original_display
elif "DISPLAY" in os.environ:
    del os.environ["DISPLAY"]
```

### AsyncMock for Display Manager in Tests (Phase 9 pattern)
```python
# Source: tests/test_opengui_p9_xvfb.py pattern
from unittest.mock import AsyncMock
from opengui.backends.virtual_display import DisplayInfo

def _make_manager(display_id=":99", offset_x=0, offset_y=0):
    mgr = AsyncMock()
    mgr.start = AsyncMock(return_value=DisplayInfo(
        display_id=display_id, width=1920, height=1080,
        offset_x=offset_x, offset_y=offset_y,
    ))
    mgr.stop = AsyncMock()
    return mgr
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `inner: object` with `# type: ignore[union-attr]` | `inner: DeviceBackend` via `TYPE_CHECKING` guard | Phase 10 (this phase) | Full type safety, no type: ignore on delegation calls |
| `shutdown()` calls `stop()` unconditionally | `_stopped` flag, idempotent, warning on duplicate | Phase 10 (this phase) | Safe for double-shutdown from explicit call + `__aexit__` |
| No lifecycle guard on `observe()`/`execute()` | `_assert_started()` raises `RuntimeError` with clear message | Phase 10 (this phase) | Developer-friendly error instead of AttributeError on None |
| No context manager | `__aenter__`/`__aexit__` delegating to `preflight()`/`shutdown()` | Phase 10 (this phase) | `async with BackgroundDesktopBackend(...)` usage in CLI and tests |

**The draft in `background.py` is the old approach.** The refined implementation is the current approach.

---

## Open Questions

1. **Sentinel vs `_started: bool` flag**
   - What we know: CONTEXT.md locks `_stopped: bool` for shutdown idempotence. It does not explicitly lock a `_started` flag name.
   - What's unclear: Whether the guard for `observe()`/`execute()` should use `_display_info is None` (simplest, already implied by locked code) or a separate `_started: bool` flag.
   - Recommendation: Use `_display_info is None` as the guard (no new field needed; it directly represents "has preflight completed"). The `_stopped` flag is separate and only controls shutdown idempotence.

2. **`started` property for external inspection**
   - What we know: CONTEXT.md marks "Whether to add a `started` property for external inspection" as Claude's Discretion.
   - What's unclear: Phase 11 CLI code will need to know if the backend is started; unclear if it will use `isinstance(backend, BackgroundDesktopBackend)` + direct inspection or always call `preflight()`.
   - Recommendation: Add `started: bool` property returning `self._display_info is not None`. Zero cost, aids debuggability and Phase 11 integration.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio 1.3.x |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `pytest tests/test_opengui_p10_background.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BGND-01 | BackgroundDesktopBackend wraps DeviceBackend and satisfies protocol (`isinstance(wrapper, DeviceBackend)`) | unit | `pytest tests/test_opengui_p10_background.py::test_isinstance_device_backend -x` | ❌ Wave 0 |
| BGND-01 | `preflight()` calls `display_manager.start()` then `inner.preflight()` in order | unit | `pytest tests/test_opengui_p10_background.py::test_preflight_calls_start_and_inner_preflight -x` | ❌ Wave 0 |
| BGND-01 | `observe()` and `execute()` before `preflight()` raise `RuntimeError` | unit | `pytest tests/test_opengui_p10_background.py::test_observe_before_preflight_raises -x` | ❌ Wave 0 |
| BGND-01 | `async with` calls `preflight()` on enter and `shutdown()` on exit | unit | `pytest tests/test_opengui_p10_background.py::test_async_context_manager -x` | ❌ Wave 0 |
| BGND-02 | After `preflight()`, `DISPLAY` env var equals the `display_id` from `DisplayInfo` | unit | `pytest tests/test_opengui_p10_background.py::test_display_env_set_after_preflight -x` | ❌ Wave 0 |
| BGND-02 | `DISPLAY` is restored (or deleted) after `shutdown()` | unit | `pytest tests/test_opengui_p10_background.py::test_display_env_restored_after_shutdown -x` | ❌ Wave 0 |
| BGND-02 | Non-X11 display_id (e.g. "noop") does NOT set `DISPLAY` | unit | `pytest tests/test_opengui_p10_background.py::test_noop_display_does_not_set_display_env -x` | ❌ Wave 0 |
| BGND-03 | Zero offset (Xvfb default): action coordinates pass through unchanged | unit | `pytest tests/test_opengui_p10_background.py::test_zero_offset_passthrough -x` | ❌ Wave 0 |
| BGND-03 | Non-zero offset: `x`, `y`, `x2`, `y2` are each incremented by offset | unit | `pytest tests/test_opengui_p10_background.py::test_nonzero_offset_applied -x` | ❌ Wave 0 |
| BGND-03 | Relative action (`action.relative=True`): offset not applied | unit | `pytest tests/test_opengui_p10_background.py::test_relative_action_offset_skipped -x` | ❌ Wave 0 |
| BGND-04 | First `shutdown()` calls `display_manager.stop()` exactly once | unit | `pytest tests/test_opengui_p10_background.py::test_shutdown_stops_manager -x` | ❌ Wave 0 |
| BGND-04 | Second `shutdown()` call is a no-op (stop() not called again) | unit | `pytest tests/test_opengui_p10_background.py::test_shutdown_idempotent -x` | ❌ Wave 0 |
| BGND-04 | `display_manager.stop()` raising does not propagate from `shutdown()` | unit | `pytest tests/test_opengui_p10_background.py::test_shutdown_suppresses_stop_error -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_opengui_p10_background.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p10_background.py` — covers BGND-01 through BGND-04 (all 13 test cases above)
- [ ] No new framework config needed — `asyncio_mode = "auto"` in `pyproject.toml` covers async tests automatically

---

## Sources

### Primary (HIGH confidence)
- `opengui/backends/background.py` — Draft implementation (direct code inspection)
- `opengui/backends/virtual_display.py` — VirtualDisplayManager protocol and DisplayInfo (direct code inspection)
- `opengui/interfaces.py` — DeviceBackend protocol, `@runtime_checkable` pattern (direct code inspection)
- `opengui/action.py` — Action frozen dataclass, `dataclasses.replace()` usage (direct code inspection)
- `opengui/backends/desktop.py` — LocalDesktopBackend reference implementation (direct code inspection)
- `.planning/phases/10-background-backend-wrapper/10-CONTEXT.md` — All locked decisions (authoritative)
- `pyproject.toml` — pytest configuration, `asyncio_mode = "auto"`, `desktop` extras (direct inspection)

### Secondary (MEDIUM confidence)
- `tests/test_opengui_p9_virtual_display.py` — Test style, AsyncMock patterns, `asyncio_mode = "auto"` confirmed working
- `tests/test_opengui_p9_xvfb.py` — Mock boundary patterns, `_make_process()` helper style

### Tertiary (LOW confidence)
- None — all findings are grounded in direct codebase inspection or locked CONTEXT.md decisions

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib only + existing project deps; verified in pyproject.toml
- Architecture: HIGH — draft exists and is mostly correct; locked decisions are explicit in CONTEXT.md
- Pitfalls: HIGH — derived from direct inspection of draft gaps vs. locked decisions; sentinel/type patterns are well-understood Python

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable; all sources are internal codebase files)
