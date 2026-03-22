---
phase: quick
plan: 260322-otm
type: execute
wave: 1
depends_on: []
files_modified:
  - nanobot/agent/planner.py
  - nanobot/agent/router.py
  - tests/test_opengui_p22_route_dispatch.py
autonomous: true
requirements: [OTM-PARAMS]
must_haves:
  truths:
    - "Planner LLM generates structured params dict on ATOM nodes when route_id is present"
    - "Router dispatch uses node.params when available instead of {param_key: node.instruction}"
    - "Multi-param routes (write_file, edit_file) can be dispatched when params is populated"
    - "Backward compatible: nodes without params still dispatch via instruction fallback"
  artifacts:
    - path: "nanobot/agent/planner.py"
      provides: "PlanNode.params field + schema + prompt guidance"
      contains: "params"
    - path: "nanobot/agent/router.py"
      provides: "params-preferring dispatch in _run_tool, _run_mcp, _dispatch_with_fallback"
      contains: "node.params"
    - path: "tests/test_opengui_p22_route_dispatch.py"
      provides: "Tests covering params-based dispatch and instruction fallback"
      contains: "params"
  key_links:
    - from: "nanobot/agent/planner.py"
      to: "nanobot/agent/router.py"
      via: "PlanNode.params dict consumed at dispatch"
      pattern: "node\\.params"
    - from: "nanobot/agent/planner.py (_CREATE_PLAN_TOOL)"
      to: "LLM output"
      via: "Tool schema tells LLM to produce params object"
      pattern: "params.*object"
---

<objective>
Make the planner generate structured tool parameters so the router can dispatch with real executable values instead of passing natural language instruction text as tool parameters.

Purpose: Currently `instruction` (human-readable text like "列出项目目录结构") gets passed as `{"path": "列出项目目录结构"}` to tools that expect real paths/commands/URLs. Adding a `params` field lets the planner produce `{"path": "/Users/jinli/project"}` alongside the human-readable instruction.

Output: Updated PlanNode with optional `params` dict, updated LLM schema and prompt, updated router dispatch preferring `params` over instruction fallback, tests.
</objective>

<execution_context>
@/Users/jinli/.claude/get-shit-done/workflows/execute-plan.md
@/Users/jinli/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@nanobot/agent/planner.py
@nanobot/agent/router.py
@tests/test_opengui_p22_route_dispatch.py

<interfaces>
<!-- PlanNode dataclass (planner.py:26-75) -->
```python
@dataclass(frozen=True)
class PlanNode:
    node_type: NodeType
    instruction: str = ""
    capability: CapabilityType = "tool"
    route_id: str | None = None
    route_reason: str = ""
    fallback_route_ids: tuple[str, ...] = ()
    children: tuple[PlanNode, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanNode: ...
```

<!-- Router dispatch points (router.py) -->
```python
# _dispatch_with_fallback line 403:
params = {param_key: node.instruction}

# _run_tool line 480:
params = {param_key: node.instruction}

# _run_mcp line 528:
params = {param_key: node.instruction}
```

<!-- _INSTRUCTION_PARAM maps single-param tools only -->
```python
_INSTRUCTION_PARAM: dict[str, str] = {
    "exec":       "command",
    "read_file":  "path",
    "list_dir":   "path",
    "web_search": "query",
    "web_fetch":  "url",
}
# write_file, edit_file are ABSENT (multi-param, currently rejected)
```

<!-- _resolve_route returns (tool_name, param_key|None) -->
```python
def _resolve_route(route_id: str, registry: Any) -> tuple[str, str | None] | None:
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add params field to PlanNode + update LLM schema and prompt</name>
  <files>nanobot/agent/planner.py, tests/test_opengui_p8_planning.py</files>
  <behavior>
    - PlanNode(params={"path": "/tmp"}) stores the dict; PlanNode().params returns None by default
    - PlanNode(params={"path": "/tmp"}).to_dict() includes "params": {"path": "/tmp"}
    - PlanNode.from_dict({"type": "atom", "instruction": "x", "params": {"path": "/tmp"}}).params == {"path": "/tmp"}
    - PlanNode.from_dict({"type": "atom", "instruction": "x"}).params is None (backward compat)
    - Existing tests in test_opengui_p8_planning.py and test_opengui_p22_route_dispatch.py still pass unchanged
  </behavior>
  <action>
    1. In PlanNode dataclass, add field: `params: dict[str, Any] | None = None` after `fallback_route_ids`. This is an optional dict of structured tool parameters. Keep the dataclass frozen.

    2. In `to_dict()`: if `self.params` is not None, add `d["params"] = self.params` (inside the `node_type == "atom"` branch, after fallback_route_ids serialization).

    3. In `from_dict()`: in the atom branch, extract params: `params=data.get("params")` and pass to constructor. The `params` value from JSON is already a dict or None, no conversion needed.

    4. In `_CREATE_PLAN_TOOL` schema (line 82-112): add `params` property to the tree node description. Update the description string for the tree property to mention params:
       ```
       "ATOM nodes have 'instruction' (human-readable description of what to do), "
       "'capability' (gui/tool/mcp/api), and may optionally include 'route_id', "
       "'route_reason', 'fallback_route_ids', and 'params' (dict of concrete "
       "executable parameter values for the routed tool)."
       ```

    5. In `_build_system_prompt()`: Add guidance after the existing rules (before the catalog section). Add these lines:
       ```
       "- When route_id points to a concrete tool or MCP route, include 'params' with the exact "
       "executable parameter values the tool expects. For example:",
       "  - tool.exec_shell: params={\"command\": \"ls -la /tmp\"}",
       "  - tool.filesystem.read: params={\"path\": \"/etc/hosts\"}",
       "  - tool.filesystem.list: params={\"path\": \"/Users/jinli/project\"}",
       "  - tool.filesystem.write: params={\"path\": \"out.txt\", \"content\": \"hello\"}",
       "  - tool.filesystem.edit: params={\"path\": \"main.py\", \"old_text\": \"foo\", \"new_text\": \"bar\"}",
       "  - tool.web.search: params={\"query\": \"python asyncio tutorial\"}",
       "  - tool.web.fetch: params={\"url\": \"https://example.com\"}",
       "  - mcp.{server}.{tool}: params={\"input\": \"the input value\"} or tool-specific keys",
       "- 'instruction' stays as the human-readable description; 'params' holds machine-executable values.",
       "- For gui capability, params is not needed (the GUI subagent interprets instruction directly).",
       ```

    6. Add tests to a new test section in test_opengui_p8_planning.py (or create a small focused test at the bottom of that file) verifying PlanNode params round-trip through to_dict/from_dict, and None default.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -m pytest tests/test_opengui_p8_planning.py tests/test_opengui_p22_route_dispatch.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>PlanNode has params field, LLM tool schema and system prompt guide param generation, to_dict/from_dict round-trip works, all existing tests pass</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Update router dispatch to prefer node.params over instruction fallback</name>
  <files>nanobot/agent/router.py, tests/test_opengui_p22_route_dispatch.py</files>
  <behavior>
    - _run_tool with node.params={"command": "ls"} dispatches {"command": "ls"} (not {param_key: instruction})
    - _run_tool with node.params=None falls back to {param_key: node.instruction} (backward compat)
    - _run_mcp with node.params={"input": "query"} dispatches {"input": "query"}
    - _run_mcp with node.params=None falls back to {param_key: node.instruction}
    - _dispatch_with_fallback with node.params dispatches params directly
    - Multi-param route (write_file) with node.params={"path": "x", "content": "y"} dispatches successfully (no longer rejected)
    - Multi-param route without node.params still rejected (param_key is None, instruction-only dispatch impossible)
  </behavior>
  <action>
    Update three dispatch points in router.py to prefer `node.params` when available:

    1. **_dispatch_with_fallback** (around line 391-403): After resolving `tool_name, param_key`, replace the params assignment:
       ```python
       # Before: params = {param_key: node.instruction}
       # After:
       if node.params is not None:
           params = dict(node.params)
       elif param_key is not None:
           params = {param_key: node.instruction}
       else:
           logger.warning(
               "Dispatch: route %s requires structured parameters and no params provided, skipping",
               route_id,
           )
           tried.append(f"{route_id}(multi-param)")
           continue
       ```
       Also update the multi-param guard earlier (lines 392-398): when `param_key is None`, check `node.params is not None` first — if params exist, proceed; only skip if both param_key and params are absent.

    2. **_run_tool** (around line 462-480): Same pattern. After resolving `tool_name, param_key`:
       ```python
       if node.params is not None:
           params = dict(node.params)
       elif param_key is not None:
           params = {param_key: node.instruction}
       else:
           # Multi-param route without structured params — cannot dispatch
           return NodeResult(
               success=False,
               error=(
                   f"Route {node.route_id} requires structured parameters; "
                   "instruction-only dispatch not supported"
               ),
           )
       ```
       Remove the earlier `if param_key is None: return NodeResult(...)` guard — the logic is now unified below.

    3. **_run_mcp** (around line 523-528): Same pattern:
       ```python
       if node.params is not None:
           params = dict(node.params)
       elif param_key is not None:
           params = {param_key: node.instruction}
       else:
           params = {param_key: node.instruction}  # MCP always has param_key="input"
       ```
       (MCP _resolve_route always returns param_key="input", so the else branch is effectively the same, but the pattern stays consistent.)

    4. **Add tests** to tests/test_opengui_p22_route_dispatch.py:
       - `test_run_tool_prefers_node_params`: Create atom with route_id="tool.exec_shell" and params={"command": "echo hi"}, verify registry.execute receives exactly {"command": "echo hi"}.
       - `test_run_tool_falls_back_to_instruction`: Create atom with route_id="tool.exec_shell" and params=None, verify registry.execute receives {"command": node.instruction}.
       - `test_run_tool_multi_param_with_params`: Create atom with route_id="tool.filesystem.write" and params={"path": "out.txt", "content": "hello"}, verify dispatch succeeds (no longer rejected).
       - `test_run_tool_multi_param_without_params`: Create atom with route_id="tool.filesystem.write" and params=None, verify NodeResult.success=False with "structured parameters" error.
       - `test_run_mcp_prefers_node_params`: Similar for MCP atom.
       - `test_dispatch_with_fallback_uses_params`: Atom with fallback_route_ids, params set, verify params used.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -m pytest tests/test_opengui_p22_route_dispatch.py tests/test_opengui_p8_planning.py -x -q 2>&1 | tail -20</automated>
  </verify>
  <done>Router prefers node.params for dispatch, falls back to instruction-based dispatch when params is None, multi-param routes work with params, all tests pass</done>
</task>

</tasks>

<verification>
Full test suite for affected modules:
```bash
cd /Users/jinli/Documents/Personal/nanobot_fork && python -m pytest tests/test_opengui_p8_planning.py tests/test_opengui_p22_route_dispatch.py tests/test_opengui_p21_planner_context.py -x -q
```

Smoke check PlanNode round-trip:
```bash
cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "
from nanobot.agent.planner import PlanNode
n = PlanNode(node_type='atom', instruction='list files', capability='tool', route_id='tool.filesystem.list', params={'path': '/tmp'})
d = n.to_dict()
assert d['params'] == {'path': '/tmp'}, f'to_dict failed: {d}'
n2 = PlanNode.from_dict(d)
assert n2.params == {'path': '/tmp'}, f'from_dict failed: {n2.params}'
n3 = PlanNode(node_type='atom', instruction='list files')
assert n3.params is None, 'default should be None'
print('PlanNode params round-trip OK')
"
```
</verification>

<success_criteria>
1. PlanNode has `params: dict[str, Any] | None = None` field with to_dict/from_dict support
2. LLM tool schema describes params field for ATOM nodes
3. System prompt instructs LLM to generate concrete executable params
4. Router dispatch at all three points prefers node.params when present
5. Multi-param routes (write_file, edit_file) dispatch successfully when params is populated
6. Backward compatibility: nodes without params still work via instruction fallback
7. All existing + new tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260322-otm-planner/260322-otm-SUMMARY.md`
</output>
