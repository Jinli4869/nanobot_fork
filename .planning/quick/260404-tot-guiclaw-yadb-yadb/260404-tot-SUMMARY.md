# Quick Task 260404-tot Summary

## Outcome

GUIClaw now ships its own `yadb` asset instead of depending on a separate local repository. When Android text input falls back to the `yadb` path, the ADB backend will automatically push the bundled asset to `/data/local/tmp/yadb` if the device does not already have it.

## What Changed

- Added bundled `yadb` asset at [`guiclaw/assets/android/yadb`](/Users/jinli/Documents/Personal/nanobot_fork/guiclaw/assets/android/yadb).
- Updated [`guiclaw/backends/adb.py`](/Users/jinli/Documents/Personal/nanobot_fork/guiclaw/backends/adb.py) to:
  - locate packaged `yadb`
  - detect whether `/data/local/tmp/yadb` already exists on the device
  - `adb push` the packaged asset when missing
  - `chmod 755` the pushed asset before use
- Updated [`pyproject.toml`](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml) so `guiclaw/assets/**/*` is included in the build.
- Updated [`guiclaw/README.md`](/Users/jinli/Documents/Personal/nanobot_fork/guiclaw/README.md) and [`guiclaw/README_CN.md`](/Users/jinli/Documents/Personal/nanobot_fork/guiclaw/README_CN.md) to document the bundled `yadb` behavior.
- Extended [`tests/test_guiclaw.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_guiclaw.py) with coverage for:
  - pushing packaged `yadb` when missing
  - skipping push when device already has `yadb`
  - integrated `input_text` fallback behavior with the new `yadb` provisioning path

## Verification

- `uv run pytest tests/test_guiclaw.py -k "ensure_yadb_pushes_packaged_asset_when_missing or ensure_yadb_skips_push_when_device_already_has_it"`
- `uv run pytest tests/test_guiclaw.py -k "adb_backend"`
- `git diff --check -- guiclaw/backends/adb.py tests/test_guiclaw.py pyproject.toml guiclaw/README.md guiclaw/README_CN.md guiclaw/assets/android/yadb`

## Implementation Commit

- `uncommitted`
