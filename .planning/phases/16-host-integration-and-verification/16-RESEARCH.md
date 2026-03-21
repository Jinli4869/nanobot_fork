# Phase 16: Host Integration and Verification - Research

**Researched:** 2026-03-21
**Domain:** Cross-host parity for background execution entry points, plus milestone-closing regression and verification coverage
**Confidence:** HIGH

<user_constraints>
## User Constraints

No `16-CONTEXT.md` exists for this phase. This research therefore treats the following as authoritative constraints:
- `.planning/ROADMAP.md` Phase 16 goal and success criteria
- `.planning/REQUIREMENTS.md` requirements `INTG-05`, `INTG-06`, and `TEST-V12-01`
- `.planning/STATE.md` and `.planning/PROJECT.md` decisions already locked by Phases 12-15
- `.planning/phases/14-windows-isolated-desktop-execution/14-VERIFICATION.md`
- `.planning/phases/15-intervention-safety-and-handoff/15-VERIFICATION.md`

### Locked Decisions Inherited From Prior Phases
- Keep `opengui/backends/background_runtime.py` as the single source of truth for capability probing, reason codes, remediation copy, mode resolution, and background-run serialization.
- Keep host entry points dispatching from `probe.backend_name` rather than reintroducing raw platform branching in `opengui/cli.py` or `nanobot/agent/tools/gui.py`.
- Preserve the Phase 13 decision that nanobot reuses the same runtime contract and remediation semantics as CLI while keeping nanobot's JSON result shape stable.
- Preserve the Phase 14 decision that Windows background-local runs default an omitted app-class hint to `classic-win32` before probing isolated support.
- Preserve the Phase 15 decision that intervention and handoff metadata are filtered to safe target-surface keys, CLI resume requires exact `resume`, and trace/log output must redact sensitive reason text.
- Do not invent new platform primitives in Phase 16. The remaining work is host integration parity and milestone verification, not another backend implementation phase.

### Claude's Discretion
- Whether to introduce a small shared helper or phase-local assertion layer to compare CLI and nanobot parity, as long as host-specific transport shapes remain intact.
- Whether Phase 16 parity coverage lives entirely in existing `p5`/`p11` test files or also adds a new `tests/test_opengui_p16_host_integration.py` matrix.
- How much of the milestone closeout evidence lives in tests versus `.planning/phases/16-host-integration-and-verification/16-MANUAL-SMOKE.md`, as long as the phase ends with both automated and manual validation paths.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INTG-05 | CLI background execution exposes consistent configuration, capability messaging, and mode reporting for macOS and Windows | Audit the CLI pre-agent path around `resolve_target_app_class()`, `probe_isolated_background_support()`, `resolve_run_mode()`, mode-resolution logging, intervention handoff output, and Windows cleanup/error token preservation |
| INTG-06 | Nanobot background execution exposes the same behavior and capability messaging as the CLI path | Keep nanobot on the shared runtime contract, preserve its JSON failure/result envelope, and verify the payload keeps the same reason codes, remediation copy, defaulting rules, cleanup tokens, and intervention semantics as the CLI path |
| TEST-V12-01 | Regression coverage verifies capability handling, lifecycle cleanup, and intervention pause/resume behavior without regressing Linux Xvfb support | Add a phase-local parity matrix plus a cross-slice regression command that includes Linux runtime contracts, macOS capability coverage, Windows isolated cleanup, and Phase 15 intervention behavior |
</phase_requirements>

## Summary

Phase 16 should be treated as an integration-and-proof phase, not a new runtime phase. The key platform primitives already exist:
- Linux background isolation and serialization in Phase 12
- macOS isolated display support in Phase 13
- Windows isolated desktop support and cleanup in Phase 14
- explicit intervention, scrubbed traces, and host handoff in Phase 15

What remains is to prove that the two host entry points, CLI and nanobot, expose the same underlying cross-platform contract without collapsing them into the same user interface.

The most important design choice is to preserve the distinction between:
1. **Shared runtime semantics** that must match exactly:
   - `reason_code`
   - remediation copy
   - `backend_name`
   - default Windows `target_app_class`
   - cleanup tokens such as `cleanup_reason=...`
   - intervention target metadata keys
2. **Host-specific transport shape** that may differ intentionally:
   - CLI logs and interactive `resume`
   - nanobot JSON failure/result payloads and non-interactive cancellation handling

That means the phase should not try to make CLI and nanobot print identical text. It should make them expose the same capability decisions and lifecycle evidence through their own host-appropriate surfaces.

**Primary recommendation:** Lock Phase 16 with a dedicated host-parity test matrix, tighten CLI and nanobot around the shared runtime vocabulary rather than host-specific rewrites, then close the milestone with a focused regression slice plus a phase-local manual smoke checklist that explicitly covers Linux Xvfb, macOS remediation, Windows isolated cleanup, and intervention handoff evidence.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`asyncio`, `json`, `logging`, `dataclasses`, `pathlib`) | Project target `>=3.11` | Host integration, structured payloads, and regression assertions | Existing CLI, nanobot, and runtime code already use these primitives |
| `opengui/backends/background_runtime.py` | repo-local | Shared probe, mode resolution, remediation, and busy-run serialization | Phase 16 should deepen this contract, not duplicate it |
| `opengui/cli.py` | repo-local | Human-facing CLI host path for background mode, intervention, and results | Primary entry point for `INTG-05` |
| `nanobot/agent/tools/gui.py` | repo-local | Structured nanobot host path for background mode and intervention | Primary entry point for `INTG-06` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.x | Focused parity coverage and milestone regression slice | Default test framework already in use |
| `pytest-asyncio` | 1.3.x | Async CLI/nanobot/background backend coverage | Required for background lifecycle and intervention paths |
| `unittest.mock.AsyncMock` | stdlib | Assert agent execution ordering, cleanup handling, and no extra intervention I/O | Matches existing testing style in Phases 12-15 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Host-parity regression matrix | Independent assertions spread across only `p5` and `p11` | Easier to miss drift when both hosts evolve separately |
| Preserving host-specific transport shapes | Forcing CLI and nanobot to emit identical strings | Breaks the Phase 13 locked decision that nanobot keeps its JSON failure semantics stable |
| Shared runtime vocabulary | New CLI-only or nanobot-only reason strings | Reintroduces cross-host drift and makes verification weaker |
| Focused regression slice | Full project test suite for every task | Higher latency with less signal for a milestone closeout phase |

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
├── backends/background_runtime.py      # shared reason-code and remediation source of truth
├── cli.py                              # CLI host path and interactive intervention UX
└── backends/
    ├── background.py                   # Linux/macOS background metadata and cleanup
    └── windows_isolated.py             # Windows isolated metadata and cleanup
nanobot/
└── agent/tools/gui.py                  # structured nanobot host path
tests/
├── test_opengui_p5_cli.py              # CLI host-entry coverage
├── test_opengui_p11_integration.py     # nanobot host-entry coverage
├── test_opengui_p10_background.py      # Linux/macOS background metadata and cleanup
├── test_opengui_p12_runtime_contracts.py
├── test_opengui_p13_macos_display.py
├── test_opengui_p14_windows_desktop.py
├── test_opengui_p15_intervention.py
└── test_opengui_p16_host_integration.py # new Phase 16 parity matrix
```

### Pattern 1: Treat `background_runtime` as the Canonical Vocabulary
**What:** Keep all reason codes, remediation copy, host-platform normalization, and mode resolution in `opengui/backends/background_runtime.py`.
**When to use:** Any time CLI or nanobot needs to report supportability, fallback, blocked behavior, or cleanup context.
**Concrete recommendation:**
- Do not add new host-local reason strings in CLI or nanobot when shared runtime already has the canonical value.
- If Phase 16 finds message drift, fix it at the shared runtime or at the host formatting boundary, not by duplicating strings in both hosts.
- Keep `backend_name`, `reason_code`, and the runtime decision order visible in test assertions.

**Why:** Phase 12-15 already established that host entry points should consume the same shared contract. Phase 16 is where that contract gets proven, not bypassed.

### Pattern 2: Preserve Host-Specific Transport, Not Host-Specific Semantics
**What:** CLI and nanobot may present the contract differently, but the underlying semantic payload must match.
**When to use:** Capability probe results, fallback/block decisions, cleanup failures, and intervention outcomes.
**Concrete recommendation:**
- CLI should keep human-readable log and prompt behavior.
- Nanobot should keep JSON `success/summary/trace_path/steps_taken/error` responses.
- Both hosts must expose the same:
  - default Windows app-class behavior
  - reason codes and remediation meaning
  - target-surface metadata keys
  - cleanup evidence tokens

**Why:** The roadmap asks for the same behavior and capability messaging, not a forced identical UX.

### Pattern 3: Add a Phase-Local Host Parity Matrix
**What:** Introduce `tests/test_opengui_p16_host_integration.py` to compare the shared semantics of CLI and nanobot directly.
**When to use:** Shared decisions that should never drift again.
**Concrete recommendation:**
- Lock these exact parity seams:
  - CLI `resolve_target_app_class()` and nanobot `_resolve_probe_target_app_class()` default Windows background-local runs to `classic-win32`
  - both host paths preserve shared `reason_code` and remediation text from `resolve_run_mode()`
  - both host paths surface cleanup/intervention metadata without unsafely leaking raw reason text
- Keep the file focused on semantic parity, not full end-to-end runs.

**Why:** Existing `p5` and `p11` tests cover each host individually, but Phase 16 needs a direct "same contract" check.

### Pattern 4: Keep Cleanup and Handoff Evidence Visible
**What:** Preserve the tokens operators and verifiers need to diagnose lifecycle behavior.
**When to use:** Windows startup failure, cancellation, isolated target handoff, and intervention-triggered cancellation.
**Concrete recommendation:**
- Do not drop `cleanup_reason=...`, `display_id`, `desktop_name`, `backend_name=...`, or similar target-surface evidence when surfacing host errors.
- Keep intervention reason text scrubbed while still surfacing safe target metadata and stable lifecycle tokens.
- Prefer assertions on exact tokens rather than vague "contains a warning" coverage.

**Why:** The Phase 14 and 15 verification reports both depend on these concrete tokens to prove cleanup and handoff behavior.

### Pattern 5: Close the Milestone with Regression First, Manual Smoke Second
**What:** Run the focused automated slice before writing or relying on manual closeout.
**When to use:** Final wave of Phase 16.
**Concrete recommendation:**
- The focused automated slice should cover:
  - `tests/test_opengui_p16_host_integration.py`
  - `tests/test_opengui_p5_cli.py`
  - `tests/test_opengui_p11_integration.py`
  - `tests/test_opengui_p10_background.py`
  - `tests/test_opengui_p12_runtime_contracts.py`
  - `tests/test_opengui_p13_macos_display.py`
  - `tests/test_opengui_p14_windows_desktop.py`
  - `tests/test_opengui_p15_intervention.py`
- After the slice is green, write a phase-local `16-MANUAL-SMOKE.md` that compares CLI and nanobot on real hosts.

**Why:** Manual smoke should validate the real host surfaces automation cannot honestly prove, not compensate for missing automated regression coverage.

### Pattern 6: Prefer Tiny Shared Helpers Over Parallel Drift
**What:** If CLI and nanobot are doing the same normalization or token shaping differently, extract or align the minimum shared helper boundary.
**When to use:** Default app-class resolution, summary formatting, or reason-token transport.
**Concrete recommendation:**
- Only extract helpers when it clearly reduces drift at a stable seam.
- Do not over-abstract the entire host path into a new subsystem.
- Keep host ownership obvious: shared runtime decides semantics, hosts decide presentation.

**Why:** Phase 16 is late in the milestone. Small targeted deduplication is useful; broad refactors are risky.

### Anti-Patterns to Avoid
- **Re-implementing probe or remediation logic inside CLI or nanobot:** creates the exact host drift this phase should close.
- **Erasing cleanup tokens in favor of friendlier prose:** weakens debuggability and verification evidence.
- **Assuming nanobot must mirror CLI interaction literally:** breaks the locked JSON-host contract.
- **Writing parity tests that only check "some warning happened":** too weak for a milestone closeout phase.
- **Running manual smoke before the focused regression slice is green:** hides regressions behind real-host complexity.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Shared reason strings | New host-local message tables | `opengui/backends/background_runtime.py` | Keeps CLI and nanobot aligned |
| Host parity proof | Only manual QA notes | A dedicated Phase 16 parity test file plus existing host suites | Gives durable regression coverage |
| Intervention evidence | Raw free-text reasons in logs or payloads | Existing scrubbed logging plus safe target metadata | Preserves Phase 15 privacy rules |
| Windows defaulting | Ad-hoc host branching that bypasses helper functions | Existing `resolve_target_app_class()` and `_resolve_probe_target_app_class()` seams | Locks Phase 14 behavior in one place per host |
| Milestone verification | A brand-new verifier subsystem | Existing test suites plus phase-local manual smoke checklist | Lowest-risk way to close the milestone |

## Common Pitfalls

### Pitfall 1: Mistaking Transport Differences for Semantic Drift
**What goes wrong:** A verifier sees CLI logs and nanobot JSON are not textually identical and treats that alone as a bug.
**Why it happens:** The hosts intentionally surface results differently.
**How to avoid:** Compare reason codes, remediation meaning, app-class defaults, cleanup tokens, and target metadata keys instead of raw prose shape.

### Pitfall 2: Losing Lifecycle Evidence in Error Reformatting
**What goes wrong:** Cleanup or intervention errors get rewritten into short summaries that omit `cleanup_reason=...`, `display_id`, or `desktop_name`.
**Why it happens:** Host wrappers optimize for readability and accidentally strip diagnosis tokens.
**How to avoid:** Preserve the stable technical tokens in summaries/errors while scrubbing only sensitive free-text fields.

### Pitfall 3: Adding Cross-Host Tests Without a Shared Assertion Layer
**What goes wrong:** CLI and nanobot each get stronger tests, but nothing directly proves they still share the same contract.
**Why it happens:** Existing phase tests are organized by subsystem, not by parity.
**How to avoid:** Add `tests/test_opengui_p16_host_integration.py` as the contract-matrix layer.

### Pitfall 4: Regressing Linux While Chasing macOS/Windows Parity
**What goes wrong:** A late host-integration cleanup subtly changes Xvfb fallback or serialization behavior.
**Why it happens:** Phase 16 work naturally focuses on macOS and Windows.
**How to avoid:** Keep `tests/test_opengui_p12_runtime_contracts.py` and `tests/test_opengui_p10_background.py` in the required regression slice.

### Pitfall 5: Treating Manual Smoke as Optional Nice-to-Have
**What goes wrong:** The phase ships "green" but never validates real macOS permission flows, Windows isolated cleanup, or CLI/nanobot parity on actual hosts.
**Why it happens:** Automation already covers a lot, so the remaining manual work feels easy to skip.
**How to avoid:** Make `16-MANUAL-SMOKE.md` a planned artifact, not an afterthought.

## Validation Architecture

The phase is best executed as a four-plan sequence with two parallel host-entry plans followed by shared regression and closeout:

1. **Plan 01:** Tighten CLI background configuration, mode reporting, intervention output, and cleanup-token visibility with explicit regression tests.
2. **Plan 02:** Tighten nanobot background capability reporting and structured payload parity while preserving the existing JSON host contract.
3. **Plan 03:** Add a dedicated Phase 16 host-parity matrix and run the focused cross-slice regression slice that proves Linux, macOS, Windows, and intervention semantics stay aligned.
4. **Plan 04:** Run the final milestone slice and write a real-host smoke checklist covering Linux Xvfb, macOS remediation, Windows isolated cleanup/app-class handling, and intervention closeout.

### Recommended Automated Coverage
- New phase test file:
  - `tests/test_opengui_p16_host_integration.py`
- Likely extensions to existing tests:
  - `tests/test_opengui_p5_cli.py`
  - `tests/test_opengui_p11_integration.py`
  - `tests/test_opengui_p10_background.py`
  - `tests/test_opengui_p12_runtime_contracts.py`
  - `tests/test_opengui_p13_macos_display.py`
  - `tests/test_opengui_p14_windows_desktop.py`
  - `tests/test_opengui_p15_intervention.py`

### Minimum Behaviors to Lock in Before Closeout
- CLI and nanobot default Windows background-local probes to `classic-win32` when no explicit app class is provided.
- CLI and nanobot preserve shared `reason_code` and remediation meaning from `background_runtime`.
- Windows isolated cleanup failures keep `cleanup_reason=...` and target metadata visible through both hosts.
- Intervention handoff output stays scrubbed while still surfacing safe target metadata.
- Linux Xvfb fallback/availability behavior remains unchanged while Phase 16 parity work lands.
- The final regression slice covers capability handling, cleanup, and intervention without relying on only one host entry point.

### Manual-Only Coverage
- Real macOS permission-denied and supported-host background runs through CLI and nanobot wrappers
- Real Windows isolated-desktop supported, unsupported-app-class, and cleanup-leak scenarios
- Real intervention handoff where CLI uses exact `resume` and nanobot surfaces a structured cancellation/needs-help outcome
- Real Linux Xvfb availability/missing-binary operator checks when background mode is requested

