# Phase 29: Shortcut Retrieval and Applicability Routing - Research

**Researched:** 2026-04-03
**Domain:** Pre-loop shortcut candidate retrieval with live-screen applicability evaluation inside GuiAgent
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SUSE-01 | GuiAgent can retrieve shortcut candidates using task text plus current app/platform context before entering the full step-by-step loop. | `GuiAgent._search_skill()` already executes a raw task-text search via `UnifiedSkillSearch` before the retry loop. Phase 29 must extend this to filter by active app/platform and return multiple ranked candidates (not just top-1), producing a shortcut candidate list that reaches `run()` before the first `_run_once()` call. |
| SUSE-02 | Runtime selection executes a shortcut only when current screen evidence satisfies its applicability checks; otherwise the run continues without shortcut reuse. | `ShortcutSkill.preconditions` and `ShortcutSkill.postconditions` are stored as `StateDescriptor` tuples. `ConditionEvaluator` in `multi_layer_executor.py` is the typed protocol for evaluating those conditions against a live screenshot. Phase 29 must introduce an explicit pre-execution applicability gate that calls a `ConditionEvaluator` on the live screen, logs a structured decision (`run / skip / fallback`), and prevents execution of any shortcut whose preconditions are not satisfied. |

</phase_requirements>

## Summary

Phase 29 extends the `GuiAgent` run path — already capable of searching the shortcut store and executing matched skills — with two missing production behaviors:

**SUSE-01:** The current `_search_skill()` method queries `UnifiedSkillSearch` with raw task text and returns only the single top result above a score threshold. It does not filter by the active app or platform, and the search happens before any live screen observation, so the candidates have no screen context. Phase 29 must change the retrieval step to (a) accept multiple candidates, (b) filter by active app/platform context derived from `backend.platform` and the initial observation's `foreground_app`, and (c) surface those candidates to the decision step that follows.

**SUSE-02:** Even when a retrieval match exists, the current code executes the skill unconditionally if score >= threshold. Execution is gated only by score, not by whether the preconditions in `ShortcutSkill.preconditions` are satisfied by the live screen. Phase 29 must interpose an explicit **applicability evaluation** step between retrieval and execution: take a screenshot, check each precondition via `ConditionEvaluator`, and produce a structured decision with one of three outcomes — `run`, `skip`, or `fallback`. Runs with no safe shortcut must proceed normally.

The cleanest implementation keeps both behaviors as collaborating pieces inside `GuiAgent.run()` without requiring changes to the existing `ShortcutExecutor`, `UnifiedSkillSearch`, or `ShortcutSkillStore`. The only new module required is a thin `ShortcutApplicabilityRouter` that encapsulates the evaluation and decision logic, keeping `agent.py` as the caller.

**Primary recommendation:** Add `_retrieve_shortcut_candidates()` and `_evaluate_shortcut_applicability()` helpers to `GuiAgent`, backed by a new `opengui/skills/shortcut_router.py` module that owns the `ApplicabilityDecision` type and the evaluation/logging contract.

## Standard Stack

### Core

| Module | Version | Purpose | Why Standard |
|--------|---------|---------|--------------|
| `opengui/agent.py` — `GuiAgent` | workspace current | Top-level change target; run loop, skill search, initial obs | Existing seam; all retrieval/applicability logic plugs in here |
| `opengui/skills/shortcut_store.py` — `ShortcutSkillStore`, `UnifiedSkillSearch` | workspace current | Search shortcut candidates before the loop | Already called by `_search_skill()`; Phase 29 extends the call to multi-candidate + app/platform filter |
| `opengui/skills/shortcut.py` — `ShortcutSkill`, `StateDescriptor` | workspace current | Applicability input: `preconditions` carry conditions to check | Already produced by Phase 28 promotions |
| `opengui/skills/multi_layer_executor.py` — `ConditionEvaluator` | workspace current | Protocol for evaluating one `StateDescriptor` against a screenshot | Phase 25 already defined this; Phase 29 uses it at the pre-execution boundary |
| `opengui/observation.py` — `Observation` | workspace current | Carries `foreground_app` and `platform` for context filtering | Already captured in `_run_once()` initial observation |
| `opengui/trajectory/recorder.py` — `TrajectoryRecorder.record_event` | workspace current | Emit structured retrieval and applicability events | Same event recording pattern used by `memory_retrieval` and `phase_change` |
| `nanobot/agent/tools/gui.py` — `GuiSubagentTool._run_task()` | workspace current | Wires `UnifiedSkillSearch` and `ConditionEvaluator` into `GuiAgent` | Already passes `unified_skill_search`; Phase 29 adds the applicability evaluator wiring |

### Supporting

| Module | Version | Purpose | When to Use |
|--------|---------|---------|-------------|
| `opengui/skills/normalization.py` — `normalize_app_identifier` | workspace current | Normalize foreground app text to canonical form for store filtering | Use when deriving the app filter key from `Observation.foreground_app` |
| `opengui/grounding/llm.py` — `LLMGrounder` | workspace current | LLM-backed vision evaluation | Could back the `ConditionEvaluator` implementation for applicability checks; already structured for screenshot-based decisions |
| `pytest`, `pytest-asyncio` | workspace locked | Phase 29 regression tests | Existing test infrastructure; new test file `test_opengui_p29_retrieval_applicability.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New `ShortcutApplicabilityRouter` module | Inline applicability logic inside `GuiAgent` | Inline is workable given the method already exists, but mixing routing decision logic into agent.py makes the decision structure invisible to tests and Phase 31 telemetry |
| LLM-backed `ConditionEvaluator` for all applicability checks | Lightweight keyword/heuristic evaluator | LLM approach is more accurate but adds latency before every run; for Phase 29 the evaluator should be injectable so a fast implementation can be provided by the caller |
| Filter candidates inside `UnifiedSkillSearch.search()` | Filter after retrieval in `GuiAgent` | Filtering inside the search layer would require adding platform/app parameters to `UnifiedSkillSearch.search()`, which changes a shared contract used elsewhere; filtering at the GuiAgent layer is less invasive |

**Installation:** No new packages required. All infrastructure (asyncio, dataclasses, typing, pytest) is already present.

## Architecture Patterns

### Recommended Project Structure

```
opengui/
├── agent.py                         # extend run() with multi-candidate retrieval + applicability gate
└── skills/
    └── shortcut_router.py           # NEW: ApplicabilityDecision, ShortcutApplicabilityRouter

nanobot/
└── agent/tools/gui.py               # wire LLMConditionEvaluator into GuiAgent construction

tests/
└── test_opengui_p29_retrieval_applicability.py   # NEW: Phase 29 focused coverage
```

### Pattern 1: Multi-Candidate Retrieval with App/Platform Filter

**What:** Replace the single top-k=1 call to `UnifiedSkillSearch.search()` with a top-k=N search followed by post-retrieval filtering on `platform` and normalized `app` derived from the initial observation.

**Why:** The current `_search_skill()` path returns at most one result and ignores platform/app context. SUSE-01 requires that candidates are relevant to the current app/platform context, not just textually similar.

**Insertion point in `GuiAgent.run()`:**

```python
# Current (Phase 28) shape:
# 2. Retrieve memory context (once)
memory_context = await self._retrieve_memory(task)

# 3. Search skill library (once)
skill_match = await self._search_skill(task)
```

Phase 29 introduces an initial observation step before skill search in `run()` or passes the active backend's platform to the search. The cleanest approach is to derive app context from `backend.platform` (always available) and defer the foreground app filter to the applicability check that uses the live screenshot. This avoids requiring a backend.observe() call before recording has started.

**Example:**

```python
# Source: agent.py run() method — Phase 29 shape
# 3. Retrieve shortcut candidates (once, before the retry loop)
shortcut_candidates = await self._retrieve_shortcut_candidates(task, platform=self.backend.platform)

# 4. Evaluate applicability on live screen and pick best candidate
selected_shortcut, applicability_decision = await self._evaluate_applicability(
    shortcut_candidates, task=task
)
```

### Pattern 2: Applicability Decision Type

**What:** A frozen dataclass `ApplicabilityDecision` with fields: `outcome: Literal["run", "skip", "fallback"]`, `shortcut_id: str | None`, `reason: str`, `score: float | None`, `failed_condition: StateDescriptor | None`.

**Why:** SUSE-02 requires explicit structured logging of the decision. A typed container makes the decision visible to tests and to Phase 31's telemetry requirements.

**Example:**

```python
# Source: opengui/skills/shortcut_router.py — new module
@dataclass(frozen=True)
class ApplicabilityDecision:
    outcome: Literal["run", "skip", "fallback"]
    shortcut_id: str | None = None
    reason: str = ""
    score: float | None = None
    failed_condition: StateDescriptor | None = None
```

### Pattern 3: ConditionEvaluator as the Applicability Gate

**What:** Before selecting a shortcut for execution, call `ConditionEvaluator.evaluate()` for each `precondition` in the candidate `ShortcutSkill`. If any precondition fails, produce an `ApplicabilityDecision(outcome="skip")` and continue to the next candidate or fall through to normal execution.

**Why:** `ConditionEvaluator` is already defined in `multi_layer_executor.py` as a `@runtime_checkable Protocol` with an `async evaluate(condition, screenshot)` signature. Using the same protocol for pre-execution applicability checks keeps the evaluator contract unified and avoids a new ad-hoc interface.

**Critical detail:** The applicability check must take a live screenshot via `backend.observe()` before evaluating conditions. This screenshot is already taken at the start of `_run_once()`. Phase 29 should use that observation's `screenshot_path` rather than triggering a separate observe call.

**Example:**

```python
# Source: opengui/skills/shortcut_router.py
class ShortcutApplicabilityRouter:
    def __init__(
        self,
        condition_evaluator: ConditionEvaluator | None = None,
    ) -> None:
        self._evaluator = condition_evaluator or _AlwaysPassEvaluator()

    async def evaluate(
        self,
        candidate: ShortcutSkill,
        screenshot_path: Path,
    ) -> ApplicabilityDecision:
        for condition in candidate.preconditions:
            if not await self._evaluator.evaluate(condition, screenshot_path):
                return ApplicabilityDecision(
                    outcome="skip",
                    shortcut_id=candidate.skill_id,
                    reason=f"precondition_failed:{condition.kind}:{condition.value}",
                    failed_condition=condition,
                )
        return ApplicabilityDecision(
            outcome="run",
            shortcut_id=candidate.skill_id,
            reason="all_preconditions_satisfied",
        )
```

### Pattern 4: Structured Trajectory Events for SUSE-02 Traceability

**What:** Emit two new event types via `TrajectoryRecorder.record_event()`:

- `shortcut_retrieval`: candidates found, count, scores, app/platform filter applied
- `shortcut_applicability`: decision outcome, shortcut_id, reason, failed_condition

**Why:** SUSE-02's success criterion explicitly requires that "logs and trace artifacts show why a shortcut was selected, skipped, or rejected." The existing `memory_retrieval` event in agent.py provides the pattern.

**Example:**

```python
# Source: agent.py _retrieve_shortcut_candidates — follow memory_retrieval pattern
self._trajectory_recorder.record_event(
    "shortcut_retrieval",
    task=task,
    platform=platform,
    candidate_count=len(candidates),
    candidates=[{"skill_id": c.skill_id, "name": c.name, "score": s} for c, s in candidates],
)

# Source: agent.py _evaluate_applicability
self._trajectory_recorder.record_event(
    "shortcut_applicability",
    outcome=decision.outcome,
    shortcut_id=decision.shortcut_id,
    reason=decision.reason,
    failed_condition=(
        {"kind": decision.failed_condition.kind, "value": decision.failed_condition.value}
        if decision.failed_condition else None
    ),
)
```

### Pattern 5: Safe Fallback — Normal Path Unchanged

**What:** When no shortcut candidate passes applicability evaluation, `run()` continues with `matched_skill = None` and the existing retry loop runs without any shortcut attempt. No exception is raised.

**Why:** SUSE-01 success criterion 3 explicitly states "runs that do not have a safe shortcut continue through the normal path without regression." The existing `matched_skill is None` code path already handles this transparently — Phase 29 just needs to not deviate from it.

### Anti-Patterns to Avoid

- **Blocking the run loop to fetch a live screenshot for retrieval:** Take the screenshot only at the applicability check step, not during the retrieval step. Retrieval can use `backend.platform` + task text without a live screenshot.
- **Calling `backend.observe()` a second time for applicability evaluation:** The initial observation in `_run_once()` already provides a screenshot. Pass that screenshot path to the applicability router rather than triggering an additional observe call.
- **Hard-coding a single top-1 candidate for applicability:** Retrieve top-N and evaluate each in score order, stopping at the first passing candidate. This lets Phase 29 gracefully handle cases where the best retrieval match fails the screen check.
- **Letting evaluation exceptions abort the run:** Catch exceptions from `ConditionEvaluator.evaluate()` and treat them as `outcome="fallback"` so unstable evaluators never kill an otherwise healthy task run.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Shortcut search | New BM25/embedding retrieval | `UnifiedSkillSearch.search()` | Phase 27 already ships multi-layer BM25+FAISS hybrid search |
| App/platform identity normalization | Custom string cleaning | `normalize_app_identifier()` from `normalization.py` | Already handles Android/iOS/desktop app identity conversion |
| Condition evaluation protocol | New LLM prompt or rule engine | `ConditionEvaluator` protocol in `multi_layer_executor.py` | Phase 25 defined the protocol; Phase 29 implements an injected instance |
| Screenshot observation | Custom screenshot call | `backend.observe()` via the existing `_run_once()` initial observation | Avoids a duplicate device round-trip |
| Trajectory event recording | Custom logging | `TrajectoryRecorder.record_event()` | Existing JSONL event format; `memory_retrieval` event is the direct precedent |

**Key insight:** All the primitives for Phase 29 already exist. The phase is primarily about wiring them together with an explicit decision boundary, not building new infrastructure.

## Common Pitfalls

### Pitfall 1: Taking a Live Screenshot Before Recorder Has Started

**What goes wrong:** `GuiAgent.run()` calls `_trajectory_recorder.start()` before searching skills. If Phase 29 inserts a `backend.observe()` call before `start()`, the screenshot event will not be recorded and could be captured to a non-existent path.

**Why it happens:** Retrieval currently happens after `start()` but before the first `_run_once()`. Inserting an observe call in `run()` before `_run_once()` skips the recorder's path setup.

**How to avoid:** Do not call `backend.observe()` during the retrieval step in `run()`. Perform applicability evaluation inside `_run_once()` using the existing initial observation, then surface the decision back to `run()` via a return value or a shared mutable state object.

**Alternative safe approach:** Pass the live screenshot path from `_run_once()`'s initial observation as an argument to the applicability router, after the recorder is started.

### Pitfall 2: Applicability Evaluation Always Passes When No ConditionEvaluator Is Wired

**What goes wrong:** If `GuiSubagentTool._run_task()` doesn't inject a real `ConditionEvaluator`, all applicability checks pass unconditionally via `_AlwaysPassEvaluator`. This satisfies test coverage but defeats SUSE-02 in production.

**Why it happens:** The `_AlwaysPassEvaluator` pattern from Phase 25 is convenient for dry-run/test use, but callers must explicitly inject a real evaluator for production runs.

**How to avoid:** Add a `shortcut_condition_evaluator` parameter to `GuiAgent.__init__()`. In `GuiSubagentTool._run_task()`, wire the same `LLMStateValidator` used by `SkillExecutor` as the applicability evaluator. Document clearly that the default is always-pass.

### Pitfall 3: App/Platform Filter Too Strict — Empty Candidates on Every Run

**What goes wrong:** Filtering by `foreground_app` at retrieval time returns zero candidates because the live foreground app does not match stored shortcut app identifiers exactly (e.g. `"com.tencent.mm"` vs `"wechat"`).

**Why it happens:** Shortcut store app identifiers are normalized via `normalize_app_identifier()`, but the runtime `foreground_app` from `Observation` may be raw (not normalized). Strict equality comparison then fails.

**How to avoid:** Apply `normalize_app_identifier(platform, foreground_app)` before comparing with stored shortcut `app` fields. Also treat missing/empty `foreground_app` as a permissive filter (don't filter on app) rather than a zero-match case.

### Pitfall 4: Changing UnifiedSkillSearch Contract for App/Platform Filtering

**What goes wrong:** Adding `platform=` and `app=` parameters to `UnifiedSkillSearch.search()` or `ShortcutSkillStore.search()` breaks Phase 27 callers that don't pass these parameters.

**Why it happens:** The search contract is shared between Phase 29 retrieval and existing memory/skill-context injection paths.

**How to avoid:** Keep all app/platform filtering at the `GuiAgent` layer. After `UnifiedSkillSearch.search()` returns top-N results, filter the list in `_retrieve_shortcut_candidates()` before passing to the applicability router. Do not change `UnifiedSkillSearch.search()` or `ShortcutSkillStore.search()` signatures.

### Pitfall 5: Applicability Decision Not Emitted When Candidates List Is Empty

**What goes wrong:** When retrieval returns no candidates, no `shortcut_applicability` event is written, so runs with empty candidate lists look identical in traces to runs where evaluation was skipped.

**Why it happens:** The applicability event is only emitted inside the evaluation loop, which doesn't run if `candidates` is empty.

**How to avoid:** Always emit a `shortcut_applicability` event at the end of `run()`, even when the outcome is `fallback` with reason `no_candidates`. This satisfies the SUSE-02 traceability requirement for all runs.

### Pitfall 6: Re-Entering `_run_once()` Without Clearing the Shortcut Decision

**What goes wrong:** The retry loop calls `_run_once()` multiple times. If a shortcut is selected and fails, retries should NOT re-attempt the same shortcut — they should fall through to free agent exploration.

**Why it happens:** The applicability decision is evaluated once before the retry loop in `run()`, and the resulting `matched_skill` is reused across attempts. If the shortcut fails during execution, subsequent retry attempts should not re-select it.

**How to avoid:** On the first `result.success == False` after shortcut-assisted execution, clear `matched_skill` and `skill_context` before entering subsequent retry iterations. This is already the correct pattern for Phase 25's skill execution fallback.

## Code Examples

Verified patterns from official codebase sources:

### Current _search_skill Pattern (Phase 28 baseline)

```python
# Source: opengui/agent.py _search_skill()
async def _search_skill(self, task: str) -> Any | None:
    if self._unified_skill_search is not None:
        search_results = await self._unified_skill_search.search(task, top_k=1)
        if not search_results:
            return None
        result = search_results[0]
        if result.score >= self._skill_threshold:
            return result   # SkillSearchResult with .skill and .score
        return None
```

Phase 29 extends this to `top_k=N` and adds post-retrieval app/platform filtering:

```python
# Source: agent.py — Phase 29 replacement pattern
async def _retrieve_shortcut_candidates(
    self, task: str, platform: str, app_hint: str | None
) -> list[SkillSearchResult]:
    if self._unified_skill_search is None:
        return []
    results = await self._unified_skill_search.search(task, top_k=5)
    candidates = [r for r in results if r.score >= self._skill_threshold]
    if app_hint:
        normalized = normalize_app_identifier(platform, app_hint)
        platform_candidates = [
            r for r in candidates
            if r.skill.platform == platform and r.skill.app == normalized
        ]
        if platform_candidates:
            candidates = platform_candidates
    return candidates
```

### ConditionEvaluator Protocol (Phase 25 baseline)

```python
# Source: opengui/skills/multi_layer_executor.py
@runtime_checkable
class ConditionEvaluator(Protocol):
    async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool: ...
```

Phase 29 reuses this protocol unchanged as the applicability gate.

### TrajectoryRecorder.record_event Pattern (memory_retrieval precedent)

```python
# Source: opengui/agent.py _log_memory_retrieval()
self._trajectory_recorder.record_event(
    "memory_retrieval",
    task=task,
    hit_count=len(hits),
    hits=hits,
    context=context[:200],
)
```

Phase 29 adds two analogous event types: `shortcut_retrieval` and `shortcut_applicability`.

### Observation foreground_app Access

```python
# Source: opengui/observation.py
@dataclasses.dataclass
class Observation:
    screenshot_path: str | None
    screen_width: int
    screen_height: int
    foreground_app: str | None = None   # <-- app context for filtering
    platform: str = "unknown"           # <-- platform for filtering
```

Phase 29 uses `obs.foreground_app` and `obs.platform` from the initial observation in `_run_once()` to contextualize the applicability check.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Legacy `SkillLibrary.search()` + `compute_confidence()` gate | `UnifiedSkillSearch` BM25+FAISS hybrid, `SkillSearchResult.score` | Phase 27 | Hybrid search replaces confidence-weighted relevance |
| Single top-1 retrieval, score-only gate | Multi-candidate retrieval + screen-aware applicability check | Phase 29 | Retrieval score is necessary but not sufficient for execution safety |
| No provenance on stored skills | Full provenance (`source_trace_path`, `source_run_id`, `source_step_indices`) | Phase 28 | Applicability logging can now reference the origin run |

**Deprecated/outdated:**
- Single top-1 `_search_skill()` pattern: Phase 29 replaces with multi-candidate retrieval + applicability evaluation. Keep `_search_skill()` name or rename to `_retrieve_shortcut_candidates()` consistently.

## Open Questions

1. **Where does the initial observation screenshot come from for applicability evaluation?**
   - What we know: `_run_once()` takes an initial observation before the step loop; the screenshot is at `run_dir / "screenshots" / "step_000.png"`. `run()` calls `_run_once()` inside the retry loop, which means the screenshot isn't available until after `run()` starts a retry attempt.
   - What's unclear: The applicability check must happen before committing to shortcut execution, but the retry loop is the natural boundary. The cleanest approach is to evaluate applicability inside the first call to `_run_once()` using its initial observation, then surface the decision upward. This requires a small refactor of how `_run_once()` returns state back to `run()` (currently only returns `AgentResult`).
   - Recommendation: Extend `AgentResult` with optional `shortcut_decision` metadata, or evaluate applicability inside `run()` with a dedicated pre-loop observe call (with appropriate care around recorder state). The planner should lock this architectural decision.

2. **Should app/platform filter be strict or permissive at retrieval time?**
   - What we know: `Observation.foreground_app` is populated by backends but may be empty (e.g. desktop backend may return `None`). Strict filter on empty app returns no candidates.
   - What's unclear: Whether permissive (no filter when foreground_app is None) or platform-only filter is acceptable.
   - Recommendation: Use platform filter always; use app filter only when `foreground_app` is non-empty and normalizes to a non-"unknown" value.

3. **How many candidates should be retrieved (top-N)?**
   - What we know: The current store may be sparse (new v1.6 store; old legacy skills migrated only selectively). Setting N=5 is safe but retrieving too many could add unnecessary evaluation overhead.
   - Recommendation: Default to `top_k=5` for retrieval, then evaluate in score order. This matches the `UnifiedSkillSearch.search()` default.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py -q` |
| Full suite command | `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SUSE-01 | GuiAgent retrieves top-N shortcut candidates filtered by platform before the step loop | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_retrieval_filters_by_platform -x` | ❌ Wave 0 |
| SUSE-01 | App filter is permissive when foreground_app is absent | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_retrieval_permissive_without_foreground_app -x` | ❌ Wave 0 |
| SUSE-01 | Retrieval emits shortcut_retrieval trajectory event | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_retrieval_emits_trajectory_event -x` | ❌ Wave 0 |
| SUSE-02 | Applicability router returns `run` when all preconditions pass | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_applicability_run_when_conditions_pass -x` | ❌ Wave 0 |
| SUSE-02 | Applicability router returns `skip` when a precondition fails | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_applicability_skip_when_condition_fails -x` | ❌ Wave 0 |
| SUSE-02 | No shortcut candidates produces `fallback` decision and normal agent run | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_fallback_when_no_candidates -x` | ❌ Wave 0 |
| SUSE-02 | Applicability emits structured shortcut_applicability trajectory event | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_applicability_emits_trajectory_event -x` | ❌ Wave 0 |
| SUSE-02 | ConditionEvaluator exception produces fallback, does not abort run | unit | `uv run pytest tests/test_opengui_p29_retrieval_applicability.py::test_applicability_exception_produces_fallback -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_opengui_p29_retrieval_applicability.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p29_retrieval_applicability.py -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_opengui_p29_retrieval_applicability.py` — new test file covering all SUSE-01 and SUSE-02 behaviors
- [ ] `opengui/skills/shortcut_router.py` — new module for `ApplicabilityDecision` and `ShortcutApplicabilityRouter`

*(Existing `ShortcutSkillStore`, `UnifiedSkillSearch`, `ConditionEvaluator`, and `TrajectoryRecorder` infrastructure already covers Phase 29's dependencies; only the new module and test file are gaps.)*

## Sources

### Primary (HIGH confidence)

- `opengui/agent.py` — `GuiAgent.run()`, `_search_skill()`, `_run_once()`, `_retrieve_memory()` — direct inspection of current skill search and execution path
- `opengui/skills/shortcut_store.py` — `UnifiedSkillSearch.search()`, `ShortcutSkillStore.search()` — current search contract
- `opengui/skills/shortcut.py` — `ShortcutSkill.preconditions`, `StateDescriptor` — applicability condition schema
- `opengui/skills/multi_layer_executor.py` — `ConditionEvaluator` Protocol, `_AlwaysPassEvaluator`, `ContractViolationReport` — existing evaluator contract
- `opengui/observation.py` — `Observation.foreground_app`, `Observation.platform` — live screen context
- `opengui/trajectory/recorder.py` — `TrajectoryRecorder.record_event()` — event recording pattern
- `nanobot/agent/tools/gui.py` — `_run_task()`, `_get_unified_skill_search()` — current wiring of UnifiedSkillSearch into GuiAgent
- `.planning/phases/28-shortcut-extraction-productionization/28-RESEARCH.md` — Phase 28 design rationale and contract decisions
- `opengui/skills/normalization.py` — `normalize_app_identifier()` — app identity normalization used for filter

### Secondary (MEDIUM confidence)

- `tests/test_opengui_p27_storage_search_agent.py` — `test_agent_skill_lookup`, `test_agent_skill_lookup_logs_layer` — current test patterns for skill search in agent
- `tests/test_opengui_p28_shortcut_productionization.py` — covers `_promote_shortcut` seam; establishes pattern for Phase 29 tests
- `.planning/phases/27-storage-search-agent-integration/deferred-items.md` — pre-existing test failures that are out of scope for Phase 29

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all modules are workspace-current and directly inspected
- Architecture: HIGH — insertion point and patterns derived from live code; one open question on screenshot timing (documented)
- Pitfalls: HIGH — derived from direct code inspection of retry loop, observation flow, and filter logic

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (stable workspace code; 30-day validity)
