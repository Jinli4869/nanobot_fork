# Phase 16 Manual Smoke Checklist

## Linux Xvfb Regression

- Run CLI background mode on a Linux host with Xvfb available.
- Run the equivalent nanobot GUI task with background enabled on the same host.
- Repeat with Xvfb unavailable.
- Expected result: CLI and nanobot surface the same supportability meaning for `xvfb_missing`, while nanobot still requires `acknowledge_background_fallback=true` before foreground fallback.

## macOS Capability Messaging

- Validate a supported macOS host with required permissions granted.
- Deny Screen Recording or Accessibility on a separate run.
- Capture the first supportability or remediation message from both CLI and nanobot.
- Expected result: both hosts surface the same remediation meaning for macOS supportability, including the relevant System Settings guidance when access is denied.

## Windows Isolated Desktop and App Class

- Run a supported classic Win32 target from an interactive Windows session.
- Run an unsupported UWP, DirectX, or GPU-heavy target.
- Force or capture a startup failure and a cancellation path.
- Expected result: evidence includes `display_id`, `desktop_name`, `windows_app_class_unsupported`, and `cleanup_reason=normal`, `cleanup_reason=startup_failed`, and `cleanup_reason=cancelled`.

## Intervention and Cleanup Closeout

- Trigger an intervention gate during a background run.
- Confirm CLI requires exact `resume`.
- Confirm nanobot returns a structured non-leaking outcome.
- Inspect trace and log output for `<redacted:intervention_reason>` and safe target keys only.

