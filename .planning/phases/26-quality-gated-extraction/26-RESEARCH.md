# Phase 26: Quality-Gated Extraction - Research

**Researched:** 2026-04-02
**Domain:** Two-layer skill extraction pipeline with step-level and trajectory-level critics
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXTR-01 | Step-level critic evaluates each trajectory step for correctness before skill extraction | Implement a `StepCritic` Protocol with an `async evaluate(step, context) -> StepVerdict` method; returns a structured verdict (pass/fail with reason). A trajectory containing any failing step is not passed to the trajectory-level critic. |
| EXTR-02 | Trajectory-level critic evaluates overall trajectory quality before a skill is promoted to the library | Implement a `TrajectoryCritic` Protocol with an `async evaluate(steps, metadata) -> TrajectoryVerdict` method; returns a structured verdict. A trajectory that fails is not promoted to the skill library (caller receives the failed verdict). |
| EXTR-03 | Extraction pipeline only promotes skills from trajectories passing both critics | `ExtractionPipeline` runs `StepCritic` on each step first; if all pass, runs `TrajectoryCritic`; only if both pass calls the `ShortcutSkillProducer` to generate the candidate. |
| EXTR-04 | Extractor produces shortcut-layer skill candidates from validated step sequences | `ShortcutSkillProducer` (or equivalent extractor) converts a validated list of trajectory steps into a well-formed `ShortcutSkill` with: `ParameterSlot`s inferred from step targets/parameters, and pre/post `StateDescriptor`s mapped from step-level validity conditions. |
</phase_requirements>

## Summary

Phase 26 builds a pure pipeline layer on top of the Phase 24 schema contracts. It does not touch `ShortcutExecutor` or `TaskSkillExecutor` from Phase 25. The work has three distinct pieces that compose in sequence: two critic protocols (step-level and trajectory-level) and one extraction transformation (trajectory steps → `ShortcutSkill` candidate).

The existing `SkillExtractor` in `opengui/skills/extractor.py` is the legacy analog of EXTR-04, but it produces a flat `Skill` object (legacy schema) not a `ShortcutSkill`. Phase 26 must produce a `ShortcutSkill` using the Phase 24 types. The simplest route is a new `ShortcutSkillProducer` class that re-uses the existing LLM extraction prompt pattern but targets the new schema. The critics are entirely new — there is no partial predecessor to adapt.

The key design constraint inherited from Phases 24 and 25 is the project's protocol-injection pattern: critics must be `@runtime_checkable Protocol` interfaces so tests can use fakes with no LLM dependency. The extraction pipeline should be a thin orchestrator that wires critics + producer together, returning structured results (not raising exceptions) on rejection.

The trajectory data structure is already well-defined in `opengui/trajectory/recorder.py`. A trajectory JSONL file contains `metadata`, `step`, and `result` events. The `step` events each carry `action`, `screenshot_path`, `observation`, `step_index`, and optional `model_output`. These are the raw inputs the critics and producer consume.

**Primary recommendation:** Build Phase 26 as a new `opengui/skills/extraction/` package (or a single new file `opengui/skills/shortcut_extractor.py`) with three public symbols: `StepCritic` protocol, `TrajectoryCritic` protocol, and `ExtractionPipeline` + `ShortcutSkillProducer`. Use the project's frozen-dataclass + `Protocol` style throughout.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `dataclasses`, `typing`, `pathlib` | `>=3.11` | Verdict dataclasses, Protocol definitions | Matches all existing `opengui` contracts |
| `opengui.skills.shortcut` | workspace current | `ShortcutSkill`, `StateDescriptor`, `ParameterSlot` | Phase 24 schema types are the target output of EXTR-04 |
| `opengui.skills.data` | workspace current | `SkillStep` — trajectory step type when steps are re-parsed | Reused throughout; trajectory steps can carry `action_type`, `target`, etc. matching this type |
| `opengui.interfaces.LLMProvider` | workspace current | LLM-driven critic and producer implementation | Same interface used by `SkillExtractor` and `LLMGrounder` |
| `opengui.trajectory.recorder` | workspace current | `TrajectoryRecorder` event format consumed by critics/pipeline | Step events have known structure; no new trajectory format needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | `>=9.0.0,<10.0.0` | Unit test runner | All Phase 26 tests |
| `pytest-asyncio` | `>=1.3.0,<2.0.0` | Async critic and pipeline tests | Critics and pipeline are async; all test functions are async |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Separate `opengui/skills/shortcut_extractor.py` | Extend `opengui/skills/extractor.py` | Extension mixes two schemas in one file and risks touching the legacy path; new file avoids coupling |
| `ShortcutSkillProducer` as a separate class | Inline production inside `ExtractionPipeline` | Inline is simpler but harder to test in isolation; a separate callable/class matches the project's single-responsibility style and enables stub replacement |
| `Protocol`-based critics | Abstract base classes | ABCs add inheritance coupling; `Protocol` matches the existing `GrounderProtocol`, `ConditionEvaluator`, `StateValidator` style across the codebase |

**Installation:**
```bash
uv sync --extra dev
```

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
└── skills/
    ├── extractor.py              # existing SkillExtractor (legacy Skill, do not touch)
    ├── shortcut.py               # existing ShortcutSkill / StateDescriptor / ParameterSlot
    ├── shortcut_extractor.py     # NEW: StepCritic, TrajectoryCritic, ExtractionPipeline, ShortcutSkillProducer
    └── __init__.py               # export new Phase 26 public symbols

tests/
└── test_opengui_p26_quality_gated_extraction.py  # NEW: Phase 26 coverage
```

A flat file `shortcut_extractor.py` is preferred over a new package (`extraction/`) to stay consistent with the existing flat module layout in `opengui/skills/`.

### Pattern 1: Verdict Dataclasses With Boolean Discriminators
**What:** Each critic returns a frozen dataclass with `passed: bool` and `reason: str`. The calling pipeline pattern-matches on `verdict.passed`.
**When to use:** Return value of both `StepCritic.evaluate()` and `TrajectoryCritic.evaluate()`.
**Example:**
```python
# Source: pattern from multi_layer_executor.py ContractViolationReport / ShortcutExecutionSuccess
@dataclass(frozen=True)
class StepVerdict:
    step_index: int
    passed: bool
    reason: str

@dataclass(frozen=True)
class TrajectoryVerdict:
    passed: bool
    reason: str
    failed_step_index: int | None = None  # set when step-level failure caused rejection
```

### Pattern 2: Protocol-Based Critics With Always-Pass Defaults
**What:** `StepCritic` and `TrajectoryCritic` are `@runtime_checkable Protocol` classes; the pipeline accepts them as optional injected dependencies. When `None`, use always-pass fakes.
**When to use:** `ExtractionPipeline.__init__()` parameters.
**Example:**
```python
# Source: ConditionEvaluator pattern in opengui/skills/multi_layer_executor.py
@runtime_checkable
class StepCritic(Protocol):
    async def evaluate(self, step: dict[str, Any], step_index: int) -> StepVerdict: ...

@runtime_checkable
class TrajectoryCritic(Protocol):
    async def evaluate(self, steps: list[dict[str, Any]], metadata: dict[str, Any]) -> TrajectoryVerdict: ...
```

### Pattern 3: Pipeline Returns Structured Result, Never Raises
**What:** `ExtractionPipeline.run()` returns a result union (`ExtractionSuccess | ExtractionRejected`). `ExtractionRejected` carries the failing verdict so callers can observe why a trajectory was blocked.
**When to use:** Whenever a trajectory is processed.
**Example:**
```python
# Source: pattern from multi_layer_executor.py result unions
@dataclass(frozen=True)
class ExtractionSuccess:
    candidate: ShortcutSkill
    step_verdicts: tuple[StepVerdict, ...]
    trajectory_verdict: TrajectoryVerdict

@dataclass(frozen=True)
class ExtractionRejected:
    reason: str  # "step_critic" | "trajectory_critic"
    failed_step_verdict: StepVerdict | None   # populated when reason == "step_critic"
    failed_trajectory_verdict: TrajectoryVerdict | None  # populated when reason == "trajectory_critic"
```

### Pattern 4: ShortcutSkillProducer Infers ParameterSlots From Step Targets
**What:** The producer scans step targets for `{{param_name}}` placeholders and maps them to `ParameterSlot` instances. Pre/post conditions are mapped from `valid_state` and `expected_state` fields of `SkillStep` objects (the same fields the legacy `SkillExtractor` populates).
**When to use:** Inside `ShortcutSkillProducer.produce()` or equivalent.
**Example:**
```python
# Source: opengui/skills/data.py SkillStep.valid_state + shortcut.py ParameterSlot
import re
_PARAM_RE = re.compile(r"\{\{(\w+)\}\}")

def _infer_slots(steps: list[SkillStep]) -> tuple[ParameterSlot, ...]:
    seen: dict[str, ParameterSlot] = {}
    for step in steps:
        for name in _PARAM_RE.findall(step.target):
            if name not in seen:
                seen[name] = ParameterSlot(name=name, type="string", description=f"Value for {name}")
    return tuple(seen.values())

def _map_conditions(steps: list[SkillStep]) -> tuple[StateDescriptor, ...]:
    conditions = []
    for step in steps:
        if step.valid_state and step.valid_state.lower() not in ("no need to verify", ""):
            conditions.append(StateDescriptor(kind="screen_state", value=step.valid_state))
    return tuple(conditions)
```

### Anti-Patterns to Avoid
- **Letting the pipeline raise exceptions on critic failure:** The Phase 25 approach of returning structured reports must be followed here. Rejection is a normal outcome, not an error.
- **Mixing legacy `Skill` output with `ShortcutSkill` output:** `shortcut_extractor.py` must only produce `ShortcutSkill` — never a legacy `Skill`. The existing `extractor.py` continues to produce `Skill` for the legacy path.
- **Embedding LLM-specific logic inside the Protocol:** `StepCritic` and `TrajectoryCritic` are protocols. The `LLMStepCritic` and `LLMTrajectoryCritic` concrete implementations wrap LLM calls, but the protocol interface stays LLM-agnostic.
- **Requiring live screenshots for critic evaluation in tests:** Critics must be testable with stub fake classes that do not need real screenshots or LLM calls. Keep the protocol signatures minimal.
- **Skipping trajectory length validation before running critics:** A trajectory with fewer than 2 steps should be rejected before either critic runs — avoid burning LLM tokens on degenerate trajectories.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON parsing and trajectory reading | Custom JSONL parser | `json.loads()` per line; pattern from `SkillExtractor.extract_from_file()` | The trajectory format is already established in `recorder.py` and consumed by `extractor.py` |
| `{{param}}` extraction from step targets | Ad hoc string parsing | `re.compile(r"\{\{(\w+)\}\}")` — same pattern used in existing extraction prompts | The existing extraction prompt already defines this convention; reuse it exactly |
| App identifier normalization | Inline string manipulation | `normalize_app_identifier()` from `opengui/skills/normalization.py` | Already handles Android, iOS, and macOS app identifier forms |
| Base64 screenshot encoding for LLM critic | New encoder | `_encode_image_b64()` from `opengui/skills/extractor.py` | Exact same PIL-based scaling + encoding pattern; extract or re-use |

**Key insight:** The data-flow for Phase 26 is trajectory steps → critics → producer → `ShortcutSkill`. Everything except the critics and the `ShortcutSkill`-specific producer already has precedent in `extractor.py`. Phase 26 is an orchestration layer over well-established primitives.

## Common Pitfalls

### Pitfall 1: Step-Level Critic Returns Aggregate Result Instead of Per-Step Verdicts
**What goes wrong:** `StepCritic` evaluates all steps and returns a single verdict, making it impossible to identify *which* step failed and short-circuit early.
**Why it happens:** It is natural to model a "trajectory step reviewer" as a single trajectory-level call.
**How to avoid:** Design `StepCritic.evaluate()` to take one step at a time (`step_index`, step dict). The pipeline loops over steps and calls `StepCritic.evaluate()` once per step, stopping at the first failure.
**Warning signs:** The protocol signature takes `list[dict]` instead of a single step dict.

### Pitfall 2: Confusing The Two Critics' Scopes
**What goes wrong:** The step critic becomes a trajectory-level analysis (action sequence quality) and the trajectory critic duplicates per-step checks. Both end up doing the same work.
**Why it happens:** The boundary between "step correctness" and "trajectory quality" is not obvious without explicit scope definitions.
**How to avoid:** Lock the scopes: the step critic checks a single step in isolation (action type valid, target non-empty, no obviously malformed parameters); the trajectory critic checks the entire sequence holistically (task goal was reached, no contradictory steps, minimum step count, overall success outcome).

### Pitfall 3: ShortcutSkillProducer Ignores `valid_state` / `expected_state` Fields
**What goes wrong:** The produced `ShortcutSkill` has empty `preconditions` and `postconditions` tuples, failing the EXTR-04 requirement that conditions are mapped to pre/post descriptors.
**Why it happens:** `valid_state` is a legacy string field on `SkillStep`. It is easy to overlook when building new `StateDescriptor` objects.
**How to avoid:** In the producer, explicitly iterate `step.valid_state` → `StateDescriptor(kind="screen_state", value=...)` for preconditions and `step.expected_state` → postconditions. Test this mapping explicitly.

### Pitfall 4: Pipeline Module Imports Executor or Storage Code
**What goes wrong:** `shortcut_extractor.py` imports `ShortcutExecutor`, `TaskSkillExecutor`, or any Phase 27 storage modules — creating coupling to execution or persistence concerns.
**Why it happens:** It is tempting to wire things together in one file.
**How to avoid:** `shortcut_extractor.py` may only import from `opengui/skills/shortcut.py`, `opengui/skills/data.py`, `opengui/skills/normalization.py`, and `opengui/interfaces.py`. No executor, no store, no Phase 27 symbols.

### Pitfall 5: Always-Pass Defaults Mask Missing Protocol Implementations In Tests
**What goes wrong:** All pipeline tests pass even with no-op critics because the always-pass default is silently used.
**Why it happens:** The always-pass default is a convenience for dry-run, but tests may forget to inject real or strict fake critics.
**How to avoid:** For tests that specifically verify the rejection path, explicitly inject a `FakeStepCritic` or `FakeTrajectoryCritic` that is configured to fail. Do not rely solely on the always-pass default in the test suite.

## Code Examples

Verified patterns from repo sources:

### Trajectory JSONL Step Event Shape
```python
# Source: opengui/trajectory/recorder.py TrajectoryRecorder.record_step()
{
    "type": "step",
    "step_index": 2,
    "phase": "agent",
    "timestamp": 1234567890.0,
    "action": {"action_type": "tap", "x": 540, "y": 120},
    "model_output": "Tapping the search bar",
    "screenshot_path": "/tmp/trace_20260402/step_002.png",
    "observation": {"screen_width": 1080, "screen_height": 1920, ...},
}
```

### Reading Steps From a JSONL File
```python
# Source: opengui/skills/extractor.py SkillExtractor.extract_from_file()
lines = trajectory_path.read_text(encoding="utf-8").strip().splitlines()
events = [json.loads(line) for line in lines if line.strip()]
steps = [e for e in events if e.get("type") == "step"]
result_events = [e for e in events if e.get("type") == "result"]
is_success = result_events[-1].get("success", True) if result_events else True
```

### Frozen Dataclass Protocol Combination (from Phase 24/25 style)
```python
# Source: opengui/skills/multi_layer_executor.py (ConditionEvaluator + ContractViolationReport)
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@runtime_checkable
class StepCritic(Protocol):
    async def evaluate(self, step: dict[str, Any], step_index: int) -> "StepVerdict": ...

@dataclass(frozen=True)
class StepVerdict:
    step_index: int
    passed: bool
    reason: str
```

### ParameterSlot Inference From Target Strings
```python
# Source: opengui/skills/extractor.py extraction prompt uses {{param}} convention
import re
_PARAM_RE = re.compile(r"\{\{(\w+)\}\}")
names = _PARAM_RE.findall("Tap on {{button_name}} in the {{panel}} view")
# names == ["button_name", "panel"]
```

### ShortcutSkill Construction (Phase 24 schema)
```python
# Source: opengui/skills/shortcut.py ShortcutSkill
import uuid, time
from opengui.skills.shortcut import ShortcutSkill, ParameterSlot, StateDescriptor
from opengui.skills.data import SkillStep

candidate = ShortcutSkill(
    skill_id=str(uuid.uuid4()),
    name="open_settings",
    description="Navigate to the Settings screen",
    app="com.android.settings",
    platform="android",
    steps=(
        SkillStep(action_type="tap", target="Settings icon"),
    ),
    parameter_slots=(
        ParameterSlot(name="section", type="string", description="Settings section to open"),
    ),
    preconditions=(
        StateDescriptor(kind="screen_state", value="Home screen is visible"),
    ),
    postconditions=(
        StateDescriptor(kind="screen_state", value="Settings screen is open"),
    ),
    created_at=time.time(),
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `SkillExtractor` produces legacy `Skill` with free-form string `preconditions` | `ShortcutSkillProducer` produces `ShortcutSkill` with structured `StateDescriptor` pre/post conditions | Phase 26 | Checkable conditions instead of text descriptions |
| No quality gate before skill promotion; any trajectory could produce a skill | Two-critic pipeline blocks promotion on step-level or trajectory-level failure | Phase 26 | Skills in the library have provably passed two evaluation checkpoints |
| Single extraction class with no protocol boundary for critics | `StepCritic` and `TrajectoryCritic` as injectable protocols | Phase 26 | Swappable critic implementations (LLM, rule-based, always-pass) |

**Deprecated/outdated:**
- Do not adapt `SkillExtractor` to produce `ShortcutSkill` — the legacy path must remain intact for any code that still uses it; Phase 26 adds a parallel extraction path.

## Open Questions

1. **What is the LLM-driven step critic checking specifically?**
   - What we know: The requirement says "correctness" — action type must be valid, target must be non-empty, parameters must not be obviously malformed.
   - What's unclear: Whether there is a LLM-based visual validation step (screenshot → does action match what's visible?) or only a structural check.
   - Recommendation: Plan for two critic variants: a structural `RuleBasedStepCritic` (fast, no LLM) that rejects degenerate steps, and an `LLMStepCritic` that optionally adds visual validation. Start with the rule-based one as the default; the Protocol makes swapping easy.

2. **What trajectory metadata does TrajectoryCritic receive?**
   - What we know: Metadata events from the JSONL include task description, platform, initial phase, and the final `result` event (success boolean, total steps, duration).
   - What's unclear: Whether the critic also receives individual step observations/screenshots or only the compact step dicts.
   - Recommendation: Pass the compact step dicts plus the result metadata dict. Screenshots can be provided as `screenshot_path` strings within each step dict — the critic decides whether to load them.

3. **Does Phase 26 produce `TaskSkill` candidates in addition to `ShortcutSkill`?**
   - What we know: EXTR-04 says "shortcut-layer skill candidates." EXTR-05 (task-level synthesis) is explicitly deferred to v1.6.
   - What's unclear: Nothing — the scope is clear: Phase 26 only produces `ShortcutSkill`.
   - Recommendation: Confirm in planning that `ShortcutSkillProducer` returns `ShortcutSkill` only.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest >=9.0.0,<10.0.0` + `pytest-asyncio >=1.3.0,<2.0.0` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXTR-01 | Step critic evaluates a single step and returns a `StepVerdict(passed=False)` that causes pipeline to stop before trajectory critic | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q -k step_critic` | ❌ Wave 0 |
| EXTR-02 | Trajectory critic evaluates complete step list and returns `TrajectoryVerdict(passed=False)` that stops promotion | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q -k trajectory_critic` | ❌ Wave 0 |
| EXTR-03 | Pipeline calls critics in order: step first, then trajectory; only calls producer when both pass | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q -k pipeline` | ❌ Wave 0 |
| EXTR-04 | Producer builds a `ShortcutSkill` from steps with inferred `ParameterSlot`s and mapped `StateDescriptor` pre/post conditions | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py -q -k producer` | ❌ Wave 0 |
| Phase 26 import safety | New module imports and compiles without circular imports | smoke | `uv run python -m py_compile opengui/skills/shortcut_extractor.py` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p24_schema_grounding.py tests/test_opengui_p25_multi_layer_execution.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p24_schema_grounding.py tests/test_opengui_p25_multi_layer_execution.py tests/test_opengui_p1_skills.py -q`
- **Phase gate:** `uv run pytest -q`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p26_quality_gated_extraction.py` — covers EXTR-01 through EXTR-04 and import safety
- [ ] `opengui/skills/shortcut_extractor.py` — the new module (empty stub or full TDD RED stubs before GREEN)
- [ ] Add `StepCritic`, `TrajectoryCritic`, `StepVerdict`, `TrajectoryVerdict`, `ExtractionPipeline`, `ExtractionSuccess`, `ExtractionRejected`, `ShortcutSkillProducer` to `opengui/skills/__init__.py` exports

## Sources

### Primary (HIGH confidence)
- `.planning/REQUIREMENTS.md` — EXTR-01 through EXTR-04 requirement text
- `opengui/skills/extractor.py` — legacy extraction pattern (LLM calls, JSONL parsing, step iteration)
- `opengui/skills/shortcut.py` — `ShortcutSkill`, `StateDescriptor`, `ParameterSlot` — Phase 24 target schema
- `opengui/skills/task_skill.py` — `SkillStep` reuse pattern, task node serialization style
- `opengui/skills/data.py` — `SkillStep.valid_state`, `SkillStep.expected_state` — source for condition mapping
- `opengui/skills/multi_layer_executor.py` — Protocol pattern, result union pattern, always-pass default pattern
- `opengui/trajectory/recorder.py` — trajectory JSONL event format and step event schema
- `opengui/skills/normalization.py` — `normalize_app_identifier()` for producer
- `opengui/interfaces.py` — `LLMProvider` and `@runtime_checkable Protocol` style
- `opengui/grounding/protocol.py` — `GrounderProtocol` / `GroundingResult` as second Protocol-style reference
- `.planning/STATE.md` — Phase 24/25 decisions, v1.5 roadmap decisions
- `.planning/phases/24-schema-and-grounding/24-RESEARCH.md` — Phase 24 research (schema reference)
- `.planning/phases/25-multi-layer-execution/25-RESEARCH.md` — Phase 25 research (Protocol injection style)
- `.planning/phases/25-multi-layer-execution/25-02-SUMMARY.md` — confirmed Phase 25 is complete, no executor regressions

### Secondary (MEDIUM confidence)
- `tests/test_opengui_p25_multi_layer_execution.py` — test stub pattern (FakeBackend, StubGrounder) confirms test style for Phase 26
- `tests/test_opengui_p24_schema_grounding.py` — existing grounding/schema protocol test style

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Derived entirely from local repo code, `pyproject.toml`, and prior phase research
- Architecture: HIGH — Directly grounded in existing Protocol patterns and legacy extractor code in the repo
- Pitfalls: HIGH — Derived from concrete schema boundaries, Protocol injection rules, and legacy extractor behavior that must not be disturbed

**Research date:** 2026-04-02
**Valid until:** 2026-05-02
