# Phase 24: Schema and Grounding - Research

**Researched:** 2026-04-02
**Domain:** Typed OpenGUI skill schemas and pluggable grounding contracts
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Module placement
- New skill types extend `opengui/skills/` — add `shortcut.py` (ShortcutSkill) and `task_skill.py` (TaskSkill) alongside the existing `data.py`
- Existing `Skill` and `SkillStep` coexist untouched in Phase 24; migration/deprecation is deferred to Phase 27
- `GrounderProtocol`, `LLMGrounder`, `GroundingContext`, and `GroundingResult` live in a new `opengui/grounding/` module

### State descriptor shape
- `StateDescriptor` is a frozen dataclass with three fields: `kind: str`, `value: str`, `negated: bool = False`
- Condition kinds are minimal and open-ended — Phase 24 ships a small starter vocab (e.g. `app_foreground`, `element_visible`, `element_absent`) but the field is a plain `str`, not an enum, so downstream phases can extend it freely
- `ParameterSlot` is a frozen dataclass with `name: str`, `type: str` (a serialization-friendly string tag like `'str'`, `'int'`, `'bool'`), `description: str`

### Grounding interface style
- `GrounderProtocol` uses `typing.Protocol` with `@runtime_checkable` — matches the existing `LLMProvider` and `DeviceBackend` pattern in `opengui/interfaces.py`
- Signature: `async def ground(self, target: str, context: GroundingContext) -> GroundingResult`
- `GroundingResult` is a frozen dataclass: `grounder_id: str`, `confidence: float`, `resolved_params: dict[str, Any]`, `fallback_metadata: dict[str, Any] | None`
- `GroundingContext` is a frozen dataclass: `screenshot_path: Path`, `observation: Observation`, `parameter_slots: tuple[ParameterSlot, ...]`, `task_hint: str | None`

### Conditional branch + fallback nodes
- TaskSkill step sequence uses a sealed dataclass union — three node types:
  - `ShortcutRefNode(shortcut_id: str, param_bindings: dict[str, str])` — reference to a ShortcutSkill by ID
  - Inline ATOM fallback steps reuse the existing `SkillStep` from `data.py` — no new type needed
  - `BranchNode(condition: StateDescriptor, then_steps: tuple[TaskNode, ...], else_steps: tuple[TaskNode, ...])` — conditional branch
- Type alias: `TaskNode = ShortcutRefNode | SkillStep | BranchNode`
- `BranchNode.condition` is a `StateDescriptor` (same type as ShortcutSkill pre/post conditions) — consistent evaluation path for the Phase 25 executor

### TaskSkill memory context pointer
- `TaskSkill` carries an optional `memory_context_id: str | None` — pointer to an app memory context entry in the existing memory system (SCHEMA-06)
- Claude's discretion on the exact field name and whether it references `opengui/memory/types.py` directly or by ID string

### Claude's Discretion
- Exact starter vocab list for `StateDescriptor.kind` beyond the three examples above
- Whether `opengui/grounding/__init__.py` re-exports all grounding types or just the Protocol
- Exact field order and optional fields on `ShortcutSkill` (e.g. `success_count`, `tags`) — can mirror the existing `Skill` class structure for consistency
- Whether `LLMGrounder.__init__` accepts the existing `LLMProvider` protocol or a concrete provider type

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCHEMA-01 | Shortcut skill defines pre/post conditions as structured, checkable state descriptors (not free-form strings) | Use `StateDescriptor` frozen dataclass for both preconditions and postconditions; keep `kind` open-string, not enum. |
| SCHEMA-02 | Shortcut skill declares typed parameter slots (name, type, description) for runtime grounding | Use `ParameterSlot` frozen dataclass and store `tuple[ParameterSlot, ...]` on `ShortcutSkill`. |
| SCHEMA-03 | Task-level skill references shortcut skills by ID with parameter binding declarations | Use `ShortcutRefNode(shortcut_id, param_bindings)` and tagged serialization inside `TaskSkill`. |
| SCHEMA-04 | Task-level skill supports inline ATOM fallback steps for actions not covered by a shortcut | Reuse existing `SkillStep` directly as the inline fallback node type. |
| SCHEMA-05 | Task-level skill supports conditional branch nodes with checkable condition expressions | Use `BranchNode(condition: StateDescriptor, then_steps, else_steps)` and explicit union tags for recursion. |
| SCHEMA-06 | Task-level skill carries an optional pointer to an app memory context entry in the existing memory system | Store only `memory_context_id: str | None`; do not embed `MemoryEntry` objects. |
| GRND-01 | GrounderProtocol defines a common async interface for resolving semantic step targets to concrete action parameters | Match existing repo protocol style: `@runtime_checkable Protocol` with `ground(target, context) -> GroundingResult`. |
| GRND-02 | LLMGrounder implements GrounderProtocol wrapping the existing vision-LLM grounding path | Reuse the current `_AgentActionGrounder` prompt/parse approach as the implementation seam, but return `GroundingResult` instead of executing actions. |
| GRND-03 | Grounding results expose the grounder used, confidence score, and fallback metadata | Keep those fields first-class on `GroundingResult` and make `resolved_params` executor-ready. |
</phase_requirements>

## Summary

Phase 24 should stay narrow. The repo already has the patterns this work needs: frozen/manual-serialized dataclasses in [`opengui/skills/data.py`](../../../../opengui/skills/data.py), structural interfaces in [`opengui/interfaces.py`](../../../../opengui/interfaces.py), runtime observation DTOs in [`opengui/observation.py`](../../../../opengui/observation.py), and string-ID memory references in [`opengui/memory/types.py`](../../../../opengui/memory/types.py). The new phase should extend those patterns, not introduce a parallel model system.

The main implementation risk is recursive serialization, not typing syntax. `TaskNode` is a sealed union that includes both new node dataclasses and legacy `SkillStep`; if the phase uses shape inference instead of an explicit discriminator, round-trip persistence will become brittle immediately and Phase 25/27 will inherit that ambiguity. The planner should therefore treat explicit `node_type` tagging as a hard requirement even though the runtime union reuses `SkillStep`.

The grounding side should also stay contract-first. There is already an executor-private `ActionGrounder` seam and an agent-private `_AgentActionGrounder` implementation, but both are scoped to immediate action execution. Phase 24 should pull out a public `GrounderProtocol` + `LLMGrounder` that returns a `GroundingResult` DTO, leaving actual `Action` construction to Phase 25 executors.

**Primary recommendation:** Implement Phase 24 as a stdlib-only schema layer built around frozen dataclasses, explicit `to_dict()`/`from_dict()` methods, tagged recursive node serialization, and a protocol-based grounding adapter that wraps the current vision-LLM path without executing anything.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`dataclasses`, `typing`, `pathlib`) | Python `>=3.11` (repo requires `>=3.11`; Ruff targets `py311`) | Frozen schemas, structural interfaces, `Path`-typed grounding context | Existing OpenGUI contracts already use these exact primitives; no new dependency is needed. |
| Existing OpenGUI contracts (`LLMProvider`, `Observation`, `SkillStep`, `MemoryEntry`) | repo-local | Reuse current protocol, DTO, fallback-step, and memory ID seams | Downstream phases already depend on these modules; Phase 24 should align with them instead of wrapping them. |
| `pytest` + `pytest-asyncio` | `pytest>=9.0.0,<10.0.0`; `pytest-asyncio>=1.3.0,<2.0.0` (declared in `pyproject.toml`) | Serialization, import, and async grounder tests | Existing test infrastructure is already configured in `pyproject.toml`. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `uv` project workflow | repo-local workflow convention | Run targeted tests and import smoke checks | Use for all phase-local verification commands. |
| `litellm` and provider adapters behind `LLMProvider` | `litellm>=1.82.1,<2.0.0` (declared) | Back existing provider implementations that `LLMGrounder` will accept indirectly | Use only through the `LLMProvider` protocol, never as a direct Phase 24 dependency seam. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Frozen dataclasses with manual serializers | Pydantic models | Adds a new dependency and diverges from existing `Skill`, `MemoryEntry`, and `Observation` patterns for little gain. |
| `typing.Protocol` grounding interface | ABC base classes | Loses structural typing parity with `LLMProvider` and `DeviceBackend`, making future grounder swapping harder. |
| Open-string `StateDescriptor.kind` | Enum-backed condition kinds | Safer locally, but blocks Phase 26/25 from extending condition vocab without schema churn. |

**Installation:**
```bash
uv sync --extra dev
```

**Version verification:** No new package should be introduced for Phase 24. Verified from `pyproject.toml` on 2026-04-02: Python `>=3.11`, `pytest>=9.0.0,<10.0.0`, `pytest-asyncio>=1.3.0,<2.0.0`, `litellm>=1.82.1,<2.0.0`.

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
├── grounding/
│   ├── __init__.py      # public re-exports for planner/executor/extractor imports
│   ├── protocol.py      # GrounderProtocol, GroundingContext, GroundingResult
│   └── llm.py           # LLMGrounder wrapping the current vision-LLM grounding path
└── skills/
    ├── data.py          # existing Skill / SkillStep stay unchanged
    ├── shortcut.py      # StateDescriptor, ParameterSlot, ShortcutSkill
    ├── task_skill.py    # ShortcutRefNode, BranchNode, TaskNode, TaskSkill
    └── __init__.py      # re-export old and new public types
```

### Pattern 1: Mirror Existing Skill Metadata, Add New Contract Fields
**What:** Keep `ShortcutSkill` and `TaskSkill` shaped like the current `Skill` wherever possible: `skill_id`, `name`, `description`, `app`, `platform`, `tags`, `created_at`, and optional success/failure counters, then add the new typed fields required by v1.5.
**When to use:** Always. This minimizes Phase 27 store/search translation and keeps the data model familiar.
**Example:**
```python
# Source: repo pattern from opengui/skills/data.py
@dataclass(frozen=True)
class ShortcutSkill:
    skill_id: str
    name: str
    description: str
    app: str
    platform: str
    steps: tuple[SkillStep, ...] = ()
    parameter_slots: tuple[ParameterSlot, ...] = ()
    preconditions: tuple[StateDescriptor, ...] = ()
    postconditions: tuple[StateDescriptor, ...] = ()
    tags: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)
```

### Pattern 2: Tagged Recursive Serialization for `TaskNode`
**What:** Serialize each task node with an explicit discriminator, even though the runtime type alias is `ShortcutRefNode | SkillStep | BranchNode`.
**When to use:** Every `TaskSkill.to_dict()` / `TaskSkill.from_dict()` call.
**Example:**
```python
# Source: repo serializer pattern from opengui/skills/data.py
def _task_node_to_dict(node: TaskNode) -> dict[str, Any]:
    if isinstance(node, ShortcutRefNode):
        return {
            "node_type": "shortcut_ref",
            "shortcut_id": node.shortcut_id,
            "param_bindings": dict(node.param_bindings),
        }
    if isinstance(node, SkillStep):
        payload = node.to_dict()
        payload["node_type"] = "atom"
        return payload
    return {
        "node_type": "branch",
        "condition": node.condition.to_dict(),
        "then_steps": [_task_node_to_dict(child) for child in node.then_steps],
        "else_steps": [_task_node_to_dict(child) for child in node.else_steps],
    }
```

### Pattern 3: Public Grounding Protocol Over the Existing Vision-LLM Path
**What:** Make `LLMGrounder` accept the existing `LLMProvider` protocol and reuse the current prompt/tool-call parsing flow, but return `GroundingResult` instead of an `Action`.
**When to use:** For the default v1.5 grounder and any future drop-in replacements.
**Example:**
```python
# Source: typing runtime protocol docs + repo pattern from opengui/interfaces.py
@runtime_checkable
class GrounderProtocol(Protocol):
    async def ground(
        self,
        target: str,
        context: GroundingContext,
    ) -> GroundingResult: ...
```

### Pattern 4: Keep Grounding Context Runtime-Only
**What:** `GroundingContext` should be a frozen dataclass, but it should not be treated as persisted schema because it carries `Path` and mutable `Observation`.
**When to use:** Always for this phase; only the skill schemas need round-trip persistence.
**Example:**
```python
# Source: repo runtime DTO from opengui/observation.py
@dataclass(frozen=True)
class GroundingContext:
    screenshot_path: Path
    observation: Observation
    parameter_slots: tuple[ParameterSlot, ...] = ()
    task_hint: str | None = None
```

### Anti-Patterns to Avoid
- **Generic `dataclasses.asdict()` for public schema shape:** The repo uses manual serializers to control field names, omit defaults, and handle nested types deliberately.
- **Shape-based `TaskNode` decoding:** Reusing `SkillStep` inside the union makes this ambiguous and fragile.
- **String expression branches:** `BranchNode.condition` should stay a `StateDescriptor`, not a mini DSL.
- **Embedding `MemoryEntry` objects in `TaskSkill`:** Persist only the ID string and resolve it later in Phase 27.
- **Grounder returning `Action` objects in Phase 24:** That pulls execution concerns into the schema layer too early.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Recursive task-node persistence | Ad-hoc node shape inference | Explicit `node_type` discriminators in `TaskSkill` serializers | Future node additions stay backward-compatible and deserialization stays deterministic. |
| Contract condition language | Custom boolean/string parser | `StateDescriptor(kind, value, negated)` | The next executor phase can evaluate one structured descriptor path consistently across shortcuts and branches. |
| Grounder plugin API | Concrete inheritance tree | `GrounderProtocol` structural interface | Matches current repo protocol style and keeps OmniParser/future grounders swappable. |
| Memory linkage | Snapshotting `MemoryEntry` payloads into task skills | `memory_context_id: str | None` | Avoids stale embedded data and keeps the schema storage-agnostic. |
| Serializer defaults | Blind deep-copy serialization | Manual `to_dict()` / `from_dict()` on all persisted schemas | Existing repo patterns already rely on explicit round-trip control and compact payloads. |

**Key insight:** The tempting custom build in this domain is a “smart” recursive serializer. Do not do that. The stable contract here is simple dataclasses plus explicit discriminators and explicit conversion methods.

## Common Pitfalls

### Pitfall 1: Ambiguous `TaskNode` Round-Trip
**What goes wrong:** `TaskSkill.from_dict()` cannot reliably tell whether a payload is a fallback `SkillStep` or a future node type.
**Why it happens:** The union reuses legacy `SkillStep`, which has no built-in discriminant.
**How to avoid:** Add `"node_type"` on write and dispatch on `"node_type"` on read.
**Warning signs:** Deserializer code starts checking for incidental keys like `"shortcut_id"` or `"condition"` instead of a single explicit tag.

### Pitfall 2: Free-Form State Strings Reappear Through Convenience Fields
**What goes wrong:** New code stores `"the settings page is open"` strings in `preconditions`, `postconditions`, or branches.
**Why it happens:** Legacy `Skill` still uses string `preconditions`, and `SkillStep.valid_state` already exists as free text.
**How to avoid:** Make `ShortcutSkill` and `BranchNode` accept only `StateDescriptor` tuples/instances; do not add string overloads.
**Warning signs:** Helper functions start accepting `str | StateDescriptor` or serializer code writes bare strings into condition arrays.

### Pitfall 3: Circular Imports Between Grounding, Skills, and Agent Modules
**What goes wrong:** Importing `LLMGrounder` pulls in `GuiAgent`, executor code, or heavy provider wiring.
**Why it happens:** The current grounding implementation lives privately in [`opengui/agent.py`](../../../../opengui/agent.py).
**How to avoid:** Keep `opengui/grounding` dependent only on `LLMProvider`, `Observation`, `ParameterSlot`, and `parse_action`-compatible payload rules. Do not import executors.
**Warning signs:** `opengui/grounding/*` imports `GuiAgent`, `SkillExecutor`, or `nanobot.*`.

### Pitfall 4: Treating Frozen Dataclasses as Deeply Immutable
**What goes wrong:** Code assumes dict fields like `param_bindings`, `resolved_params`, or `fallback_metadata` are hash-safe and cannot mutate.
**Why it happens:** `frozen=True` stops attribute reassignment, not in-place mutation of nested dicts.
**How to avoid:** Do not rely on hashing these dataclasses; copy dicts on serialization and in constructors when necessary.
**Warning signs:** New code uses these instances as set members or dict keys.

### Pitfall 5: Over-Serializing Runtime Grounding Types
**What goes wrong:** The phase tries to give `GroundingContext` or `Observation` full persistence semantics.
**Why it happens:** The skill schemas require round-trip serialization, and it is easy to over-apply that requirement.
**How to avoid:** Limit `to_dict()` / `from_dict()` requirements to persisted skill schemas and node types. Treat grounding context as runtime-only.
**Warning signs:** Serializer code starts converting `Path` and `Observation.extra` just to satisfy Phase 24.

## Code Examples

Verified patterns from official sources and current repo contracts:

### Structured State Descriptors
```python
# Source: docs.python.org dataclasses docs + repo pattern from opengui/skills/data.py
@dataclass(frozen=True)
class StateDescriptor:
    kind: str
    value: str
    negated: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = {"kind": self.kind, "value": self.value}
        if self.negated:
            data["negated"] = True
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateDescriptor":
        return cls(
            kind=data["kind"],
            value=data["value"],
            negated=data.get("negated", False),
        )
```

### Recursive `TaskSkill` Node Dispatch
```python
# Source: repo serializer pattern from opengui/skills/data.py
@classmethod
def _task_node_from_dict(cls, data: dict[str, Any]) -> TaskNode:
    node_type = data["node_type"]
    if node_type == "shortcut_ref":
        return ShortcutRefNode(
            shortcut_id=data["shortcut_id"],
            param_bindings=dict(data.get("param_bindings", {})),
        )
    if node_type == "atom":
        atom_payload = dict(data)
        atom_payload.pop("node_type", None)
        return SkillStep.from_dict(atom_payload)
    if node_type == "branch":
        return BranchNode(
            condition=StateDescriptor.from_dict(data["condition"]),
            then_steps=tuple(cls._task_node_from_dict(v) for v in data.get("then_steps", [])),
            else_steps=tuple(cls._task_node_from_dict(v) for v in data.get("else_steps", [])),
        )
    raise ValueError(f"Unknown task node type: {node_type}")
```

### Grounder Protocol and Default LLM Grounder
```python
# Source: docs.python.org typing Protocol docs + repo pattern from opengui/interfaces.py
@runtime_checkable
class GrounderProtocol(Protocol):
    async def ground(self, target: str, context: GroundingContext) -> GroundingResult: ...


@dataclass(frozen=True)
class GroundingResult:
    grounder_id: str
    confidence: float
    resolved_params: dict[str, Any]
    fallback_metadata: dict[str, Any] | None = None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single flat `Skill` model for all reuse | Two-layer `ShortcutSkill` + `TaskSkill` model (planned v1.5) | Roadmap updated 2026-04-01 | Separates reusable macro actions from task composition and storage concerns. |
| Free-form string state checks (`preconditions`, `valid_state`) | Structured `StateDescriptor` contracts | Phase 24 context locked 2026-04-02 | Enables one consistent condition representation for execution and extraction. |
| Executor-private `ActionGrounder` returning `Action` | Public `GrounderProtocol` returning `GroundingResult` | v1.5 requirements defined 2026-04-01 | Decouples grounding backend choice from executor logic and future grounder plugins. |

**Deprecated/outdated:**
- Building new v1.5 features on top of legacy `Skill.preconditions: tuple[str, ...]`: legacy `Skill` survives for coexistence only; downstream v1.5 work should target the new typed schemas.
- Treating grounding as an executor-only concern: v1.5 explicitly makes grounding a public swappable protocol.

## Open Questions

1. **What command counts as the required "type-check pass"?**
   - What we know: The roadmap success criteria require a type-check pass, but the repo currently has no `mypy` or `pyright` config and no static type-check command checked in.
   - What's unclear: Whether the phase should add a static type checker or treat import/compile verification as sufficient.
   - Recommendation: Treat this as a Wave 0 planning decision. Prefer adding a minimal `mypy` slice for `opengui/skills/*.py` and `opengui/grounding/*.py`; if that is out of scope, document that the gate is `py_compile + targeted pytest` instead of a true static type check.

2. **How much of `_AgentActionGrounder` should be extracted now?**
   - What we know: The current vision-LLM grounding path already exists privately in [`opengui/agent.py`](../../../../opengui/agent.py).
   - What's unclear: Whether Phase 24 should refactor shared prompt/retry helpers out of the agent, or keep a narrow wrapper to avoid broader churn.
   - Recommendation: Keep the refactor minimal. Either move only the prompt/tool-call parsing logic into `opengui/grounding/llm.py` or duplicate a small private helper there. Do not broaden the phase into agent cleanup.

3. **Should `GroundingResult.resolved_params` include only grounded parameters or a full action payload?**
   - What we know: `GrounderProtocol.ground()` receives `target` plus `GroundingContext`, while the executor will already know the step's `action_type`.
   - What's unclear: Whether later executors should expect `resolved_params` to contain `action_type`.
   - Recommendation: Keep `resolved_params` limited to executor-ready parameter kwargs (`x`, `y`, `text`, `key`, `duration_ms`, etc.) and let Phase 25 merge those with the known step `action_type`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` `>=9.0.0,<10.0.0` + `pytest-asyncio` `>=1.3.0,<2.0.0` |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py -q` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCHEMA-01 | `ShortcutSkill` round-trips structured pre/post `StateDescriptor` tuples | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_shortcut_skill_round_trip_preserves_state_descriptors -q` | ❌ Wave 0 |
| SCHEMA-02 | `ShortcutSkill` preserves typed `ParameterSlot` tuples through `to_dict()` / `from_dict()` | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_shortcut_skill_round_trip_preserves_parameter_slots -q` | ❌ Wave 0 |
| SCHEMA-03 | `TaskSkill` serializes/deserializes `ShortcutRefNode` with `shortcut_id` and bindings | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_task_skill_round_trip_preserves_shortcut_refs -q` | ❌ Wave 0 |
| SCHEMA-04 | `TaskSkill` supports inline `SkillStep` fallback nodes without wrapping them in a new class | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_task_skill_round_trip_preserves_atom_fallback_steps -q` | ❌ Wave 0 |
| SCHEMA-05 | `TaskSkill` round-trips recursive `BranchNode` condition / then / else trees | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_task_skill_round_trip_preserves_branch_nodes -q` | ❌ Wave 0 |
| SCHEMA-06 | `TaskSkill` preserves optional `memory_context_id` string pointer | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_task_skill_preserves_memory_context_id -q` | ❌ Wave 0 |
| GRND-01 | `GrounderProtocol` is runtime-checkable and `LLMGrounder` conforms structurally | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_llm_grounder_satisfies_grounder_protocol -q` | ❌ Wave 0 |
| GRND-02 | `LLMGrounder` wraps scripted `LLMProvider` output into grounded params without backend execution | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_llm_grounder_returns_grounding_result_from_scripted_provider -q` | ❌ Wave 0 |
| GRND-03 | `GroundingResult` exposes `grounder_id`, `confidence`, `resolved_params`, and `fallback_metadata` | unit | `uv run pytest tests/test_opengui_p24_schema_and_grounding.py::test_grounding_result_exposes_required_fields -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p24_schema_and_grounding.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p24_schema_and_grounding.py tests/test_opengui_p1_skills.py tests/test_gui_skill_executor_wiring.py -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p24_schema_and_grounding.py` — covers SCHEMA-01..06 and GRND-01..03
- [ ] Static type-check decision for the phase — no existing `mypy`/`pyright` config or command is present in the repo

## Sources

### Primary (HIGH confidence)
- Repo: `opengui/skills/data.py` - existing frozen dataclass + manual `to_dict()` / `from_dict()` pattern for skill schemas
- Repo: `opengui/interfaces.py` - current `@runtime_checkable Protocol` pattern used by `LLMProvider` and `DeviceBackend`
- Repo: `opengui/observation.py` - `Observation` DTO shape carried by `GroundingContext`
- Repo: `opengui/memory/types.py` - current memory entry ID contract that supports `memory_context_id`
- Repo: `opengui/agent.py` - existing private vision-LLM grounding flow (`_AgentActionGrounder`) that `LLMGrounder` should wrap
- Repo: `.planning/phases/24-schema-and-grounding/24-CONTEXT.md` - locked design decisions and discretion boundaries
- Repo: `.planning/REQUIREMENTS.md` - authoritative Phase 24 requirement definitions
- Repo: `.planning/ROADMAP.md` - current v1.5 success criteria and downstream phase dependencies
- https://docs.python.org/3.11/library/typing.html - `Protocol` and `@runtime_checkable` semantics
- https://docs.python.org/3.11/library/dataclasses.html - frozen dataclass behavior and explicit field-based serialization rules

### Secondary (MEDIUM confidence)
- Repo: `pyproject.toml` - current Python and test dependency constraints
- Repo: `tests/test_opengui_p1_skills.py` - existing serializer/persistence test style for OpenGUI data models
- Repo: `tests/test_gui_skill_executor_wiring.py` - confirms current skill/executor wiring seam that later phases will build on

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Phase 24 should use existing repo patterns and stdlib features already present in the codebase.
- Architecture: HIGH - Locked context decisions plus current module boundaries strongly constrain the right design.
- Pitfalls: MEDIUM - Most are derived from current code patterns and downstream requirements, but the new schema is not implemented yet.

**Research date:** 2026-04-02
**Valid until:** 2026-05-02
