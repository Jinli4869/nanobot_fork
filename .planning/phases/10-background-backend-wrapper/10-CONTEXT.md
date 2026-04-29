# Phase 10: Background Backend Wrapper - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

BackgroundDesktopBackend decorator that wraps any DeviceBackend to run GUI actions against a virtual display. Sets DISPLAY for X11, applies coordinate offsets for non-zero-offset platforms, and manages the display lifecycle. This phase delivers the wrapper only — CLI flags and nanobot config integration are Phase 11.

</domain>

<decisions>
## Implementation Decisions

### Display lifecycle
- Virtual display starts in `preflight()` — calls `display_manager.start()`, sets DISPLAY env, then delegates to `inner.preflight()`
- Support async context manager (`__aenter__` / `__aexit__`) for automatic cleanup — `__aenter__` calls `preflight()`, `__aexit__` calls `shutdown()`
- If `observe()` or `execute()` is called before `preflight()`, raise `RuntimeError` with a clear message ("call preflight() or use async with before observe/execute")

### Environment isolation
- Use process-global `os.environ["DISPLAY"]` — pyautogui and mss read os.environ directly, subprocess env passthrough is not feasible
- One BackgroundDesktopBackend per process is the expected usage
- Save original `os.environ.get("DISPLAY")` at preflight time; restore (or delete) it at shutdown for clean teardown

### Idempotent shutdown
- Track `_stopped: bool` guard flag
- First `shutdown()` call: run `display_manager.stop()`, restore DISPLAY env, set `_stopped = True`
- Subsequent `shutdown()` calls: log a warning, return immediately (no-op)
- If `display_manager.stop()` raises: log the error and suppress — still restore env and set `_stopped = True`. Shutdown never propagates exceptions (best-effort cleanup)

### Type safety & protocol conformance
- BackgroundDesktopBackend satisfies the `DeviceBackend` protocol — implements `observe()`, `execute()`, `preflight()`, `list_apps()` with correct signatures
- Inner backend typed as `DeviceBackend` (not `object`) using `TYPE_CHECKING` import from `opengui.interfaces`
- Expose `platform` property delegating to `inner.platform` — GuiAgent and prompts read this for OS identification
- No explicit `class BackgroundDesktopBackend(DeviceBackend)` subclassing — structural conformance via duck typing (consistent with other backends)

### Claude's Discretion
- Logging format and verbosity for lifecycle events
- Whether to add a `started` property for external inspection
- Internal method naming and organization
- Test structure and mock patterns

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — BGND-01 through BGND-04 define the four deliverables for this phase

### Roadmap
- `.planning/ROADMAP.md` — Phase 10 success criteria (4 items), dependency on Phase 9

### Phase 9 context (predecessor)
- `.planning/phases/09-virtual-display-protocol/09-CONTEXT.md` — VirtualDisplayManager protocol decisions, DisplayInfo fields, error handling patterns

### Existing code
- `opengui/backends/background.py` — Draft BackgroundDesktopBackend implementation (untracked, needs refinement per decisions above)
- `opengui/backends/virtual_display.py` — VirtualDisplayManager protocol, DisplayInfo dataclass, NoOpDisplayManager
- `opengui/interfaces.py` — DeviceBackend protocol definition (the protocol BackgroundDesktopBackend must satisfy)
- `opengui/backends/desktop.py` — LocalDesktopBackend (the primary inner backend this wrapper will wrap)
- `opengui/action.py` — Action dataclass with x/y/x2/y2 coordinate fields used by `_apply_offset()`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `opengui/backends/background.py` (draft): Already implements DISPLAY injection, coordinate offset logic, and basic delegation. Needs lifecycle guards, context manager, idempotent shutdown, and type fixes.
- `opengui/backends/virtual_display.py`: Stable `VirtualDisplayManager` protocol and `DisplayInfo` dataclass — direct dependency
- `opengui/interfaces.py`: `DeviceBackend` protocol with `@runtime_checkable` — BackgroundDesktopBackend must structurally match this

### Established Patterns
- Protocols use `@typing.runtime_checkable` + `typing.Protocol` (never subclassed by implementations)
- Frozen dataclasses for immutable data (`Action`, `DisplayInfo`)
- `dataclasses.replace()` for creating modified copies of frozen dataclasses (used in `_apply_offset`)
- Lazy/conditional imports with `TYPE_CHECKING` guard for type-only dependencies

### Integration Points
- Phase 11 will instantiate `BackgroundDesktopBackend(LocalDesktopBackend(), XvfbDisplayManager(...))` from CLI and nanobot config
- `GuiAgent` calls `backend.preflight()` before the loop and reads `backend.platform` — wrapper must support both
- `_apply_offset()` uses `dataclasses.replace()` on `Action` — works because Action is a frozen dataclass

</code_context>

<specifics>
## Specific Ideas

- Context manager support (`async with`) makes CLI usage and tests cleaner — automatic cleanup even on exceptions
- Warning log on duplicate shutdown helps catch lifecycle bugs during development without crashing
- Save/restore DISPLAY pattern prevents side effects on the host process after the wrapper is done

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 10-background-backend-wrapper*
*Context gathered: 2026-03-20*
