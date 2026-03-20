# Phase 12: Background Runtime Contracts - Research

**Researched:** 2026-03-20
**Domain:** Shared background-runtime contracts for capability probing, mode resolution, and process-scope serialization
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
### Unsupported-host behavior
- If the user requests background mode but isolated execution is unavailable, the default behavior is to continue in foreground with an explicit warning.
- The runtime must not silently fall back. Users are told before automation begins.
- If downgrade is allowed, CLI may proceed immediately after warning.
- If downgrade is allowed, nanobot should require explicit acknowledgment before continuing.
- Hard-block only applies when the caller explicitly requests isolation-only behavior. Standard background requests may downgrade.
- Unavailable-isolation messages should include the resolved status and reason, plus actionable remediation.

### Mode reporting contract
- Shared mode vocabulary is `isolated`, `fallback`, and `blocked`.
- Every background run should report its resolved mode explicitly, including successful isolated runs.
- Mode reporting for Phase 12 is log-driven rather than added to final CLI human output or JSON output.
- Mode reports should include a stable reason code plus a human-readable message.

### Overlap policy
- Overlapping desktop background runs should serialize automatically rather than fail fast.
- Phase 12 only needs process-scope overlap protection; host-wide locking can come later.
- When a run is waiting behind another active run, the runtime should surface an explicit busy/status message rather than a generic error.
- If active-run metadata is available, the busy/status message should include identifying details for the run that currently holds the background-runtime slot.

### Probe result shape
- The pre-run probe should answer only whether isolated execution is available.
- The probe itself should stay narrow and not encode fallback or block policy.
- The probe should distinguish between retryable-after-remediation cases and permanent unsupported cases.
- Remediation guidance is not part of the structured probe result in Phase 12; callers/logging layers can translate probe results into user-facing messaging.
- Phase 12 should expose a shared probe contract with a small standard metadata set for host/platform context.

### Runtime decision split
- The runtime contract should separate two concerns:
- Probe result: whether isolated execution is supported on the current host right now.
- Resolved run mode: `isolated`, `fallback`, or `blocked`, derived from the probe result plus caller policy and whether the request was isolation-only.
- This split keeps the shared contract usable for future macOS and Windows implementations without baking policy into the probe itself.

### Claude's Discretion
- Exact naming of the probe/result types and fields.
- Exact reason-code taxonomy, as long as it is stable and suitable for logs across CLI and nanobot.
- Whether serialized runs expose busy state via logs only or also through in-memory status hooks, provided Phase 12 user-visible behavior stays consistent with the decisions above.
- Exact standard metadata fields for host/platform context, provided they stay small and shared across Linux, macOS, and Windows.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BGND-05 | User can start a background desktop run only after the runtime probes whether isolated execution is supported on the current host | Add a shared probe contract that runs before backend wrapping or agent startup; keep Linux probe cheap and side-effect free; normalize unsupported/retryable outcomes into a single result shape |
| BGND-06 | User is told explicitly whether the run will be isolated, downgraded with warning, or blocked before automation begins | Add a shared mode-resolution object with `isolated` / `fallback` / `blocked`, stable reason codes, and log helpers used by both CLI and nanobot before automation starts |
| BGND-07 | Background desktop execution rejects or serializes overlapping desktop background runs on the same host to avoid shared global-state interference | Add a process-scope runtime coordinator using `asyncio.Condition` around the full background backend lifetime; log busy/waiting state with active-run metadata |
</phase_requirements>

## Summary

Phase 12 should not add another platform-specific backend layer. It should add one shared runtime contract that all desktop background callers use before they decide whether to run isolated, fall back, or block. The current codebase does not have that contract: `opengui/cli.py` and `nanobot/agent/tools/gui.py` each make their own Linux-only fallback decision, while [`opengui/backends/background.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/backends/background.py) mutates `os.environ["DISPLAY"]` for the whole process with no serialization guard. That is the main planning risk.

The standard implementation path is: keep `BackgroundDesktopBackend` as the execution wrapper, add a new shared `background_runtime` module for probing and mode resolution, and add a process-scope async lease that protects the entire wrapped lifetime from `preflight()` through `shutdown()`. Use a narrow probe result, a separate mode-resolution object, and centralized logging helpers so CLI and nanobot stop drifting.

The most important design choice is the concurrency primitive. Use `asyncio.Condition`, not a sleep loop and not `lock.locked()` plus ad hoc metadata. Python’s docs explicitly position `Condition` as the combination of an event and a lock for exclusive shared-resource coordination, which matches the “wait, report busy state, then acquire exclusive runtime slot” requirement exactly.

**Primary recommendation:** Add `opengui/backends/background_runtime.py` to own probe/result/resolution/coordinator contracts, wire both CLI and nanobot through it, and have `BackgroundDesktopBackend` acquire a global process-scope lease for its full lifecycle.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`asyncio`, `dataclasses`, `typing`, `logging`, `os`, `shutil`, `sys`) | Runtime verified at 3.12.12; project target is `>=3.11` | Capability probe, pure contract types, async serialization, structured logging, env management | Matches existing code style and avoids adding runtime dependencies for a coordination problem the stdlib already solves |
| `pydantic` | 2.12.5 | Keep nanobot config validation aligned with any new policy fields or stricter mode flags | Already used in [`nanobot/config/schema.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/config/schema.py) and officially supports model-level validation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.0.2 | Unit and integration coverage for probe/decision/serialization behavior | Default test framework for all phase work |
| `pytest-asyncio` | 1.3.0 | Async tests for the coordinator and wrapper lifecycle | Required for runtime lease and overlap tests |
| `unittest.mock.AsyncMock` | Python 3.12 stdlib | Mock async display managers and callers without real Xvfb | Keep tests CI-safe and side-effect free |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncio.Condition`-based coordinator | `asyncio.Lock` only | Simpler, but awkward for “busy/waiting with active-run metadata” and easy to get wrong under cancellation |
| Process-scope in-memory serialization | File lock / host-wide mutex | Broader protection, but explicitly out of scope for Phase 12 |
| Shared runtime contract module | Continue edge-level `sys.platform` checks in CLI and nanobot | Faster short term, but guarantees more drift before macOS/Windows phases |

**Installation:**
```bash
uv sync --extra dev
```

**Version verification:** Verified from the local environment on 2026-03-20 with:
```bash
uv run python -c "import sys; print(sys.version.split()[0])"
uv run python -c "import pydantic, pytest, pytest_asyncio; print(pydantic.__version__, pytest.__version__, pytest_asyncio.__version__)"
```

No new third-party runtime package is recommended for this phase.

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
├── backends/
│   ├── background.py            # existing wrapper; consume the shared runtime lease
│   ├── background_runtime.py    # new: probe/result/resolution/coordinator contracts
│   ├── virtual_display.py       # existing display protocol and DisplayInfo
│   └── displays/
│       └── xvfb.py              # existing Linux isolated backend; add a cheap probe helper
tests/
├── test_opengui_p12_runtime_contracts.py  # new: probe, resolution, serialization coverage
├── test_opengui_p5_cli.py                 # extend: mode reporting order and fallback/block paths
└── test_opengui_p11_integration.py        # extend: nanobot uses the shared contract
```

### Pattern 1: Probe Separate From Policy
**What:** Create one narrow probe result and one separate resolved mode object.
**When to use:** Always. The probe answers host capability only; the resolver applies caller policy.
**Example:**
```python
from dataclasses import dataclass
from typing import Literal

RunMode = Literal["isolated", "fallback", "blocked"]

@dataclass(frozen=True)
class IsolationProbeResult:
    supported: bool
    reason_code: str
    retryable: bool
    host_platform: Literal["linux", "macos", "windows"]
    isolation_backend: str | None


@dataclass(frozen=True)
class ResolvedRunMode:
    mode: RunMode
    reason_code: str
    message: str
    requires_acknowledgement: bool = False
```
Source: Python dataclass + typing patterns from the existing repo, aligned with official `asyncio` coordination guidance at https://docs.python.org/3.11/library/asyncio-sync.html

### Pattern 2: Lease the Runtime Slot Across the Full Background Lifetime
**What:** Serialize the entire isolated background lifetime, not just startup.
**When to use:** Any path that may mutate process-global state such as `os.environ["DISPLAY"]`.
**Example:**
```python
import asyncio
from contextlib import asynccontextmanager


class BackgroundRuntimeCoordinator:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active_run: dict[str, str] | None = None

    @asynccontextmanager
    async def lease(self, run_metadata: dict[str, str]):
        async with self._condition:
            while self._active_run is not None:
                current = dict(self._active_run)
                # Log "busy/waiting" with current holder metadata here.
                await self._condition.wait()
            self._active_run = dict(run_metadata)
        try:
            yield
        finally:
            async with self._condition:
                self._active_run = None
                self._condition.notify_all()
```
Source: `asyncio.Condition` semantics from https://docs.python.org/3.11/library/asyncio-sync.html

### Pattern 3: Resolve and Report Before Automation Starts
**What:** Probe, resolve the mode, log it, then either wrap the backend or continue in foreground.
**When to use:** Both CLI and nanobot entry points.
**Example:**
```python
probe = await runtime_probe()
decision = resolve_run_mode(
    probe=probe,
    background_requested=True,
    require_isolation=False,
    require_ack_for_fallback=is_nanobot,
)
log_mode_resolution(decision)

if decision.mode == "blocked":
    raise RuntimeError(decision.message)
if decision.mode == "fallback":
    return await run_foreground()

async with runtime_coordinator.lease({"owner": "cli", "task": task_id}):
    async with BackgroundDesktopBackend(inner_backend, display_manager):
        return await run_isolated()
```
Source: Repo integration points in [`opengui/cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py) and [`nanobot/agent/tools/gui.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py), with synchronization behavior grounded in https://docs.python.org/3.11/library/asyncio-sync.html

### Anti-Patterns to Avoid
- **Duplicated platform gating:** Do not keep separate fallback logic in CLI and nanobot once the shared contract exists.
- **Probe inside `start()`:** Do not treat “backend startup crashed” as the only capability signal; log a resolved mode before automation begins.
- **Serialize only `preflight()`:** The dangerous shared state exists until `shutdown()` restores `DISPLAY`.
- **Sleep-loop contention handling:** Do not poll with `asyncio.sleep()` while checking a shared boolean.
- **Host-wide lock creep:** Do not add file locks or multiprocess coordination in this phase.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async wait-for-slot behavior | A manual `while busy: await asyncio.sleep(...)` loop | `asyncio.Condition` | It already models “wait for state change, then reacquire exclusive access” |
| Shared mode vocabulary | Scattered string literals in multiple files | One central `Literal`/type alias + constructors in `background_runtime.py` | Keeps logs and tests stable |
| Busy-state ownership | Infer owner from `lock.locked()` | Explicit `active_run` record stored under the coordinator lock | `locked()` alone cannot tell callers who holds the slot |
| Capability checks | Inline `sys.platform` / `shutil.which()` checks in each caller | One shared probe function or provider registry | Prevents drift before macOS and Windows plug in |
| User messaging | Ad hoc f-strings in CLI and nanobot | Shared logging helper driven by `ResolvedRunMode` | Stable reason codes and consistent wording |

**Key insight:** This phase is a contract-hardening problem, not a new-backend problem. The expensive mistakes are duplicated policy, leaked busy state, and partial serialization around a process-global environment mutation.

## Common Pitfalls

### Pitfall 1: Logging the mode after the run already started
**What goes wrong:** The user only learns about fallback or block after backend startup or after the agent is already running.
**Why it happens:** Today the decision is embedded inside caller-specific control flow.
**How to avoid:** Make probe and mode resolution explicit entry-point steps before agent construction or `BackgroundDesktopBackend` startup.
**Warning signs:** Logs only mention Xvfb errors, not a prior “resolved mode=fallback/blocked”.

### Pitfall 2: Using `lock.locked()` as the overlap contract
**What goes wrong:** Waiters know the slot is busy but cannot report who owns it or safely coordinate wakeups.
**Why it happens:** `asyncio.Lock` protects exclusion but does not model shared state transitions by itself.
**How to avoid:** Store active-run metadata under an `asyncio.Condition` and wait on state changes.
**Warning signs:** Busy logs lack owner metadata, or waiters race after a release.

### Pitfall 3: Leaking busy state on exceptions or cancellation
**What goes wrong:** Later runs wait forever because the runtime slot was never cleared.
**Why it happens:** Lease release is not in a `finally` path that always executes.
**How to avoid:** Treat the coordinator as an async context manager and always release under `finally`.
**Warning signs:** A cancelled run leaves all later background runs stuck in “waiting”.

### Pitfall 4: Forgetting that `os.environ` is process-wide
**What goes wrong:** Overlapping background runs clobber each other’s `DISPLAY` value or restore the wrong original value.
**Why it happens:** `BackgroundDesktopBackend` currently mutates the process environment directly.
**How to avoid:** Hold the process-scope lease for the entire wrapped lifetime and keep restore logic in one place.
**Warning signs:** Flaky tests where the second run sees the first run’s display ID.

### Pitfall 5: Mixing host platform identifiers
**What goes wrong:** Reason codes or metadata drift between `sys.platform` values (`darwin`, `win32`) and repo vocabulary (`macos`, `windows`).
**Why it happens:** No shared normalization layer exists yet.
**How to avoid:** Normalize once in the probe contract and log the normalized value everywhere else.
**Warning signs:** Tests assert `macos` in one place and `darwin` in another.

### Pitfall 6: Over-probing Linux
**What goes wrong:** A “capability probe” starts behaving like a real launch attempt and introduces side effects or long delays.
**Why it happens:** It is tempting to reuse `XvfbDisplayManager.start()` as the probe.
**How to avoid:** Keep the probe cheap and side-effect free for Phase 12; use actual startup only during isolated execution.
**Warning signs:** Probe code creates subprocesses, sockets, or temporary X displays.

## Code Examples

Verified patterns from official sources:

### Centralized Mode Resolution
```python
def resolve_run_mode(
    *,
    probe: IsolationProbeResult,
    require_isolation: bool,
    require_ack_for_fallback: bool,
) -> ResolvedRunMode:
    if probe.supported:
        return ResolvedRunMode(
            mode="isolated",
            reason_code=probe.reason_code,
            message="Isolated background execution is available.",
        )
    if require_isolation:
        return ResolvedRunMode(
            mode="blocked",
            reason_code=probe.reason_code,
            message="Isolation was required but is unavailable on this host.",
        )
    return ResolvedRunMode(
        mode="fallback",
        reason_code=probe.reason_code,
        message="Isolated execution is unavailable; continuing in foreground.",
        requires_acknowledgement=require_ack_for_fallback,
    )
```
Source: repo policy split from [`opengui/cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py) and [`nanobot/agent/tools/gui.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py)

### Cancellation-Safe Lease Release
```python
async with coordinator.lease(run_metadata):
    async with BackgroundDesktopBackend(inner_backend, display_manager) as backend:
        return await _execute_agent(args, config, backend, provider, task)
```
Source: `async with` usage pattern backed by https://docs.python.org/3.11/library/asyncio-sync.html and the existing wrapper contract in [`opengui/backends/background.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/backends/background.py)

### Nanobot Config Guard Remains Model-Level
```python
@model_validator(mode="after")
def _validate_background_requires_local(self) -> "GuiConfig":
    if self.background and self.backend != "local":
        raise ValueError("background mode requires backend='local'")
    return self
```
Source: current pattern in [`nanobot/config/schema.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/config/schema.py) and official Pydantic docs at https://docs.pydantic.dev/latest/concepts/validators/

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Linux-only fallback checks live directly in CLI and nanobot entry points | Shared probe + shared mode-resolution contract used by both entry points | Phase 12 | Prevents policy drift and prepares macOS/Windows plug-in points |
| Background wrapper manages lifecycle only | Background wrapper plus process-scope runtime lease | Phase 12 | Prevents overlapping background runs from corrupting process-global state |
| Background capability is inferred from startup success/failure | Probe capability first, then decide and log `isolated` / `fallback` / `blocked` | Phase 12 | Satisfies explicit pre-run reporting requirement |

**Deprecated/outdated:**
- Caller-specific `sys.platform != "linux"` checks as the primary background decision path
- Starting isolated background execution without a prior shared probe result
- Treating “background busy” as an implementation detail instead of a user-visible status event

## Open Questions

1. **Should the coordinator live inside `BackgroundDesktopBackend` or only in callers?**
   - What we know: [`opengui/backends/background.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/backends/background.py) is already the shared lifecycle seam, and direct wrapper usage should not bypass serialization accidentally.
   - What's unclear: Whether future isolated backends will need the same guard without using this wrapper.
   - Recommendation: Put the process-scope lease acquisition in `BackgroundDesktopBackend` for safety, but keep probe/resolution outside in `background_runtime.py`.

2. **Should Phase 12 fully implement nanobot fallback acknowledgement?**
   - What we know: The locked decision requires nanobot to be stricter than CLI, but Phase 12 mode reporting is log-driven and Phase 15/16 still own larger interaction work.
   - What's unclear: Whether explicit acknowledgement UX belongs in this phase or should be exposed as a decision flag now and enforced later.
   - Recommendation: Include `requires_acknowledgement` on the resolved mode now; Phase 12 can log it and preserve the contract even if full interaction lands later.

3. **How deep should the Linux probe go?**
   - What we know: `sys.platform` and `shutil.which("Xvfb")` are cheap and side-effect free; `XvfbDisplayManager.start()` is not.
   - What's unclear: Whether Phase 12 should treat “binary present but launch later fails” as a probe miss or a startup error.
   - Recommendation: Keep the probe cheap in Phase 12 and normalize actual startup failures into the same reason-code family when surfaced.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.2` + `pytest-asyncio 1.3.0` |
| Config file | [`pyproject.toml`](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml) |
| Quick run command | `uv run pytest tests/test_opengui_p12_runtime_contracts.py -q` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BGND-05 | Probe happens before any isolated backend startup or fallback/block decision | unit + integration | `uv run pytest tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py -q` | ❌ Wave 0 |
| BGND-06 | Resolved mode is logged explicitly before automation begins for isolated, fallback, and blocked cases | integration | `uv run pytest tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q` | ❌ Wave 0 |
| BGND-07 | Overlapping background runs serialize deterministically and emit busy/waiting status with active-run metadata | unit | `uv run pytest tests/test_opengui_p12_runtime_contracts.py -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p12_runtime_contracts.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p12_runtime_contracts.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] [`tests/test_opengui_p12_runtime_contracts.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p12_runtime_contracts.py) — new probe, mode-resolution, and coordinator serialization coverage for `BGND-05` to `BGND-07`
- [ ] [`tests/test_opengui_p5_cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_cli.py) — extend with pre-run mode logging order and blocked/fallback assertions
- [ ] [`tests/test_opengui_p11_integration.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p11_integration.py) — extend nanobot parity tests to use the shared runtime contract

## Sources

### Primary (HIGH confidence)
- Repo inspection: [`opengui/backends/background.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/backends/background.py), [`opengui/cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py), [`nanobot/agent/tools/gui.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/tools/gui.py), [`nanobot/config/schema.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/config/schema.py), [`tests/test_opengui_p10_background.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p10_background.py), [`tests/test_opengui_p5_cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_cli.py), [`tests/test_opengui_p11_integration.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p11_integration.py)
- Python `asyncio` synchronization primitives: https://docs.python.org/3.11/library/asyncio-sync.html
- Python `os.environ` semantics: https://docs.python.org/3.11/library/os.html
- Pydantic validators and `model_validator`: https://docs.pydantic.dev/latest/concepts/validators/

### Secondary (MEDIUM confidence)
- Windows window station / desktop creation context for future probe shape: https://learn.microsoft.com/en-us/windows/win32/winstation/window-station-and-desktop-creation

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new runtime dependency is needed; repo and official docs align cleanly
- Architecture: MEDIUM - the contract shape is strongly grounded in current code seams, but future macOS/Windows backends may still force naming or metadata refinement
- Pitfalls: HIGH - directly supported by existing code behavior and Python official docs for `asyncio` and `os.environ`

**Research date:** 2026-03-20
**Valid until:** 2026-04-19
