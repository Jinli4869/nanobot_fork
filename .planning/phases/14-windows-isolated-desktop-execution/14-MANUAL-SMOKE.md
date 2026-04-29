# Phase 14 Windows Manual Smoke Checklist

Use this checklist on a real Windows host after the automated Phase 14 regression slice is green.

## Supported Win32 App

- Start from an interactive, signed-in Windows user session.
- Use a classic Win32/GDI app such as Notepad or File Explorer as the target.
- Launch the isolated run and capture logs before the first agent step.
- Expected availability signal: `windows_isolated_desktop_available`.
- Expected target-surface metadata: `backend_name=windows_isolated_desktop`.
- Expected target-surface metadata: `display_id=windows_isolated_desktop:`.
- Confirm the foreground user desktop does not switch away while the isolated desktop run starts and executes.
- Record whether the target app rendered and accepted automation input on the isolated desktop.

## Non-Interactive Launch Context

- Attempt the same isolated run from a Windows service, Session 0, or another non-interactive launch context.
- Confirm the run blocks before the first agent step.
- Expected blocking message includes `windows_non_interactive_session`.
- Expected blocking message includes `Session 0 and service contexts`.
- Record the exact launch context used and the blocking log line.

## Unsupported App Class

- Attempt an isolated run against a UWP app, DirectX surface, or another GPU-heavy target.
- Confirm the run warns or blocks before automation begins.
- Expected support message includes `windows_app_class_unsupported`.
- Expected support message includes `classic Win32/GDI`.
- Record the target app class, whether the run warned or blocked, and the first supportability message emitted.

## Cleanup Paths

- Verify normal success cleanup after a completed isolated run.
- Force a startup failure after desktop creation and before steady-state automation.
- Cancel a run mid-flight and capture the shutdown evidence.
- Expected cleanup evidence includes `cleanup_reason=normal`.
- Expected cleanup evidence includes `cleanup_reason=startup_failed`.
- Expected cleanup evidence includes `cleanup_reason=cancelled`.
- Confirm no stale OpenGUI desktop handles remain after each path.
- Confirm no orphaned child processes remain after each path.
- Record the cleanup evidence, any remaining handles/processes, and the remediation taken if cleanup was incomplete.
