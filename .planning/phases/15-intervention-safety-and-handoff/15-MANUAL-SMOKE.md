# Phase 15 Manual Smoke Checklist

Use this checklist on real hosts after the automated Phase 15 regression slice is green. Keep the run phase-local: do not promote these notes into broader product documentation from this wave.

## Linux / macOS Background Handoff

- Start a background run that reaches a login, payment, or OTP gate.
- Confirm the intervention request surfaces target metadata for the background display.
- Record the surfaced `display_id` for the active background target.
- Verify no new screenshots are created while the run is paused.

## Windows Isolated Desktop Handoff

- Start a Windows isolated-desktop run that reaches a manual gate.
- Confirm the handoff payload includes `desktop_name` and `display_id`.
- Verify the user can complete the manual step inside the isolated target before resume.

## Resume Confirmation

- Type anything except `resume` first and confirm the run does not continue.
- Then type `resume`.
- Verify the next automated step uses a fresh screenshot captured after the human step.

## Artifact Scrubbing

- Inspect `trace.jsonl` and the trajectory JSONL after a credential-like handoff.
- Verify intervention reasons are redacted as `<redacted:intervention_reason>`.
- Verify typed secrets are redacted as `<redacted:input_text>`.
