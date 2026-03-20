# Phase 9: Virtual Display Protocol - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Define VirtualDisplayManager protocol and DisplayInfo dataclass with two implementations: NoOpDisplayManager (for testing and Android) and XvfbDisplayManager (for Linux CI and production). This phase delivers the abstraction layer only — the BackgroundDesktopBackend wrapper (Phase 10) and CLI/nanobot integration (Phase 11) are separate.

</domain>

<decisions>
## Implementation Decisions

### Protocol location
- VirtualDisplayManager protocol and DisplayInfo dataclass live in `opengui.backends.virtual_display`
- Re-export both from `opengui.interfaces` so `from opengui.interfaces import VirtualDisplayManager, DisplayInfo` works (satisfies ROADMAP SC-1)
- NoOpDisplayManager stays in `opengui.backends.virtual_display` alongside the protocol

### DisplayInfo fields
- Field naming: `offset_x` / `offset_y` (not `x_offset` / `y_offset` from ROADMAP — update ROADMAP to match)
- Keep `monitor_index: int = 1` field for future macOS mss screenshot support (default=1 is harmless for Xvfb)
- Full frozen dataclass: `display_id`, `width`, `height`, `offset_x`, `offset_y`, `monitor_index`

### Xvfb error handling
- Custom `XvfbNotFoundError` when Xvfb binary is not installed — catch `FileNotFoundError` from subprocess, wrap with install hint (e.g., "apt install xvfb")
- Auto-increment display number on collision: start at configured number (default :99), try up to `max_retries=5` increments, raise if all taken
- Startup timeout: 5 seconds default, configurable via `startup_timeout` parameter
- Capture stderr from Xvfb process (pipe, don't DEVNULL) — needed for crash detection and debugging

### Xvfb crash detection
- Basic process health check: verify Xvfb process is still alive before operations
- Capture stderr buffer for error reporting when crash is detected
- Raise descriptive error (e.g., `XvfbCrashedError`) with stderr content when process dies unexpectedly

### Draft code approach
- Untracked draft files exist: `virtual_display.py`, `displays/xvfb.py`
- Claude's discretion on whether to refine drafts or rewrite — use decisions above as the requirements
- Phase 9 scope only: do NOT modify `background.py` (that's Phase 10)

### Claude's Discretion
- Refine existing drafts vs clean rewrite (based on how well drafts align with decisions)
- Internal error class hierarchy (single module vs separate exceptions module)
- Socket polling interval tuning (currently 0.2s in draft)
- Logging verbosity and format

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — VDISP-01 through VDISP-04 define the four deliverables for this phase

### Roadmap
- `.planning/ROADMAP.md` — Phase 9 success criteria (5 items), dependency on Phase 8

### Project context
- `.planning/PROJECT.md` — Zero host dependency constraint, decorator pattern decision, Xvfb subprocess management decision

### Existing code (draft baseline)
- `opengui/interfaces.py` — Current protocols (DeviceBackend, LLMProvider) where re-exports will be added
- `opengui/backends/virtual_display.py` — Draft VirtualDisplayManager protocol, DisplayInfo, NoOpDisplayManager
- `opengui/backends/displays/xvfb.py` — Draft XvfbDisplayManager implementation
- `opengui/backends/__init__.py` — Backend import pattern (explicit imports, no wildcard)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `opengui/interfaces.py`: Established protocol pattern using `@typing.runtime_checkable` + `typing.Protocol` — VirtualDisplayManager should follow the same pattern
- `opengui/backends/dry_run.py`: Example of a simple no-op backend — NoOpDisplayManager follows the same simplicity principle
- Draft code in `virtual_display.py` and `displays/xvfb.py` already implements most of the protocol and Xvfb logic

### Established Patterns
- Protocols are `@typing.runtime_checkable` with `typing.Protocol` base
- Data types use `@dataclasses.dataclass(frozen=True)`
- Backends use explicit imports (no `__init__.py` wildcard re-exports)
- Async lifecycle: backends have async methods (`observe`, `execute`, `preflight`)

### Integration Points
- `opengui/interfaces.py` — Add re-exports for `VirtualDisplayManager` and `DisplayInfo`
- `opengui/backends/__init__.py` — May add import documentation for new modules
- Phase 10 (`background.py`) will consume `VirtualDisplayManager` protocol and `DisplayInfo` — ensure protocol is stable before Phase 10

</code_context>

<specifics>
## Specific Ideas

- Auto-increment display numbers is important for CI environments where multiple jobs may run concurrently
- Crash detection should capture stderr content so developers can diagnose Xvfb failures without manual reproduction
- Custom error types (XvfbNotFoundError, XvfbCrashedError) should include actionable messages (install hints, stderr dumps)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-virtual-display-protocol*
*Context gathered: 2026-03-20*
