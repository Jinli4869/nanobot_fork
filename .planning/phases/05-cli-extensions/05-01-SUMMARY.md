---
phase: 05-cli-extensions
plan: 01
subsystem: cli
tags: [opengui, cli, argparse, yaml, openai-compatible, dry-run, pytest]
requires:
  - phase: 02-agent-loop-integration
    provides: Stable GuiAgent constructor seams for llm, backend, recorder, memory, skills, and progress callbacks
  - phase: 04-desktop-backend
    provides: LocalDesktopBackend and DryRunBackend options exposed through the standalone CLI
provides:
  - Standalone `python -m opengui.cli` entry point with YAML config loading and backend selection
  - OpenAI-compatible chat and embedding adapters inside `opengui` runtime code
  - Optional memory and skill bundle wiring gated behind embedding config
affects: [05-02-PLAN.md, host-integrations, developer-workflows, manual-cli-smoke-tests]
tech-stack:
  added: [PyYAML]
  patterns: [thin CLI wrapper around GuiAgent, OpenAI-compatible provider bridge, all-or-nothing optional retrieval bundle]
key-files:
  created: [.planning/phases/05-cli-extensions/05-01-SUMMARY.md, opengui/cli.py, opengui/__main__.py, tests/test_opengui_p5_cli.py]
  modified: [pyproject.toml]
key-decisions:
  - "The standalone CLI owns its config schema and OpenAI-compatible provider bridge so `opengui` never imports nanobot runtime code."
  - "Embedding-backed memory retrieval, skill search, and skill execution are enabled only as a bundle to avoid partial capability states."
patterns-established:
  - "CLI entry points in `opengui` should assemble existing runtime pieces and delegate execution to `GuiAgent.run()`."
  - "Machine-readable CLI output is isolated behind `--json`, while progress text uses the existing async progress callback."
requirements-completed: [CLI-01]
duration: unknown
completed: 2026-03-18
---

# Phase 5 Plan 1: Standalone CLI Summary

**Standalone `opengui` CLI with YAML config loading, OpenAI-compatible provider wiring, backend selection, and optional memory/skills bundle**

## Performance

- **Duration:** unknown (executor interrupted after verification because git writes are blocked in this sandbox)
- **Started:** unknown
- **Completed:** 2026-03-18T14:01:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added [`opengui/cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py) with argparse parsing, config loading from `~/.opengui/config.yaml`, backend factory selection, OpenAI-compatible chat and embedding adapters, and `GuiAgent` run orchestration.
- Added [`opengui/__main__.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/__main__.py) so the package has a direct module entry point that delegates to the CLI.
- Added [`tests/test_opengui_p5_cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_cli.py) to lock the CLI contract: task parsing, config/env fallback, backend variants, dry-run execution, JSON output, module delegation, and optional memory/skills bundle gating.
- Added `PyYAML>=6.0` to [`pyproject.toml`](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml) as a runtime dependency for the CLI config file.

## Task Commits

Git commits could not be created from this sandbox because writes inside `.git/` are denied (`.git/index.lock: Operation not permitted`). Task boundaries were still executed and verified atomically:

1. **Task 1: Create Phase 5 CLI tests and add runtime YAML parsing support** - not committed (`git index.lock` creation denied)
2. **Task 2: Implement the standalone CLI, provider bridge, backend factory, and optional memory/skills bundle** - not committed (`git index.lock` creation denied)

**Plan metadata:** not committed for the same reason.

## Files Created/Modified

- [`opengui/cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py) - Standalone CLI parser, YAML config loader, provider bridges, backend factory, and `GuiAgent` wiring.
- [`opengui/__main__.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/__main__.py) - Minimal package entry point delegating to `opengui.cli.main`.
- [`tests/test_opengui_p5_cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_cli.py) - Regression coverage for the full Phase 5 CLI contract.
- [`pyproject.toml`](/Users/jinli/Documents/Personal/nanobot_fork/pyproject.toml) - Adds the runtime YAML dependency needed by `~/.opengui/config.yaml`.

## Decisions Made

- Kept the provider and embedding adapters inside `opengui/cli.py` so the CLI stays self-contained and runtime-independent from nanobot.
- Reused `TrajectoryRecorder`, `GuiAgent`, and the async `progress_callback` seam rather than introducing a second execution pathway for CLI runs.
- Enabled memory retrieval, skill search, and skill execution together only when embedding config exists, preventing a half-enabled skill system.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Git commits could not be created because this sandbox cannot write inside `.git/` (`index.lock` creation fails with `Operation not permitted`). The implementation, tests, and summary were still completed successfully.

## User Setup Required

External services require manual configuration for real model-backed CLI runs.

- Provide `~/.opengui/config.yaml` with `provider.base_url` and `provider.model`.
- Set `OPENAI_API_KEY` when the config omits `provider.api_key`.
- Add optional `embedding` settings only if memory retrieval and skill execution should be enabled.

## Next Phase Readiness

- `CLI-01` is implemented and covered by targeted regression tests.
- The full test suite passes with the new CLI in place.
- Manual smoke tests for `--backend adb` and `--backend local` still require a configured model endpoint plus the appropriate device/desktop environment outside this sandbox.

## Self-Check: PASSED

- [x] [`opengui/cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/cli.py) exists
- [x] [`opengui/__main__.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/__main__.py) exists
- [x] [`tests/test_opengui_p5_cli.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_cli.py) exists
- [x] Targeted CLI and adapter regression passes: `9 passed`
- [x] Full test suite passes: `585 passed, 7 warnings`

