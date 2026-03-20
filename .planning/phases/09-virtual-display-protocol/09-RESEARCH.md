# Phase 9: Virtual Display Protocol - Research

**Researched:** 2026-03-20
**Domain:** Python asyncio subprocess management, typing.Protocol, virtual X11 display (Xvfb)
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Protocol location
- VirtualDisplayManager protocol and DisplayInfo dataclass live in `opengui.backends.virtual_display`
- Re-export both from `opengui.interfaces` so `from opengui.interfaces import VirtualDisplayManager, DisplayInfo` works (satisfies ROADMAP SC-1)
- NoOpDisplayManager stays in `opengui.backends.virtual_display` alongside the protocol

#### DisplayInfo fields
- Field naming: `offset_x` / `offset_y` (not `x_offset` / `y_offset` from ROADMAP — update ROADMAP to match)
- Keep `monitor_index: int = 1` field for future macOS mss screenshot support (default=1 is harmless for Xvfb)
- Full frozen dataclass: `display_id`, `width`, `height`, `offset_x`, `offset_y`, `monitor_index`

#### Xvfb error handling
- Custom `XvfbNotFoundError` when Xvfb binary is not installed — catch `FileNotFoundError` from subprocess, wrap with install hint (e.g., "apt install xvfb")
- Auto-increment display number on collision: start at configured number (default :99), try up to `max_retries=5` increments, raise if all taken
- Startup timeout: 5 seconds default, configurable via `startup_timeout` parameter
- Capture stderr from Xvfb process (pipe, don't DEVNULL) — needed for crash detection and debugging

#### Xvfb crash detection
- Basic process health check: verify Xvfb process is still alive before operations
- Capture stderr buffer for error reporting when crash is detected
- Raise descriptive error (e.g., `XvfbCrashedError`) with stderr content when process dies unexpectedly

#### Draft code approach
- Untracked draft files exist: `virtual_display.py`, `displays/xvfb.py`
- Claude's discretion on whether to refine drafts or rewrite — use decisions above as the requirements
- Phase 9 scope only: do NOT modify `background.py` (that's Phase 10)

### Claude's Discretion
- Refine existing drafts vs clean rewrite (based on how well drafts align with decisions)
- Internal error class hierarchy (single module vs separate exceptions module)
- Socket polling interval tuning (currently 0.2s in draft)
- Logging verbosity and format

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VDISP-01 | VirtualDisplayManager protocol with async start/stop lifecycle | Protocol pattern, runtime_checkable usage in codebase confirmed |
| VDISP-02 | DisplayInfo frozen dataclass with display_id, dimensions, offsets | Dataclass pattern confirmed; field names locked to offset_x/offset_y |
| VDISP-03 | NoOpDisplayManager for testing and Android (no virtual display needed) | Draft already implements this correctly; no changes needed |
| VDISP-04 | XvfbDisplayManager launches Xvfb subprocess and waits for X11 socket | Draft exists but missing: error types, auto-increment, stderr pipe, crash detection |
</phase_requirements>

---

## Summary

Phase 9 delivers the complete virtual display abstraction layer. Three of the four deliverables are already nearly correct in untracked draft files; the primary work is in `XvfbDisplayManager`, which needs four additions over the draft: (1) `FileNotFoundError` catch wrapped as `XvfbNotFoundError`, (2) display number auto-increment with up to 5 retries using `/tmp/.X{N}-lock` pre-check and exit-code detection, (3) stderr piped (not DEVNULL) with a background reader task for crash detection, and (4) a `XvfbCrashedError` raised when `process.returncode` is non-None before the socket appears. The `opengui/interfaces.py` re-export is a trivial two-line addition. The draft `virtual_display.py` already matches all locked decisions (offset_x/offset_y naming, frozen dataclass, monitor_index field, NoOpDisplayManager) and needs no substantive changes.

**Primary recommendation:** Refine the existing drafts rather than rewrite — `virtual_display.py` is production-ready; `displays/xvfb.py` needs four targeted additions documented below.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio` (stdlib) | Python 3.11+ | Subprocess launch and socket polling | No third-party dependency; already used throughout codebase |
| `dataclasses` (stdlib) | Python 3.11+ | DisplayInfo frozen dataclass | Matches existing codebase pattern (ToolCall, LLMResponse) |
| `typing` (stdlib) | Python 3.11+ | `Protocol`, `runtime_checkable` | Matches DeviceBackend / LLMProvider pattern in interfaces.py |
| `pathlib` (stdlib) | Python 3.11+ | X11 socket and lock file path operations | Already used in draft |
| `logging` (stdlib) | Python 3.11+ | Xvfb lifecycle events | Already in draft, matches project pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio.subprocess.PIPE` | stdlib | Capture Xvfb stderr for crash detection | XvfbDisplayManager only |
| `asyncio.wait_for` | stdlib | Enforce startup_timeout during socket poll loop | XvfbDisplayManager.start() |

No third-party libraries are needed for this phase. Xvfb itself must be installed on the host (`apt install xvfb` on Debian/Ubuntu), but is NOT a Python dependency.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib asyncio subprocess | `pyvirtualdisplay` PyPI package | pyvirtualdisplay is an existing wrapper, but introduces a third-party dep; project constraint is zero host deps; stdlib is correct |
| Manual socket polling | `inotify` / `watchdog` | Over-engineered for a 5-second startup window; polling at 0.2s is standard practice in Xvfb wrappers |

---

## Architecture Patterns

### Recommended Project Structure
```
opengui/
├── backends/
│   ├── virtual_display.py        # Protocol + DisplayInfo + NoOpDisplayManager (refine draft)
│   ├── displays/
│   │   ├── __init__.py           # "Platform-specific virtual display implementations." (exists)
│   │   └── xvfb.py              # XvfbDisplayManager + error types (refine draft)
│   └── __init__.py               # Existing; no wildcard re-export needed
└── interfaces.py                 # Add re-exports at bottom (2 lines)
```

### Pattern 1: Protocol + Runtime Checkable
**What:** `@typing.runtime_checkable` on a `typing.Protocol` class allows `isinstance()` checks without inheritance.
**When to use:** Every protocol in this codebase — matches `DeviceBackend` and `LLMProvider` exactly.
**Example:**
```python
# Source: opengui/interfaces.py (existing codebase pattern)
@typing.runtime_checkable
class VirtualDisplayManager(typing.Protocol):
    async def start(self) -> DisplayInfo: ...
    async def stop(self) -> None: ...
```

### Pattern 2: Frozen Dataclass for Immutable Return Value
**What:** `@dataclasses.dataclass(frozen=True)` creates a hashable, immutable value object.
**When to use:** `DisplayInfo` — passed from `start()` to callers who should not mutate it.
**Example:**
```python
# Source: opengui/interfaces.py (ToolCall pattern)
@dataclasses.dataclass(frozen=True)
class DisplayInfo:
    display_id: str
    width: int
    height: int
    offset_x: int = 0
    offset_y: int = 0
    monitor_index: int = 1
```

### Pattern 3: Display Collision Detection via Lock File Pre-check
**What:** Before launching Xvfb on display `:N`, check `/tmp/.X{N}-lock`. If it exists, the display is likely in use. Skip to `:N+1`. Launch Xvfb and also watch for immediate process exit (returncode non-None within the polling window) as a secondary collision signal.
**When to use:** `XvfbDisplayManager.start()` auto-increment loop.
**Key facts:**
- Xvfb writes `/tmp/.X{N}-lock` AND creates `/tmp/.X11-unix/X{N}` socket on successful start
- On collision, Xvfb prints to stderr: `(EE) Server is already active for display N` and exits with code `1`
- The lock file may exist as a stale file from a crashed process (no live server behind it)
- Correct order: check lock file → skip if exists → launch → poll socket → if process dies before socket, check stderr for collision message

**Example — lock file pre-check and retry loop:**
```python
# Source: derived from xvfbwrapper.py pattern (cgoldberg/xvfbwrapper on GitHub)
import pathlib

def _display_locked(display_num: int) -> bool:
    lock_path = pathlib.Path(f"/tmp/.X{display_num}-lock")
    return lock_path.exists()

async def _try_start(self, display_num: int) -> DisplayInfo:
    if _display_locked(display_num):
        raise _DisplayInUse()
    # ... launch subprocess, poll socket ...
```

### Pattern 4: Non-blocking Stderr Buffering from a Running Subprocess
**What:** When `stderr=asyncio.subprocess.PIPE`, the process's `.stderr` attribute is an `asyncio.StreamReader`. Reading it while the process runs requires a separate coroutine/task. The canonical approach is `asyncio.create_task(proc.stderr.read())` — but for crash detection we only need the buffered content at the moment of crash, so a simpler approach is to use `proc.stderr.read(4096)` with a timeout in a background task, or to call `proc.communicate()` only after `stop()` is called.

**Critical gotcha:** Do NOT call `proc.communicate()` or `await proc.stderr.read()` while the process is alive and during the socket-polling loop — this will block until the process exits (deadlock if Xvfb never exits).

**Recommended pattern for Phase 9:** Store the process, keep stderr=PIPE, read stderr only in two cases:
1. Process dies before socket appears during `start()` — call `await asyncio.wait_for(proc.stderr.read(), timeout=0.5)` since process has already exited
2. During `stop()` — after `terminate()` + `wait()`, read stderr for any crash content

```python
# Safe stderr drain after process has exited
proc.terminate()
await proc.wait()  # process is now dead
stderr_output = await proc.stderr.read()  # safe, process already exited, pipe will drain
```

### Pattern 5: Re-export from opengui.interfaces
**What:** Import the types at module level in `interfaces.py` so they appear as if defined there.
**When to use:** Any type that downstream consumers should access via the stable public API path.
**Example:**
```python
# Add to bottom of opengui/interfaces.py
from opengui.backends.virtual_display import DisplayInfo as DisplayInfo  # noqa: F401
from opengui.backends.virtual_display import VirtualDisplayManager as VirtualDisplayManager  # noqa: F401
```
The `as Name` form plus `# noqa: F401` is the standard re-export pattern (PEP 484 compliant; explicit `__all__` is an alternative).

### Anti-Patterns to Avoid
- **`stderr=asyncio.subprocess.DEVNULL`:** Draft uses this — crashes are silent and undebuggable. Change to `asyncio.subprocess.PIPE`.
- **Reading stderr with `await proc.stderr.read()` in the polling loop while Xvfb is alive:** This blocks until EOF (process exit). Only read after the process is known dead.
- **Using `proc.communicate()` for crash detection:** `communicate()` closes stdin and waits for EOF on all pipes — it cannot be called on a still-running process mid-lifecycle and then again in `stop()`.
- **Skipping lock file check:** Without it, on collision the startup loop will wait the full `startup_timeout` before detecting failure — 5 seconds × 5 retries = 25 second delay.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| X11 display socket existence | Custom socket ping / X11 protocol probe | `pathlib.Path.exists()` on `/tmp/.X11-unix/XN` | Socket existence IS the readiness signal; this is industry standard (xvfbwrapper, cypress-io/xvfb both use it) |
| Display number availability | Enumerate live processes | `/tmp/.XN-lock` file check | Lock file is written by the X server itself; reliable, fast, filesystem-only |
| Process liveness check | Signal polling | `proc.returncode is not None` | asyncio Process.returncode is None while running, non-None after exit |
| Virtual display Python wrapper | Custom module | stdlib asyncio only | `pyvirtualdisplay` exists but adds a dep; all needed functionality fits in ~100 lines with stdlib |

**Key insight:** The entire Xvfb lifecycle (launch, socket detection, crash detection, cleanup) is expressible with stdlib pathlib + asyncio — no third-party libraries needed.

---

## Common Pitfalls

### Pitfall 1: Stale Lock Files After Xvfb Crash
**What goes wrong:** `/tmp/.X99-lock` persists after Xvfb crashes or is killed. The auto-increment loop sees the lock file and skips `:99`, even though no server is listening.
**Why it happens:** The OS does not clean lock files on process crash; Xvfb only removes them on clean shutdown.
**How to avoid:** After the lock file check causes a skip, do not silently loop — log a warning at DEBUG level: `"Skipping display :{N} — lock file exists (may be stale)"`. Phase 10/11 (BackgroundDesktopBackend teardown) should ensure clean `stop()` is called. This phase does not clean stale locks (out of scope).
**Warning signs:** All 5 increments are skipped despite no live Xvfb processes.

### Pitfall 2: Collision Detected via Exit Code, Not Lock File
**What goes wrong:** Lock file doesn't exist (another process won the race between our check and their Xvfb start), but Xvfb still exits immediately with code 1.
**Why it happens:** TOCTOU (time-of-check-time-of-use) race in concurrent CI environments.
**How to avoid:** In the polling loop, check `proc.returncode is not None` on every iteration. If Xvfb exits before the socket appears, read stderr and raise `XvfbCrashedError` (or retry if stderr contains "already active").

### Pitfall 3: Timeout Does Not Clean Up the Process
**What goes wrong:** `start()` times out, but Xvfb process keeps running in the background.
**Why it happens:** Draft's `stop()` call in the timeout path is correct, but must ensure the process is actually terminated before re-raising.
**How to avoid:** The draft's pattern (`await self.stop()` then `raise TimeoutError(...)`) is correct. Verify `stop()` sets `self._process = None` unconditionally (via `finally:` block — already in draft).

### Pitfall 4: `XvfbDisplayManager.stop()` Called Twice
**What goes wrong:** Calling `stop()` twice raises `ProcessLookupError` if the first call already terminated the process but didn't reset `self._process`.
**Why it happens:** Race between idempotency guard (`if self._process is None: return`) and process already dead.
**How to avoid:** The draft already uses `finally: self._process = None` and catches `ProcessLookupError`. This is correct — verify it stays in the final implementation.

### Pitfall 5: ROADMAP Success Criteria Field Name Mismatch
**What goes wrong:** ROADMAP SC-2 says `x_offset / y_offset` but the locked decision is `offset_x / offset_y`. If a future Phase 10 implementer reads the ROADMAP instead of the CONTEXT, they'll use the wrong field names.
**Why it happens:** CONTEXT.md decision overrides the ROADMAP and explicitly says "update ROADMAP to match".
**How to avoid:** The planner should include a task to update ROADMAP.md SC-2 field names from `x_offset/y_offset` to `offset_x/offset_y`. This is a one-line documentation fix — do not defer.

---

## Code Examples

Verified patterns from official sources and codebase inspection:

### XvfbNotFoundError — Wrapping FileNotFoundError
```python
# Pattern: catch at subprocess creation, wrap with actionable hint
class XvfbNotFoundError(RuntimeError):
    """Raised when Xvfb binary is not installed."""

try:
    self._process = await asyncio.create_subprocess_exec("Xvfb", ...)
except FileNotFoundError as exc:
    raise XvfbNotFoundError(
        "Xvfb is not installed. Install it with: apt install xvfb"
    ) from exc
```

### Auto-increment Loop with Lock File Pre-check
```python
# Source: derived from xvfbwrapper pattern + project auto-increment decision
_MAX_RETRIES = 5

async def start(self) -> DisplayInfo:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        num = self._display_num + attempt
        lock = pathlib.Path(f"/tmp/.X{num}-lock")
        if lock.exists():
            logger.debug("Skipping display :%d — lock file exists", num)
            continue
        try:
            return await self._try_start(num)
        except _DisplayCollisionError as exc:
            last_exc = exc
            logger.debug("Display :%d collision, retrying", num)
    raise RuntimeError(
        f"Could not acquire a free display after {_MAX_RETRIES} attempts"
    ) from last_exc
```

### Stderr Drain After Process Exit (Safe Pattern)
```python
# Source: asyncio docs — communicate() deadlock warning; read only after process dead
proc.terminate()
await proc.wait()             # process is now definitely exited
raw = await proc.stderr.read()  # safe: pipe will drain immediately
return raw.decode(errors="replace")
```

### Runtime Checkable Protocol Verification
```python
# Source: opengui/interfaces.py existing pattern
assert isinstance(NoOpDisplayManager(), VirtualDisplayManager)   # True at runtime
assert isinstance(XvfbDisplayManager(), VirtualDisplayManager)  # True at runtime
```

### Re-export in interfaces.py
```python
# Add to opengui/interfaces.py — two lines at the bottom
from opengui.backends.virtual_display import DisplayInfo as DisplayInfo  # noqa: F401
from opengui.backends.virtual_display import VirtualDisplayManager as VirtualDisplayManager  # noqa: F401
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `subprocess.Popen` (blocking) | `asyncio.create_subprocess_exec` | Python 3.5+ | Non-blocking subprocess in async context; no thread pool needed |
| Poll with `time.sleep()` | `await asyncio.sleep(interval)` | Python 3.5+ | Non-blocking poll in async event loop |
| `pyvirtualdisplay` library | stdlib-only asyncio subprocess | Project decision | Zero Python dependencies; Xvfb binary only |
| `Xvfb :N -screen 0 WxHxD &` in shell | `asyncio.create_subprocess_exec("Xvfb", ...)` | — | Programmatic control, proper cleanup, no shell injection |

**Deprecated/outdated:**
- `stderr=asyncio.subprocess.DEVNULL` in `displays/xvfb.py` draft: must be changed to `asyncio.subprocess.PIPE` per locked decision

---

## Gap Analysis: Draft vs. Locked Decisions

| Gap | File | What's Missing | Effort |
|-----|------|----------------|--------|
| `XvfbNotFoundError` | `displays/xvfb.py` | `try/except FileNotFoundError` around `create_subprocess_exec` | ~8 lines |
| `XvfbCrashedError` | `displays/xvfb.py` | Check `proc.returncode is not None` in socket poll loop | ~10 lines |
| stderr pipe | `displays/xvfb.py` | Change `DEVNULL` to `PIPE`; add stderr drain in `stop()` and crash path | ~5 lines |
| Auto-increment | `displays/xvfb.py` | Lock file pre-check + retry loop wrapping `_try_start()` | ~25 lines |
| Re-exports | `opengui/interfaces.py` | Two import lines at bottom | 2 lines |
| ROADMAP field name fix | `.planning/ROADMAP.md` | SC-2: `x_offset/y_offset` → `offset_x/offset_y` | 1 line |

`virtual_display.py` (protocol + DisplayInfo + NoOpDisplayManager) already matches all locked decisions. No changes needed beyond confirming the draft is the final version.

---

## Open Questions

1. **Error class location: single module or separate `exceptions.py`?**
   - What we know: Project has no existing `exceptions.py` pattern; all errors live in their home module
   - What's unclear: Whether `XvfbNotFoundError` and `XvfbCrashedError` belong in `displays/xvfb.py` or a shared `backends/errors.py`
   - Recommendation: Keep error classes in `displays/xvfb.py` (simpler, no new file); Phase 10 consumers import from there. Only create `backends/errors.py` if Phase 10 needs to catch them without importing the Xvfb module.

2. **Stale lock file recovery**
   - What we know: Stale lock files cause display slots to be skipped; cleaning them is risky (could interfere with live server)
   - What's unclear: Should `XvfbDisplayManager` auto-clean stale locks?
   - Recommendation: Do not auto-clean. Log a warning and skip. Document in docstring that users should run `rm /tmp/.X{N}-lock` to recover.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `pytest tests/test_opengui_p9_virtual_display.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VDISP-01 | `VirtualDisplayManager` importable from `opengui.interfaces`; `isinstance()` checks pass | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_protocol_importable -x` | ❌ Wave 0 |
| VDISP-01 | `start()` and `stop()` are async methods in protocol | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_protocol_methods_are_async -x` | ❌ Wave 0 |
| VDISP-02 | `DisplayInfo` is a frozen dataclass with all 6 fields | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_display_info_frozen -x` | ❌ Wave 0 |
| VDISP-02 | `DisplayInfo` uses `offset_x`/`offset_y` field names | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_display_info_field_names -x` | ❌ Wave 0 |
| VDISP-03 | `NoOpDisplayManager.start()` returns `DisplayInfo` without subprocess | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_noop_start_returns_display_info -x` | ❌ Wave 0 |
| VDISP-03 | `NoOpDisplayManager.stop()` is idempotent (no-op) | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_noop_stop_is_idempotent -x` | ❌ Wave 0 |
| VDISP-04 | `XvfbDisplayManager.start()` launches Xvfb, waits for socket, returns `DisplayInfo` | unit (mocked subprocess) | `pytest tests/test_opengui_p9_virtual_display.py::test_xvfb_start_returns_display_info -x` | ❌ Wave 0 |
| VDISP-04 | `XvfbDisplayManager.start()` raises `XvfbNotFoundError` when binary missing | unit (mock FileNotFoundError) | `pytest tests/test_opengui_p9_virtual_display.py::test_xvfb_not_found_error -x` | ❌ Wave 0 |
| VDISP-04 | `XvfbDisplayManager.start()` raises `TimeoutError` when socket never appears | unit (mock socket absent) | `pytest tests/test_opengui_p9_virtual_display.py::test_xvfb_start_timeout -x` | ❌ Wave 0 |
| VDISP-04 | `XvfbDisplayManager.start()` auto-increments display number on lock-file collision | unit (mock lock exists) | `pytest tests/test_opengui_p9_virtual_display.py::test_xvfb_auto_increment -x` | ❌ Wave 0 |
| VDISP-04 | `XvfbDisplayManager.stop()` on never-started manager does not raise | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_xvfb_stop_never_started -x` | ❌ Wave 0 |
| VDISP-04 | `XvfbDisplayManager.stop()` is idempotent (double-call safe) | unit | `pytest tests/test_opengui_p9_virtual_display.py::test_xvfb_stop_idempotent -x` | ❌ Wave 0 |
| VDISP-04 | `XvfbDisplayManager` raises `XvfbCrashedError` when process exits before socket | unit (mock early exit) | `pytest tests/test_opengui_p9_virtual_display.py::test_xvfb_crashed_error -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_opengui_p9_virtual_display.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p9_virtual_display.py` — all 13 tests above (covers VDISP-01 through VDISP-04)
- [ ] No framework install needed — pytest + pytest-asyncio already in `dev` extras

*(All subprocess calls in tests must be mocked at `asyncio.create_subprocess_exec` boundary — no real Xvfb needed in CI. Use `unittest.mock.patch("asyncio.create_subprocess_exec")` with an `AsyncMock` that sets `returncode=None` initially and creates a fake socket path.)*

---

## Sources

### Primary (HIGH confidence)
- `opengui/backends/virtual_display.py` — Draft code inspected directly; all field names and structure verified
- `opengui/backends/displays/xvfb.py` — Draft code inspected directly; gaps identified against locked decisions
- `opengui/interfaces.py` — Existing protocol pattern (DeviceBackend, LLMProvider) confirmed
- `opengui/backends/dry_run.py` — NoOp backend pattern confirmed
- `pyproject.toml` — Test framework (pytest 9.x, asyncio_mode=auto) and no-extra-dep requirement confirmed
- [Python asyncio subprocess official docs](https://docs.python.org/3/library/asyncio-subprocess.html) — Subprocess patterns, returncode semantics, communicate() deadlock warning

### Secondary (MEDIUM confidence)
- [cgoldberg/xvfbwrapper on GitHub](https://github.com/cgoldberg/xvfbwrapper/blob/master/xvfbwrapper.py) — Lock file pre-check pattern, socket existence detection, process liveness via returncode
- [cypress-io/xvfb issue #98](https://github.com/cypress-io/xvfb/issues/98) — Xvfb stderr message `(EE) Server is already active for display N` confirmed as collision signal

### Tertiary (LOW confidence)
- WebSearch result on Xvfb exit code = 1 on collision — not directly verified from official Xvfb man page; treat as expected but handle defensively

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib-only; confirmed from pyproject.toml and existing code
- Architecture: HIGH — draft files read directly; patterns match existing codebase conventions
- Pitfalls: MEDIUM-HIGH — lock file/stderr patterns verified via xvfbwrapper source + asyncio docs; Xvfb exit code on collision is MEDIUM (not verified from man page)

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stdlib patterns are stable; Xvfb behavior is stable)
