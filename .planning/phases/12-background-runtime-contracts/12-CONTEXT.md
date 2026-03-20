# Phase 12: Background Runtime Contracts - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden the shared background-execution runtime so it can probe whether isolated execution is available on the current host, report the resolved run mode clearly before automation starts, and prevent overlapping desktop background runs from corrupting process-global state. This phase defines the shared runtime contract for later macOS and Windows implementations; it does not add the platform-specific isolated backends themselves.

</domain>

<decisions>
## Implementation Decisions

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

</decisions>

<specifics>
## Specific Ideas

- The runtime should model capability probing separately from policy resolution. Probe answers "can this host isolate?"; runtime policy answers "given that answer, do we run isolated, fall back, or block?"
- `fallback` is preferred over `downgraded` as the user-facing mode label.
- Nanobot should be stricter than CLI when falling back: it should require an explicit acknowledgment before continuing.
- Serialized overlap handling should still make the waiting condition visible rather than feeling like the run is hung.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/ROADMAP.md` — Phase 12 goal, dependency, and success criteria for shared runtime contracts
- `.planning/REQUIREMENTS.md` — `BGND-05`, `BGND-06`, and `BGND-07`, plus the out-of-scope rule forbidding silent fallback

### Prior phase decisions
- `.planning/STATE.md` — Current milestone position and previously locked v1.1 background-runtime decisions
- `.planning/phases/09-virtual-display-protocol/09-CONTEXT.md` — Virtual display abstraction and `DisplayInfo` decisions that Phase 12 builds on
- `.planning/phases/10-background-backend-wrapper/10-CONTEXT.md` — Wrapper lifecycle, `DISPLAY` env isolation, and one-background-run-per-process assumptions that Phase 12 must harden
- `.planning/phases/11-integration-tests/11-CONTEXT.md` — Current CLI and nanobot Linux-only fallback behavior that Phase 12 will replace with a cross-platform runtime contract

### Runtime code surfaces
- `opengui/backends/virtual_display.py` — Current `VirtualDisplayManager` / `DisplayInfo` contract that Phase 12 will extend or wrap
- `opengui/backends/background.py` — Current background wrapper seam and process-global display assumptions
- `opengui/cli.py` — Current CLI background-mode fallback and logging behavior
- `nanobot/agent/tools/gui.py` — Current nanobot background-mode fallback path that must converge on the shared runtime contract
- `nanobot/config/schema.py` — Existing background-mode config boundary and validation

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `opengui/backends/background.py`: Existing `BackgroundDesktopBackend` already centralizes background lifecycle around a `display_manager.start()` / `stop()` seam and is the natural place to consume a stronger runtime contract.
- `opengui/backends/virtual_display.py`: `DisplayInfo` already carries cross-platform-friendly fields like `offset_x`, `offset_y`, and `monitor_index`.
- `opengui/backends/displays/xvfb.py`: Linux Xvfb path is a concrete example of an isolated-capability implementation that currently assumes success/failure directly at startup.
- `opengui/cli.py`: Current CLI path already gates background behavior in one place inside `run_cli()`.
- `nanobot/agent/tools/gui.py`: Nanobot path already applies a parallel decision point before wrapping the backend.

### Established Patterns
- Background behavior is currently implemented as a thin wrapper/decorator around an existing desktop backend, not as a separate backend hierarchy.
- Existing fallback behavior is platform-gated at the host entry points (`cli.py` and `gui.py`) instead of through a shared runtime decision object.
- Process-global state still matters: `BackgroundDesktopBackend` mutates `os.environ["DISPLAY"]`, so overlap protection cannot be ignored.
- Logging is already the primary user-visible reporting surface for background-mode state changes.

### Integration Points
- `opengui/backends/background.py` likely becomes the shared runtime decision consumer or host for any new runtime coordinator.
- `opengui/cli.py` and `nanobot/agent/tools/gui.py` need to stop making ad hoc Linux-only decisions and instead consume the shared Phase 12 contract.
- Phase 13 and Phase 14 will need to plug macOS and Windows capability probes into the same shared probe/result shape defined here.
- Phase 16 will need one consistent mode-reporting surface across CLI and nanobot, so Phase 12 should avoid locking into CLI-only structures.

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 12-background-runtime-contracts*
*Context gathered: 2026-03-20*
