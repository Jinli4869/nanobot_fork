# Phase 22: Route-Aware Tool And MCP Dispatch - Research

**Researched:** 2026-03-22
**Domain:** Nanobot router execution, tool dispatch, MCP route resolution, and fallback observability
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CAP-03 | Router can execute `tool` plan nodes through real dispatch instead of placeholder-only success responses | Replace `_run_tool()` placeholder with route-resolver logic that maps `route_id` to a registry tool name, then invokes `ToolRegistry.execute()` with instruction-derived parameters. |
| CAP-04 | Router can execute `mcp` plan nodes through real dispatch with route validation and fallback behavior | Replace `_run_mcp()` placeholder with route-resolver logic that maps `mcp.{server}.{tool}` route IDs to `mcp_{server}_{tool}` registry keys, validates availability, and falls back through `fallback_route_ids` when the primary route is missing or fails. |
</phase_requirements>

## Summary

Phase 21 established a complete planner-time contract: `PlanNode` now carries `route_id`, `route_reason`, and `fallback_route_ids`; the planner prompt includes a live capability catalog; and `RouterContext` already receives `tool_registry` and `mcp_client` (which is the same `ToolRegistry` instance). The router, however, still returns placeholder `NodeResult(success=True)` for both `tool` and `mcp` atoms — it ignores the route metadata entirely.

Phase 22 must close this gap. The key insight is that all MCP tools are already registered in `ToolRegistry` under wrapped names (`mcp_{server}_{tool}`), and all local tools (`exec`, `read_file`, etc.) are also in the same registry. What is missing is (1) a route resolver that maps planner-facing route IDs back to registry tool names, (2) a parameter extraction mechanism so the natural-language `instruction` can drive a real tool call, and (3) fallback logic that tries `fallback_route_ids` in order when the primary route is unavailable or fails, with structured diagnostics at each stage.

The central architectural challenge is instruction-to-parameters translation. The planner produces natural-language instructions such as "disable bluetooth on this Mac" alongside `route_id="tool.exec_shell"`. The `ExecTool.execute()` method needs a concrete `command` string. Two options exist: (a) use a secondary LLM call to generate tool parameters from the instruction, or (b) treat the raw instruction as the primary parameter value for single-parameter tools (pass `instruction` as `command` for shell, as `query` for web search, etc.). Option (b) is far simpler and consistent with how `_run_gui` works today — `GuiAgent.run(instruction)` takes the instruction string directly. The research confirms this is the right approach: route-specific parameter mapping is a deterministic schema lookup, not a semantic translation problem.

**Primary recommendation:** Add a `RouteDispatcher` (or inline logic in `TreeRouter`) that maps `route_id` to registry tool name and instruction parameter, calls `ToolRegistry.execute()` with structured arguments, chains through `fallback_route_ids` on failure, and logs `planned_route`, `resolved_route`, and `fallback_taken` at each dispatch step.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.11+ | Runtime — async coroutines, dataclasses | Repo target; no change |
| `nanobot.agent.router` | repo current | `TreeRouter`, `RouterContext`, `NodeResult` | Owns all dispatch logic; Phase 22 extends, not replaces |
| `nanobot.agent.tools.registry.ToolRegistry` | repo current | Registry for all local and MCP tools | Already in `RouterContext`; `execute(name, params)` is the dispatch surface |
| `nanobot.agent.planner.PlanNode` | repo current | Carries `route_id`, `capability`, `fallback_route_ids` | Schema established in Phase 21; no schema changes needed in Phase 22 |
| `nanobot.agent.capabilities.CapabilityCatalog` | repo current | Route ID → capability metadata | Used in Phase 21; Phase 22 uses route_ids as keys for resolver lookup |
| `pytest` + `pytest-asyncio` | repo current | Test framework | Existing coverage in `test_opengui_p8_planning.py`; Phase 22 adds new file |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `nanobot.agent.tools.mcp.MCPToolWrapper` | repo current | Identifies MCP tools in registry via `mcp_{server}_{tool}` naming | Used to derive registry key from `mcp.{server}.{tool}` route_id |
| `logging` (stdlib) | stdlib | Structured dispatch logging | Use for `planned_route`, `resolved_route`, and `fallback_taken` log entries |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct instruction-as-parameter routing | Secondary LLM call to generate tool parameters | LLM call adds latency, token cost, and a new failure mode; instruction-as-parameter works for all existing route types |
| Inline dispatch in `_run_tool` / `_run_mcp` | Separate `RouteDispatcher` class | A separate class is cleaner but adds indirection; for Phase 22 scope, extending the private methods is sufficient and avoids over-engineering |
| Fallback as part of OR-node priority | Fallback as router-level retry on failure | `fallback_route_ids` is planner-declared intent; the router should respect it before resorting to the general OR-node retry |

**Installation:**
```bash
uv sync --extra dev
```

No new external packages are needed. Phase 22 stays on the repo's existing async Python stack.

## Architecture Patterns

### Recommended Project Structure
```
nanobot/agent/
├── router.py            # MODIFY: implement _run_tool, _run_mcp, add _resolve_route, _dispatch_with_fallback
├── planner.py           # NO CHANGE: PlanNode schema complete from Phase 21
├── capabilities.py      # NO CHANGE: route catalog complete from Phase 21
└── planning_memory.py   # NO CHANGE: hint extraction complete from Phase 21

tests/
├── test_opengui_p8_planning.py        # MODIFY: assert real dispatch replaces placeholders
└── test_opengui_p22_route_dispatch.py # NEW: route resolver, tool dispatch, MCP dispatch, fallback, logging
```

### Pattern 1: Route ID to Registry Tool Name Resolution
**What:** Map planner-facing route IDs to concrete `ToolRegistry` keys using deterministic string rules.
**When to use:** Every `tool` and `mcp` atom dispatch in `_run_tool` and `_run_mcp`.
**Example:**
```python
# Route ID → registry tool name mapping (source: router.py research)
_ROUTE_ID_TO_TOOL: dict[str, str] = {
    "tool.exec_shell":        "exec",
    "tool.filesystem.read":   "read_file",
    "tool.filesystem.write":  "write_file",
    "tool.filesystem.edit":   "edit_file",
    "tool.filesystem.list":   "list_dir",
    "tool.web.search":        "web_search",
    "tool.web.fetch":         "web_fetch",
}

def _resolve_tool_route(route_id: str, registry: ToolRegistry) -> str | None:
    """Map a route_id to the registered tool name, or None if unavailable."""
    if route_id in _ROUTE_ID_TO_TOOL:
        tool_name = _ROUTE_ID_TO_TOOL[route_id]
        return tool_name if registry.has(tool_name) else None
    if route_id.startswith("mcp."):
        # mcp.{server}.{tool} → mcp_{server}_{tool}
        suffix = route_id[4:]  # strip "mcp."
        parts = suffix.split(".", 1)
        if len(parts) == 2:
            tool_name = f"mcp_{parts[0]}_{parts[1]}"
            return tool_name if registry.has(tool_name) else None
    return None
```

### Pattern 2: Instruction-as-Parameter Dispatch
**What:** For each route type, map the instruction string to the primary parameter of the target tool.
**When to use:** Building the `params` dict passed to `ToolRegistry.execute()`.
**Example:**
```python
# Source: inspection of ExecTool, ReadFileTool, WebSearchTool parameter schemas
_ROUTE_PARAM: dict[str, str] = {
    "exec":       "command",
    "read_file":  "path",
    "write_file": "path",   # Note: write_file needs content too — see Pitfall 2
    "edit_file":  "path",
    "list_dir":   "path",
    "web_search": "query",
    "web_fetch":  "url",
}

def _build_params(tool_name: str, instruction: str) -> dict[str, Any]:
    """Map instruction to tool-specific parameter dict."""
    primary_param = _ROUTE_PARAM.get(tool_name, "input")
    return {primary_param: instruction}
```

### Pattern 3: Dispatch With Fallback Chain
**What:** Try the primary `route_id`, then each `fallback_route_id` in order, logging each step.
**When to use:** `_run_tool` and `_run_mcp` after resolving route.
**Example:**
```python
async def _dispatch_with_fallback(
    self,
    node: PlanNode,
    context: RouterContext,
) -> NodeResult:
    # Build the ordered list of routes to try: primary first, then fallbacks
    route_ids_to_try = list(filter(None, [node.route_id])) + list(node.fallback_route_ids or ())
    logger.info(
        "Dispatch: planned_route=%s fallbacks=%s instruction=%r",
        node.route_id,
        list(node.fallback_route_ids),
        node.instruction,
    )
    for route_id in route_ids_to_try:
        tool_name = _resolve_tool_route(route_id, context.tool_registry)
        if tool_name is None:
            logger.warning("Route unavailable: route_id=%s (not in registry)", route_id)
            continue
        logger.info("Dispatch: resolved_route=%s tool=%s", route_id, tool_name)
        params = _build_params(tool_name, node.instruction)
        raw = await context.tool_registry.execute(tool_name, params)
        output = str(raw) if raw is not None else ""
        if not output.startswith("Error"):
            if route_id != node.route_id:
                logger.info("Dispatch: fallback_taken=%s (primary was %s)", route_id, node.route_id)
            return NodeResult(success=True, output=output)
        logger.warning("Dispatch: route_id=%s failed: %s", route_id, output[:120])
    return NodeResult(
        success=False,
        error=f"All routes failed for instruction: {node.instruction!r} (tried: {route_ids_to_try})",
    )
```

### Pattern 4: GUI Fallback As Last Resort
**What:** If `fallback_route_ids` includes `gui.desktop` and all tool routes fail, delegate to `GuiAgent`.
**When to use:** After exhausting all named route fallbacks.
**Example:**
```python
# In _dispatch_with_fallback, after the loop:
if "gui.desktop" in node.fallback_route_ids and context.gui_agent is not None:
    logger.info("Dispatch: fallback_taken=gui.desktop (all other routes failed)")
    return await self._run_gui(node.instruction, context)
```

### Pattern 5: No-Route-ID Fallback (Backward Compatibility)
**What:** When a `tool` or `mcp` atom has no `route_id` (old plans), fall back to a reasonable default or fail with a diagnostic.
**When to use:** Any atom where `route_id is None`.
**Example:**
```python
if node.route_id is None:
    logger.warning(
        "Dispatch: no route_id on %s atom, using instruction-only fallback", node.capability
    )
    # Try to find any registered tool matching the capability type
    # or return a structured diagnostic NodeResult
    return NodeResult(
        success=False,
        error=f"No route_id specified for {node.capability} atom: {node.instruction!r}",
    )
```

### Anti-Patterns to Avoid
- **Using an LLM to translate instructions to tool parameters:** Adds latency and a new failure surface. The instruction IS the primary parameter (the same pattern used by `GuiAgent.run(instruction)`).
- **Passing the full instruction string to multi-parameter tools like `write_file`:** `write_file` needs both `path` and `content`. See Common Pitfalls section.
- **Directly calling MCP sessions bypassing `ToolRegistry.execute()`:** MCP tools are already wrapped in `MCPToolWrapper` and registered in the registry. Use the registry, not raw sessions.
- **Modifying `PlanNode` schema for Phase 22:** The schema is complete from Phase 21. Phase 22 is execution-only.
- **Changing OR-node priority sort for Phase 22:** The `_CAPABILITY_PRIORITY` sort is still correct for general OR-node routing. Planner-declared `fallback_route_ids` is a separate, more specific mechanism.
- **Assuming `ToolRegistry.execute()` success means task success:** The registry returns error strings (not exceptions) for tool failures. Check `output.startswith("Error")` as the current convention.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP invocation | Custom MCP session call in router | `ToolRegistry.execute("mcp_{server}_{tool}", params)` | MCPToolWrapper already handles timeout, CancelledError, and content extraction |
| Tool parameter validation | Manual schema check in router | `ToolRegistry.execute()` which calls `tool.validate_params()` | The Tool base class already validates against JSON Schema |
| Route availability check | Query MCP server directly | `registry.has(tool_name)` | All available tools are registered at startup; `has()` is O(1) |
| Error detection | Exception-based routing | String prefix check `output.startswith("Error")` | Registry methods return error strings, not exceptions, by convention |

**Key insight:** The `ToolRegistry` is already the single point of dispatch for all tools, including MCP. The router needs only a route-ID-to-tool-name resolver and an instruction-to-parameters mapper, not a new execution engine.

## Common Pitfalls

### Pitfall 1: Confusing MCP Route ID Format With Registry Tool Name
**What goes wrong:** `route_id="mcp.demo.lookup"` does not directly match any registry key; the registry uses `mcp_demo_lookup`.
**Why it happens:** The catalog builder normalizes MCP tool names for planner readability (dots), but the registry uses underscores.
**How to avoid:** Use the mapping rule: `mcp.{server}.{tool}` → `mcp_{server}_{tool}` (replace prefix and dots).
**Warning signs:** `registry.has("mcp.demo.lookup")` returns `False` unexpectedly — the key is `mcp_demo_lookup`.

### Pitfall 2: Multi-Parameter Tools Cannot Be Driven By Instruction Alone
**What goes wrong:** `write_file` requires both `path` and `content`; passing only `instruction` as `path` will fail validation.
**Why it happens:** The instruction-as-parameter mapping works for single-required-parameter tools (exec, read_file, web_search, web_fetch) but breaks for write_file and edit_file.
**How to avoid:** For Phase 22, limit real dispatch to routes that are instruction-friendly (`tool.exec_shell`, `tool.filesystem.read`, `tool.filesystem.list`, `tool.web.search`, `tool.web.fetch`, and all `mcp.*` routes). Log structured diagnostics and return `NodeResult(success=False)` with a clear message for multi-parameter routes that cannot be driven from instruction alone; let them fall back to GUI.
**Warning signs:** `tool.validate_params()` returns `missing required path` or `missing required content` errors immediately.

### Pitfall 3: Error String Convention vs. Exceptions
**What goes wrong:** Router assumes tool failure raises an exception and wraps `_run_tool` in a try/except that never fires; placeholders return `success=True` on error strings.
**Why it happens:** `ToolRegistry.execute()` catches exceptions and returns them as formatted error strings by convention. The current placeholder ignores the `output` value entirely.
**How to avoid:** Check `output.startswith("Error")` after every `ToolRegistry.execute()` call.
**Warning signs:** Tests show `NodeResult.success=True` even when the underlying tool returned `"Error: Tool 'exec' not found..."`.

### Pitfall 4: No Route ID On Atom Breaks Dispatch
**What goes wrong:** Plans produced by earlier versions (or plans where the LLM didn't include `route_id`) have `node.route_id is None`. The dispatcher then has nothing to resolve.
**Why it happens:** `route_id` is optional in `PlanNode` (defaults to `None` from Phase 21).
**How to avoid:** Add explicit handling for `route_id is None`: log a structured diagnostic and return `NodeResult(success=False, error="...")`. Do not silently succeed with a placeholder.
**Warning signs:** Router logs show dispatch called but no `resolved_route=` log entry appears.

### Pitfall 5: Fallback Chain Silently Skips GUI
**What goes wrong:** `fallback_route_ids=("gui.desktop",)` is declared but `context.gui_agent` is `None` (e.g. in non-GUI mode), so the fallback silently fails without a diagnostic.
**Why it happens:** `gui.desktop` routing requires a live `GuiAgent`; its absence is only caught inside `_run_gui`.
**How to avoid:** Before trying `gui.desktop` fallback, check `context.gui_agent is not None` and log explicitly when the GUI fallback is unavailable.
**Warning signs:** All routes fail, `gui.desktop` is in fallback list, but the final error doesn't mention GUI unavailability.

### Pitfall 6: OR-Node Fallback Conflicts With Route Fallback
**What goes wrong:** An OR-node wraps a `tool` atom and a `gui` atom. The `tool` atom's `fallback_route_ids` includes `gui.desktop`. If the tool atom triggers its own GUI fallback internally AND the OR-node also tries the `gui` atom, the GUI is invoked twice.
**Why it happens:** The OR-node sorting and the atom-level fallback chain are two separate mechanisms.
**How to avoid:** Keep the `fallback_route_ids` chain inside `_dispatch_with_fallback` and let the OR-node's own children handle route-level alternation. Do not escalate from atom fallback into OR-node children. If the atom's internal fallback succeeds, return success from the atom; the OR-node sees a success and stops.
**Warning signs:** GUI runs twice for the same instruction in the trace.

## Code Examples

Verified patterns from current repo:

### How ToolRegistry.execute() Signals Failure
```python
# Source: nanobot/agent/tools/registry.py lines 38-59
async def execute(self, name: str, params: dict[str, Any]) -> Any:
    tool = self._tools.get(name)
    if not tool:
        return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
    try:
        params = tool.cast_params(params)
        errors = tool.validate_params(params)
        if errors:
            return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
        result = await tool.execute(**params)
        if isinstance(result, str) and result.startswith("Error"):
            return result + _HINT
        return result
    except Exception as e:
        return f"Error executing {name}: {str(e)}" + _HINT
```

**Implication:** Router must check `isinstance(output, str) and output.startswith("Error")` for failure detection.

### How MCP Tools Are Named In Registry
```python
# Source: nanobot/agent/tools/mcp.py lines 77-83
class MCPToolWrapper(Tool):
    def __init__(self, session, server_name: str, tool_def, tool_timeout: int = 30):
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
```

**Implication:** Route ID `mcp.demo.lookup` → registry key `mcp_demo_lookup`. The conversion rule is:
1. Strip `mcp.` prefix
2. Take `{server}.{tool}` suffix
3. Replace `.` with `_` once to get `{server}_{tool}`
4. Prepend `mcp_`: `mcp_{server}_{tool}`

Note: tool names with dots in them would need special handling, but the current `_build_mcp_route()` in `capabilities.py` uses `split("_", 1)` on the stripped suffix, suggesting tool names don't contain dots in practice.

### Current Placeholder Signatures Being Replaced
```python
# Source: nanobot/agent/router.py lines 286-296
async def _run_tool(self, instruction: str, context: RouterContext) -> NodeResult:
    """Dispatch to ToolRegistry — placeholder until Phase 3."""
    if context.tool_registry is None:
        return NodeResult(success=False, error="No ToolRegistry configured for tool dispatch")
    return NodeResult(success=True, output=f"Tool executed: {instruction}")

async def _run_mcp(self, instruction: str, context: RouterContext) -> NodeResult:
    """Dispatch to MCP client — placeholder until Phase 3."""
    if context.mcp_client is None:
        return NodeResult(success=False, error="No MCP client configured")
    return NodeResult(success=True, output=f"MCP executed: {instruction}")
```

**Implication:** Both methods now receive only `instruction` and `context`. Phase 22 needs access to the full `PlanNode` (for `route_id` and `fallback_route_ids`). The signatures must change to accept `node: PlanNode` instead of `instruction: str`, matching the existing `_dispatch_atom` signature pattern.

### Existing Dispatch Entry Point
```python
# Source: nanobot/agent/router.py lines 254-272
async def _dispatch_atom(self, node: Any, context: RouterContext) -> NodeResult:
    capability = node.capability
    instruction = node.instruction
    try:
        if capability == "gui":
            return await self._run_gui(instruction, context)
        if capability == "tool":
            return await self._run_tool(instruction, context)
        if capability == "mcp":
            return await self._run_mcp(instruction, context)
        ...
```

**Implication:** `_dispatch_atom` already has access to the full `node`. The cleanest change is to pass `node` instead of `node.instruction` to `_run_tool` and `_run_mcp`, letting them access `route_id` and `fallback_route_ids`.

### Route ID → Tool Name Mapping Table (Built From Catalog Builder)
```python
# Source: nanobot/agent/capabilities.py _ROUTE_SPECS — verified
_ROUTE_ID_TO_TOOL_NAME: dict[str, str] = {
    "gui.desktop":          "gui_task",      # handled by _run_gui, not this table
    "tool.exec_shell":      "exec",
    "tool.filesystem.read": "read_file",
    "tool.filesystem.write": "write_file",
    "tool.filesystem.edit": "edit_file",
    "tool.filesystem.list": "list_dir",
    "tool.web.search":      "web_search",
    "tool.web.fetch":       "web_fetch",
}

# Primary parameter for instruction-as-parameter dispatch (single-required-param tools only)
_INSTRUCTION_FRIENDLY_ROUTES: dict[str, str] = {
    "exec":       "command",
    "read_file":  "path",
    "list_dir":   "path",
    "web_search": "query",
    "web_fetch":  "url",
    # Note: write_file, edit_file are NOT in this table — need structured params
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `_run_tool` returns `NodeResult(success=True)` unconditionally | Real `ToolRegistry.execute()` call with route resolution | Phase 22 | CAP-03: tool atoms produce real results |
| `_run_mcp` returns `NodeResult(success=True)` unconditionally | Real registry dispatch via `mcp_{server}_{tool}` key | Phase 22 | CAP-04: MCP atoms invoke actual MCP sessions |
| No fallback chain in atom dispatch | `fallback_route_ids` tried in order on primary failure | Phase 22 | Graceful degradation without losing task context |
| No route logging | `planned_route`, `resolved_route`, `fallback_taken` in logs | Phase 22 | CAP-03/CAP-04 success criterion: execution traces are inspectable |

**Deprecated/outdated after Phase 22:**
- Placeholder comment "placeholder until Phase 3" in `_run_tool` and `_run_mcp` — remove.
- `mcp_client` field in `RouterContext` — in `loop.py` it is already set to `self.tools` (same as `tool_registry`). After Phase 22, the dispatch logic uses `tool_registry` exclusively; `mcp_client` is redundant but can be kept for backward compatibility.

## Recommended Phase Split

### 22-01: Route Resolver And Router Contract Extension
**Scope:**
- Add `_ROUTE_ID_TO_TOOL_NAME` mapping table and `_INSTRUCTION_FRIENDLY_ROUTES` in `router.py`
- Add `_resolve_route(route_id, registry)` helper returning `(tool_name, param_key) | None`
- Change `_run_tool` and `_run_mcp` signatures to accept `node: PlanNode` instead of `instruction: str`
- Update `_dispatch_atom` to pass `node` (not `node.instruction`) to these methods
- Add structured logging for `planned_route`, `resolved_route`, `fallback_taken`
- Keep dispatch logic minimal: if route resolves → call registry → return result. No fallback chain yet (that's 22-02).
- Wave 0 gap: `tests/test_opengui_p22_route_dispatch.py` with failing tests for resolver and basic dispatch

### 22-02: Fallback Handling And Observability
**Scope:**
- Implement `_dispatch_with_fallback(node, context)` that chains through `fallback_route_ids`
- Handle `gui.desktop` fallback by delegating to `_run_gui`
- Handle `route_id is None` gracefully (structured diagnostic)
- Handle multi-parameter routes (write_file, edit_file) with a descriptive `NodeResult(success=False)` and explicit fallback
- Add structured error diagnostics including which routes were tried
- Update existing Phase 8 tests to assert placeholder behavior is gone

## Open Questions

1. **Should `write_file` and `edit_file` routes ever be dispatched from instruction alone in Phase 22?**
   - What we know: These tools need both `path` and `content` — instruction alone is insufficient.
   - What's unclear: Whether the planner ever realistically selects these routes in single-atom plans.
   - Recommendation: Return `NodeResult(success=False, error="write_file/edit_file route requires structured parameters; falling back")` and check `fallback_route_ids` (typically falls back to GUI). Document this limitation in the plan.

2. **Should `mcp_client` be removed from `RouterContext` in Phase 22?**
   - What we know: In `loop.py`, `mcp_client=self.tools` makes `mcp_client` identical to `tool_registry`. MCP tools are dispatched through the registry.
   - What's unclear: Whether external callers of `RouterContext` depend on the distinction.
   - Recommendation: Keep `mcp_client` in `RouterContext` for backward compatibility but have `_run_mcp` use `context.tool_registry` exclusively. Phase 22 plans should note this cleanup opportunity for Phase 23.

3. **Should route resolution be a standalone class (`RouteResolver`) or inline in `router.py`?**
   - What we know: The mapping is a small, deterministic lookup with ~8 entries.
   - What's unclear: Whether Phase 23 will need to extend route resolution with memory-derived suggestions.
   - Recommendation: Keep it as module-level constants and helpers in `router.py` for Phase 22. The planner already handles route selection; the router only needs to execute what the planner chose.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest >=9.0.0,<10.0.0` + `pytest-asyncio >=1.3.0,<2.0.0` |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_opengui_p22_route_dispatch.py` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAP-03 | `_run_tool` no longer returns placeholder; calls `ToolRegistry.execute()` with resolved tool name and instruction param | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "tool_dispatch"` | ❌ Wave 0 |
| CAP-03 | Route ID `tool.exec_shell` resolves to tool name `exec` and param key `command` | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "route_resolver"` | ❌ Wave 0 |
| CAP-03 | `tool` atom with `route_id=None` returns structured failure, not placeholder success | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "no_route_id"` | ❌ Wave 0 |
| CAP-04 | `_run_mcp` resolves `mcp.{server}.{tool}` to registry key `mcp_{server}_{tool}` and calls `execute()` | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "mcp_dispatch"` | ❌ Wave 0 |
| CAP-04 | When primary MCP route unavailable, `fallback_route_ids` are tried in order | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "fallback"` | ❌ Wave 0 |
| CAP-04 | `gui.desktop` in `fallback_route_ids` delegates to `_run_gui` when other routes fail | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "gui_fallback"` | ❌ Wave 0 |
| CAP-03/04 | Logs contain `planned_route=`, `resolved_route=`, and `fallback_taken=` entries | unit | `uv run pytest -q tests/test_opengui_p22_route_dispatch.py -k "logging"` | ❌ Wave 0 |
| CAP-03 | Existing Phase 8 `_run_tool` placeholder tests updated to assert real dispatch | regression | `uv run pytest -q tests/test_opengui_p8_planning.py` | ✅ (update needed) |

### Sampling Rate
- **Per task commit:** `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_opengui_p22_route_dispatch.py`
- **Per wave merge:** `uv run pytest -q tests/test_opengui_p8_planning.py tests/test_opengui_p21_planner_context.py tests/test_opengui_p22_route_dispatch.py`
- **Phase gate:** `uv run pytest` (full suite, currently 869 passing)

### Wave 0 Gaps
- [ ] `tests/test_opengui_p22_route_dispatch.py` — route resolver, tool dispatch, MCP dispatch, fallback chain, GUI fallback, and logging coverage
- [ ] Update `tests/test_opengui_p8_planning.py` — remove assumptions about placeholder return values in tool/MCP dispatch

*(No new framework install needed — existing pytest + pytest-asyncio infrastructure covers all Phase 22 tests.)*

## Sources

### Primary (HIGH confidence)
- `nanobot/agent/router.py` — current `TreeRouter`, placeholder dispatch, `RouterContext` definition
- `nanobot/agent/planner.py` — `PlanNode` schema with `route_id`, `fallback_route_ids` from Phase 21
- `nanobot/agent/capabilities.py` — `CapabilityCatalogBuilder._ROUTE_SPECS` for route ID → tool name mapping
- `nanobot/agent/tools/registry.py` — `ToolRegistry.execute()` signature, error string convention
- `nanobot/agent/tools/mcp.py` — `MCPToolWrapper` naming convention (`mcp_{server}_{tool}`)
- `nanobot/agent/tools/shell.py` — `ExecTool` parameter schema (`command` is primary param)
- `nanobot/agent/tools/filesystem.py` — filesystem tool schemas (read_file, write_file, etc.)
- `nanobot/agent/loop.py` — `_plan_and_execute()` shows `mcp_client=self.tools` (same as tool_registry)
- `tests/test_opengui_p8_planning.py` — existing router/planner test coverage to preserve
- `.planning/ROADMAP.md` — Phase 22 plan descriptions and success criteria
- `docs/plans/2026-03-22-capability-aware-planner-routing-design.md` — design intent for route-aware dispatch
- `.planning/REQUIREMENTS.md` — CAP-03 and CAP-04 definitions

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — Phase 21 completion decisions and constraints carried forward
- `.planning/phases/21-capability-catalog-and-planner-context/21-RESEARCH.md` — Phase 21 research confirming router unchanged until Phase 22

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries and tools verified by direct code inspection
- Architecture: HIGH — based on deep inspection of `router.py`, `registry.py`, `mcp.py`, and `capabilities.py`
- Pitfalls: HIGH — most pitfalls are directly visible in the current placeholder implementation and existing test patterns

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable internal codebase; no external dependency changes expected)
