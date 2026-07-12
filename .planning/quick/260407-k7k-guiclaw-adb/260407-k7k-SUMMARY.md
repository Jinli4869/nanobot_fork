# Quick Task 260407-k7k Summary

## Outcome

Fixed the ADB text-input fallback so ASCII text containing spaces is no longer encoded with a literal `\ ` sequence that can be truncated by Android-side parsing. The fallback now uses Android `input text`'s `%s` space placeholder.

## What Changed

- Updated [`guiclaw/backends/adb.py`](/Users/jinli/Documents/Personal/nanobot_fork/guiclaw/backends/adb.py) so `_escape_shell_text()`:
  - emits `%s` for spaces
  - continues escaping other special characters for the ADB `input text` fallback path
- Updated [`tests/test_guiclaw.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_guiclaw.py) to lock the corrected fallback encoding for `"hello world"` as `"hello%sworld"`.

## Verification

- `uv run pytest tests/test_guiclaw.py -q`
- `uv run pytest tests/test_guiclaw_p8_trajectory.py -q`
