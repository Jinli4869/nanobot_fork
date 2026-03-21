# Phase 15: Intervention Safety and Handoff - Research

**Researched:** 2026-03-21
**Domain:** Explicit human-intervention requests for background desktop runs, with safe pause/resume semantics and scrubbed trace output
**Confidence:** MEDIUM

<user_constraints>
## User Constraints

No `15-CONTEXT.md` exists for this phase. This research therefore treats the following as authoritative constraints:
- `.planning/ROADMAP.md` Phase 15 goal and success criteria
- `.planning/REQUIREMENTS.md` requirements `SAFE-01`, `SAFE-02`, `SAFE-03`, and `SAFE-04`
- `.planning/STATE.md` and `.planning/PROJECT.md` decisions already locked by Phases 12-14
- `.planning/todos/pending/2026-03-20-background-gui-execution-with-user-intervention-handoff.md`

### Locked Decisions Inherited From Prior Phases
- Keep the shared background-runtime contract introduced in Phase 12 and reused by the CLI and nanobot in Phases 13-14.
- Keep background execution protocol-driven: host-specific behavior should not be hard-coded into `GuiAgent`.
- Do not silently continue after a safety-sensitive state; explicit acknowledgement is part of the milestone promise.
- Preserve Linux, macOS, and Windows isolated execution behavior from earlier phases unless the change is required for intervention pause/resume.
- Keep trajectory and trace artifacts available, but prevent credential-like or other sensitive handoff data from leaking into them.

### Claude's Discretion
- Exact names for the intervention dataclasses/protocols and whether they live in `opengui.interfaces` or a small dedicated module.
- Whether the intervention request is represented as a new `Action` type or as a richer terminal/non-terminal control object, as long as the LLM can request it explicitly.
- Whether host resume is implemented with an in-process handler callback, a blocking prompt adapter, or a lightweight coordination object, as long as resume requires explicit confirmation and uses a fresh observation.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SAFE-01 | Agent can request user intervention explicitly when it reaches a sensitive, blocked, or uncertain state | Add a first-class intervention action/decision to the tool schema, prompt, parser, and step loop instead of overloading `done` or free-text assistant output |
| SAFE-02 | Background runs pause autonomous input and screenshot capture while waiting for user intervention | Move pause semantics above backend execution so the agent does not call `backend.execute()` or `backend.observe()` once intervention is requested, and gate background backends with an intervention session state |
| SAFE-03 | User can switch into the automation target, complete the manual step, and resume the run from a fresh observation | Introduce a host-facing intervention handler that can activate the target surface, wait for explicit user confirmation, then resume with a new screenshot and no replayed stale observation |
| SAFE-04 | Intervention events are recorded with scrubbed trace data that does not leak sensitive input | Extend trace/trajectory scrubbing beyond image URLs so `input_text`, intervention reasons, and any host-provided sensitive fields are redacted before persistence |
</phase_requirements>

## Summary

Phase 15 should not be implemented as "just add a notification." The real seam is the `GuiAgent` step loop: today `_run_step()` always executes the chosen action and then immediately captures the next screenshot. That behavior is incompatible with safe intervention because the sensitive moment is precisely when the agent must stop touching the target and stop collecting new screenshots until a human explicitly takes over and hands control back.

The recommended design is to add an explicit intervention control path that is parallel to normal UI actions:

1. The LLM emits a new intervention request action when it detects payment, login, OTP, consent, blocked uncertainty, or similar sensitive states.
2. `GuiAgent` recognizes that action before any backend call, records a scrubbed intervention event, and enters a paused state.
3. A host-provided `InterventionHandler` (CLI or nanobot) receives a structured request, activates the automation target for the user, and waits for explicit resume confirmation.
4. While intervention is pending, no autonomous `execute()` and no autonomous `observe()` calls occur.
5. On resume, the handler returns control and the agent acquires a brand-new observation before continuing the step loop.

This keeps the safety boundary in the orchestration layer, while leaving platform-specific "bring the automation target forward" behavior in the desktop background backends that actually know which display/desktop they created.

**Primary recommendation:** Add a first-class intervention action plus a host-facing `InterventionHandler` protocol, let `GuiAgent` own pause/resume and trace scrubbing, and let background backends expose just enough target-surface metadata/hooks for the handler to hand the user into the right automation surface.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`asyncio`, `dataclasses`, `json`, `pathlib`, `time`) | Project target `>=3.11` | Pause/resume coordination, event recording, and handler payloads | Existing agent and backend runtime already use these primitives |
| Existing OpenGUI protocols (`Action`, `Observation`, `DeviceBackend`, `TrajectoryRecorder`) | repo-local | Extend the current control loop instead of introducing a second orchestration layer | Phase 15 is a contract extension, not a new subsystem |
| Existing desktop backends and runtime wrappers | repo-local | Reuse target-surface ownership from Phases 13-14 | Those backends already know how to reach the isolated target the human needs to enter |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.x | Unit + integration coverage for intervention actions, pause behavior, and host integration | Default test framework already in use |
| `pytest-asyncio` | 1.3.x | Async tests for pause/resume orchestration and no-observe/no-execute guarantees | Required for the agent loop and background lifecycle tests |
| `unittest.mock.AsyncMock` | stdlib | Assert that no backend I/O occurs while intervention is pending | Fits the current testing style for Phases 12-14 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New intervention action | Reuse `done` with a special failure string | Too implicit; host integration and tests cannot reliably distinguish "task failed" from "human needed" |
| Host-facing handler protocol | Direct `input()` / terminal prompt inside `GuiAgent` | Couples the reusable agent core to CLI UX and blocks nanobot parity |
| Pause at the agent loop boundary | Let background backends decide when to stop | Backends do not see model uncertainty/safety intent, only concrete actions |
| Scrubbed event payloads | Log raw intervention reasons and text | Violates `SAFE-04` and leaks the most sensitive part of the run into traces |

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
├── action.py                         # add explicit intervention action parsing/validation
├── agent.py                          # pause/resume orchestration and fresh-observation resume
├── prompts/system.py                 # teach the model when to request intervention
├── interfaces.py                     # add InterventionHandler / payload protocols
├── trajectory/recorder.py            # intervention lifecycle event recording
├── backends/background.py            # optional target-surface handoff hooks for Linux/macOS
├── backends/windows_isolated.py      # optional target-surface handoff hooks for Windows isolated desktop
└── cli.py                            # interactive host-side intervention/resume wiring
nanobot/
└── agent/tools/gui.py                # structured intervention handling with the same core contract
tests/
├── test_opengui_p15_intervention.py  # agent-level pause/resume + scrubbing coverage
├── test_opengui_p5_cli.py            # CLI intervention flow coverage
├── test_opengui_p11_integration.py   # nanobot intervention flow coverage
└── test_opengui_p14_windows_desktop.py / test_opengui_p10_background.py  # backend target-surface hook coverage
```

### Pattern 1: Make Intervention Explicit in the Tool Contract
**What:** Extend the action vocabulary with a dedicated intervention request, for example `action_type="request_intervention"`, with structured text fields describing why the user is needed.
**When to use:** Whenever the model reaches a payment, login, OTP, permission, uncertainty, or blocked state where automation should stop.
**Concrete recommendation:**
- Add `request_intervention` to:
  - `opengui/action.py::VALID_ACTION_TYPES`
  - the tool schema in `opengui/agent.py`
  - the tool schema in `opengui/prompts/system.py`
- Require a human-readable `text` reason for that action.
- Keep `done` reserved for terminal success/failure only.

**Why:** The host and tests need a deterministic branch for "pause and ask the user," not a stringly-typed convention hidden in `done` or assistant text.

### Pattern 2: Pause Above the Backend Boundary
**What:** `GuiAgent._run_step()` should recognize intervention before any backend mutation or follow-up screenshot capture.
**When to use:** The moment the parsed action is `request_intervention`.
**Concrete recommendation:**
- In `GuiAgent._run_step()`:
  - do not call `backend.execute()`
  - do not call `backend.observe()`
  - instead return a structured intervention result or invoke an intervention handler path
- In `GuiAgent._run_once()`:
  - when intervention is requested, call the handler
  - wait for explicit resume confirmation
  - after resume, call `backend.observe()` once to obtain a fresh screenshot before continuing

**Why:** `SAFE-02` is about stopping both autonomous input and screenshot capture. The only place that can guarantee both today is the agent loop itself.

### Pattern 3: Use a Host-Facing `InterventionHandler` Protocol
**What:** Introduce a small protocol that receives the intervention request and coordinates the human handoff/resume.
**When to use:** Every host that embeds `GuiAgent` and wants consistent intervention behavior.
**Concrete recommendation:**
- Add a protocol in `opengui/interfaces.py`, for example:
  - `request_intervention(request: InterventionRequest) -> InterventionResolution`
- `InterventionRequest` should include:
  - task
  - reason/category
  - step index
  - platform/backend metadata
  - target-surface metadata safe to show to the host
- `InterventionResolution` should include:
  - `resume_confirmed: bool`
  - optional scrubbed operator note
  - timestamp(s)

**Why:** This keeps the OpenGUI core reusable while letting the CLI block on terminal confirmation and nanobot choose its own user-facing mediation without forking agent logic.

### Pattern 4: Let Background Backends Provide Target-Surface Handoff Metadata, Not Policy
**What:** Linux/macOS background wrappers and the Windows isolated backend should expose enough information for the host to switch the user into the automation target.
**When to use:** Only when the host is preparing the human handoff.
**Concrete recommendation:**
- Reuse existing `DisplayInfo` / desktop metadata instead of inventing a second targeting model.
- Add a small backend-side helper or metadata payload for:
  - display ID / monitor index for Linux/macOS
  - isolated desktop name / display ID for Windows
  - original foreground app when available
- Keep policy in the agent/host layer; backends should not decide whether an intervention is warranted.

**Why:** The platform-specific knowledge already lives in the backends from Phases 13-14, but the decision to stop belongs to the agent and host contract.

### Pattern 5: Scrub Before Writing, Not After Reading
**What:** Expand log/trace scrubbing so sensitive intervention payloads never hit disk in raw form.
**When to use:** Before writing:
- `trace.jsonl`
- trajectory JSONL step/event payloads
- host-visible summaries when they contain raw action text
**Concrete recommendation:**
- Extend `GuiAgent._scrub_for_log()` to redact:
  - `input_text` action payloads
  - intervention `text` / reason strings when flagged sensitive
  - host notes / extra metadata fields such as `credential`, `otp`, `password`, `secret`, `token`
- Add dedicated `record_event("intervention_requested", ...)`, `record_event("intervention_resumed", ...)`, and `record_event("intervention_cancelled", ...)` events with scrubbed payloads.
- Do not store screenshots captured during intervention because the design should not capture them in the first place.

**Why:** The current scrubber only removes image data URLs. That is not enough for `SAFE-04`.

### Pattern 6: Resume Must Start with a Fresh Observation
**What:** Never reuse the pre-handoff observation after the user completes the manual step.
**When to use:** Immediately after the host confirms resume.
**Concrete recommendation:**
- After resume confirmation, call `backend.observe()` into a new screenshot path and continue the next iteration from that observation.
- Do not synthesize a successful tool result from stale state.
- Record the resume event before or alongside the new observation so traces show the pause boundary clearly.

**Why:** The manual step may have changed the UI, authentication state, foreground app, or surface entirely.

### Anti-Patterns to Avoid
- **Encoding intervention as `done failure`:** loses the distinction between "stop permanently" and "pause for user help."
- **Capturing screenshots while the user types credentials:** directly violates `SAFE-02` and `SAFE-04`.
- **Prompting the user from inside backend classes:** couples platform plumbing to host UX.
- **Auto-resuming after a timeout:** the roadmap explicitly requires explicit confirmation instead.
- **Logging raw intervention reasons and typed text:** sensitive context often appears exactly when intervention occurs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Intervention state | Ad-hoc booleans spread across `GuiAgent`, CLI, and backends | One explicit request/resolution flow | Easier to verify and keeps host parity |
| Host interaction | Inline `print()/input()` calls in agent code | `InterventionHandler` implementation per host | Preserves reusability |
| Handoff targeting | A brand-new target descriptor unrelated to Phase 13/14 metadata | Existing `DisplayInfo` / isolated desktop metadata | Avoids parallel abstractions |
| Trace privacy | Post-processing traces to scrub later | Scrub before persistence | Eliminates leak windows |
| Resume behavior | Reuse the old observation and continue | Fresh `observe()` after resume | Matches the actual user-visible state |

## Common Pitfalls

### Pitfall 1: Treating Intervention as a Normal Action Result
**What goes wrong:** The agent logs "action executed" and then immediately takes another screenshot before the human touches anything.
**Why it happens:** The current control loop is optimized around `execute()` + `observe()` as an inseparable pair.
**How to avoid:** Branch before backend calls and model intervention as a separate control path.

### Pitfall 2: Letting the Host Prompt Without Knowing the Target Surface
**What goes wrong:** The user is told to intervene, but the host cannot actually bring them to the right window/display/desktop.
**Why it happens:** The agent knows intervention is needed, but only the backends know the isolated target details.
**How to avoid:** Pass safe target-surface metadata from the backend layer into the intervention request.

### Pitfall 3: Logging Sensitive Free-Text Reasons Verbatim
**What goes wrong:** A model says "enter the OTP from email" or echoes part of a credential field and that text lands in trace artifacts.
**Why it happens:** Existing trace serialization keeps raw action text and only strips image data URLs.
**How to avoid:** Redact intervention/action payloads before both trace and trajectory writes.

### Pitfall 4: Resuming Without a Fresh Screenshot
**What goes wrong:** The agent continues from a pre-login or pre-consent screenshot and makes the wrong next move.
**Why it happens:** It is tempting to treat resume like a `wait`.
**How to avoid:** Make resume perform a mandatory new `observe()` step.

### Pitfall 5: Baking CLI-Specific UX Into the Core
**What goes wrong:** The CLI works, but nanobot must fork the agent code to do something slightly different.
**Why it happens:** The fastest path is often `input("Press enter to resume")` inside the agent.
**How to avoid:** Keep the agent generic and move all user interaction into host-supplied handlers.

## Validation Architecture

The phase is well suited to a four-plan split with Wave 0 test coverage landing first:

1. **Plan 01:** Add red tests plus the explicit intervention action/prompt/parser contract.
2. **Plan 02:** Implement `GuiAgent` pause/resume orchestration, handler protocol, and scrubbed trajectory events.
3. **Plan 03:** Wire CLI and nanobot through the same intervention contract and backend target-surface metadata.
4. **Plan 04:** Run the regression slice and add a manual smoke checklist for real background handoff flows on macOS/Windows/Linux.

### Recommended Automated Coverage
- New phase test file:
  - `tests/test_opengui_p15_intervention.py`
- Likely extensions to existing tests:
  - `tests/test_opengui.py`
  - `tests/test_opengui_p5_cli.py`
  - `tests/test_opengui_p11_integration.py`
  - `tests/test_opengui_p10_background.py`
  - `tests/test_opengui_p14_windows_desktop.py`

### Minimum Behaviors to Lock in Before Production Refactors
- `parse_action()` accepts `request_intervention` and requires a reason field.
- The system prompt/tool schema advertises the intervention action.
- `GuiAgent` does not call `backend.execute()` or `backend.observe()` after an intervention request until resume is confirmed.
- Resume triggers exactly one fresh observation before the next model step.
- Trace/trajectory payloads redact intervention reasons and typed text.
- CLI and nanobot surface intervention-required states through the same structured contract.
- Background backends expose the target-surface metadata needed for handoff without changing the normal isolation path.

### Manual-Only Coverage
- Real host handoff to a macOS CGVirtualDisplay target.
- Real host handoff to a Windows isolated desktop.
- Linux Xvfb handoff behavior when the target surface is not the user's visible desktop.
- Verification that the user can manually complete a credential/OTP step without any screenshot capture during the pause window.

## Planning Implications

The cleanest plan is to separate the phase into one contract plan, one agent-core plan, one host-integration plan, and one closeout plan. Trying to implement prompt/schema, pause semantics, host interaction, and trace privacy in one plan would make acceptance criteria too vague and make it hard to preserve the cross-host contract established in Phases 12-14.

The highest-risk area is trace privacy, not the prompt change. The code already records detailed prompt/model/execution snapshots on every step, so the plan must explicitly cover every persistence path, not just the human-visible summary.

## Final Recommendation

Plan Phase 15 around a protocol-based intervention contract:
- explicit intervention action in the model/tool schema
- agent-owned pause/resume boundary that halts both action and observation
- host-owned intervention handler for CLI and nanobot parity
- backend-provided target-surface metadata for handoff
- scrub-before-write trace hygiene across all artifacts

That gives the phase a clear safety story without undoing the background execution architecture already shipped in Phases 12-14.
