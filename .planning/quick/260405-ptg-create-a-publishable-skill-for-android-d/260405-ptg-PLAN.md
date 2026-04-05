# Quick Task 260405-ptg: Create a publishable skill for Android deep link probing that explores adb/dumpsys signals and consolidates findings for the main agent

**Status:** Completed
**Date:** 2026-04-05

## Tasks

### 1. Define a lightweight but publishable skill contract
- Files: `nanobot/skills`, `nanobot/skills/README.md`
- Action: Add a new built-in skill package whose trigger text, required tools, and output contract keep the main agent context small.
- Verify: The skill package follows the existing `nanobot/skills/<name>/SKILL.md` structure and documents when to use fast vs investigate probing.

### 2. Implement a deterministic probe helper for adb deep-link exploration
- Files: `nanobot/skills/android-deeplink-prober/scripts/probe_deeplinks.py`
- Action: Build a script that can derive candidate schemes/paths from a task, optionally execute `adb am start` / `dumpsys`, and emit a structured summary the main agent can consume.
- Verify: The helper supports a no-device dry-run mode and JSON output for candidate URIs, commands, and next-step recommendations.

### 3. Bundle concise reference material and quick-task bookkeeping
- Files: `nanobot/skills/android-deeplink-prober/references/android-deeplink-method.md`, `.planning/quick/260405-ptg-create-a-publishable-skill-for-android-d/260405-ptg-SUMMARY.md`, `.planning/STATE.md`
- Action: Capture the operating method behind the skill and record the quick task in planning state.
- Verify: The reference stays out of the main skill body, the summary documents the final behavior, and `STATE.md` includes the new quick-task row.
- Done: Added the reference, wrote the quick-task summary, and updated `STATE.md` with the new task entry.
