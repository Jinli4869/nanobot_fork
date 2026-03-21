---
phase: 19-operations-console
plan: 02
subsystem: api
tags: [fastapi, pydantic, nanobot-tui, operations, opengui, task-launch]
requires:
  - phase: 19-operations-console
    provides: runtime status DTOs, app-local operations registry, run_id-addressed inspection
provides:
  - typed launch request DTOs for the allowed nanobot and OpenGUI operations
  - async /tasks/runs launches backed by the shared operations registry
  - tui-local nanobot and OpenGUI adapters without CLI subprocess execution
affects: [19-03, operations-console, web-task-launch, runtime-status]
tech-stack:
  added: []
  patterns: [discriminated launch allowlist, registry-backed async task dispatch, tui-local OpenGUI adapters]
key-files:
  created: [tests/test_tui_p19_tasks.py]
  modified: [nanobot/tui/contracts.py, nanobot/tui/schemas/tasks.py, nanobot/tui/schemas/__init__.py, nanobot/tui/services/tasks.py, nanobot/tui/dependencies.py, nanobot/tui/routes/tasks.py]
key-decisions:
  - "Phase 17's read-only get_task_launch_contract() stays unchanged; the mutable Phase 19 launch contract is injected only through get_task_launch_service()."
  - "Nanobot-backed launches translate typed requests into private GuiSubagentTool task text inside nanobot/tui so the public API never exposes free-form task or prompt fields."
  - "OpenGUI-backed launches use tui-local backend adapters for local and dry-run execution instead of shelling out through opengui.cli."
patterns-established:
  - "Use discriminated unions plus extra=forbid to make unsupported browser launch shapes structurally impossible."
  - "Create queued run state synchronously, then advance the shared registry from an async background task to keep POST contracts immediate."
requirements-completed: [OPS-02]
duration: 11min
completed: 2026-03-21
---

# Phase 19 Plan 02: Operations Console Summary

**Typed browser-safe task launches for nanobot URL/settings flows and allowlisted OpenGUI app/settings actions, all returning immediate run ids through the shared registry**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-21T14:37:30Z
- **Completed:** 2026-03-21T14:48:26Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Added discriminated task-launch DTOs that only admit `nanobot_open_url`, `nanobot_open_settings`, `opengui_launch_app`, and `opengui_open_settings`.
- Implemented async `/tasks/runs` launches that create stable `run_id` values immediately and update the shared operations registry through queued, running, and terminal states.
- Kept browser-facing launch behavior under `nanobot/tui` by translating nanobot requests privately to `GuiSubagentTool` and handling OpenGUI requests through local or dry-run backend adapters instead of CLI subprocesses.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Wave 0 launch tests and explicit task-launch schemas** - `28c0065` (test)
2. **Task 2: Implement async launch orchestration over the shared run registry** - `e6b69d2` (feat)

## Files Created/Modified
- `tests/test_tui_p19_tasks.py` - Phase 19 launch-contract and orchestration coverage for accepted kinds, rejected unsafe payloads, immediate responses, and registry state transitions.
- `nanobot/tui/schemas/tasks.py` - Strict discriminated launch request models and immediate launch response DTO.
- `nanobot/tui/contracts.py` - Typed task-launch callable signature using the explicit request union and response model.
- `nanobot/tui/services/tasks.py` - Registry-backed launch orchestration plus private nanobot and OpenGUI adapters.
- `nanobot/tui/dependencies.py` - Task-launch service wiring, runtime launch availability, and adapter construction.
- `nanobot/tui/routes/tasks.py` - Browser capability route plus async `POST /tasks/runs`.

## Decisions Made
- Preserved Phase 17 compatibility by leaving `get_task_launch_contract()` read-only and introducing the mutable Phase 19 contract only in the actual launch-service dependency.
- Used direct OpenGUI backend actions for the allowlisted browser operations so the web surface reuses OpenGUI behavior without becoming a generic command runner.
- Marked runtime inspection as `task_launch_available=True` once the typed launch path existed so the runtime and launch surfaces stay aligned.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Switched verification to the documented pytest fallback**
- **Found during:** Task 1
- **Issue:** `uv run --extra dev pytest ...` failed locally while building `python-olm`, so the plan's default verification command was unavailable in this environment.
- **Fix:** Used the plan-approved fallback `.venv/bin/python -m pytest ...` for Task 1, Task 2, and final verification.
- **Files modified:** None
- **Verification:** `.venv/bin/python -m pytest tests/test_tui_p19_tasks.py tests/test_tui_p19_runtime.py tests/test_opengui_p3_nanobot.py tests/test_opengui_p16_host_integration.py -q`
- **Committed in:** `e6b69d2` (verification path only; no code change)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The fallback was already documented by the plan and did not broaden scope or change implementation.

## Issues Encountered
- Transient `.git/index.lock` conflicts appeared during parallel staging, so the remaining `git add` calls were retried sequentially.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 19 now has a narrow, typed browser launch surface with stable run ids and registry-backed status transitions.
- Plan 19-03 can build trace and log inspection on the same run ids and registry metadata without revisiting launch semantics.

## Self-Check: PASSED

- Found summary file at `.planning/phases/19-operations-console/19-operations-console-02-SUMMARY.md`
- Found task commit `28c0065`
- Found task commit `e6b69d2`

---
*Phase: 19-operations-console*
*Completed: 2026-03-21*
