# Phase 25: Multi-layer Execution - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement `ShortcutExecutor` and `TaskSkillExecutor` — the execution layer for the two-layer skill types defined in Phase 24. Executors handle step-by-step execution, pre/post contract verification, grounded parameter resolution through `GrounderProtocol`, conditional branch evaluation, and shortcut reference resolution. Storage, search, and GuiAgent integration are deferred to Phase 27.

</domain>

<decisions>
## Implementation Decisions

### Pre/post violation behavior
- Any failed StateDescriptor condition (pre or post) aborts execution immediately — no soft-continue path
- Violation produces a `ContractViolationReport` dataclass containing: `skill_id`, `step_index`, `failed_condition: StateDescriptor`, `boundary: Literal['pre', 'post']`
- `ShortcutExecutor.execute()` returns a result union: success payload **or** `ContractViolationReport` — not an exception, not a status enum
- The result type carries an `is_violation` discriminator so callers can pattern-match cleanly
- Both pre-condition failures (before step executes) and post-condition failures (after step executes) use the same abort-and-report policy

### Condition evaluation
- New `ConditionEvaluator` Protocol: `async def evaluate(condition: StateDescriptor, screenshot: Path) -> bool`
- Follows the existing `@runtime_checkable` Protocol pattern from `executor.py` (StateValidator, ActionGrounder, etc.)
- `ConditionEvaluator` is **optional** at construction — if not injected, conditions always pass (always-pass default)
- This keeps executors usable for dry-run and test scenarios with no live device/LLM dependency (satisfies SC4)
- Signature intentionally minimal: condition + screenshot path only — no full GroundingContext needed

### Shortcut resolution in TaskSkillExecutor
- TaskSkillExecutor accepts a `shortcut_resolver: Callable[[str], ShortcutSkill | None]` at construction
- Tests pass a lambda or dict-lookup; Phase 27 wires in the real store's `get_by_id`
- When `shortcut_id` cannot be resolved: fall back to any inline ATOM (SkillStep) fallback steps on the same node; if there are no fallback steps, abort with a structured missing-shortcut report
- TaskSkillExecutor receives an injected `ShortcutExecutor` instance at construction — explicit dependency, easy to stub, no implicit sub-executor construction

### param_bindings semantics
- `ShortcutRefNode.param_bindings: dict[str, str]` values are **literal concrete values** — passed directly into the ShortcutSkill's parameter slots with no expression evaluation
- When a binding is missing for a declared parameter slot: pass the step to `GrounderProtocol` as unresolved — the grounder resolves the target from the current screenshot
- No template expression syntax (`{{...}}`) in Phase 25 — defer to a future phase if dynamic binding is needed

### Claude's Discretion
- Module placement: new file(s) alongside existing `executor.py` (e.g. `shortcut_executor.py`) vs. extending it — given `executor.py` is already ~570 lines, a new file is reasonable
- Exact success result payload shape for `ShortcutExecutor.execute()` on happy path (e.g. list of step results, execution summary string)
- Whether `ConditionEvaluator` lives in `opengui/skills/` alongside `executor.py` or in `opengui/grounding/` alongside other evaluation-related protocols
- Naming of the `ContractViolationReport` type and whether it's defined in the same file as the executor

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/ROADMAP.md` — Phase 25 goal, requirements (EXEC-01 through EXEC-03), success criteria, and dependency on Phase 24
- `.planning/REQUIREMENTS.md` — Full v1.5 EXEC requirement definitions; EXEC-01 (ShortcutExecutor contract verification), EXEC-02 (TaskSkillExecutor shortcut/ATOM/branch handling), EXEC-03 (GrounderProtocol routing)

### Phase 24 contracts (build targets for this phase)
- `opengui/skills/shortcut.py` — `ShortcutSkill`, `StateDescriptor`, `ParameterSlot` — executor input types
- `opengui/skills/task_skill.py` — `TaskSkill`, `TaskNode`, `ShortcutRefNode`, `BranchNode` — task executor input types
- `opengui/grounding/protocol.py` — `GrounderProtocol`, `GroundingContext`, `GroundingResult` — grounding interface
- `opengui/grounding/llm.py` — `LLMGrounder` — reference implementation of GrounderProtocol
- `.planning/phases/24-schema-and-grounding/24-CONTEXT.md` — Phase 24 design decisions (param_bindings schema, TaskNode union, memory_context_id semantics)

### Existing executor patterns to follow
- `opengui/skills/executor.py` — `SkillExecutor`, `StateValidator`, `ActionGrounder`, `ScreenshotProvider`, `SkillExecutionResult` — existing Protocol injection patterns and result dataclass shapes that new executors should mirror
- `opengui/skills/data.py` — `SkillStep` — reused as ATOM fallback node in TaskSkill; ShortcutExecutor executes these directly
- `opengui/interfaces.py` — `LLMProvider`, `DeviceBackend` — `@runtime_checkable Protocol` pattern the new ConditionEvaluator must follow

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SkillExecutor` (`opengui/skills/executor.py`): Step-by-step executor for old-style `Skill` — review its `execute()` loop, `_resolve_action()`, and `StepResult` shape for structural reference
- `LLMStateValidator` (`opengui/skills/executor.py`): Existing string-based condition validator — can serve as a real `ConditionEvaluator` implementation if adapted to accept `StateDescriptor`
- `SkillExecutionResult`, `StepResult`, `SubgoalResult` (`opengui/skills/executor.py`): Frozen dataclass result types — new executors should produce analogous structures
- `ExecutionState` enum (`opengui/skills/executor.py`): Existing state enum — new executors may define their own or reuse

### Established Patterns
- Protocol-based injection via `@runtime_checkable` Protocol: `StateValidator`, `ActionGrounder`, `ScreenshotProvider`, `SubgoalRunner` all injected at `SkillExecutor` construction — `ConditionEvaluator` must follow this pattern
- Frozen dataclasses with `to_dict()` / `from_dict()` for all result and report types
- All public exports via `opengui/skills/__init__.py` with an explicit `__all__` — new executor types must be added there

### Integration Points
- `opengui/skills/__init__.py`: Must export `ShortcutExecutor`, `TaskSkillExecutor`, `ContractViolationReport`, and `ConditionEvaluator` (the new protocol)
- Phase 27 will wire `shortcut_resolver` callable from the ShortcutSkill store's `get_by_id` method
- Phase 26 (extraction) does not consume executors — it only uses Phase 24 schema types
- GuiAgent integration in Phase 27 will construct executor instances with real `ConditionEvaluator` and `GrounderProtocol` implementations

</code_context>

<specifics>
## Specific Ideas

- The injected-ShortcutExecutor pattern for TaskSkillExecutor mirrors how Phase 21's `PlanningContext` wraps planner-only inputs — explicit injection at construction keeps the dependency graph clear
- `ConditionEvaluator` always-pass default enables Phase 25 executors to run in dry-run and test modes with zero extra configuration, matching the existing `DryRunBackend` philosophy

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 25-multi-layer-execution*
*Context gathered: 2026-04-02*
