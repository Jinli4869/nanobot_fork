# Phase 21: Capability Catalog And Planner Context - Research

**Researched:** 2026-03-22
**Domain:** Nanobot planner-time capability catalog, plan schema evolution, and routing-memory prompt context
**Confidence:** HIGH

<user_constraints>
## User Constraints

- No phase-specific `*-CONTEXT.md` exists for Phase 21.
- Treat `.planning/ROADMAP.md` as the source of truth for Phase 21 scope because the roadmap helper is currently unreliable for this phase.
- Keep Phase 21 scoped to planner-time catalog and planner context. Do not pull Phase 22 router execution work forward.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CAP-01 | Planner can see a compact summary of currently available GUI, tool, shell/exec, and MCP routes instead of reasoning from coarse capability labels alone | Add a planner-only `CapabilityCatalogBuilder`, serialize bounded route summaries into the planner prompt, and extend `PlanNode` with optional route metadata so plans can name the chosen route explicitly. |
| CAP-02 | Planner context can include routing-relevant memory hints about previously successful routes without dumping unrelated memory into the prompt | Add a planner-only `PlanningMemoryHintExtractor` that reads existing memory stores, emits capped route hints, and keeps raw `MEMORY.md` / `HISTORY.md` out of the planner prompt. |
</phase_requirements>

## Summary

The current planning path is narrow and coarse. `AgentLoop._plan_and_execute()` instantiates `TaskPlanner(llm=self.provider)` directly, passes no `skills_loader`, no runtime tool inventory, and no memory context, so the planner only sees static capability labels from `planner.py`: `gui`, `tool`, `mcp`, and `api`. `PlanNode` can only encode `instruction` plus `capability`, which means the planner cannot name a concrete route, explain why it chose one route over another, or declare a fallback route for later execution.

The runtime already contains enough local state to support CAP-01 without touching execution semantics: `ToolRegistry` knows the currently registered local tools, MCP tools are wrapped and registered after connection, `GuiSubagentTool` presence tells us whether GUI routing is actually available, and config/runtime state in `AgentLoop` exposes whether `exec` and MCP are enabled. The gap is not missing data; it is missing planner-facing normalization. Phase 21 should introduce a planner-only `CapabilityCatalog` contract and build it just before `planner.plan()`.

CAP-02 needs a separate, bounded seam. The normal agent path injects all long-term memory through `ContextBuilder.build_system_prompt()`, but the planner path bypasses `ContextBuilder` entirely. That is good for prompt size, but it means the planner has no routing memory at all today. Phase 21 should not reuse the full memory prompt. It should add a tiny `PlanningMemoryHint` extraction layer that reads existing memory stores conservatively and injects only route-relevant hints. Route outcome persistence belongs to Phase 23, so Phase 21 should build the extraction contract and prompt budget guardrails, not a new feedback store.

**Primary recommendation:** Add a planner-only `PlanningContext` build step in `AgentLoop` that produces a compact `CapabilityCatalog` plus bounded `PlanningMemoryHints`, and expand `PlanNode` with optional route metadata that the router can ignore until Phase 22.

## Recommended Phase Split

### 21-01: Capability Catalog And Plan Schema
- Build `CapabilityCatalogBuilder` from live `ToolRegistry`, MCP registration state, GUI availability, and host/runtime signals already visible in `AgentLoop`.
- Expand `PlanNode` with optional `route_id`, `route_reason`, and `fallback_route_ids`.
- Update `TaskPlanner` prompt assembly to inject the compact catalog and instruct the model to choose explicit routes.
- Update human-readable plan logging so route metadata is visible in both the pretty tree and raw `to_dict()` output.

### 21-02: Planning Memory Hints And Prompt Guardrails
- Add `PlanningMemoryHintExtractor` that reads `MemoryStore` outputs and emits a capped list of route-relevant hints only.
- Inject hints into the planner prompt separately from the capability catalog.
- Enforce hard size limits: max hint count, max chars per hint, and total prompt-budget truncation behavior.
- Add tests that prove unrelated memory is excluded and empty-hint behavior is safe.

### Why This Split Is Low-Coupling
- `21-01` is deterministic, runtime-inventory work. It depends on code inspection and schema evolution, not on memory summarization logic.
- `21-02` consumes the route IDs and prompt contracts established in `21-01`, but does not need router execution changes.
- Neither plan needs to implement `ToolRegistry.execute()` by route identity or MCP invocation by route identity. That remains Phase 22.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.11+ | Runtime language for planner, router, and memory seams | Existing repo target in `pyproject.toml`; no new runtime needed |
| `nanobot.agent.planner` | repo current | Planner prompt assembly and `PlanNode` schema | Already owns plan-tree contract; Phase 21 should evolve this, not fork it |
| `nanobot.agent.loop` | repo current | Runtime seam that decides when planning runs | Already has the only safe place to build live planner context |
| `nanobot.agent.tools.registry.ToolRegistry` | repo current | Live local-tool inventory source | Already tracks registered tools and definitions at runtime |
| `nanobot.agent.memory.MemoryStore` | repo current | Read-only source for planner memory hints | Existing persistent memory boundary; Phase 21 should reuse it rather than add storage |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `nanobot.agent.tools.mcp.MCPToolWrapper` | repo current | Identifies connected MCP routes already present in the registry | Use when building MCP route summaries from live connected tools |
| `pytest` | `>=9.0.0,<10.0.0` | Unit and regression coverage | Use for new Phase 21 tests and targeted slices |
| `pytest-asyncio` | `>=1.3.0,<2.0.0` | Async planner/router tests | Use for `TaskPlanner`, `AgentLoop`, and builder coverage |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Typed planner-only capability catalog | Dump `ToolRegistry.get_definitions()` into the prompt | Too verbose, leaks raw schemas, and does not explain route suitability |
| Planner-only routing memory hints | Reuse `ContextBuilder.build_system_prompt()` and full memory context | Pulls unrelated memory and bootstrap text into the planner prompt |
| Optional `PlanNode` route metadata in Phase 21 | Delay route fields until Phase 22 | Leaves CAP-01 incomplete because the planner still cannot express chosen route identity |

**Installation:**
```bash
uv sync --extra dev
```

**Version verification:** `pyproject.toml` is the source of truth here. This phase should stay on the repo’s current Python/pytest stack and should not introduce new external planner libraries.

## Architecture Patterns

### Recommended Project Structure
```text
nanobot/agent/
├── planner.py              # PlanNode schema + planner prompt assembly
├── loop.py                 # Build planner-only runtime context before plan()
├── capabilities.py         # NEW: route summary DTOs + catalog builder
├── planning_memory.py      # NEW: planning hint DTOs + extractor
└── router.py               # Reads route metadata later, but Phase 21 keeps dispatch behavior unchanged
```

### Pattern 1: Build Planner Context At The Last Responsible Moment
**What:** Construct planner context inside `AgentLoop._plan_and_execute()` from live runtime state immediately before `planner.plan(task)`.
**When to use:** Every time planning is triggered after `_needs_planning()` returns `True`.
**Example:**
```python
catalog = CapabilityCatalogBuilder().build(
    tool_registry=self.tools,
    gui_tool=self.tools.get("gui_task"),
    mcp_servers=self._mcp_servers,
    exec_config=self.exec_config,
)
hints = PlanningMemoryHintExtractor(self.workspace).build(task=task, catalog=catalog)
tree = await planner.plan(task, planning_context=PlanningContext(catalog=catalog, hints=hints))
```

### Pattern 2: Evolve `PlanNode` Backward-Compatibly
**What:** Add optional route fields to `PlanNode` and preserve old plans/tests that only know `instruction` plus `capability`.
**When to use:** Any schema change in `planner.py`.
**Example:**
```python
@dataclass(frozen=True)
class PlanNode:
    node_type: NodeType
    instruction: str = ""
    capability: CapabilityType = "tool"
    route_id: str | None = None
    route_reason: str = ""
    fallback_route_ids: tuple[str, ...] = ()
    children: tuple["PlanNode", ...] = field(default_factory=tuple)
```

### Pattern 3: Summarize Routes, Do Not Dump Schemas
**What:** Convert live tool and MCP objects into compact planner-facing `RouteSummary` items with `route_id`, `capability`, `kind`, `summary`, `use_for`, `avoid_for`, and `availability`.
**When to use:** Catalog construction and prompt serialization.
**Example:**
```python
RouteSummary(
    route_id="tool.exec_shell",
    capability="tool",
    kind="shell",
    summary="Run short local shell commands on this host",
    use_for=("system toggles", "local automation", "file inspection"),
    avoid_for=("visual workflows", "unsafe destructive commands"),
    availability="ready",
)
```

### Anti-Patterns to Avoid
- **Reusing `ContextBuilder` for planner prompts:** That pulls full memory, bootstrap docs, and unrelated skills text into the planning path.
- **Cataloging every registry tool automatically:** `message`, `spawn`, and `cron` are not planner route alternatives for this phase.
- **Making route metadata required immediately:** Existing tests and any old serialized plan payloads should continue to parse.
- **Calling real tool or MCP execution by `route_id` in Phase 21:** That is Phase 22 work.

## Proposed Artifacts And Contracts

| Artifact | Scope In Phase 21 | Why It Belongs Here |
|---------|-------------------|---------------------|
| `CapabilityCatalog`, `RouteSummary`, `CapabilityCatalogBuilder` | New planner-only DTOs and builder | Satisfies CAP-01 without changing execution |
| `PlanningMemoryHint`, `PlanningMemoryHintExtractor` | New planner-only memory DTOs and extractor | Satisfies CAP-02 with bounded context |
| `PlanNode.route_id`, `PlanNode.route_reason`, `PlanNode.fallback_route_ids` | Optional schema fields only | Lets the planner express route intent before router execution exists |
| Planner prompt serializer | New helper in `planner.py` or a small adjacent module | Keeps prompt growth controlled and testable |
| Log formatting update | Expand pretty tree output to show route metadata when present | Matches Phase 21 success criterion for inspectable planner logs |

### Contract Decisions To Lock In Before Planning
- **Route IDs must be stable and planner-facing.** Do not use raw log text as identifiers. Recommended shape: `gui.desktop`, `tool.exec_shell`, `tool.filesystem.read`, `mcp.<server>.<tool>`.
- **Catalog entries should be allowlisted, not “every tool in the registry.”** Phase 21 should expose only routeable execution options.
- **MCP cataloging should use live connected wrappers, not config-only declarations.** CAP-01 is about current availability.
- **Memory hints must be bounded and lossy by design.** Empty hints are acceptable; raw memory dumps are not.
- **Router ignores route metadata in Phase 21 except for logging/trace visibility.** No execution semantics change yet.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Planner-time route inventory | Raw schema dump from `get_definitions()` | Typed `CapabilityCatalogBuilder` | Raw schemas are too noisy and do not encode suitability |
| Routing memory context | Full `MEMORY.md` / `HISTORY.md` prompt injection | `PlanningMemoryHintExtractor` | Keeps prompts bounded and relevant |
| Future dispatch behavior | Early route resolver in planner code | Optional `PlanNode` route fields only | Avoids dragging Phase 22 execution logic into Phase 21 |
| Tool/MCP classification | Ad hoc string parsing scattered across planner code | Central classification table in catalog builder | Prevents drift and makes tests deterministic |

**Key insight:** Phase 21 is mostly a normalization problem. The runtime already knows a lot; the planner just cannot consume it in a compact, stable form.

## Common Pitfalls

### Pitfall 1: Planner Path Still Sees Only Coarse Capability Labels
**What goes wrong:** CAP-01 appears implemented on paper, but `_plan_and_execute()` still calls `TaskPlanner(llm=self.provider)` with no live route context.
**Why it happens:** The planner path bypasses `ContextBuilder` and currently has no dedicated planning-context seam.
**How to avoid:** Build a planner-only context object in `AgentLoop._plan_and_execute()` and pass it explicitly into `TaskPlanner.plan()`.
**Warning signs:** Tests only assert `PlanNode.capability`, never `route_id` or prompt content.

### Pitfall 2: Route Catalog Includes Non-Route Tools
**What goes wrong:** The planner sees `message`, `spawn`, or `cron` alongside execution routes and starts choosing them incorrectly.
**Why it happens:** `ToolRegistry` is generic and does not distinguish planner-routeable tools from support tools.
**How to avoid:** Add a central allowlist/classifier in the catalog builder for Phase 21.
**Warning signs:** Planner outputs routes that are control channels rather than task executors.

### Pitfall 3: Route Metadata Breaks Older Plan Parsing
**What goes wrong:** Existing tests or stored plan fixtures fail because new fields are treated as required.
**Why it happens:** `PlanNode.from_dict()` and `to_dict()` were originally designed around only `instruction` and `capability`.
**How to avoid:** Make new fields optional with empty/default values and preserve old payload parsing.
**Warning signs:** Existing Phase 8 planner/router tests start failing on simple ATOM trees.

### Pitfall 4: Planning Memory Hints Become A Back Door For Full Memory
**What goes wrong:** CAP-02 regresses prompt quality because the planner sees large unrelated memory excerpts.
**Why it happens:** It is tempting to reuse `MemoryStore.get_memory_context()` directly.
**How to avoid:** Extract only route-centric hints and enforce count/size caps in code and tests.
**Warning signs:** Planner prompt snapshots contain broad user history, policy notes, or bootstrap text unrelated to routing.

### Pitfall 5: Phase 21 Quietly Starts Phase 22
**What goes wrong:** The phase grows into real route resolution or `ToolRegistry.execute()` by route ID.
**Why it happens:** Once route IDs exist, execution changes feel close at hand.
**How to avoid:** Keep router behavior unchanged except for carrying/logging metadata. All real dispatch stays in Phase 22.
**Warning signs:** New code in `router.py` starts validating route IDs or invoking named tools/MCP wrappers directly.

## Code Examples

Verified patterns from current repo seams:

### Planner-Time Context Assembly
```python
# Existing seam: nanobot.agent.loop.AgentLoop._plan_and_execute
planner = TaskPlanner(llm=self.provider)
tree = await planner.plan(task)
```

Recommended Phase 21 evolution:
```python
planning_context = PlanningContext(
    catalog=CapabilityCatalogBuilder().build_from_runtime(...),
    memory_hints=PlanningMemoryHintExtractor(self.workspace).build(task=task),
)
tree = await planner.plan(task, planning_context=planning_context)
```

### Backward-Compatible Plan Serialization
```python
def to_dict(self) -> dict[str, Any]:
    data = {"type": self.node_type}
    if self.node_type == "atom":
        data["instruction"] = self.instruction
        data["capability"] = self.capability
        if self.route_id:
            data["route_id"] = self.route_id
        if self.route_reason:
            data["route_reason"] = self.route_reason
        if self.fallback_route_ids:
            data["fallback_route_ids"] = list(self.fallback_route_ids)
    else:
        data["children"] = [child.to_dict() for child in self.children]
    return data
```

### Memory Hint Guardrail
```python
def serialize_hints(hints: list[PlanningMemoryHint]) -> str:
    hints = hints[:5]
    lines = [hint.to_prompt_line(max_chars=160) for hint in hints]
    return "\n".join(line for line in lines if line)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Planner chooses only `gui/tool/mcp/api` | Planner should choose `capability + route_id + fallback_route_ids` | Phase 21 target | Route intent becomes inspectable and testable |
| Planner path sees no runtime route inventory | Planner should get live `CapabilityCatalog` from `AgentLoop` | Phase 21 target | CAP-01 becomes grounded in actual runtime availability |
| Planner path sees no routing memory | Planner should get bounded `PlanningMemoryHints` | Phase 21 target | CAP-02 can bias route choice without prompt bloat |

**Deprecated/outdated:**
- `TaskPlanner` with only coarse capability labels in the system prompt: too weak for v1.4 routing goals.
- `ToolRegistry` as a planner input source without a normalization layer: too generic to expose directly.

## Risks And Migration Notes

- The current router sorts OR children by coarse capability priority (`mcp > tool > gui > api`). Once explicit `fallback_route_ids` exist, that priority rule may conflict with planner-declared fallback order. Phase 21 should document this but not change execution order yet.
- Current MCP visibility is implicit: MCP tools are registered as wrapped tool names like `mcp_<server>_<tool>`. Phase 21 should normalize those into planner-facing route IDs and not leak wrapper naming details into prompts.
- Existing memory files likely contain little or no normalized route-success data because Phase 23 owns that feedback loop. The extractor must tolerate sparse or empty hints.
- Human-readable plan logs currently print only capability and instruction. If route metadata is added but not shown, Phase 21 will technically serialize it but still fail its inspectability goal.

## Open Questions

1. **How broad should the local-tool catalog be in Phase 21?**
   - What we know: `ToolRegistry` includes execution tools and support/control tools.
   - What's unclear: whether Phase 22 will execute only `exec` first or a broader local-tool set.
   - Recommendation: lock an explicit routeable-tool allowlist in `21-01` and keep it narrow at first (`gui_task`, `exec`, selected filesystem/web helpers, connected MCP wrappers).

2. **Should planner route IDs equal raw tool names?**
   - What we know: raw tool names exist today (`exec`, `gui_task`, `mcp_<server>_<tool>`).
   - What's unclear: whether those names are stable and human-friendly enough for planner prompts and logs.
   - Recommendation: use planner-facing route IDs that can map to raw runtime targets later; do not expose raw wrapper names directly.

3. **How should empty or weak memory hints be represented?**
   - What we know: existing memory storage is free-form markdown and not route-normalized.
   - What's unclear: how often Phase 21 can extract high-confidence hints before Phase 23 lands.
   - Recommendation: permit an empty hints section and test that planner behavior remains valid without hints.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest >=9.0.0,<10.0.0` + `pytest-asyncio >=1.3.0,<2.0.0` |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_mcp_tool.py tests/test_opengui_p21_planner_context.py` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAP-01 | Build a bounded live capability catalog from current runtime state and expose route metadata in plan serialization/logging | unit | `uv run pytest -q tests/test_opengui_p21_planner_context.py -k "catalog or route_metadata"` | ❌ Wave 0 |
| CAP-01 | Preserve backward-compatible `PlanNode` parsing/logging for old capability-only plans | unit | `uv run pytest -q tests/test_opengui_p8_planning.py -k "plan or route"` | ✅ |
| CAP-02 | Inject routing-relevant memory hints only, with count/size caps and safe empty-hint behavior | unit | `uv run pytest -q tests/test_opengui_p21_planner_context.py -k "memory_hint or guardrail"` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_mcp_tool.py tests/test_opengui_p21_planner_context.py`
- **Per wave merge:** `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_mcp_tool.py tests/test_opengui_p21_planner_context.py`
- **Phase gate:** `uv run pytest`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p21_planner_context.py` — capability catalog builder, route classification, prompt serialization, and memory-hint guardrails
- [ ] Update `tests/test_opengui_p8_planning.py` — `PlanNode` route metadata serialization, planner logging with route info, and `_plan_and_execute()` context injection
- [ ] Update `tests/test_mcp_tool.py` if MCP wrapper or inventory helpers are added to support planner catalog normalization

## Sources

### Primary (HIGH confidence)
- `.planning/ROADMAP.md` - Phase 21 scope, required split, and success criteria
- `.planning/REQUIREMENTS.md` - CAP-01 and CAP-02 definitions
- `docs/plans/2026-03-22-capability-aware-planner-routing-design.md` - milestone design intent and route-aware target contracts
- `nanobot/agent/planner.py` - current `PlanNode` schema and planner prompt limits
- `nanobot/agent/loop.py` - current planning trigger and `_plan_and_execute()` wiring
- `nanobot/agent/router.py` - current router behavior and placeholder `tool` / `mcp` dispatch
- `nanobot/agent/tools/registry.py` - current tool inventory surface
- `nanobot/agent/tools/mcp.py` - current MCP wrapper naming and registration behavior
- `nanobot/agent/context.py` - current full-memory prompt path that the planner bypasses
- `nanobot/agent/memory.py` - current persistent memory model and its lack of route-normalized feedback
- `tests/test_opengui_p8_planning.py` - current planner/router regression seams
- `tests/test_mcp_tool.py` - MCP registration coverage and wrapper naming behavior
- `pyproject.toml` - pytest/async test configuration and runtime versions

### Secondary (MEDIUM confidence)
- `.planning/PROJECT.md` - current milestone framing and accepted design direction
- `.planning/STATE.md` - recent planning decisions and quick-task references

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - based entirely on inspected local repo modules and `pyproject.toml`
- Architecture: HIGH - based on direct inspection of `planner.py`, `loop.py`, `router.py`, and the Phase 21 design doc
- Pitfalls: MEDIUM - current code makes the likely failure modes clear, but Phase 22 interactions will need validation once route execution exists

**Research date:** 2026-03-22
**Valid until:** 2026-04-21
