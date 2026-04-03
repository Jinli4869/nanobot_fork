# Phase 31: Shortcut Observability and Regression Hardening - Research

**Researched:** 2026-04-03
**Domain:** Structured telemetry emission in the shortcut runtime path and focused regression coverage for mobile + desktop seams
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SSTA-03 | Shortcut runs emit structured telemetry for retrieval, applicability, grounding, settle, validation, fallback, and final outcome so unstable shortcuts can be diagnosed. | The trajectory recorder's `record_event()` API already supports arbitrary named events with key-value payloads and timestamps. Phases 29 and 30 already emit `shortcut_retrieval`, `shortcut_applicability`, and `shortcut_execution` events from `GuiAgent`. The gap is grounding-level events (which grounder resolved what, which step failed, what the live target was) and settle-level events inside `ShortcutExecutor`. Both can be added to existing methods without schema changes. |
| SSTA-04 | Regression coverage proves shortcut extraction and execution remain stable across representative mobile and desktop execution seams or their CI-safe equivalents. | The Phase 30 test file (`test_opengui_p30_stable_shortcut_execution.py`) already uses an android fake backend (`platform="android"`). The gap is a desktop seam (`platform="macos"`) and a test that exercises the full extraction-to-execution pipeline end-to-end using a JSONL trace fixture. Existing patterns from Phase 28 (JSONL fixture-driven promotion tests) and Phase 30 (fake backend with call_log patterns) directly apply. |

</phase_requirements>

## Summary

Phase 31 is an observability and hardening phase that closes the v1.6 milestone. The core implementation work was completed in Phases 28–30: shortcuts are extracted, selected with applicability checks, and executed with live binding, settle timing, and safe fallback. Phase 31's job is to make that behavior visible to engineers through telemetry, and to prove it stays stable through representative regression tests.

The two plans are cleanly separated. Plan 01 adds structured telemetry events to the existing shortcut runtime path — primarily grounding-level and settle-level events inside `ShortcutExecutor.execute()`, which currently emits no events of its own. The existing `TrajectoryRecorder.record_event()` API handles this without any schema changes. Plan 02 adds focused regression tests that prove extraction and execution work correctly for both Android (mobile) and macOS (desktop) seams using fake backends and JSONL trace fixtures, building on established Phase 28/29/30 test patterns.

The codebase is in a strong position for this phase. `TrajectoryRecorder` is a simple JSONL append-only recorder that already handles arbitrary event types. The existing `shortcut_retrieval`, `shortcut_applicability`, and `shortcut_execution` events cover the GuiAgent layer well. The telemetry gap is inside `ShortcutExecutor.execute()`, which currently only logs at `logger.info` level and does not write to the trajectory file. Grounding results and settle durations should be promoted to structured events in that method.

**Primary recommendation:** Add grounding and settle events inside `ShortcutExecutor.execute()` by injecting an optional `trajectory_recorder` or by returning richer step-level metadata in `ShortcutStepResult`. Then add two regression test seams — one Android, one macOS/desktop — that each run the full extraction pipeline against a JSONL fixture and then execute the promoted shortcut through a fake backend.

## Standard Stack

### Core

| Module | Version | Purpose | Why Standard |
|--------|---------|---------|--------------|
| `opengui/trajectory/recorder.py` — `TrajectoryRecorder` | workspace current | Append-only JSONL recorder with `record_event(event_type, **payload)` API | Already used for all shortcut observability events in Phase 29/30; no schema changes needed for new event types |
| `opengui/skills/multi_layer_executor.py` — `ShortcutExecutor` | workspace current | Executes shortcut steps with settle timing and condition evaluation | The primary new telemetry site: grounding result and settle duration should be emitted per step |
| `opengui/skills/multi_layer_executor.py` — `ShortcutStepResult` | workspace current | Per-step record in `ShortcutExecutionSuccess.step_results` | Already carries `grounding: GroundingResult | None` and `backend_result`; telemetry can read these fields |
| `opengui/agent.py` — `GuiAgent._retrieve_shortcut_candidates()` | workspace current | Emits `shortcut_retrieval` event; already covers retrieval telemetry | No changes needed; Pattern 29 already complete |
| `opengui/agent.py` — `GuiAgent._evaluate_shortcut_applicability()` | workspace current | Emits `shortcut_applicability` event on all paths including skip/fallback/run | No changes needed; Pattern 29 already complete |
| `opengui/skills/shortcut_promotion.py` — `ShortcutPromotionPipeline` | workspace current | Production shortcut promotion pipeline, exercised in regression seam | Used in Phase 28 tests via JSONL fixture + store; reuse same pattern |
| `opengui/skills/shortcut_store.py` — `ShortcutSkillStore` | workspace current | Stores promoted shortcuts; queryable for post-promotion assertions | Phase 28 tests use `store.list_all(platform=...)` as assertion point |
| `pytest`, `pytest-asyncio` | workspace locked | Test framework and async support | Established in all prior shortcut phases |

### Supporting

| Module | Version | Purpose | When to Use |
|--------|---------|---------|-------------|
| `opengui/grounding/protocol.py` — `GroundingResult` | workspace current | Returned by `LLMGrounder.ground()`; carried in `ShortcutStepResult.grounding` | Use fields `.resolved_params` and `.target` as telemetry payload when grounding occurs |
| `opengui/grounding/protocol.py` — `GroundingContext` | workspace current | Input to grounder containing screenshot + observation | Reference only; do not serialize fully — only log resolved target and param names |
| `unittest.mock` — `AsyncMock`, `MagicMock`, `patch` | stdlib | Mock injection for fake backends and grounqers in regression tests | Established pattern across Phases 25–30 |
| `tests/test_opengui_p30_stable_shortcut_execution.py` — `_FakeBackend`, `_CapturingRecorder` | workspace | Reusable test helpers for fake backend (Android platform) and event capture | Reuse directly for Plan 02 regression seams; extend `_FakeBackend` to support `platform="macos"` variant |
| `tests/test_opengui_p28_shortcut_productionization.py` | workspace | JSONL fixture patterns for promotion pipeline testing | Reference for how to build JSONL trace fixtures and assert `store.list_all()` results |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Injecting `trajectory_recorder` into `ShortcutExecutor` | Returning richer data from `execute()` and logging at GuiAgent level | Richer return data from `execute()` would require callers to know telemetry detail; injecting the recorder keeps observability self-contained in the executor, matches how the agent already owns its recorder |
| New telemetry event type per boundary (e.g., `shortcut_step_grounded`, `shortcut_step_settled`) | Adding fields to the existing `shortcut_execution` event | Per-boundary events make log queries simpler and let engineers filter to grounding vs settle events independently; the existing `shortcut_execution` event fires once for the full execution outcome, not per step |
| Real device integration tests for regression | CI-safe fake backend regression tests | Live device tests are manual-only per the established repo pattern; CI-safe fakes with platform-specific configurations are sufficient to prove the seam is stable |

**Installation:** No new packages needed. All telemetry uses existing `TrajectoryRecorder.record_event()` API.

## Architecture Patterns

### Recommended Project Structure

```
opengui/
├── agent.py                              # No changes — existing events are complete
└── skills/
    └── multi_layer_executor.py           # Add grounding + settle events inside execute()

tests/
└── test_opengui_p31_shortcut_observability.py   # NEW: Phase 31 telemetry + regression tests
```

### Pattern 1: Adding Telemetry to ShortcutExecutor

`ShortcutExecutor` currently has no `trajectory_recorder` injection. The cleanest approach is to add an optional `trajectory_recorder` field to the `ShortcutExecutor` dataclass, defaulting to `None`. When present, emit events inside `execute()` for each step boundary.

**What:** Optional recorder injection + per-step event emission.
**When to use:** Grounding and settle events that are only meaningful at the executor level (inside the step loop), not at the `GuiAgent` level.

```python
# Source: opengui/skills/multi_layer_executor.py — extended ShortcutExecutor
@dataclass
class ShortcutExecutor:
    backend: DeviceBackend
    grounder: GrounderProtocol
    condition_evaluator: ConditionEvaluator | None = None
    screenshot_dir: Path = field(...)
    post_action_settle_seconds: float = field(default=0.50)
    trajectory_recorder: Any = None   # NEW: TrajectoryRecorder | None

    async def execute(self, shortcut: ShortcutSkill, ...) -> ...:
        ...
        for step_index, step in enumerate(shortcut.steps):
            ...
            action, grounding = await self._execute_step(...)
            backend_result = await self.backend.execute(action, timeout=timeout)

            # Emit grounding event if grounder was called (non-fixed step)
            if self.trajectory_recorder is not None and grounding is not None:
                self.trajectory_recorder.record_event(
                    "shortcut_grounding",
                    skill_id=shortcut.skill_id,
                    step_index=step_index,
                    target=step.target,
                    resolved_params=grounding.resolved_params,
                )

            settle = self._settle_seconds_for(action)
            if settle > 0:
                await asyncio.sleep(settle)
                if self.trajectory_recorder is not None:
                    self.trajectory_recorder.record_event(
                        "shortcut_settle",
                        skill_id=shortcut.skill_id,
                        step_index=step_index,
                        action_type=action.action_type,
                        settle_seconds=settle,
                    )
            ...
```

**Key design decision:** Use `Any` for `trajectory_recorder` type to avoid circular imports (same pattern as `skill_executor: Any = None` in `GuiAgent`).

### Pattern 2: Existing Telemetry Events Already in Place

The following shortcut events are already emitted by `GuiAgent` and do NOT need to be added in Phase 31:

| Event | Where | Payload Fields |
|-------|-------|----------------|
| `shortcut_retrieval` | `GuiAgent._retrieve_shortcut_candidates()` | `task`, `platform`, `app_hint`, `candidate_count`, `candidates[]` |
| `shortcut_applicability` | `GuiAgent._evaluate_shortcut_applicability()` | `outcome`, `shortcut_id`, `reason`, `score`, `failed_condition` |
| `shortcut_execution` | `GuiAgent.run()` shortcut dispatch block | `outcome` (success/violation/exception), `skill_id`, `step_index`, `boundary`, `failed_condition`, `steps_taken`, `error_type`, `error_message` |

These three event types already cover the required "selection, grounding from the applicability side, fallback, and outcome" boundary. Phase 31 Plan 01 adds the missing "grounding" and "settle" events from inside the executor.

### Pattern 3: CI-Safe Regression Seams

Regression coverage for "representative mobile and desktop seams" means two test configurations using fake backends, not live devices.

**Mobile seam (Android):** `platform="android"`, `app="com.example.app"`, extraction from a JSONL fixture with `platform: android` metadata row, shortcut stored and then retrieved + executed through `ShortcutExecutor(_FakeBackend(platform="android"))`.

**Desktop seam (macOS):** `platform="macos"`, `app="com.apple.safari"`, extraction from a JSONL fixture with `platform: macos` metadata row, shortcut stored and then retrieved + executed through `ShortcutExecutor(_FakeBackend(platform="macos"))`.

Both seams use the same Phase 28 JSONL fixture pattern and the Phase 30 `_FakeBackend` helper.

```python
# Pattern: JSONL fixture for promotion testing (from Phase 28)
ANDROID_TRACE = "\n".join([
    '{"type": "metadata", "task": "Open settings", "platform": "android"}',
    '{"type": "step", "action": {"action_type": "tap", "x": 100, "y": 200}, "phase": "agent"}',
    '{"type": "step", "action": {"action_type": "tap", "x": 300, "y": 400}, "phase": "agent"}',
    '{"type": "result", "success": true}',
])

async def test_android_shortcut_seam(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(ANDROID_TRACE)
    store = ShortcutSkillStore(tmp_path / "store")
    pipeline = ShortcutPromotionPipeline(platform="android")
    skill_id = await pipeline.promote_from_trace(trace_path, is_success=True, store=store)
    assert skill_id is not None
    # Retrieve and execute
    candidates = store.list_all(platform="android")
    shortcut = candidates[0]
    executor = ShortcutExecutor(
        backend=_FakeBackend(),  # platform="android"
        grounder=_NeverCalledGrounder(),
        screenshot_dir=tmp_path / "exec",
        post_action_settle_seconds=0.0,
    )
    result = await executor.execute(shortcut)
    assert isinstance(result, ShortcutExecutionSuccess)
```

### Pattern 4: Telemetry Test Assertions Using `_CapturingRecorder`

Reuse the `_CapturingRecorder` from Phase 30 tests. Inject it into `ShortcutExecutor` to capture step-level events.

```python
# Source: tests/test_opengui_p30_stable_shortcut_execution.py — _CapturingRecorder
class _CapturingRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
    def record_event(self, event: str, **payload) -> None:
        self.events.append((event, payload))
    def set_phase(self, *args, **kwargs): pass
    def start(self, **kwargs): pass
    def finish(self, **kwargs): pass
    def record_step(self, *args, **kwargs): pass
    @property
    def path(self): return None

# Test: verify grounding event is emitted for non-fixed steps
async def test_grounding_telemetry(tmp_path):
    recorder = _CapturingRecorder()
    executor = ShortcutExecutor(
        backend=_FakeBackend(),
        grounder=_FakeGrounder(),  # returns a GroundingResult
        trajectory_recorder=recorder,
        screenshot_dir=tmp_path,
        post_action_settle_seconds=0.0,
    )
    shortcut = _make_non_fixed_shortcut()  # step.fixed=False
    await executor.execute(shortcut)
    grounding_events = [e for e, _ in recorder.events if e == "shortcut_grounding"]
    assert len(grounding_events) == 1
```

### Anti-Patterns to Avoid

- **Don't add telemetry to `GuiAgent` for events that happen inside `ShortcutExecutor`.** Grounding and settle are executor-internal concerns. Routing them back through `GuiAgent` would require changing the return contract of `execute()` and break Plan 03's clean `ContractViolationReport | ShortcutExecutionSuccess` discriminator.
- **Don't add a new JSONL format or recorder class.** The existing `TrajectoryRecorder.record_event()` with arbitrary kwargs is sufficient. Every new event type just needs a distinct `event_type` string.
- **Don't write integration tests that require live backends.** The established repo pattern is to use fake backends for CI coverage and document real-host validation as manual-only. Phase 31 regression tests must follow this same rule.
- **Don't add desktop/mobile platform branching logic to ShortcutExecutor.** The two regression seams differ only in the `platform` field on the shortcut and backend fake — there is no platform-specific execution code path to test.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Event serialization | Custom JSON log writer | `TrajectoryRecorder.record_event()` with `**payload` | Already handles timestamp, step index, and JSONL append atomically |
| Test recorder assertion | File-based JSONL parsing in tests | `_CapturingRecorder` in-memory event list | Deterministic, fast, no temp file races; established in Phase 30 |
| Mobile/desktop fixture variation | Separate fixture modules | Single parametrized or duplicate fixture strings with different platform fields | Platform difference is only one field in the metadata row |
| Grounding output parsing | String-based target extraction | `GroundingResult.resolved_params` dict | The grounder protocol already structures the output |

**Key insight:** Every telemetry gap in this phase can be filled with `record_event(event_type, **kwargs)` calls added at the right call site inside `ShortcutExecutor.execute()`. The recorder API was designed for exactly this extensibility.

## Common Pitfalls

### Pitfall 1: Missing Recorder in ShortcutExecutor Constructor

**What goes wrong:** The planner adds `trajectory_recorder` calls in `ShortcutExecutor.execute()` but forgets to add the field to the dataclass, so the field is not available at construction time and tests cannot inject a fake.
**Why it happens:** `ShortcutExecutor` is a `@dataclass` — fields must be declared before they can be used.
**How to avoid:** Add `trajectory_recorder: Any = None` as a dataclass field with a default of `None` so existing callers that don't pass it are unaffected.
**Warning signs:** `AttributeError: ShortcutExecutor has no attribute trajectory_recorder` at test time.

### Pitfall 2: Grounding Event Emitted for Fixed Steps

**What goes wrong:** The grounding event is emitted for every step, including fixed steps that never call the grounder. Fixed steps return `grounding=None` from `_execute_step()`.
**Why it happens:** Checking `grounding is not None` before emitting is easy to forget when adding telemetry.
**How to avoid:** Guard all `shortcut_grounding` event emission behind `if grounding is not None`.
**Warning signs:** Regression tests that use `_NeverCalledGrounder()` suddenly see unexpected grounding events.

### Pitfall 3: Settle Event Emitted When Settle Duration is Zero

**What goes wrong:** A `shortcut_settle` event is emitted even when `settle = 0.0` and `asyncio.sleep` is not called. This produces noisy telemetry that falsely implies settling occurred.
**Why it happens:** Emitting the settle event without checking `if settle > 0` mirrors the existing `asyncio.sleep` guard pattern but is easy to skip.
**How to avoid:** Place settle event emission inside `if settle > 0:` (same block as `asyncio.sleep`).
**Warning signs:** Tests using exempt action types (`"done"`, `"wait"`, `"request_intervention"`) see unexpected settle events.

### Pitfall 4: Regression Fixtures Too Simple to Catch Real Failures

**What goes wrong:** JSONL fixtures only have one step, or only fixed steps with no parameter slots, so the test cannot detect regressions in grounding or parameter binding.
**Why it happens:** Minimal fixtures are easiest to write but miss the execution path that most commonly regresses.
**How to avoid:** Include at least two steps in each fixture, and include at least one step with a recognizable action type (e.g., `"tap"` with `x`/`y` values that the test can assert appeared in `backend.executed_actions`).
**Warning signs:** Tests pass even when `ShortcutExecutor._execute_step()` is completely broken.

### Pitfall 5: Circular Import When Importing TrajectoryRecorder in multi_layer_executor

**What goes wrong:** Importing `TrajectoryRecorder` directly in `multi_layer_executor.py` creates a circular import because `agent.py` imports from `multi_layer_executor.py`.
**Why it happens:** `TrajectoryRecorder` is in `trajectory/recorder.py`, which has no circular dependency risk with `multi_layer_executor.py` directly, but must be verified.
**How to avoid:** Use `Any` for the `trajectory_recorder` type annotation (same pattern as `skill_executor: Any = None` in `GuiAgent.__init__()`). Do not import `TrajectoryRecorder` at module level in `multi_layer_executor.py`. Verify import graph before adding.
**Warning signs:** `ImportError` or `circular import` error when running any test that imports `multi_layer_executor`.

### Pitfall 6: Platform Regression Seams Not Actually Testing the Seam

**What goes wrong:** The desktop seam test uses `platform="android"` by copy-paste error, so both seams test the same path and the desktop seam never exercises macOS-specific behavior.
**Why it happens:** Fixtures are easy to copy without changing the platform field.
**How to avoid:** Assert `shortcut.platform == "macos"` (or the platform under test) inside each seam test as an explicit guard against fixture mistakes.
**Warning signs:** Both seam tests pass identically regardless of which platform is set.

## Code Examples

Verified patterns from the existing codebase:

### Existing record_event Call Pattern (from opengui/agent.py)

```python
# Source: opengui/agent.py lines 1719-1733 (_retrieve_shortcut_candidates)
self._trajectory_recorder.record_event(
    "shortcut_retrieval",
    task=task,
    platform=platform,
    app_hint=app_hint,
    candidate_count=len(filtered),
    candidates=[
        {
            "skill_id": r.skill.skill_id,
            "name": r.skill.name,
            "score": round(r.score, 4),
        }
        for r in filtered
    ],
)
```

### ShortcutExecutor Step Loop (current state — telemetry gap location)

```python
# Source: opengui/skills/multi_layer_executor.py lines 247-310
for step_index, step in enumerate(shortcut.steps):
    pre_screenshot_path = self._screenshot_path(shortcut.skill_id, step_index, "pre")
    observation = await self.backend.observe(pre_screenshot_path, timeout=timeout)

    for condition in shortcut.preconditions:
        if not await evaluator.evaluate(condition, pre_screenshot_path):
            return ContractViolationReport(...)   # pre-boundary violation

    action, grounding = await self._execute_step(
        step=step, shortcut=shortcut, params=params,
        screenshot_path=pre_screenshot_path, observation=observation, timeout=timeout,
    )
    backend_result = await self.backend.execute(action, timeout=timeout)

    # --- TELEMETRY GAP: no grounding event emitted here ---
    # --- TELEMETRY GAP: no settle event emitted here ---
    settle = self._settle_seconds_for(action)
    if settle > 0:
        await asyncio.sleep(settle)

    post_screenshot_path = self._screenshot_path(shortcut.skill_id, step_index, "post")
    await self.backend.observe(post_screenshot_path, timeout=timeout)

    for condition in shortcut.postconditions:
        if not await evaluator.evaluate(condition, post_screenshot_path):
            return ContractViolationReport(...)   # post-boundary violation
```

### ShortcutSkillStore Assertion Pattern (from Phase 28 tests)

```python
# Source: tests/test_opengui_p28_shortcut_productionization.py
store = ShortcutSkillStore(tmp_path / "store")
pipeline = ShortcutPromotionPipeline(platform="android")
skill_id = await pipeline.promote_from_trace(trace_path, is_success=True, store=store)
assert skill_id is not None
promoted = store.list_all(platform="android")
assert len(promoted) == 1
assert promoted[0].platform == "android"
```

### _FakeBackend and _CapturingRecorder (from Phase 30 tests — reuse directly)

```python
# Source: tests/test_opengui_p30_stable_shortcut_execution.py
class _FakeBackend:
    def __init__(self) -> None:
        self.executed_actions: list[Action] = []
    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.touch()
        return Observation(screenshot_path=str(screenshot_path),
                           screen_width=1080, screen_height=1920,
                           foreground_app="com.example.app", platform="android")
    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        self.executed_actions.append(action)
        return f"ok:{action.action_type}"
    @property
    def platform(self) -> str: return "android"
```

For the macOS seam, create `_FakeDesktopBackend` with `platform="macos"` and `foreground_app="com.apple.safari"` — only those two fields need to differ.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No shortcut-specific events in JSONL traces | `shortcut_retrieval` + `shortcut_applicability` + `shortcut_execution` events | Phases 29–30 | Engineers can now see why a shortcut was retrieved, selected/rejected, and whether it succeeded or violated |
| Telemetry at GuiAgent level only | Will add grounding + settle events inside ShortcutExecutor (Phase 31) | Phase 31 | Engineers will be able to see what the grounder resolved for each step and how long settle waited |
| No regression seams for mobile vs desktop | Will add two parametrized seams (android + macos) | Phase 31 | CI proves both platforms work through the full extract-promote-retrieve-execute pipeline |
| Manual inspection of JSONL files to diagnose shortcut failures | Structured event payload with `skill_id`, `step_index`, `boundary`, `failed_condition` | Phase 30 | Enables automated tooling to count violation rates by skill, step, and boundary |

**Deprecated/outdated:**
- `logger.info()` calls inside `ShortcutExecutor._execute_step()` and the step loop: these remain useful for human log reading but are not structured. Phase 31 adds parallel structured events — the logger calls should not be removed.

## Open Questions

1. **Should `ShortcutExecutor` receive a `trajectory_recorder` at all, or should `GuiAgent` harvest the step results post-execution?**
   - What we know: `ShortcutExecutionSuccess.step_results` already carries `grounding` per step. `GuiAgent` could loop over the step results and emit events after `execute()` returns.
   - What's unclear: Post-hoc emission from `GuiAgent` means grounding events fire after settle, losing temporal ordering relative to the settle event.
   - Recommendation: Inject the recorder directly into `ShortcutExecutor` for correct per-step event ordering. If circular imports are a concern, use `Any` type annotation (established pattern in this codebase).

2. **What is a "desktop seam" in the context of shortcut execution?**
   - What we know: The codebase uses `platform="macos"` in desktop backends and `platform="android"` for mobile. No shortcut-specific code branches on platform — the platform is metadata only.
   - What's unclear: Whether "desktop seam" implies testing with a `LocalDesktopBackend` fake or simply a `ShortcutSkill` with `platform="macos"`.
   - Recommendation: A `platform="macos"` shortcut executed through a `_FakeDesktopBackend` with `platform="macos"` is the correct CI-safe equivalent. Full desktop backend integration tests are manual-only per established repo conventions.

3. **Should grounding events include the full `resolved_params` dict or only a summary?**
   - What we know: `GroundingResult.resolved_params` is a `dict[str, str]` and typically small (3–5 keys). Full inclusion is safe.
   - What's unclear: Whether any params could contain PII (e.g., input_text values from a real run).
   - Recommendation: Include `resolved_params` as-is for diagnostic value; note that scrubbing (per `GuiAgent._record_safe_event()` pattern at line 1553) may be appropriate if Phase 31 is deployed to production runs. For the test seam, params are fixture-controlled and safe.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest with pytest-asyncio |
| Config file | pyproject.toml |
| Quick run command | `uv run python -m pytest tests/test_opengui_p31_shortcut_observability.py -x -q --tb=short` |
| Full suite command | `uv run python -m pytest tests/ -q --tb=short` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SSTA-03 | `shortcut_grounding` event emitted for non-fixed step with correct `skill_id`, `step_index`, `resolved_params` | unit | `pytest tests/ -k "test_grounding_telemetry" -x -q` | Wave 0 |
| SSTA-03 | `shortcut_settle` event emitted only for non-exempt actions with correct `settle_seconds` | unit | `pytest tests/ -k "test_settle_telemetry" -x -q` | Wave 0 |
| SSTA-03 | All 6 event types present in a complete trace artifact for a shortcut run (retrieval, applicability, grounding, settle, validation, outcome) | unit | `pytest tests/ -k "test_full_trace_event_coverage" -x -q` | Wave 0 |
| SSTA-04 | Android seam: promote from JSONL fixture, execute promoted shortcut, all steps succeed | integration-safe | `pytest tests/ -k "test_android_extraction_execution_seam" -x -q` | Wave 0 |
| SSTA-04 | macOS/desktop seam: promote from JSONL fixture with `platform="macos"`, execute promoted shortcut, all steps succeed | integration-safe | `pytest tests/ -k "test_macos_extraction_execution_seam" -x -q` | Wave 0 |
| SSTA-04 | Regression: Phase 28/29/30 tests remain green after Phase 31 changes | regression | `pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py tests/test_opengui_p30_stable_shortcut_execution.py -q` | Exists |

### Sampling Rate

- **Per task commit:** `uv run python -m pytest tests/test_opengui_p31_shortcut_observability.py -x -q --tb=short`
- **Per wave merge:** `uv run python -m pytest tests/ -q --tb=short`
- **Phase gate:** Full suite green (except pre-existing deferred failures documented in Phase 30 `deferred-items.md`) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_opengui_p31_shortcut_observability.py` — covers SSTA-03 (grounding/settle telemetry) and SSTA-04 (android + desktop seams)

*(Existing test infrastructure covers all prior-phase regression checks; only the new Phase 31 file is missing.)*

## Sources

### Primary (HIGH confidence)

- Direct code inspection: `opengui/agent.py` lines 560–641, 1692–1858 — existing `shortcut_retrieval`, `shortcut_applicability`, `shortcut_execution` events and their payload shapes
- Direct code inspection: `opengui/trajectory/recorder.py` — `record_event(event_type, **payload)` API
- Direct code inspection: `opengui/skills/multi_layer_executor.py` lines 212–330 — `ShortcutExecutor.execute()` step loop showing telemetry gaps
- Direct code inspection: `tests/test_opengui_p30_stable_shortcut_execution.py` — `_FakeBackend`, `_CapturingRecorder`, `_NeverCalledGrounder` helper patterns
- Direct code inspection: `tests/test_opengui_p28_shortcut_productionization.py` — JSONL fixture + `ShortcutPromotionPipeline` + `store.list_all()` regression pattern

### Secondary (MEDIUM confidence)

- Test run result: `uv run python -m pytest tests/test_opengui_p30_stable_shortcut_execution.py tests/test_opengui_p29_retrieval_applicability.py -q` → 35 passed, 0 failed (2026-04-03) confirms current test baseline is green
- Phase 30 deferred-items.md: 15 pre-existing failures outside Phase 30 scope remain unresolved; Phase 31 tests should not touch those files

### Tertiary (LOW confidence)

- None — all findings are from direct codebase inspection, no web search needed.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all modules are directly inspected in the workspace
- Architecture: HIGH — the telemetry gap is clearly identified in `multi_layer_executor.py` lines 247–310
- Pitfalls: HIGH — most pitfalls are derived from reading existing patterns (dataclass field declarations, circular import guard, None-check before event emission)
- Regression seam design: HIGH — Phase 28 JSONL fixture pattern and Phase 30 fake backend pattern are both present and working

**Research date:** 2026-04-03
**Valid until:** This research does not depend on external libraries or versions. Valid until `multi_layer_executor.py` or `recorder.py` are substantially changed.
