---
phase: 15-intervention-safety-and-handoff
verified: 2026-03-21T04:01:17Z
status: human_needed
score: 4/5 must-haves verified
human_verification:
  - test: "Linux / macOS background handoff"
    expected: "The handoff surfaces background target metadata and no new screenshots are created while paused."
    why_human: "Requires a real background display and an actual manual gate such as login, payment, or OTP."
  - test: "Windows isolated desktop handoff"
    expected: "The handoff payload includes desktop_name/display_id and the user can complete the manual step inside the isolated target before resume."
    why_human: "Requires a real Windows isolated desktop session."
  - test: "Resume confirmation"
    expected: "Any response other than resume keeps the run paused/cancelled; typing resume continues from a post-handoff screenshot."
    why_human: "Needs live operator input and real screenshot timing."
  - test: "Artifact scrubbing"
    expected: "trace.jsonl and trajectory JSONL redact intervention reasons as <redacted:intervention_reason> and typed secrets as <redacted:input_text>."
    why_human: "Needs inspection of real-host artifacts after an actual credential-like handoff."
---

# Phase 15: Intervention Safety and Handoff Verification Report

**Phase Goal:** The agent can request intervention explicitly, pause autonomous behavior safely, hand the user into the automation target, and resume from a fresh observation with scrubbed trace data.
**Verified:** 2026-03-21T04:01:17Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Agent/runtime can emit an explicit intervention request for sensitive, blocked, or uncertain states. | ✓ VERIFIED | `request_intervention` is accepted in [opengui/action.py](opengui/action.py):22, [opengui/action.py](opengui/action.py):249, exposed in [opengui/prompts/system.py](opengui/prompts/system.py):24 and [opengui/agent.py](opengui/agent.py):97, and covered by [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):67 and [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):88. |
| 2 | Input execution and screenshot capture pause while intervention is pending. | ✓ VERIFIED | [opengui/agent.py](opengui/agent.py):661 returns an intervention `StepResult` before backend execution; [opengui/agent.py](opengui/agent.py):421 waits on the handler and only resumes observation at [opengui/agent.py](opengui/agent.py):430; negative backend I/O assertions live in [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):104 and [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):165. |
| 3 | User can enter the automation target, complete the manual step, and resume from a new observation. | ? UNCERTAIN | The code surfaces target metadata in [opengui/backends/background.py](opengui/backends/background.py):138, [opengui/backends/windows_isolated.py](opengui/backends/windows_isolated.py):154, [opengui/cli.py](opengui/cli.py):582, and resumes from a fresh screenshot at [opengui/agent.py](opengui/agent.py):429. Real host entry into the target still needs the manual smoke flow in [.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md](.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md):5. |
| 4 | Sensitive handoff events are recorded without leaking credential-like input. | ✓ VERIFIED | Scrubbing is implemented in [opengui/agent.py](opengui/agent.py):1008 and [opengui/agent.py](opengui/agent.py):1031, all attempt events are scrubbed before trace/trajectory writes at [opengui/agent.py](opengui/agent.py):1104, and redaction is asserted in [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):285, [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):343, [tests/test_opengui_p5_cli.py](tests/test_opengui_p5_cli.py):1641, and [tests/test_opengui_p11_integration.py](tests/test_opengui_p11_integration.py):737. |
| 5 | Resume requires explicit confirmation instead of timing out back into automation. | ✓ VERIFIED | The CLI handler only resumes on exact `resume` input in [opengui/cli.py](opengui/cli.py):589, cancellation propagates through [opengui/agent.py](opengui/agent.py):449 and [opengui/agent.py](opengui/agent.py):505, and this is covered by [tests/test_opengui_p5_cli.py](tests/test_opengui_p5_cli.py):1572 and [tests/test_opengui_p5_cli.py](tests/test_opengui_p5_cli.py):1641. |

**Score:** 4/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `opengui/action.py` | Parser and action description support `request_intervention` with required reason text | ✓ VERIFIED | Present and substantive at lines 22-27, 166-170, and 249-250. |
| `opengui/prompts/system.py` | Model-facing tool schema and safety rules advertise `request_intervention` | ✓ VERIFIED | Enum and guidance are present at lines 24-29 and 136-137. |
| `opengui/interfaces.py` | Host intervention request/resolution protocol exists | ✓ VERIFIED | `InterventionRequest`, `InterventionResolution`, and `InterventionHandler` are defined at lines 41-57 and 106-112. |
| `opengui/agent.py` | Agent pause/resume, handler mediation, fresh observation resume, and scrub-before-write logging exist | ✓ VERIFIED | Intervention branch, resume path, cancellation path, and scrubbing are implemented at lines 169, 398-449, 505-512, 661-676, 1008-1038, and 1098-1110. |
| `opengui/cli.py` | CLI supplies a host handler, surfaces scrubbed handoff metadata, and requires exact `resume` confirmation | ✓ VERIFIED | Handler and injection are present at lines 420-433 and 572-623. |
| `nanobot/agent/tools/gui.py` | Nanobot uses the shared intervention handler contract instead of bespoke pause logic | ✓ VERIFIED | `GuiAgent` receives `intervention_handler` at line 219 and the tool-specific handler is defined at lines 441-484. |
| `opengui/backends/background.py` | Linux/macOS background backend exposes safe handoff target metadata | ✓ VERIFIED | `get_intervention_target()` returns display metadata at lines 138-148. |
| `opengui/backends/windows_isolated.py` | Windows isolated backend exposes safe handoff target metadata | ✓ VERIFIED | `get_intervention_target()` returns desktop/display metadata at lines 154-164. |
| `tests/test_opengui_p15_intervention.py` | Regression coverage locks parser/schema, pause semantics, fresh resume, and scrubbing | ✓ VERIFIED | Contains the full focused Phase 15 slice at lines 67-383. |
| `tests/test_opengui_p5_cli.py`, `tests/test_opengui_p11_integration.py`, `tests/test_opengui_p10_background.py`, `tests/test_opengui_p14_windows_desktop.py` | Host wiring and backend metadata are covered | ✓ VERIFIED | Required integration tests exist at lines 1572, 1641, 681, 737, 288, and 483 respectively. |
| `.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md` | Manual real-host checklist exists for the unautomatable handoff flow | ✓ VERIFIED | All four required sections are present at lines 5, 12, 18, and 24. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `opengui/prompts/system.py::_default_tool_definition` | `opengui/action.py::parse_action` | Shared `request_intervention` vocabulary | ✓ WIRED | Both schema and parser include the same action token in [opengui/prompts/system.py](opengui/prompts/system.py):24 and [opengui/action.py](opengui/action.py):22. |
| `opengui/agent.py::_run_step` | `opengui/interfaces.py::InterventionHandler` | Parsed intervention actions become host requests, not backend execution | ✓ WIRED | `_run_step()` emits `intervention_requested` at [opengui/agent.py](opengui/agent.py):661, and `_run_once()` converts it into `InterventionRequest` / handler invocation at [opengui/agent.py](opengui/agent.py):399 and [opengui/agent.py](opengui/agent.py):421. |
| `opengui/agent.py::_run_once` | `opengui/agent.py::backend.observe` | Resume path reacquires a brand-new observation | ✓ WIRED | After confirmation, the next screenshot path is generated and observed at [opengui/agent.py](opengui/agent.py):429-433; this is asserted in [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):273. |
| `opengui/cli.py::run_cli` | `opengui/agent.py::GuiAgent` | CLI injects the host intervention handler | ✓ WIRED | `GuiAgent(... intervention_handler=_build_intervention_handler(backend))` is wired at [opengui/cli.py](opengui/cli.py):420-433. |
| `nanobot/agent/tools/gui.py::_run_task` | `opengui/agent.py::GuiAgent` | Nanobot injects the same host intervention handler contract | ✓ WIRED | `GuiAgent(... intervention_handler=self._build_intervention_handler(...))` is wired at [nanobot/agent/tools/gui.py](nanobot/agent/tools/gui.py):210-220. |
| `opengui/backends/background.py::get_intervention_target` | `opengui/cli.py::_resolve_intervention_target` | Backend display metadata is surfaced to the host handoff message | ✓ WIRED | Background metadata is produced at [opengui/backends/background.py](opengui/backends/background.py):142-147 and filtered/merged by the CLI at [opengui/cli.py](opengui/cli.py):599-610. |
| `opengui/backends/windows_isolated.py::get_intervention_target` | `opengui/cli.py::_resolve_intervention_target` | Windows isolated metadata is surfaced to the host handoff message | ✓ WIRED | Windows metadata is produced at [opengui/backends/windows_isolated.py](opengui/backends/windows_isolated.py):158-164 and filtered/merged by the CLI at [opengui/cli.py](opengui/cli.py):599-610. |
| `opengui/agent.py::_log_attempt_event` | `opengui/trajectory/recorder.py::record_event` | Scrubbed lifecycle payloads are persisted to both trace sinks | ✓ WIRED | `_log_attempt_event()` scrubs before writing at [opengui/agent.py](opengui/agent.py):1104-1110 and `TrajectoryRecorder.record_event()` persists the event at [opengui/trajectory/recorder.py](opengui/trajectory/recorder.py):109-118. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `SAFE-01` | `15-01`, `15-04` | Agent can request user intervention explicitly when it reaches a sensitive, blocked, or uncertain state | ✓ SATISFIED | Parser/schema support in [opengui/action.py](opengui/action.py):22 and [opengui/prompts/system.py](opengui/prompts/system.py):137; runtime schema parity in [opengui/agent.py](opengui/agent.py):97; contract tests in [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):67-99. |
| `SAFE-02` | `15-02`, `15-03`, `15-04` | Background runs pause autonomous input and screenshot capture while waiting for user intervention | ✓ SATISFIED | Intervention short-circuits execution in [opengui/agent.py](opengui/agent.py):661-676 and pauses until handler resolution at [opengui/agent.py](opengui/agent.py):421-433; pause assertions in [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):104-160 and [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):165-223. |
| `SAFE-03` | `15-02`, `15-03`, `15-04` | User can switch into the automation target, complete the manual step, and resume the run from a fresh observation | ? NEEDS HUMAN | The resume-from-fresh-observation path is implemented at [opengui/agent.py](opengui/agent.py):429-447 and surfaced with target metadata via [opengui/cli.py](opengui/cli.py):580-592 plus backend metadata methods, but the real host handoff still requires the checklist in [.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md](.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md):5-28. |
| `SAFE-04` | `15-02`, `15-03`, `15-04` | Intervention events are recorded with scrubbed trace data that does not leak sensitive input | ✓ SATISFIED | Scrubbing rules are in [opengui/agent.py](opengui/agent.py):1008-1038 and applied before writes at [opengui/agent.py](opengui/agent.py):1104-1110; redaction is exercised in [tests/test_opengui_p15_intervention.py](tests/test_opengui_p15_intervention.py):285-383, [tests/test_opengui_p5_cli.py](tests/test_opengui_p5_cli.py):1641-1696, and [tests/test_opengui_p11_integration.py](tests/test_opengui_p11_integration.py):737-784. |

Orphaned Phase 15 requirements: none. Every Phase 15 requirement listed in `REQUIREMENTS.md` appears in phase plan frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| None | - | No TODO/FIXME, placeholder copy, console-only handlers, or stub implementations found in the scanned phase files. | - | No blocker or warning anti-patterns detected. |

### Human Verification Required

### 1. Linux / macOS Background Handoff

**Test:** Follow [.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md](.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md):5 on a real background run that reaches a login, payment, or OTP gate.
**Expected:** The intervention prompt surfaces safe target metadata for the active background display, and no new screenshots are created while paused.
**Why human:** Requires a live background display plus a real manual gate.

### 2. Windows Isolated Desktop Handoff

**Test:** Follow [.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md](.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md):12 on a real Windows isolated-desktop run.
**Expected:** The handoff payload includes `desktop_name` and `display_id`, and the user can complete the manual step inside the isolated target before resume.
**Why human:** Requires a real Windows isolated desktop and operator handoff.

### 3. Resume Confirmation

**Test:** Follow [.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md](.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md):18 by entering a non-`resume` response first, then `resume`.
**Expected:** The run does not continue on the first response and only resumes from a fresh post-handoff screenshot after the exact `resume` confirmation.
**Why human:** Depends on live operator input and real screenshot timing.

### 4. Artifact Scrubbing

**Test:** Follow [.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md](.planning/phases/15-intervention-safety-and-handoff/15-MANUAL-SMOKE.md):24 after a credential-like intervention.
**Expected:** `trace.jsonl` and the trajectory JSONL redact intervention reasons as `<redacted:intervention_reason>` and typed secrets as `<redacted:input_text>`.
**Why human:** Needs inspection of real-host artifacts produced during a real handoff.

### Gaps Summary

No blocking code gaps were found in the Phase 15 implementation. The remaining validation is operational: the real-host handoff flow in background Linux/macOS and Windows isolated targets still needs a human smoke pass to confirm the manual step and resume behavior outside mocks.

---

_Verified: 2026-03-21T04:01:17Z_
_Verifier: Claude (gsd-verifier)_
