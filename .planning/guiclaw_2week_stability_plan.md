# GUICLaw Two-Week Stability Sprint Plan

## Goal
Raise success rate and reliability for system-app and single-app benchmark tasks, then scale to broader app coverage with traceable checkpoints and safe rollback.

## Rules (must follow)
1. One focused change per checkpoint commit.
2. Every checkpoint must include: changed files, validation command, and rollback pointer.
3. No mixed commits across unrelated modules.
4. Keep main execution path and observability path separately testable.

## Week 1: Reliability Core

### CP-S1: Failure taxonomy + trace labels
- Scope: classify timeout/stuck/popup/permission/locator failures in run trace.
- Primary files: `opengui/agent.py`, `opengui/trajectory/recorder.py`, `nanobot/tui/services/traces.py`
- Exit criteria:
  - Trace contains normalized `failure_label`.
  - Failure aggregation can run without manual log parsing.

### CP-S2: Fast execution / careful reasoning controller
- Scope: state machine for fast and careful modes with deterministic switching rules.
- Primary files: `opengui/agent.py`, `opengui/prompts/system.py`
- Exit criteria:
  - Mode switch visible in trace.
  - Repeated-action loops reduce in pilot tasks.

### CP-S3: Generic popup/permission guard
- Scope: add common-dialog detector and prioritized handling policy.
- Primary files: `opengui/agent.py`, `opengui/postprocessing.py`
- Exit criteria:
  - Popup interference tasks show lower timeout rate.

### CP-S4: Per-step observability completion
- Scope: each step is replayable with screenshot + action + model output + execution result.
- Primary files: `nanobot/tui/routes/traces.py`, `nanobot/tui/services/traces.py`, `nanobot/tui/web/src/features/operations/OperationsWorkspaceRoute.tsx`
- Exit criteria:
  - Operations UI can replay full step timeline for a run.

## Week 2: Evaluation Trust + Expansion

### CP-S5: Tiered benchmark pipeline
- Scope: split benchmarks into `system`, `single-app`, `cross-app` tiers.

### CP-S6: Ablation-ready toggles
- Scope: clean toggles for memory/skill/planner/evaluator.

### CP-S7: Statistical reporting
- Scope: repeated-run summary with confidence intervals and variance.

### CP-S8: Promotion gate
- Scope: define candidate thresholds (success rate, p95 latency, timeout rate, intervention rate).

## Rollback Strategy
1. Inspect checkpoints: `git log --oneline -n 30`
2. Temporary rollback test: `git checkout <commit_hash>`
3. Return to branch head: `git switch feat/opencua`
4. Stable rollback commit: `git revert <commit_hash>`
