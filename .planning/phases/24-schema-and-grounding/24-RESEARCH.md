# Phase 24: Schema and Grounding - Research

**Researched:** 2026-04-02
**Domain:** Two-layer OpenGUI skill contracts, recursive task-skill serialization, and pluggable grounding protocol boundaries
**Confidence:** HIGH

<user_constraints>
## User Constraints

- Use `.planning/phases/24-schema-and-grounding/24-CONTEXT.md` as the source of truth for locked Phase 24 decisions.
- Keep Phase 24 scoped to schema and protocol contracts only. Executors, critics, storage, and agent integration stay in Phases 25-27.
- Preserve the existing OpenGUI style: stdlib-first models, `typing.Protocol` interfaces, frozen dataclasses with explicit `to_dict()` / `from_dict()` helpers, and minimal third-party dependencies in core `opengui` contracts.
- Avoid circular imports with the existing `opengui` module tree.

### Locked Decisions Inherited From Prior Phases
- Existing `Skill` and `SkillStep` remain in place during Phase 24; this phase adds new types rather than replacing the current executor path immediately.
- `GrounderProtocol` should follow the existing `@runtime_checkable Protocol` pattern used by `LLMProvider` and `DeviceBackend`.
- `TaskSkill` may reuse `SkillStep` as the inline ATOM fallback node type.
- Existing skill data is reference-only; this milestone is a fresh-start schema, not a migration phase.

### Claude's Discretion
- Exact starter vocabulary shipped for `StateDescriptor.kind` beyond the locked examples.
- Whether the new grounding package re-exports all types from `opengui/grounding/__init__.py` or only the main protocol/result surface.
- Exact optional metadata mirrored from the legacy `Skill` model onto `ShortcutSkill` and `TaskSkill`, provided round-trip serialization remains stable and downstream phases get the required fields.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCHEMA-01 | Shortcut skill defines pre/post conditions as structured, checkable state descriptors | Introduce a reusable `StateDescriptor` dataclass and use tuples of descriptors on `ShortcutSkill` instead of free-form strings. |
| SCHEMA-02 | Shortcut skill declares typed parameter slots for runtime grounding | Introduce a `ParameterSlot` dataclass with string-serializable type tags and descriptions; keep it detached from execution logic. |
| SCHEMA-03 | Task-level skill references shortcut skills by ID with parameter binding declarations | Add `ShortcutRefNode` with stable `shortcut_id` and explicit `param_bindings` dict. |
| SCHEMA-04 | Task-level skill supports inline ATOM fallback steps | Reuse `SkillStep` from `opengui/skills/data.py` as the inline ATOM node so later executors can share existing action semantics. |
| SCHEMA-05 | Task-level skill supports conditional branch nodes with checkable condition expressions | Add `BranchNode` whose `condition` is a structured `StateDescriptor`, not a free-form expression string. |
| SCHEMA-06 | Task-level skill carries an optional pointer to an app memory context entry | Keep `memory_context_id: str | None` as an opaque ID that points into the existing memory store without importing storage behavior into the schema. |
| GRND-01 | GrounderProtocol defines a common async interface for resolving semantic step targets to concrete action parameters | Add a dedicated `opengui/grounding` package with `GrounderProtocol`, `GroundingContext`, and `GroundingResult`. |
| GRND-02 | LLMGrounder implements GrounderProtocol wrapping the existing vision-LLM grounding path | Make `LLMGrounder` a thin adapter around the current agent-side grounding style instead of embedding executor logic in the protocol layer. |
| GRND-03 | Grounding results expose grounder used, confidence score, and fallback metadata | `GroundingResult` should include `grounder_id`, `confidence`, `resolved_params`, and nullable `fallback_metadata`. |
</phase_requirements>

## Summary

Phase 24 should be planned as a contract-foundation phase, not an execution phase. The current codebase already gives strong signals about how these contracts should look:
- `opengui/skills/data.py` uses frozen dataclasses plus explicit serialization helpers.
- `opengui/interfaces.py` uses stdlib-only `Protocol` interfaces to avoid heavyweight dependencies in core contracts.
- `opengui/agent.py` already contains a concrete LLM-driven grounding path, but it is embedded inside agent wiring instead of exposed as a reusable protocol/result surface.

The safest planning direction is to keep all new Phase 24 contracts in that same style: frozen dataclasses for persisted models and context/result payloads, `typing.Protocol` for pluggable interfaces, and explicit discriminators for any recursive union that must round-trip through JSON.

The highest-risk area is `TaskSkill` serialization. The locked context already chooses a union of `ShortcutRefNode | SkillStep | BranchNode`. That is a good runtime shape, but it will not serialize safely unless the plan includes an explicit node discriminator at the dict level. A plain dataclass union is not enough for round-trip persistence. The planner should therefore require a `kind`-tagged serialization layer for task nodes, even if the in-memory API stays as a Python union type alias.

The second important design choice is to keep grounding contracts narrow. `GrounderProtocol` should resolve semantic targets into action parameters, not produce `Action` objects directly. That keeps Phase 24 aligned with the roadmap language and makes Phase 25 executors responsible for combining skill step semantics with grounded parameters. `LLMGrounder` can still reuse the current screenshot-plus-LLM flow conceptually, but the public result of Phase 24 should be parameter-resolution metadata, not a full action executor.

**Primary recommendation:** plan Phase 24 around three deliverables:
1. Shared schema primitives and `ShortcutSkill`
2. Recursive `TaskSkill` node model with explicit round-trip serialization tags
3. Grounding protocol package plus regression tests proving import-safety, serialization, and type-check safety

## Recommended Phase Split

### 24-01: Shared Skill Schema Primitives And ShortcutSkill
- Add `StateDescriptor` and `ParameterSlot` under `opengui/skills/shortcut.py`
- Add `ShortcutSkill` with explicit `to_dict()` / `from_dict()` and tuple-based descriptor/slot fields
- Keep optional metadata close to the legacy `Skill` shape where that reduces downstream friction
- Update `opengui/skills/__init__.py` exports

### 24-02: TaskSkill Recursive Node Model
- Add `ShortcutRefNode`, `BranchNode`, `TaskNode`, and `TaskSkill` under `opengui/skills/task_skill.py`
- Reuse `SkillStep` for inline ATOM fallback nodes
- Implement explicit node discriminator serialization for the union, with backwards-safe parsing only for Phase 24 shapes
- Add tests proving nested branch structures serialize and round-trip cleanly

### 24-03: Grounding Protocol Package And Safety Coverage
- Add `opengui/grounding/` with `GrounderProtocol`, `GroundingContext`, `GroundingResult`, and `LLMGrounder`
- Keep `GroundingContext` executor-agnostic: screenshot reference, `Observation`, `ParameterSlot`s, optional `task_hint`
- Ensure imports do not pull in executor or host-specific modules
- Add regression coverage for protocol conformance, result shape, exports, and type-check / import-compile safety

### Why This Split Is Low-Coupling
- `24-01` establishes the reusable descriptor and slot primitives that both `TaskSkill` and grounding depend on.
- `24-02` depends on those primitives but not on any live grounding implementation.
- `24-03` depends on `ParameterSlot` and `Observation`, but not on executors, storage, or extraction logic from later phases.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib dataclasses / typing / pathlib | Python 3.11+ | Schema objects, recursive type aliases, protocol definitions | Matches existing `opengui` model style and keeps core contracts dependency-light |
| `opengui/skills/data.py` | repo current | Existing `SkillStep` fallback node and serialization pattern | Phase 24 should extend this seam, not replace it |
| `opengui/interfaces.py` | repo current | `@runtime_checkable Protocol` reference pattern | Defines the style `GrounderProtocol` should match |
| `opengui/observation.py` | repo current | Existing observation payload consumed by grounding context | Already the canonical screen-state data carrier |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | `>=9.0.0,<10.0.0` | Schema and round-trip regression tests | Default unit-test framework already used across OpenGUI |
| `pytest-asyncio` | `>=1.3.0,<2.0.0` | Async `LLMGrounder` interface tests | Needed once protocol calls are async |
| `uv run python -m py_compile` | repo current | Fast import/compile sanity gate for new modules | Good lightweight proxy for the roadmap’s type/import safety criterion |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Frozen dataclasses with explicit serializers | Pydantic models in core `opengui` modules | Easier discriminated unions, but introduces a heavier dependency style than the current core contracts use |
| Structured `StateDescriptor` condition objects | Raw string expressions for branch conditions | Faster to write, but weakens checkability and drifts from SCHEMA-01 / SCHEMA-05 |
| `GroundingResult` returning resolved params | Protocol returns full `Action` objects | Couples grounding to executor semantics too early and makes Phase 25 less modular |
| Explicit `kind` tags for task-node serialization | Heuristic deserialization by field presence | Brittle for nested unions and risky for storage/search phases later |

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
├── skills/
│   ├── data.py                 # existing Skill / SkillStep
│   ├── shortcut.py             # NEW: StateDescriptor, ParameterSlot, ShortcutSkill
│   ├── task_skill.py           # NEW: ShortcutRefNode, BranchNode, TaskNode, TaskSkill
│   └── __init__.py             # export new schema contracts
├── grounding/
│   ├── __init__.py             # NEW: explicit public exports
│   ├── protocol.py             # NEW: GrounderProtocol, GroundingContext, GroundingResult
│   └── llm.py                  # NEW: LLMGrounder implementation
tests/
├── test_opengui_p1_skills.py   # extend existing skill serialization coverage
└── test_opengui_p24_schema_grounding.py  # NEW: Phase 24 schema / grounding contract tests
```

### Pattern 1: Use Explicit Serialization Tags For Recursive Task Nodes
**What:** Serialize `TaskNode` unions with a required `kind` field such as `shortcut_ref`, `atom_step`, or `branch`.
**When to use:** Every `TaskSkill.to_dict()` / `from_dict()` round-trip.
**Example shape:**
```python
{"kind": "shortcut_ref", "shortcut_id": "open_settings", "param_bindings": {"panel": "{{panel}}"}}
{"kind": "atom_step", "step": {...SkillStep.to_dict()...}}
{"kind": "branch", "condition": {...}, "then_steps": [...], "else_steps": [...]}
```
**Why:** The in-memory union is clean, but persistence/search phases need deterministic round-trip parsing.

### Pattern 2: Keep Contracts Executor-Agnostic
**What:** Schema and grounding modules should not import `SkillExecutor`, `GuiAgent`, or host-specific backends.
**When to use:** Module layout and constructor design for all new Phase 24 types.
**Why:** The roadmap explicitly requires import safety and no circular imports before execution work begins.

### Pattern 3: Match Existing OpenGUI Contract Style
**What:** Prefer frozen dataclasses plus small manual serializers and `Protocol` interfaces.
**When to use:** All new persisted or shared contract objects in `opengui`.
**Why:** This keeps Phase 24 aligned with `Skill`, `SkillStep`, `LLMProvider`, `DeviceBackend`, and other already-shipped code.

### Pattern 4: Treat `memory_context_id` As An Opaque Link
**What:** Store the memory reference as a plain string ID instead of importing storage behavior into `TaskSkill`.
**When to use:** `TaskSkill` field design and serialization.
**Why:** Storage lookup and injection logic belong to Phase 27, while Phase 24 only needs a stable pointer shape.

### Pattern 5: Make `LLMGrounder` A Thin Adapter, Not A New Execution Loop
**What:** `LLMGrounder` should package LLM-driven target grounding behind `GrounderProtocol`, but it should not own retries, execution, or recovery orchestration beyond what is necessary to produce a `GroundingResult`.
**When to use:** Planning the grounding module boundaries.
**Why:** Phase 24 defines contracts; deeper runtime behavior belongs in Phase 25 executors.

### Anti-Patterns to Avoid
- **Replacing legacy `Skill` immediately:** Phase 24 only needs parallel contracts, not a migration.
- **Using enums for every descriptor or slot type:** locks the schema too early and makes extension heavier for later phases.
- **Serializing task nodes without a discriminator:** too fragile for recursive unions.
- **Letting `GrounderProtocol` depend on executor-only types:** creates circular import risk.
- **Embedding storage/search concerns into schema classes:** Phase 27 should own persistence decisions.

## Proposed Artifacts And Contracts

| Artifact | Scope In Phase 24 | Why It Belongs Here |
|---------|-------------------|---------------------|
| `StateDescriptor` | Shared structured state predicate | Needed by both `ShortcutSkill` and `BranchNode` |
| `ParameterSlot` | Shared typed grounding slot contract | Needed by schemas, extractor, and grounding |
| `ShortcutSkill` | New shortcut-layer skill model | Satisfies SCHEMA-01 and SCHEMA-02 |
| `ShortcutRefNode` / `BranchNode` / `TaskNode` / `TaskSkill` | Task-layer composition grammar | Satisfies SCHEMA-03 through SCHEMA-06 |
| `GrounderProtocol` / `GroundingContext` / `GroundingResult` | Pluggable grounding boundary | Satisfies GRND-01 and GRND-03 |
| `LLMGrounder` | Concrete grounding implementation adapter | Satisfies GRND-02 |

### Contract Decisions To Lock Before Planning
- `TaskNode` needs explicit serialized discriminators even if the public Python type is a union.
- `GroundingContext` should carry `Observation` plus a concrete screenshot reference so later executors do not need to reconstruct screen state.
- `GroundingResult.confidence` should remain a simple float in `[0.0, 1.0]`; fallback reasoning belongs in `fallback_metadata`, not in the primary fields.
- `ParameterSlot.type` should stay a serialization-friendly string tag for now; no runtime registry is needed in Phase 24.
- `ShortcutSkill` and `TaskSkill` should each own their own `to_dict()` / `from_dict()` rather than relying on generic dataclass introspection helpers.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Recursive union persistence | Ad hoc field-presence guessing | Explicit `kind`-tagged node serialization | Deterministic and future-proof for storage/search |
| Grounding interface reuse | Executor-specific `ActionGrounder` in `skills/executor.py` | Dedicated `GrounderProtocol` in `opengui/grounding` | Keeps the new contract reusable outside the current executor |
| Type/import safety | Assuming tests alone catch import cycles | Targeted compile/import checks plus schema unit tests | Matches the roadmap’s explicit import/type-check goal |
| Memory linkage | Inline memory payloads inside `TaskSkill` | Opaque `memory_context_id` string pointer | Keeps schema clean and Phase 27-friendly |

## Common Pitfalls

### Pitfall 1: Recursive `TaskNode` round-trip breaks on nested branches
**What goes wrong:** `TaskSkill.from_dict()` cannot reliably tell branch nodes from shortcut refs or inline steps once nesting is involved.
**How to avoid:** Require a `kind` discriminator for every serialized node.

### Pitfall 2: `GrounderProtocol` becomes a second executor API
**What goes wrong:** Grounding starts returning fully materialized actions or owns retry/recovery logic that should live in executors.
**How to avoid:** Keep the interface focused on parameter resolution plus metadata.

### Pitfall 3: New schema modules import runtime-heavy code
**What goes wrong:** `shortcut.py`, `task_skill.py`, or `grounding/*` reach into agent/executor modules and create circular imports.
**How to avoid:** Restrict imports to `SkillStep`, `Observation`, stdlib types, and protocol-only surfaces.

### Pitfall 4: Over-modeling descriptor vocab too early
**What goes wrong:** An enum-heavy or validator-heavy state descriptor makes later extractor/executor work brittle.
**How to avoid:** Keep `kind` as an open string with a small starter vocabulary and document examples rather than enforcing a closed set.

### Pitfall 5: Tests only cover happy-path serialization
**What goes wrong:** Phase 24 appears complete, but nested unions, optional memory pointers, and protocol import safety are unverified.
**How to avoid:** Add a dedicated Phase 24 test file covering round-trip, nested branches, protocol conformance, and import compile checks.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest >=9.0.0,<10.0.0` + `pytest-asyncio >=1.3.0,<2.0.0` |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest -q tests/test_opengui_p1_skills.py tests/test_opengui_p1_memory.py tests/test_opengui_p24_schema_grounding.py` |
| Full suite command | `uv run pytest` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCHEMA-01, SCHEMA-02 | `ShortcutSkill`, `StateDescriptor`, and `ParameterSlot` serialize and round-trip cleanly | unit | `uv run pytest -q tests/test_opengui_p24_schema_grounding.py -k "shortcut or parameter_slot or state_descriptor"` | ❌ Wave 0 |
| SCHEMA-03, SCHEMA-04, SCHEMA-05, SCHEMA-06 | `TaskSkill` supports shortcut refs, inline `SkillStep` fallbacks, nested branches, and optional `memory_context_id` | unit | `uv run pytest -q tests/test_opengui_p24_schema_grounding.py -k "task_skill or branch or memory_context"` | ❌ Wave 0 |
| GRND-01, GRND-02, GRND-03 | `GrounderProtocol` and `LLMGrounder` expose async protocol-conformant results with `grounder_id`, `confidence`, and `fallback_metadata` | unit | `uv run pytest -q tests/test_opengui_p24_schema_grounding.py -k "grounder or grounding_result or protocol"` | ❌ Wave 0 |
| Phase 24 SC-4 | New schema and grounding modules import and compile without circular import failures | smoke | `uv run python -m py_compile opengui/skills/data.py opengui/skills/shortcut.py opengui/skills/task_skill.py opengui/grounding/__init__.py opengui/grounding/protocol.py opengui/grounding/llm.py` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest -q tests/test_opengui_p1_skills.py tests/test_opengui_p1_memory.py tests/test_opengui_p24_schema_grounding.py`
- **Per wave merge:** `uv run pytest -q tests/test_opengui_p1_skills.py tests/test_opengui_p1_memory.py tests/test_opengui_p24_schema_grounding.py`
- **Phase gate:** `uv run pytest`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p24_schema_grounding.py` — new Phase 24 coverage for schema round-trip, recursive task nodes, grounding protocol/result shape, and import safety
- [ ] Update `tests/test_opengui_p1_skills.py` — export visibility and compatibility checks where legacy `SkillStep` coexists with the new task node model
- [ ] Add compile/import verification command for the new `opengui/grounding` and `opengui/skills` modules

## Sources

### Primary (HIGH confidence)
- `.planning/ROADMAP.md` - Phase 24 scope, requirements, and success criteria
- `.planning/REQUIREMENTS.md` - SCHEMA and GRND requirement definitions
- `.planning/phases/24-schema-and-grounding/24-CONTEXT.md` - locked design decisions for this phase
- `.planning/PROJECT.md` - milestone-level design direction and constraints
- `.planning/STATE.md` - current milestone state and prior-phase decisions
- `opengui/skills/data.py` - existing dataclass serialization pattern and `SkillStep` reuse seam
- `opengui/skills/__init__.py` - existing export pattern
- `opengui/skills/executor.py` - current grounding/executor split and existing `ActionGrounder` surface
- `opengui/agent.py` - current LLM-driven grounding implementation style
- `opengui/interfaces.py` - `Protocol` style and import-light contract boundary
- `opengui/observation.py` - grounding-context observation payload
- `opengui/memory/types.py` - current memory entry identity model
- `tests/test_opengui_p1_skills.py` - existing skill serialization / execution regression seam
- `tests/test_opengui_p1_memory.py` - memory entry round-trip seam relevant to `memory_context_id`
- `pyproject.toml` - runtime and test stack

### Secondary (MEDIUM confidence)
- `tests/test_gui_skill_executor_wiring.py` - current skill executor wiring seam that later phases must not break

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - based on local repo code and `pyproject.toml`
- Architecture: HIGH - directly grounded in current `opengui` model, protocol, and agent code
- Pitfalls: MEDIUM - strongly suggested by current recursive-serialization and import-boundary risks, but final execution/storage interactions land in later phases

**Research date:** 2026-04-02
**Valid until:** 2026-05-02
