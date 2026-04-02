# Phase 24: Schema and Grounding - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Define the two-layer skill data models (ShortcutSkill, TaskSkill) and the pluggable grounding protocol (GrounderProtocol, LLMGrounder) as stable typed contracts. Nothing executes in this phase — downstream phases 25, 26, and 27 build against these schemas. The deliverable is importable types that pass a type-check pass and serialize round-trip cleanly.

</domain>

<decisions>
## Implementation Decisions

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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/ROADMAP.md` — Phase 24 goal, requirements (SCHEMA-01 through SCHEMA-06, GRND-01 through GRND-03), success criteria, and dependency on Phase 23
- `.planning/REQUIREMENTS.md` — Full v1.5 requirement definitions for SCHEMA and GRND groups; also shows EXEC/EXTR/STOR/INTEG so phase 24 schemas can be designed with downstream consumers in mind

### Existing codebase contracts
- `opengui/skills/data.py` — Existing `Skill` and `SkillStep` dataclasses that coexist and that ATOMFallbackNode (SkillStep reuse) builds on
- `opengui/interfaces.py` — Existing `LLMProvider` and `DeviceBackend` Protocol pattern that `GrounderProtocol` must follow
- `opengui/observation.py` — `Observation` type that `GroundingContext.observation` carries
- `opengui/memory/types.py` — Memory context types that `TaskSkill.memory_context_id` may reference

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SkillStep` (`opengui/skills/data.py`): Frozen dataclass with `action_type`, `target`, `parameters`, `fixed`/`fixed_values` — Phase 24 reuses this directly as the ATOM fallback node type in TaskSkill
- `Observation` (`opengui/observation.py`): Existing type for device state snapshots — used in `GroundingContext`
- `LLMProvider` / `DeviceBackend` (`opengui/interfaces.py`): The `@runtime_checkable Protocol` pattern Phase 24 must replicate for `GrounderProtocol`

### Established Patterns
- Frozen dataclasses with `to_dict()` / `from_dict()` for serialization (used by `Skill`, `SkillStep`, `TrajectoryRecorder`)
- `typing.Protocol` with `@runtime_checkable` for structural interfaces — no inheritance required for implementations
- All public exports via `__init__.py` with an explicit `__all__` list (see `opengui/skills/__init__.py`)

### Integration Points
- `opengui/skills/__init__.py`: Must be updated to export new types from `shortcut.py` and `task_skill.py`
- `opengui/grounding/__init__.py`: New file — exports `GrounderProtocol`, `LLMGrounder`, `GroundingContext`, `GroundingResult`
- Phase 25 (executor) will import `ShortcutSkill`, `TaskSkill`, `TaskNode`, and `GrounderProtocol` directly
- Phase 26 (extraction) will import `ShortcutSkill`, `ParameterSlot`, and `StateDescriptor` to produce skill candidates
- Phase 27 (storage) will import both skill types for versioned JSON persistence

</code_context>

<specifics>
## Specific Ideas

- `GrounderProtocol` is a structural Protocol (not ABC) so `LLMGrounder` can duck-type without inheriting — mirrors `LLMProvider` in `interfaces.py`
- `StateDescriptor.kind` is an open string (not an Enum) so Phase 26 critics can introduce new condition kinds without a schema change
- `BranchNode.condition` is a `StateDescriptor` rather than a string expression — keeps condition evaluation consistent with pre/post contract checking in the Phase 25 executor
- `TaskNode` type alias defined at module level in `task_skill.py` so downstream imports have one clear place to grab the union

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 24-schema-and-grounding*
*Context gathered: 2026-04-02*
