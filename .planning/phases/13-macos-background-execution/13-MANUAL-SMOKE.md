# Phase 13 Manual Smoke Checklist

## Supported Host

- macOS support-floor host with PyObjC installed
- Screen Recording granted
- Accessibility granted
- event-post capability available
- Expected result: isolated mode logs `macos_virtual_display_available`, creates the target surface, captures the correct monitor, and tears down cleanly

## Denied Permissions

- Deny Screen Recording
- Deny Accessibility
- Expected result: shared remediation mentions `System Settings > Privacy & Security`
- Verify the run blocks or warns before the first automation step

## Scaled / Offset Layout

- Place the isolated display at a non-zero origin
- Use a scaled/Retina layout
- Run a tap and drag scenario
- Expected result: screenshot dimensions match the target display and input lands on the same surface

## Cleanup Checks

- Stop the run mid-flight
- Rerun immediately
- Expected result: no stale target-display metadata and no double-stop failure
