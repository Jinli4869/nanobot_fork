# Phase 30: Stable Shortcut Execution and Fallback - Research

**Researched:** 2026-04-03
**Domain:** Live shortcut binding, settle/verification guards, and safe fallback in the GuiAgent runtime path
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SUSE-03 | Shortcut execution binds live parameters and targets from the current observation instead of replaying stale recorded coordinates or assumptions. | `ShortcutExecutor._execute_step()` already calls `GrounderProtocol.ground()` for non-fixed steps using a live screenshot and observation from `backend.observe()`. The gap is that `ShortcutExecutor` is not currently wired into the `GuiAgent` runtime path for the new shortcut candidates selected by Phase 29 — only the legacy `SkillExecutor` is wired. Phase 30 must connect the Phase 25 `ShortcutExecutor` (which already binds live parameters via `LLMGrounder`) to the Phase 29 applicability-approved shortcut path inside `GuiAgent.run()`. |
| SUSE-04 | If a shortcut becomes invalid or unavailable mid-run, execution falls back cleanly to task-level or default agent behavior without terminating an otherwise recoverable task. | `ContractViolationReport` from `ShortcutExecutor.execute()` already carries structured failure signals (step index, failed condition, boundary). The gap is that `GuiAgent.run()` currently does not call `ShortcutExecutor.execute()` for Phase 29-selected shortcuts — it re-uses the legacy `SkillExecutor` path which has incompatible fail-open semantics. Phase 30 must route Phase 29 `outcome="run"` decisions through `ShortcutExecutor.execute()`, handle `ContractViolationReport` and exceptions by falling back to free agent exploration, and guarantee the task is never worse off than if the shortcut had been skipped. |
| SSTA-01 | Each shortcut step waits for action completion and captures the next observation only after the UI has settled enough to evaluate the effect. | `ShortcutExecutor.execute()` already captures a `post_screenshot_path` by calling `backend.observe()` after `backend.execute()` for each step. However, there is NO settle wait between `execute()` and the post-step `observe()` in the current Phase 25 implementation. The existing `GuiAgent._post_action_settle_seconds()` and `_POST_ACTION_SETTLE_SECONDS = 0.50` pattern is the model to follow — Phase 30 must add an action-type-aware settle wait inside `ShortcutExecutor._execute_step()` (or after `backend.execute()` in the loop) before the post-step observe call. |
| SSTA-02 | Shortcut execution verifies post-step state after every action and surfaces structured failure reasons when drift or contract violations occur. | `ShortcutExecutor.execute()` already checks `shortcut.postconditions` after each step using `ConditionEvaluator.evaluate()` and returns `ContractViolationReport(boundary="post")` on the first failure. The gap is: (a) the `post_screenshot_path` observe call does NOT currently wait for settle before capturing the verification screenshot; (b) the full set of `postconditions` only reflects shortcut-level conditions, not per-step expected state from `SkillStep.expected_state`; and (c) `ContractViolationReport` is never surfaced to `GuiAgent` — the Phase 29 execution path bypasses `ShortcutExecutor` entirely. All three gaps are addressed by Phase 30. |

</phase_requirements>

## Summary

Phase 30 completes the shortcut execution pipeline that Phase 29 started. Phase 29 delivered selection: it can retrieve candidates and approve one for execution. Phase 30 delivers execution: the approved shortcut must be run through `ShortcutExecutor` (not the legacy `SkillExecutor`), with settle timing between action and post-step observation, structured failure signals surfaced on violation or drift, and a guarantee that shortcut failure never leaves the task worse off than if no shortcut had been attempted.

The codebase already has all the necessary building blocks. `ShortcutExecutor` in `multi_layer_executor.py` implements pre/post condition checking, grounder-based live binding, and `ContractViolationReport` for structured failures. `GuiAgent` has `_POST_ACTION_SETTLE_SECONDS` and `_post_action_settle_seconds()` for settle timing. `LLMGrounder` is the live binding mechanism for non-fixed steps. What is missing is the wiring that connects Phase 29's `outcome="run"` decision to `ShortcutExecutor.execute()`, a settle wait inside the shortcut executor's per-step loop, and a fallback handler that translates `ContractViolationReport` back to free agent exploration without task termination.

The three plans map cleanly to: (1) live binding — wire `ShortcutExecutor` into the nanobot path with `LLMGrounder` and call it from `GuiAgent.run()`; (2) settle and post-step validation — add settle timing and verify SSTA-01/SSTA-02 behavior through the new executor path; (3) fallback — handle `ContractViolationReport` and exceptions by clearing shortcut state and continuing with the normal agent loop.

**Primary recommendation:** Route Phase 29-approved shortcuts through `ShortcutExecutor.execute()` in `GuiAgent.run()`, inject settle timing inside `ShortcutExecutor` after `backend.execute()`, and translate all failure forms (`ContractViolationReport`, exceptions, no-settle fallback) into structured signals that let the retry loop continue without the shortcut.

## Standard Stack

### Core

| Module | Version | Purpose | Why Standard |
|--------|---------|---------|--------------|
| `opengui/skills/multi_layer_executor.py` — `ShortcutExecutor` | workspace current | Step-by-step shortcut execution with pre/post condition checking and grounder-based live binding | Phase 25 shipped this with the exact contract Phase 30 needs; it is NOT the legacy `SkillExecutor` |
| `opengui/skills/multi_layer_executor.py` — `ContractViolationReport` | workspace current | Structured failure signal when a condition fails; `is_violation=True` discriminator | Already returned by `ShortcutExecutor.execute()` on pre or post condition failure |
| `opengui/skills/multi_layer_executor.py` — `ShortcutExecutionSuccess` | workspace current | Returned by `ShortcutExecutor.execute()` when all steps complete | `step_results` tuple carries per-step records for telemetry and fallback accounting |
| `opengui/grounding/llm.py` — `LLMGrounder` | workspace current | Resolves semantic step targets to concrete action parameters using live screenshot + observation | Implements `GrounderProtocol`; used in `ShortcutExecutor._execute_step()` for non-fixed steps |
| `opengui/grounding/protocol.py` — `GrounderProtocol`, `GroundingContext`, `GroundingResult` | workspace current | Protocol contract for grounding; `GroundingContext` carries screenshot and observation for live binding | Phase 24 defined the contract; `ShortcutExecutor` already consumes it |
| `opengui/agent.py` — `GuiAgent` | workspace current | Top-level runtime; `run()` is the main change target for Phase 30 wiring | Phase 29 already introduced the `shortcut_candidates` retrieval and `_evaluate_shortcut_applicability` gate |
| `opengui/skills/shortcut.py` — `ShortcutSkill` | workspace current | The shortcut schema; `steps`, `preconditions`, `postconditions`, `parameter_slots` | Phase 25 executor consumes this directly |
| `opengui/interfaces.py` — `DeviceBackend` | workspace current | `execute()` and `observe()` called per step inside `ShortcutExecutor` | Already used; settle timing slots in after `execute()` and before the post-step `observe()` |

### Supporting

| Module | Version | Purpose | When to Use |
|--------|---------|---------|-------------|
| `opengui/skills/executor.py` — `LLMStateValidator` | workspace current | Implements both `StateValidator` (for legacy `SkillExecutor`) and acts as the `ConditionEvaluator` for `ShortcutApplicabilityRouter` | Already wired in nanobot path; Phase 30 passes it as the `ConditionEvaluator` for `ShortcutExecutor` |
| `opengui/trajectory/recorder.py` — `TrajectoryRecorder.record_event` | workspace current | Emit structured events for shortcut execution outcome, violation, and fallback | Follow `shortcut_retrieval` / `shortcut_applicability` event patterns from Phase 29 |
| `pytest`, `pytest-asyncio` | workspace locked | Phase 30 regression tests | Existing test infrastructure; new test file `test_opengui_p30_stable_shortcut_execution.py` |
| `asyncio.sleep` | stdlib | Settle wait between `backend.execute()` and post-step `backend.observe()` | Already used in `GuiAgent._run_step()` via `_post_action_settle_seconds()` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ShortcutExecutor` for Phase 29-approved shortcuts | Legacy `SkillExecutor` | `SkillExecutor` has fail-open semantics and template-substitution fallback that are incompatible with SUSE-03/SSTA-02; it does not use `GrounderProtocol` and cannot produce `ContractViolationReport` |
| `asyncio.sleep` settle inside `ShortcutExecutor` | Caller-side settle in `GuiAgent.run()` | Caller-side settle would require duplicating action-type inspection outside the executor; executor-internal settle keeps the contract self-contained and lets the same settle logic apply when `ShortcutExecutor` is called from `TaskSkillExecutor` |
| Per-step `postconditions` checks | Shortcut-level `postconditions` only | Shortcut-level conditions are coarse; per-step `expected_state` from `SkillStep` enables finer-grained drift detection. However, Phase 30 should NOT redesign the `ShortcutSkill` schema — use the existing `postconditions` tuple for now and leave per-step validation to Phase 31 extensions |

**Installation:** No new packages. `asyncio`, `dataclasses`, `typing`, `pytest` already present.

## Architecture Patterns

### Recommended Project Structure

```
opengui/
├── agent.py                              # extend run() to call ShortcutExecutor for approved shortcuts
└── skills/
    └── multi_layer_executor.py           # add settle wait in ShortcutExecutor._execute_step() or after execute()

nanobot/
└── agent/tools/gui.py                   # wire LLMGrounder + ShortcutExecutor into GuiAgent construction

tests/
└── test_opengui_p30_stable_shortcut_execution.py   # NEW: Phase 30 focused coverage
```

### Pattern 1: ShortcutExecutor Wiring in GuiAgent.run()

**What:** When Phase 29's `_evaluate_shortcut_applicability()` returns `outcome="run"`, the approved `ShortcutSkill` must be executed via `ShortcutExecutor.execute()` rather than the legacy `SkillExecutor`.

**Why:** `ShortcutExecutor` uses `GrounderProtocol` for live binding (SUSE-03), checks pre/post conditions (SSTA-02), and returns `ContractViolationReport` for structured failure signaling (SUSE-04). `SkillExecutor` has none of these semantics.

**Insertion point:** In `GuiAgent.run()`, inside the `if applicability_decision.outcome == "run":` block (currently handling the legacy path), replace the `self._skill_executor.execute(matched_skill)` call with a call to a new `self._shortcut_executor` that is a `ShortcutExecutor` instance.

**Current code (Phase 29 shape):**
```python
# opengui/agent.py GuiAgent.run() — Phase 29 shape (from code inspection)
if approved is not None:
    matched_skill = approved.skill
    ...
    if self._skill_executor is not None:
        skill_result = await self._skill_executor.execute(matched_skill)
        # skill_result.state.value gives "succeeded" or not
```

**Phase 30 shape:**
```python
# opengui/agent.py GuiAgent.run() — Phase 30 shape
if approved is not None:
    matched_skill = approved.skill
    ...
    if self._shortcut_executor is not None:
        shortcut_result = await self._shortcut_executor.execute(matched_skill)
        if shortcut_result.is_violation:
            # ContractViolationReport — structured failure, fall through to free exploration
            self._trajectory_recorder.record_event(
                "shortcut_execution",
                outcome="violation",
                skill_id=shortcut_result.skill_id,
                step_index=shortcut_result.step_index,
                boundary=shortcut_result.boundary,
                failed_condition=shortcut_result.failed_condition.to_dict(),
            )
            # Do NOT set skill_context — let the normal retry loop handle it
        else:
            # ShortcutExecutionSuccess — build skill_context from step_results
            skill_context = _build_shortcut_execution_summary(shortcut_result)
```

### Pattern 2: ShortcutExecutor Construction in the Nanobot Host Path

**What:** `ShortcutExecutor` requires `backend`, `grounder`, and optional `condition_evaluator`. In `nanobot/agent/tools/gui.py`, construct it alongside the existing `SkillExecutor` when `enable_skill_execution=True`.

**Why:** `LLMGrounder` wraps the same `_llm_adapter` already used for `SkillExecutor`. The `ConditionEvaluator` for `ShortcutExecutor` is the same `LLMStateValidator` (which is already wired to `ShortcutApplicabilityRouter`). Using the same instances avoids redundant LLM adapter construction.

**Important:** `LLMStateValidator.validate(valid_state, screenshot)` takes a `str` + `Path`; `ConditionEvaluator.evaluate(condition: StateDescriptor, screenshot: Path)` takes a `StateDescriptor` + `Path`. These are DIFFERENT protocols. `LLMStateValidator` does NOT implement `ConditionEvaluator` directly — an adapter or a separate `LLMConditionEvaluator` that wraps `LLMStateValidator` is needed, OR the `LLMGrounder`-based vision LLM call is used directly. This is the key architectural decision Phase 30 must make:

- **Option A (Simpler):** Create a thin `LLMConditionEvaluator` adapter in `opengui/skills/` that wraps `LLMStateValidator` and maps `StateDescriptor.value` to the `valid_state` string, implementing `ConditionEvaluator.evaluate()`.
- **Option B:** Re-use `LLMStateValidator` directly but add an `evaluate()` method shim.

The codebase uses `state_validator` (an `LLMStateValidator`) as the `ConditionEvaluator` for `ShortcutApplicabilityRouter` in the Phase 29 wiring (see `nanobot/agent/tools/gui.py` line 255-256). This WORKS because `ShortcutApplicabilityRouter.__init__` accepts `object | None` and calls `self._evaluator.evaluate(condition, screenshot)` via duck typing. `LLMStateValidator` does NOT have an `evaluate()` method — it has `validate()`. This means the Phase 29 wiring has a mismatch that is hidden by `_AlwaysPassEvaluator` fallback in tests. **Phase 30 must resolve this gap explicitly.**

**Resolution:** Create a `LLMConditionEvaluator` adapter class that wraps `LLMStateValidator` and implements the `ConditionEvaluator` protocol with `async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool`. This adapter calls `self._validator.validate(condition.value, screenshot)`.

```python
# NEW: opengui/skills/shortcut_executor_adapter.py or added to multi_layer_executor.py
class LLMConditionEvaluator:
    """Adapts LLMStateValidator to the ConditionEvaluator protocol.

    Maps StateDescriptor.value to the valid_state string for LLM-based evaluation.
    """
    def __init__(self, state_validator: LLMStateValidator) -> None:
        self._validator = state_validator

    async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool:
        return await self._validator.validate(condition.value, screenshot)
```

**Wiring in nanobot/agent/tools/gui.py:**
```python
# After constructing state_validator...
from opengui.skills.multi_layer_executor import ShortcutExecutor, LLMConditionEvaluator
from opengui.grounding.llm import LLMGrounder

condition_evaluator = LLMConditionEvaluator(state_validator)
shortcut_executor = ShortcutExecutor(
    backend=active_backend,
    grounder=LLMGrounder(llm=self._llm_adapter),
    condition_evaluator=condition_evaluator,
    screenshot_dir=run_dir / "shortcut_screenshots",
)

# Also fix ShortcutApplicabilityRouter to use condition_evaluator (not raw state_validator)
shortcut_applicability_router = ShortcutApplicabilityRouter(
    condition_evaluator=condition_evaluator,
)
```

### Pattern 3: Settle Timing in ShortcutExecutor

**What:** Add an action-type-aware settle wait between `backend.execute(action)` and the post-step `backend.observe(post_screenshot_path)` inside `ShortcutExecutor.execute()`.

**Why:** SSTA-01 requires "waits for action completion and captures the next observation only after the UI has settled enough." Currently, `ShortcutExecutor.execute()` calls `backend.execute()` and immediately calls `backend.observe()` for postconditions with no settle delay. The main agent loop has `_POST_ACTION_SETTLE_SECONDS = 0.50` and `_NO_SETTLE_ACTIONS` for this exact purpose — Phase 30 must apply the same policy inside the shortcut executor.

**Settle policy (matches GuiAgent):**
- `_POST_ACTION_SETTLE_SECONDS = 0.50` seconds for all coordinate/input/app actions
- No settle for `wait`, `done`, `request_intervention`
- Action types without coordinates (hotkey, back, home) still get the 0.50 settle

**Implementation inside `ShortcutExecutor.execute()` loop:**
```python
# After: backend_result = await self.backend.execute(action, timeout=timeout)
# Before: post_screenshot_path = self._screenshot_path(...)
settle = self._settle_seconds_for(action)
if settle > 0:
    await asyncio.sleep(settle)

# Then: await self.backend.observe(post_screenshot_path, timeout=timeout)

# Private method on ShortcutExecutor:
_POST_ACTION_SETTLE_SECONDS: ClassVar[float] = 0.50
_NO_SETTLE_ACTIONS: ClassVar[frozenset[str]] = frozenset({
    "wait", "done", "request_intervention"
})

def _settle_seconds_for(self, action: Action) -> float:
    if action.action_type in self._NO_SETTLE_ACTIONS:
        return 0.0
    return self._POST_ACTION_SETTLE_SECONDS
```

**The `settle_seconds` value should be configurable** at `ShortcutExecutor` construction time (defaulting to `0.50`) so backends with different settle characteristics (mobile vs. desktop) can override it without changing the class.

### Pattern 4: Fallback from ContractViolation to Free Agent Exploration

**What:** When `ShortcutExecutor.execute()` returns `ContractViolationReport`, the shortcut has drifted from its expected state. `GuiAgent.run()` must surface a structured event, clear shortcut state, and let the retry loop continue from the point of failure rather than restarting from scratch or terminating the task.

**Why:** SUSE-04 states "execution falls back cleanly to task-level or default agent behavior without terminating an otherwise recoverable task." SUSTA success criterion 4 states "a failed shortcut never makes the task path worse than if shortcut reuse had been skipped entirely."

**Fallback contract:**
1. Log a `shortcut_execution` trajectory event with `outcome="violation"`, `skill_id`, `step_index`, `boundary`, `failed_condition`.
2. Set `matched_skill = None` and `skill_context = None` so the subsequent `_run_once()` call has no stale shortcut context.
3. Let the retry loop proceed normally — `_shortcut_attempted = True` was already set, which clears the shortcut on the next retry (Phase 29 pattern).
4. Do NOT propagate the exception or return an error from `run()` due to shortcut failure alone.

**When `ShortcutExecutor.execute()` raises an exception** (unexpected backend error, grounder failure, etc.):
- Catch broadly in `GuiAgent.run()` inside the shortcut execution block.
- Log a `shortcut_execution` event with `outcome="exception"` and `error_type`.
- Fall through to the normal `_run_once()` path with no skill context.
- Never re-raise the exception to the outer `run()` error path.

**Fallback code shape in GuiAgent.run():**
```python
# Inside: if approved is not None and self._shortcut_executor is not None:
try:
    shortcut_result = await self._shortcut_executor.execute(matched_skill)
    if shortcut_result.is_violation:
        # Structured contract violation — surface and fall back
        self._trajectory_recorder.record_event(
            "shortcut_execution",
            outcome="violation",
            skill_id=shortcut_result.skill_id,
            step_index=shortcut_result.step_index,
            boundary=shortcut_result.boundary,
            failed_condition=shortcut_result.failed_condition.to_dict()
            if shortcut_result.failed_condition else None,
        )
        matched_skill = None
        skill_context = None
    else:
        # Success: build summary for the agent
        skill_context = _summarize_shortcut_success(shortcut_result)
        self._trajectory_recorder.record_event(
            "shortcut_execution",
            outcome="success",
            skill_id=shortcut_result.skill_id,
            steps_taken=len(shortcut_result.step_results),
        )
except Exception as exc:
    self._trajectory_recorder.record_event(
        "shortcut_execution",
        outcome="exception",
        error_type=type(exc).__name__,
        error_message=str(exc),
    )
    matched_skill = None
    skill_context = None
_shortcut_attempted = True
```

### Pattern 5: GuiAgent Constructor Extension

**What:** Add `shortcut_executor: ShortcutExecutor | None = None` to `GuiAgent.__init__()` alongside the existing `skill_executor` parameter.

**Why:** The existing `skill_executor` parameter is for the legacy `SkillExecutor` path. Phase 30 adds a parallel `shortcut_executor` for the new Phase 25 executor. Keeping them separate preserves backward compatibility and allows either, both, or neither to be wired.

**Constructor change:**
```python
def __init__(
    self,
    ...
    skill_executor: Any = None,       # existing
    shortcut_executor: Any = None,    # NEW: ShortcutExecutor | None
    ...
) -> None:
    ...
    self._shortcut_executor = shortcut_executor
```

### Anti-Patterns to Avoid

- **Using `SkillExecutor` for Phase 29-approved shortcuts:** `SkillExecutor` uses template substitution fallback and fail-open semantics — it cannot produce `ContractViolationReport` and does not use `GrounderProtocol`. It is the wrong executor for `ShortcutSkill` objects.
- **Calling `ShortcutExecutor.execute()` before `_evaluate_shortcut_applicability` gate:** The executor should only run when the applicability decision is `outcome="run"`. Never skip the Phase 29 gate.
- **Forgetting settle between execute() and post-step observe():** This is the most likely SSTA-01 failure mode. The post-step screenshot must be taken AFTER the settle wait or postcondition checks will see the UI mid-transition.
- **Propagating `ContractViolationReport` as an exception:** `is_violation=True` means structured failure; catch it at the `GuiAgent.run()` level and convert to fallback, never re-raise.
- **Using `LLMStateValidator` directly as `ConditionEvaluator`:** `LLMStateValidator` has `validate(valid_state: str, screenshot)` while `ConditionEvaluator` protocol requires `evaluate(condition: StateDescriptor, screenshot: Path)`. An adapter class is required.
- **Hardcoding settle duration as a constant:** The correct pattern is a configurable field on `ShortcutExecutor` with a sensible default (0.50s), matching `GuiAgent._POST_ACTION_SETTLE_SECONDS`.
- **Running ShortcutExecutor after failed Phase 29 applicability:** When `applicability_decision.outcome != "run"`, the shortcut path must be entirely skipped — `shortcut_executor` should never be called.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Live parameter binding | Custom LLM prompt for coordinate resolution | `LLMGrounder.ground()` via `GrounderProtocol` | Phase 24/25 already defines the contract and implementation; `ShortcutExecutor._execute_step()` already calls it |
| Pre/post condition checking | Custom condition evaluation loop | `ShortcutExecutor.execute()` with injected `ConditionEvaluator` | Phase 25 already shipped this loop including `ContractViolationReport` |
| Settle timing | Custom `time.sleep()` or backend-specific polling | `asyncio.sleep(N)` following `GuiAgent._post_action_settle_seconds()` pattern | The main loop already uses this pattern; duplicate the constant and no-settle action set |
| Structured violation signals | Custom error types or string error codes | `ContractViolationReport` dataclass from `multi_layer_executor.py` | Already frozen, typed, and discriminated with `is_violation: Literal[True]` |
| Shortcut execution summary | Custom narrative builder | Follow `_build_execution_summary()` pattern from `executor.py` | Pattern is established in the legacy executor; a Phase 30 equivalent for `ShortcutExecutionSuccess` is straightforward |

**Key insight:** Phase 30 is a wiring phase. Every primitive needed (executor, grounder, condition evaluator, violation report, settle timing, trajectory events) already exists in the codebase. The work is connecting them through the `GuiAgent.run()` path and adding the settle wait that is currently missing from `ShortcutExecutor`.

## Common Pitfalls

### Pitfall 1: LLMStateValidator vs. ConditionEvaluator Protocol Mismatch

**What goes wrong:** Phase 29 wires `LLMStateValidator` directly as the `ConditionEvaluator` for `ShortcutApplicabilityRouter`. In production runs, `ShortcutApplicabilityRouter._evaluator.evaluate(condition, screenshot)` is called — but `LLMStateValidator` only has `validate(valid_state, screenshot)`, not `evaluate()`. This means production applicability checks actually fall through to the always-pass default when the `evaluate()` call fails AttributeError, OR the duck-typing works by accident because the test `_AlwaysPassEvaluator` is used in tests while production breaks silently.

**Why it happens:** The Phase 29 wiring in `nanobot/agent/tools/gui.py` (line 255-256) constructs `ShortcutApplicabilityRouter(condition_evaluator=state_validator)` where `state_validator` is `LLMStateValidator`. `ShortcutApplicabilityRouter.__init__` accepts `object | None`, so no type error at construction. The `evaluate()` call happens later at runtime.

**How to avoid:** Phase 30 must introduce `LLMConditionEvaluator` (an adapter class) that wraps `LLMStateValidator` and exposes `async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool`. Use this adapter for both `ShortcutApplicabilityRouter` and `ShortcutExecutor` in the nanobot path. Update the Phase 29 wiring in `gui.py` to use the adapter.

**Warning signs:** If all preconditions pass even when the screen is clearly wrong, the evaluator is probably falling through to always-pass behavior.

### Pitfall 2: Missing Settle Wait Causes Postcondition False Failures

**What goes wrong:** The post-step screenshot for postcondition checking is taken immediately after `backend.execute()`. On mobile devices and some desktop animations, the UI is still transitioning when the screenshot is captured. Postconditions that check for a new screen element fail because the transition hasn't completed yet.

**Why it happens:** `ShortcutExecutor.execute()` currently calls `await self.backend.execute(action, timeout=timeout)` and then immediately `await self.backend.observe(post_screenshot_path, timeout=timeout)`. No settle wait is inserted.

**How to avoid:** Add `await asyncio.sleep(self._post_action_settle_seconds)` (with action-type-aware exception for `wait`, `done`, `request_intervention`) between `execute()` and the post-step `observe()`. This matches the pattern in `GuiAgent._run_step()`.

**Warning signs:** Postcondition failures that disappear when a manual delay is added, or that only occur on slow/busy backends.

### Pitfall 3: Shortcut Execution Result Incompatible with Legacy Skill Context Injection

**What goes wrong:** The existing code after `self._skill_executor.execute(matched_skill)` reads `skill_result.state.value == "succeeded"` and `skill_result.execution_summary`. `ShortcutExecutionSuccess` has neither of these fields — it has `step_results` and `is_violation=False`. Replacing the executor without adapting the post-execution code causes an `AttributeError`.

**Why it happens:** `ShortcutExecutionSuccess` (Phase 25) and `SkillExecutionResult` (legacy) are different types with different field names. The `if approved is not None:` block in `GuiAgent.run()` currently uses the legacy result shape.

**How to avoid:** When `shortcut_result.is_violation is False`, build `skill_context` from `shortcut_result.step_results` — not from `shortcut_result.execution_summary` (which doesn't exist). Write a helper function `_summarize_shortcut_success(result: ShortcutExecutionSuccess) -> str` that produces a human-readable summary from the step records.

### Pitfall 4: ShortcutExecutor screenshot_dir Collides with Run Artifacts

**What goes wrong:** `ShortcutExecutor` defaults `screenshot_dir` to `Path(tempfile.gettempdir()) / "opengui-skill-execution"`. In production, multiple concurrent runs or a fast-running test suite can cause screenshot files from different runs to collide in the same temp directory.

**Why it happens:** The default was chosen for simplicity in Phase 25 tests. In the nanobot path, `run_dir` is already created per task attempt and is unique.

**How to avoid:** Pass `screenshot_dir=run_dir / "shortcut_screenshots"` when constructing `ShortcutExecutor` in `nanobot/agent/tools/gui.py`. Create the directory before passing the path.

### Pitfall 5: ContractViolationReport Treated as an Exception Instead of a Value

**What goes wrong:** Code that calls `await shortcut_executor.execute(shortcut)` checks `isinstance(result, ContractViolationReport)` but the calling code might also have a blanket `except Exception` that catches the case where `result` is unexpectedly None or the executor raises for an unrelated reason, masking the structured failure.

**Why it happens:** The discriminated union pattern (`result.is_violation` as `Literal[True]` vs `Literal[False]`) is clean in typed code but requires discipline at the call site.

**How to avoid:** Always check `result.is_violation` (not `isinstance(result, ContractViolationReport)`) for the fast path, and separately have an outer `except Exception` for unexpected executor crashes. Use the `is_violation` attribute because `ShortcutExecutionSuccess.is_violation` is `False` by definition.

### Pitfall 6: Fallback Leaves Partial Shortcut State in UI

**What goes wrong:** When a shortcut fails at step N after successfully executing steps 0..N-1, the UI is now in a partially-changed state. The fallback to free agent exploration starts from this partially-executed state, not from the original state. This is expected behavior, but if `skill_context` is injected with a partial summary, the agent might skip UI steps that were NOT actually executed.

**Why it happens:** `ContractViolationReport.step_index` tells us where the violation occurred but not how many steps succeeded before it.

**How to avoid:** When `shortcut_result.is_violation is True`, do NOT inject any `skill_context`. The free agent must start from a fresh observation of the current (partially-executed) state. The trajectory event with `step_index` and `boundary` provides enough context for post-hoc diagnostics without confusing the agent's next action.

## Code Examples

Verified patterns from official codebase sources:

### ShortcutExecutor.execute() — Current Phase 25 Shape

```python
# Source: opengui/skills/multi_layer_executor.py ShortcutExecutor.execute()
async def execute(
    self,
    shortcut: ShortcutSkill,
    params: dict[str, str] | None = None,
    *,
    timeout: float = 5.0,
) -> ShortcutExecutionSuccess | ContractViolationReport:
    params = params or {}
    evaluator: ConditionEvaluator = self.condition_evaluator or _AlwaysPassEvaluator()
    step_results: list[ShortcutStepResult] = []

    for step_index, step in enumerate(shortcut.steps):
        # 1. Capture screenshot (used for pre-check AND grounding)
        pre_screenshot_path = self._screenshot_path(shortcut.skill_id, step_index, "pre")
        observation = await self.backend.observe(pre_screenshot_path, timeout=timeout)

        # 2. Check preconditions
        for condition in shortcut.preconditions:
            if not await evaluator.evaluate(condition, pre_screenshot_path):
                return ContractViolationReport(...)

        # 3. Execute step (grounded or fixed)
        action, grounding = await self._execute_step(...)
        backend_result = await self.backend.execute(action, timeout=timeout)
        # MISSING: settle wait here — Phase 30 adds asyncio.sleep()

        # 4. Postcondition screenshot + check
        post_screenshot_path = self._screenshot_path(shortcut.skill_id, step_index, "post")
        await self.backend.observe(post_screenshot_path, timeout=timeout)  # No settle before this
        for condition in shortcut.postconditions:
            if not await evaluator.evaluate(condition, post_screenshot_path):
                return ContractViolationReport(...)

    return ShortcutExecutionSuccess(skill_id=..., step_results=tuple(step_results))
```

Phase 30 inserts `await asyncio.sleep(self._post_action_settle_seconds(action))` between `backend.execute()` and the post_screenshot_path observation.

### GuiAgent.run() — Phase 29 Shape (Shortcut Execution Block)

```python
# Source: opengui/agent.py GuiAgent.run() — Phase 29 shape (lines ~562-607)
if applicability_decision.outcome == "run":
    approved = next(
        (r for r in shortcut_candidates if r.skill.skill_id == applicability_decision.shortcut_id),
        None,
    )
    if approved is not None:
        matched_skill = approved.skill
        final_score = applicability_decision.score
        memory_context = await self._inject_skill_memory_context(matched_skill, memory_context)
        if self._skill_executor is not None:                          # <-- Phase 30: change to _shortcut_executor
            self._trajectory_recorder.set_phase(ExecutionPhase.SKILL, ...)
            try:
                skill_result = await self._skill_executor.execute(matched_skill)  # <-- wrong executor type
                exec_summary = getattr(skill_result, "execution_summary", None)   # <-- incompatible field
                skill_context = exec_summary if isinstance(exec_summary, str) else None
                ...
            except Exception:
                self._trajectory_recorder.set_phase(ExecutionPhase.AGENT, reason="Shortcut execution failed, falling back")
        _shortcut_attempted = True
```

Phase 30 replaces `self._skill_executor.execute(matched_skill)` with `self._shortcut_executor.execute(matched_skill)` and adapts the result handling to use `shortcut_result.is_violation` and `shortcut_result.step_results`.

### LLMConditionEvaluator Adapter

```python
# NEW class — location: opengui/skills/multi_layer_executor.py (added to existing module)
# Or: opengui/skills/shortcut_executor_support.py (new module)
from opengui.skills.shortcut import StateDescriptor

class LLMConditionEvaluator:
    """Adapter that maps ConditionEvaluator protocol to LLMStateValidator.

    StateDescriptor.value is used as the valid_state string for the LLM validation call.
    StateDescriptor.negated inverts the result when True.
    """
    def __init__(self, state_validator: "LLMStateValidator") -> None:
        self._validator = state_validator

    async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool:
        result = await self._validator.validate(condition.value, screenshot)
        return (not result) if condition.negated else result
```

### Settle Timing in ShortcutExecutor

```python
# Source: opengui/agent.py — pattern to replicate inside ShortcutExecutor
_POST_ACTION_SETTLE_SECONDS = 0.50  # class attribute on GuiAgent
_NO_SETTLE_ACTIONS = frozenset({"wait", "done", "request_intervention"})

def _post_action_settle_seconds(self, action: Action) -> float:
    if action.action_type in self._NO_SETTLE_ACTIONS:
        return 0.0
    return self._POST_ACTION_SETTLE_SECONDS
```

Phase 30 adds equivalent class attributes and method to `ShortcutExecutor` (or a configurable `post_action_settle_seconds: float = 0.50` field).

### ContractViolationReport — Discriminated Union Pattern

```python
# Source: opengui/skills/multi_layer_executor.py
result = await executor.execute(shortcut)
if result.is_violation:
    # result is ContractViolationReport
    log(result.failed_condition)
    log(result.boundary)     # "pre" or "post"
    log(result.step_index)
else:
    # result is ShortcutExecutionSuccess
    for step in result.step_results:
        log(step.action)
```

### Shortcut Execution Summary Builder

```python
# NEW helper — follows _build_execution_summary() pattern from executor.py
def _summarize_shortcut_success(result: "ShortcutExecutionSuccess") -> str:
    steps_taken = len(result.step_results)
    lines = [f"Shortcut '{result.skill_id}' executed ({steps_taken} step(s)):"]
    for sr in result.step_results:
        lines.append(f"  Step {sr.step_index}: {sr.action.action_type} — ok")
    return "\n".join(lines)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Legacy `SkillExecutor` with template substitution fallback | `ShortcutExecutor` with `GrounderProtocol` for live binding | Phase 25 | Live binding eliminates stale coordinate replaying |
| Score-only gating for shortcut execution | Pre-execution applicability check (`ShortcutApplicabilityRouter`) | Phase 29 | Execution only proceeds when live screen satisfies preconditions |
| No structured failure signals on skill drift | `ContractViolationReport` with step_index, boundary, failed_condition | Phase 25 | Structured signals enable targeted fallback and Phase 31 diagnostics |
| No settle wait in shortcut executor | Will add settle after `backend.execute()` | Phase 30 | Prevents postcondition false-negatives from UI mid-transition |

**Deprecated/outdated in Phase 30 scope:**
- Calling `self._skill_executor.execute(matched_skill)` for Phase 29-approved shortcuts: replaced by `self._shortcut_executor.execute(matched_skill)`.
- Passing `LLMStateValidator` directly as `ConditionEvaluator`: replaced by `LLMConditionEvaluator` adapter.

## Open Questions

1. **Where should `LLMConditionEvaluator` live?**
   - What we know: It's a small adapter class (5-10 lines). `multi_layer_executor.py` already defines `ConditionEvaluator` protocol and `_AlwaysPassEvaluator`. Adding it there keeps all condition evaluator implementations together.
   - What's unclear: Whether it belongs in `multi_layer_executor.py` (which would require importing `LLMStateValidator` from `executor.py`, potentially creating a circular dependency) or in a new module.
   - Recommendation: Add `LLMConditionEvaluator` to `opengui/skills/multi_layer_executor.py` with a `TYPE_CHECKING` import guard for `LLMStateValidator` to avoid runtime circular imports. Alternatively, put it in `opengui/skills/shortcut_executor_support.py` as a thin standalone module. The planner should decide.

2. **Should `ShortcutExecutor.post_action_settle_seconds` be configurable per instance or a class constant?**
   - What we know: `GuiAgent._POST_ACTION_SETTLE_SECONDS` is a class constant (0.50). Mobile backends may need longer settle times for animated transitions; desktop backends (local mouse/keyboard) may need shorter.
   - Recommendation: Make it a dataclass field with default `0.50` on `ShortcutExecutor`. This matches the Phase 25 dataclass pattern and lets callers (nanobot, CLI) override per backend if needed.

3. **Should `_summarize_shortcut_success()` be a free function or a method on `ShortcutExecutionSuccess`?**
   - What we know: `_build_execution_summary()` in `executor.py` is a free function operating on `SkillExecutionResult`. The `ShortcutExecutionSuccess` dataclass is frozen and simple.
   - Recommendation: Free function in `agent.py` is simplest and avoids adding string-formatting logic to the schema module. Follow the existing `executor.py` pattern.

4. **Should the `ShortcutExecutor` receive `app_hint` / task context to improve grounding?**
   - What we know: `LLMGrounder.ground()` receives a `GroundingContext` that includes `observation.foreground_app` and `task_hint`. These are already populated from the pre-step `backend.observe()` call.
   - What's unclear: Whether passing the overall task string as `task_hint` to `GroundingContext` inside `_execute_step()` helps grounding accuracy.
   - Recommendation: Pass `task_hint=shortcut.description` as already done in Phase 25 (`_execute_step()` currently passes `shortcut.description`). The overall task string is not accessible inside `ShortcutExecutor` without passing it at `execute()` call time — the planner may want to extend the `execute()` signature to accept an optional `task_hint` string.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py -q` |
| Full suite command | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py tests/test_opengui_p30_stable_shortcut_execution.py -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SUSE-03 | ShortcutExecutor calls grounder for non-fixed steps using live observation | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_non_fixed_step_calls_grounder -x` | ❌ Wave 0 |
| SUSE-03 | GuiAgent.run() with approved shortcut calls shortcut_executor.execute(), not skill_executor | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_run_uses_shortcut_executor_for_approved -x` | ❌ Wave 0 |
| SUSE-03 | Nanobot path constructs ShortcutExecutor with LLMGrounder when enable_skill_execution=True | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_nanobot_wires_shortcut_executor -x` | ❌ Wave 0 |
| SUSE-04 | ContractViolationReport from ShortcutExecutor triggers fallback, not task termination | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_violation_triggers_fallback -x` | ❌ Wave 0 |
| SUSE-04 | Exception from ShortcutExecutor triggers fallback, task continues normally | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_executor_exception_triggers_fallback -x` | ❌ Wave 0 |
| SUSE-04 | Task succeeds after shortcut fails (fallback to free exploration) | integration | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_task_succeeds_after_shortcut_fallback -x` | ❌ Wave 0 |
| SSTA-01 | ShortcutExecutor waits settle time between execute() and post-step observe() | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_settle_wait_between_execute_and_observe -x` | ❌ Wave 0 |
| SSTA-01 | Settle is skipped for no-settle action types (wait, done, request_intervention) | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_no_settle_for_terminal_actions -x` | ❌ Wave 0 |
| SSTA-02 | ShortcutExecutor returns ContractViolationReport with boundary="post" when postcondition fails | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_postcondition_failure_returns_violation -x` | ❌ Wave 0 |
| SSTA-02 | shortcut_execution trajectory event with outcome="violation" emitted on contract breach | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_violation_emits_trajectory_event -x` | ❌ Wave 0 |
| SSTA-02 | shortcut_execution trajectory event with outcome="success" emitted when all steps complete | unit | `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py::test_success_emits_trajectory_event -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_opengui_p30_stable_shortcut_execution.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py tests/test_opengui_p30_stable_shortcut_execution.py -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_opengui_p30_stable_shortcut_execution.py` — new test file covering all SUSE-03, SUSE-04, SSTA-01, SSTA-02 behaviors
- [ ] `LLMConditionEvaluator` adapter class — needed in `opengui/skills/multi_layer_executor.py` or a new support module before the wiring tests can exercise it
- [ ] `post_action_settle_seconds` dataclass field on `ShortcutExecutor` — needed for the settle timing tests

*(Existing `ShortcutExecutor`, `ContractViolationReport`, `LLMGrounder`, `GrounderProtocol`, `TrajectoryRecorder`, and `ShortcutApplicabilityRouter` infrastructure already covers Phase 30 dependencies; only the adapter class, settle field, and test file are gaps.)*

## Sources

### Primary (HIGH confidence)

- `opengui/skills/multi_layer_executor.py` — `ShortcutExecutor.execute()`, `ShortcutExecutor._execute_step()`, `ContractViolationReport`, `ShortcutExecutionSuccess`, `ConditionEvaluator` protocol — direct code inspection of the Phase 25 executor contract and gap identification
- `opengui/agent.py` — `GuiAgent.run()` (lines 541-607), `_run_step()` (lines 936-1101), `_POST_ACTION_SETTLE_SECONDS`, `_post_action_settle_seconds()` — settle timing pattern and Phase 29 shortcut execution block (current wrong executor usage)
- `opengui/grounding/llm.py` — `LLMGrounder.ground()` — live binding implementation via `GrounderProtocol`
- `opengui/grounding/protocol.py` — `GrounderProtocol`, `GroundingContext`, `GroundingResult` — grounding contract consumed by `ShortcutExecutor._execute_step()`
- `opengui/skills/executor.py` — `LLMStateValidator` — protocol mismatch with `ConditionEvaluator` confirmed by inspecting `validate()` vs `evaluate()` signatures
- `nanobot/agent/tools/gui.py` (lines 220-274) — current `ShortcutApplicabilityRouter` wiring that uses `LLMStateValidator` directly (confirmed protocol mismatch)
- `opengui/skills/shortcut.py` — `ShortcutSkill.steps`, `preconditions`, `postconditions`, `parameter_slots` — schema consumed by executor
- `opengui/trajectory/recorder.py` — `TrajectoryRecorder.record_event()` — event emission pattern followed by Phase 29

### Secondary (MEDIUM confidence)

- `tests/test_opengui_p29_retrieval_applicability.py` — test structure and mock patterns for Phase 29; Phase 30 tests follow the same conventions
- `tests/test_opengui_p28_shortcut_productionization.py` — Phase 28 test patterns for shortcut promotion and store operations
- `.planning/phases/29-shortcut-retrieval-applicability-routing/29-RESEARCH.md` — Phase 29 architectural decisions that Phase 30 builds on
- `.planning/phases/29-shortcut-retrieval-applicability-routing/29-02-PLAN.md` — Phase 29 execution contract, especially the `_shortcut_attempted` flag pattern for retry clearing

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all modules are workspace-current and directly inspected
- Architecture: HIGH — insertion points, patterns, and protocol mismatch gap all derived from live code inspection
- Pitfalls: HIGH — protocol mismatch and settle timing gaps are confirmed by direct code reading; screenshot collision and summary incompatibility derived from field inspection

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (stable workspace code; 30-day validity)
