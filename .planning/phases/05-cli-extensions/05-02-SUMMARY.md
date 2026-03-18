---
phase: 05-cli-extensions
plan: 02
subsystem: testing
tags: [docs, protocols, adapters, opengui, pytest]
requires:
  - phase: 02-agent-loop-integration
    provides: Stable opengui protocol seams that host adapters conform to
  - phase: 03-nanobot-subagent
    provides: NanobotLLMAdapter as a real adapter reference
provides:
  - Repo-root ADAPTERS.md guide for host LLMProvider and DeviceBackend adapters
  - Protocol-level pointer from opengui/interfaces.py to the adapter guide
  - Docs regression tests for EXT-01 content requirements
affects: [05-01-PLAN.md, host-integrations, future-claw-adapters]
tech-stack:
  added: []
  patterns: [repo-root adapter guide plus protocol pointer, text-only docs regression tests]
key-files:
  created: [.planning/phases/05-cli-extensions/05-02-SUMMARY.md, ADAPTERS.md, tests/test_opengui_p5_adapters.py]
  modified: [opengui/interfaces.py]
key-decisions:
  - "Adapter documentation lives in repo-root ADAPTERS.md with a short pointer in opengui/interfaces.py."
  - "NanobotLLMAdapter is documented as a reference-only example and not a runtime dependency for opengui."
patterns-established:
  - "Protocol boundary docs live outside runtime modules, with a one-line code pointer at the protocol definition site."
  - "Documentation contracts are enforced with direct file-text pytest checks instead of runtime imports."
requirements-completed: [EXT-01]
duration: 8 min
completed: 2026-03-18
---

# Phase 5 Plan 2: Adapter Documentation Summary

**Repo-root adapter guide for LLMProvider and DeviceBackend, plus a protocol pointer and regression tests locking the EXT-01 contract**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-18T13:33:37Z
- **Completed:** 2026-03-18T13:41:37Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added [`ADAPTERS.md`](/Users/jinli/Documents/Personal/nanobot_fork/ADAPTERS.md) with explicit `LLMProvider` and `DeviceBackend` sections, a copy-paste `ExampleHostLLMAdapter` skeleton, and reference guidance for `NanobotLLMAdapter`.
- Added the required protocol-level pointer sentence in [`opengui/interfaces.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/interfaces.py) so adapter authors can find the full guide from the protocol boundary.
- Added passing docs regression tests in [`tests/test_opengui_p5_adapters.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_adapters.py) to lock the required headings, example class name, and reference links.

## Task Commits

Git commits could not be created from this sandbox because writes inside `.git/` are denied (`.git/index.lock: Operation not permitted`). Task boundaries were still executed and verified atomically:

1. **Task 1: Add docs regression tests for the adapter guide and in-code pointer** - not committed (`git index.lock` creation denied)
2. **Task 2: Write ADAPTERS.md and add the protocol-level pointer in interfaces.py** - not committed (`git index.lock` creation denied)

**Plan metadata:** not committed for the same reason.

## Files Created/Modified

- [`ADAPTERS.md`](/Users/jinli/Documents/Personal/nanobot_fork/ADAPTERS.md) - Host adapter guide covering the protocol contracts, wiring pattern, and starter LLM adapter skeleton.
- [`opengui/interfaces.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/interfaces.py) - Added the exact one-line pointer from the protocol definitions to the repo-root adapter guide and nanobot reference example.
- [`tests/test_opengui_p5_adapters.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_adapters.py) - Added direct text assertions for the adapter guide content contract and protocol pointer.

## Decisions Made

- Kept the real adapter guidance in a repo-root markdown file so the protocols module stays small and dependency-free.
- Documented `NanobotLLMAdapter` and [`nanobot/agent/gui_adapter.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/gui_adapter.py) as a production reference while stating explicitly that `opengui` runtime code must not import nanobot.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Git commits could not be created because this sandbox cannot write inside `.git/` (`index.lock` creation fails with `Operation not permitted`). The code, tests, summary, and planning files were still updated and verified in the workspace.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `EXT-01` is complete and now regression-tested.
- Future host integrations can use [`ADAPTERS.md`](/Users/jinli/Documents/Personal/nanobot_fork/ADAPTERS.md) as the starting point without reading nanobot internals first.
- Git commit creation still requires a rerun with `.git` write access if strict atomic commit history is required.

## Self-Check: PASSED

- [x] [`ADAPTERS.md`](/Users/jinli/Documents/Personal/nanobot_fork/ADAPTERS.md) exists
- [x] [`tests/test_opengui_p5_adapters.py`](/Users/jinli/Documents/Personal/nanobot_fork/tests/test_opengui_p5_adapters.py) exists
- [x] [`.planning/phases/05-cli-extensions/05-02-SUMMARY.md`](/Users/jinli/Documents/Personal/nanobot_fork/.planning/phases/05-cli-extensions/05-02-SUMMARY.md) exists
- [x] Targeted docs regression passes: `2 passed`
- [x] Pointer/reference links confirmed in [`opengui/interfaces.py`](/Users/jinli/Documents/Personal/nanobot_fork/opengui/interfaces.py) and [`ADAPTERS.md`](/Users/jinli/Documents/Personal/nanobot_fork/ADAPTERS.md)
