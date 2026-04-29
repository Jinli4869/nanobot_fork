# Phase 25: Multi-layer Execution - Research

**Researched:** 2026-04-02
**Domain:** OpenGUI multi-layer skill execution
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXEC-01 | ShortcutExecutor verifies pre/post contracts at each step boundary and reports violations | Use a dedicated `ShortcutExecutor` with per-step boundary checks, an optional `ConditionEvaluator`, and a typed result union returning `ContractViolationReport` on first failure |
| EXEC-02 | TaskSkillExecutor resolves shortcut references, executes ATOM fallback steps, and evaluates conditional branches | Implement a recursive `TaskNode` walker with three explicit node paths: shortcut ref, inline `SkillStep`, and `BranchNode` |
| EXEC-03 | Both executors route all action parameter resolution through GrounderProtocol | Centralize step execution in one helper that builds `GroundingContext`, calls `GrounderProtocol.ground()`, and converts `resolved_params` through `parse_action()` |
</phase_requirements>

## Summary

Phase 25 is the first runtime consumer of the Phase 24 contracts, so the main planning constraint is consistency with the existing OpenGUI execution style. The current [opengui/skills/executor.py](../../../../opengui/skills/executor.py) already establishes the repo's preferred patterns: protocol-based dependency injection, dataclass result objects, and isolated tests with fake backends. Phase 25 should reuse those patterns, but it must not inherit two legacy behaviors from `SkillExecutor`: fail-open validation and template-based grounding fallback.

The clean implementation boundary is a new phase-specific executor module under `opengui/skills/` that owns both `ShortcutExecutor` and `TaskSkillExecutor`, plus the new report/protocol types. `ShortcutExecutor` should be the only component that knows how to execute a `SkillStep` under Phase 25 semantics. `TaskSkillExecutor` should stay thin and recursive: resolve a `ShortcutRefNode`, delegate to the injected `ShortcutExecutor`, evaluate `BranchNode` via `ConditionEvaluator`, or run an inline `SkillStep` through the same shared step runner.

Grounding must be explicit and uniform. For any step that is not already concrete through `fixed_values`, the executor should capture an `Observation` with `backend.observe()`, build a `GroundingContext`, call the injected `GrounderProtocol`, and turn the returned `resolved_params` into an `Action` with `opengui.action.parse_action()`. That keeps executor logic independent of `LLMGrounder`, satisfies `EXEC-03`, and makes stub-grounder tests straightforward.

**Primary recommendation:** Implement a new multi-layer executor module that shares one `SkillStep` execution helper across both executors and treats `GrounderProtocol` + `ConditionEvaluator` as the only injected decision points.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | `>=3.11` | Async execution, dataclasses, protocols, pathlib | Repo baseline from `pyproject.toml`; all Phase 25 types fit naturally in stdlib async/dataclass patterns |
| `opengui.grounding.GrounderProtocol` | workspace current | Semantic target resolution | Phase 24 made this the stable contract for grounding; Phase 25 should not invent a parallel interface |
| `opengui.action.parse_action` | workspace current | Validate and normalize grounded params into `Action` | Prevents duplicate action-shape logic and reuses the canonical validation boundary |
| `opengui.interfaces.DeviceBackend` | workspace current | Observation + execution boundary | Already standard across all backends; Phase 25 should observe and execute only through this protocol |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | `9.0.2` | Unit test runner | Use for all phase tests; verified in `uv.lock` (uploaded 2025-12-06) |
| `pytest-asyncio` | `1.3.0` | Async executor tests | Use for `ShortcutExecutor` and `TaskSkillExecutor` async coverage; verified in `uv.lock` (uploaded 2025-11-10) |
| `DryRunBackend` | workspace current | Zero-device backend for isolated tests | Useful when you want real `observe()`/`execute()` shapes without live hardware |
| `LLMGrounder` | workspace current | Production `GrounderProtocol` implementation | Use only as the default real grounder; do not couple executor logic to it |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New multi-layer executor module | Extend legacy `opengui/skills/executor.py` | Avoids a new file, but it mixes incompatible semantics into an already large module and makes Phase 25 harder to test and evolve |
| `parse_action()` from grounded payloads | Hand-build `Action(...)` objects | Slightly shorter code, but duplicates validation and increases drift from the agent/backend action path |
| `ConditionEvaluator` over `StateDescriptor` | Custom branch-expression parser | More flexible on paper, but unnecessary for the locked Phase 24 schema and adds avoidable parsing complexity |

**Installation:**
```bash
uv sync --extra dev
```

**Version verification:** Networkless research means current registry checks were not possible here. Versions were verified from local repo sources: `pyproject.toml` and `uv.lock` (`pytest 9.0.2`, `pytest-asyncio 1.3.0`, `pydantic 2.12.5`, `ruff 0.15.7`).

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
├── grounding/
│   ├── protocol.py              # existing GrounderProtocol + GroundingContext
│   └── llm.py                   # existing LLMGrounder
└── skills/
    ├── executor.py              # legacy SkillExecutor; leave untouched
    ├── multi_layer_executor.py  # new ShortcutExecutor, TaskSkillExecutor, reports
    └── __init__.py              # export new executors/protocols/reports

tests/
└── test_opengui_p25_multi_layer_execution.py
```

### Pattern 1: Shared Step Runner for Both Executors
**What:** Put all `SkillStep` runtime logic in one internal helper used by both `ShortcutExecutor` and inline ATOM execution in `TaskSkillExecutor`.
**When to use:** Every time a `SkillStep` needs observation, grounding, action construction, and backend execution.
**Example:**
```python
# Source: repo pattern adapted from opengui/skills/executor.py and opengui/grounding/protocol.py
async def _execute_step(
    step: SkillStep,
    *,
    backend: DeviceBackend,
    grounder: GrounderProtocol,
    parameter_slots: tuple[ParameterSlot, ...],
    task_hint: str | None,
    screenshot_path: Path,
) -> StepExecutionRecord:
    observation = await backend.observe(screenshot_path)
    context = GroundingContext(
        screenshot_path=screenshot_path,
        observation=observation,
        parameter_slots=parameter_slots,
        task_hint=task_hint,
    )
    grounding = await grounder.ground(step.target, context)
    action = parse_action({"action_type": step.action_type, **grounding.resolved_params})
    backend_result = await backend.execute(action)
    return StepExecutionRecord(action=action, grounding=grounding, backend_result=backend_result)
```

### Pattern 2: Boundary Contracts Are Checked Around Every Step
**What:** Evaluate all shortcut preconditions before each step and all postconditions after each step, aborting immediately on the first failure.
**When to use:** Only inside `ShortcutExecutor`; `TaskSkillExecutor` delegates shortcut semantics to it.
**Example:**
```python
# Source: locked phase decision in 25-CONTEXT.md
for step_index, step in enumerate(shortcut.steps):
    for condition in shortcut.preconditions:
        if not await evaluator.evaluate(condition, screenshot_before):
            return ContractViolationReport(
                skill_id=shortcut.skill_id,
                step_index=step_index,
                failed_condition=condition,
                boundary="pre",
            )

    step_result = await _execute_step(...)

    for condition in shortcut.postconditions:
        if not await evaluator.evaluate(condition, screenshot_after):
            return ContractViolationReport(
                skill_id=shortcut.skill_id,
                step_index=step_index,
                failed_condition=condition,
                boundary="post",
            )
```

### Pattern 3: Task Execution Is a Recursive `TaskNode` Walker
**What:** `TaskSkillExecutor` handles exactly the three Phase 24 node types and delegates shortcut execution instead of duplicating it.
**When to use:** For the top-level `TaskSkill.steps` tuple and branch subtrees.
**Example:**
```python
# Source: repo schema from opengui/skills/task_skill.py
async def _run_node(node: TaskNode) -> TaskNodeOutcome:
    if isinstance(node, ShortcutRefNode):
        shortcut = shortcut_resolver(node.shortcut_id)
        if shortcut is not None:
            return await shortcut_executor.execute(shortcut, params=node.param_bindings)
        if fallback_atom is not None:
            return await _execute_step(fallback_atom, ...)
        return MissingShortcutReport(task_skill_id=task.skill_id, shortcut_id=node.shortcut_id)

    if isinstance(node, SkillStep):
        return await _execute_step(node, ...)

    branch_taken = await condition_evaluator.evaluate(node.condition, screenshot_path)
    branch = node.then_steps if branch_taken else node.else_steps
    return [await _run_node(child) for child in branch]
```

### Anti-Patterns to Avoid
- **Extending legacy fail-open behavior:** `SkillExecutor` allows missing validators and template fallbacks. Phase 25 must return structured reports on contract failure and keep semantic grounding behind `GrounderProtocol`.
- **Duplicating step execution logic in both executors:** That guarantees drift in grounding, screenshots, and result payloads. Share one helper.
- **Treating `param_bindings` as templates:** The locked decision says bindings are literal concrete values in Phase 25. Do not evaluate `{{...}}`.
- **Adding direct store dependencies:** Use the injected `shortcut_resolver` callable now; Phase 27 will wire storage later.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Action validation | Custom `dict -> Action` mapper inside each executor | `opengui.action.parse_action()` | Centralizes aliases, coordinate validation, and required-field checks |
| Screenshot capture state | Ad hoc screenshot provider stack | `DeviceBackend.observe()` + `Observation` | Grounding already depends on `Observation`; use one backend truth source |
| Branch/contract expression engine | New mini DSL or string parser | `StateDescriptor` + `ConditionEvaluator` | Phase 24 already fixed the condition schema; new syntax adds complexity without requirement coverage |
| Shortcut lookup ownership | Embedded store/index inside executor | Injected `shortcut_resolver` callable | Keeps Phase 25 storage-free and testable with dict/lambda fakes |
| LLM-specific grounding path | Special cases for `LLMGrounder` | `GrounderProtocol` only | Required for swappable stub grounders and isolated tests |

**Key insight:** Almost all Phase 25 complexity is orchestration, not new domain logic. Reuse the existing contracts and keep the executors as thin coordinators.

## Common Pitfalls

### Pitfall 1: Checking Contracts Only Once Per Skill
**What goes wrong:** Preconditions pass before step 1, later UI drift occurs, but the executor never detects it.
**Why it happens:** It is natural to read shortcut pre/post conditions as skill-level checks.
**How to avoid:** Follow the locked decision literally: evaluate the preconditions before each step and the postconditions after each step.
**Warning signs:** Tests only cover failure before the first step or after the final step.

### Pitfall 2: Reusing Template Grounding from `SkillExecutor`
**What goes wrong:** Inline ATOM execution appears to work even when the grounder is missing or ignored, masking `EXEC-03` regressions.
**Why it happens:** The legacy executor falls back to `_ground_text()` template substitution.
**How to avoid:** In Phase 25, semantic parameter resolution should go through `GrounderProtocol`; only fully concrete `fixed_values` should bypass grounding.
**Warning signs:** Swapping in a stub grounder does not change execution output.

### Pitfall 3: Coupling `TaskSkillExecutor` to Shortcut Storage
**What goes wrong:** Task execution silently grows store/search responsibilities that belong to Phase 27.
**Why it happens:** Resolving `shortcut_id` by lookup feels like executor work.
**How to avoid:** Accept `shortcut_resolver: Callable[[str], ShortcutSkill | None]` and keep resolution outside the executor.
**Warning signs:** The executor imports store modules or search/index types.

### Pitfall 4: Making `ConditionEvaluator` Too Smart
**What goes wrong:** The protocol starts depending on `Observation`, backend state, or grounding internals, making dry-run tests harder.
**Why it happens:** It is tempting to align branch evaluation with full grounding context.
**How to avoid:** Keep the locked signature: `condition + screenshot path -> bool`.
**Warning signs:** Constructor needs backend or LLM objects just to instantiate a fake evaluator.

### Pitfall 5: Losing the Inline ATOM Fallback Path
**What goes wrong:** Missing shortcuts become hard failures even when the task node could execute directly.
**Why it happens:** `ShortcutRefNode` and `SkillStep` are separate node types, so fallback semantics are easy to implement incompletely.
**How to avoid:** Decide in planning how the inline fallback step is represented at the task level and test both "resolved shortcut" and "missing shortcut -> ATOM fallback" paths explicitly.
**Warning signs:** There is no failing test for unresolved `shortcut_id` with a provided fallback step.

## Code Examples

Verified patterns from repo sources:

### Runtime-Checkable Protocol
```python
# Source: opengui/interfaces.py and opengui/grounding/protocol.py
@runtime_checkable
class ConditionEvaluator(Protocol):
    async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool: ...
```

### Grounding Context Assembly
```python
# Source: opengui/grounding/protocol.py
context = GroundingContext(
    screenshot_path=screenshot_path,
    observation=observation,
    parameter_slots=shortcut.parameter_slots,
    task_hint=shortcut.description,
)
grounding = await grounder.ground(step.target, context)
```

### Stub-Grounder Test Pattern
```python
# Source: test style adapted from tests/test_opengui_p24_schema_grounding.py
class FakeGrounder:
    async def ground(self, target: str, context: GroundingContext) -> GroundingResult:
        return GroundingResult(
            grounder_id="fake:test",
            confidence=1.0,
            resolved_params={"text": f"resolved:{target}"},
            fallback_metadata=None,
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-layer `Skill` executed by legacy `SkillExecutor` | Two-layer `ShortcutSkill` + `TaskSkill` from Phase 24 | 2026-04-02 / Phase 24 | Phase 25 must execute schema types that the legacy executor does not understand |
| String `valid_state` checks with fail-open semantics | Structured `StateDescriptor` checks with typed violation reports | Locked for Phase 25 on 2026-04-02 | Contract failures become explicit outputs, not hidden success paths |
| Template substitution fallback for unresolved params | GrounderProtocol-mediated grounding | Phase 24 introduced protocol on 2026-04-02 | Swapping grounders must change behavior without changing executor code |

**Deprecated/outdated:**
- Extending `SkillExecutor` for Phase 25 semantics: wrong abstraction boundary and wrong failure model.
- `{{...}}` expression semantics inside `ShortcutRefNode.param_bindings`: explicitly deferred.
- Store-backed shortcut lookup inside the executor: deferred to Phase 27 wiring.

## Open Questions

1. **Where should screenshot artifacts live for executor-only runs?**
   - What we know: `DeviceBackend.observe()` requires a `Path`, and the agent uses a run-dir `screenshots/step_XXX.png` convention.
   - What's unclear: Whether Phase 25 should accept a caller-provided screenshot/work dir or create temporary paths internally.
   - Recommendation: Decide this in planning. Prefer a caller-provided `work_dir: Path` or small path-factory helper so tests can use `tmp_path` deterministically.

2. **How rich should happy-path results be?**
   - What we know: The context only locks the failure/report shape, not the exact success payload.
   - What's unclear: Whether the planner should introduce one shared `StepExecutionRecord` type, or keep success payloads minimal and phase-local.
   - Recommendation: Use a small frozen success dataclass with executed actions, backend results, and a short summary. Do not over-design cross-phase result history yet.

3. **How should missing-shortcut fallback be represented in `TaskSkill` execution?**
   - What we know: The locked decision requires ATOM fallback when resolution fails and a structured report when no fallback exists.
   - What's unclear: The current `ShortcutRefNode` schema does not embed fallback steps directly, so the implementation needs a clear local convention for "same node" fallback handling.
   - Recommendation: Resolve this explicitly in planning before coding. If no schema extension is allowed, document a deterministic executor rule for adjacent inline `SkillStep` fallback and test it.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.2` + `pytest-asyncio 1.3.0` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXEC-01 | Pre/post contract failure returns `ContractViolationReport` with boundary + failed descriptor and aborts immediately | unit | `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q -k contract` | ❌ Wave 0 |
| EXEC-02 | Task executor resolves shortcut refs, evaluates branches, and uses inline ATOM fallback or missing-shortcut report | unit | `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q -k task_executor` | ❌ Wave 0 |
| EXEC-03 | Swapping stub grounders changes resolved action parameters without touching executor logic | unit | `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q -k grounder` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p25_multi_layer_execution.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p24_schema_grounding.py tests/test_opengui_p1_skills.py tests/test_opengui_p25_multi_layer_execution.py -q`
- **Phase gate:** `uv run pytest -q`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p25_multi_layer_execution.py` — covers EXEC-01, EXEC-02, EXEC-03
- [ ] Stub helpers inside the new Phase 25 test file for backend, grounder, evaluator, and resolver seams

## Sources

### Primary (HIGH confidence)
- `.planning/phases/25-multi-layer-execution/25-CONTEXT.md` - locked decisions, phase boundary, and required semantics
- `.planning/REQUIREMENTS.md` - authoritative EXEC-01 through EXEC-03 requirement text
- `.planning/ROADMAP.md` - Phase 25 success criteria and dependency boundary
- `opengui/skills/executor.py` - existing executor patterns, protocol injection style, and legacy behaviors to avoid
- `opengui/skills/shortcut.py` - `ShortcutSkill`, `ParameterSlot`, and `StateDescriptor` runtime inputs
- `opengui/skills/task_skill.py` - `TaskNode` union and task-level node shapes
- `opengui/grounding/protocol.py` - `GrounderProtocol`, `GroundingContext`, and `GroundingResult`
- `opengui/grounding/llm.py` - production `GrounderProtocol` implementation contract
- `opengui/action.py` - canonical action validation and normalization boundary
- `opengui/interfaces.py` - `@runtime_checkable Protocol` style and backend contract
- `pyproject.toml` and `uv.lock` - Python/runtime/test stack versions
- `tests/test_opengui_p1_skills.py` - existing executor test style
- `tests/test_opengui_p24_schema_grounding.py` - existing grounding/schema protocol test style

### Secondary (MEDIUM confidence)
- None

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Verified from repo contracts, `pyproject.toml`, and `uv.lock`
- Architecture: HIGH - Derived from locked phase decisions and existing executor/grounding code
- Pitfalls: HIGH - Directly tied to known legacy behaviors and the Phase 25 success criteria

**Research date:** 2026-04-02
**Valid until:** 2026-05-02
