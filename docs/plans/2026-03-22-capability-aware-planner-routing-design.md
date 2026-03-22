# Capability-Aware Planner And Routing Design

**Date:** 2026-03-22
**Status:** Proposed
**Scope:** Nanobot planner and router follow-on design for v1.4

## Problem

Nanobot's current planner reasons over coarse capability labels such as `gui`, `tool`, `mcp`, and `api`, but it does not see the live callable route inventory behind those labels. As a result:

- tasks that could be handled through a direct shell/tool/MCP route are often planned as GUI work
- the planner cannot tell which tools are actually available in the current runtime
- the router cannot faithfully execute `tool` or `mcp` atoms because those paths are still placeholders
- memory-derived knowledge about which routes succeeded in the past does not influence planning

This makes the system conservative, but also inefficient and harder to improve over time.

## Goals

1. Give the planner a compact, trustworthy summary of the currently available execution routes.
2. Let plans express route intent explicitly instead of only naming a coarse capability class.
3. Make router execution for `tool` and `mcp` nodes real, inspectable, and fallback-safe.
4. Feed routing-relevant memory back into planning without bloating prompts with unrelated context.
5. Preserve GUI as an important fallback rather than the default answer for every ambiguous task.

## Non-Goals

- Dumping full tool schemas or raw MCP manifests into the planner prompt
- Replacing the current planner with a new orchestration engine
- Building general semantic tool search before route-aware execution exists
- Removing GUI routing from mixed tasks where visual confirmation is still the safest choice

## Proposed Architecture

### 1. Build A Planner-Time Capability Catalog

Introduce a planner-facing `CapabilityCatalogBuilder` that compiles a compact summary from live runtime state just before planning. Its inputs should include:

- registered local tools from `ToolRegistry`
- MCP server inventory and exposed callable routes
- host/runtime availability signals such as GUI support, shell/exec availability, and background constraints
- optional skill- or host-provided route hints when they are stable and cheap to compute

The planner should not receive raw schemas for every route. Instead, it should receive a bounded catalog of route summaries shaped roughly like:

```json
{
  "route_id": "tool.exec_shell",
  "capability": "tool",
  "kind": "shell",
  "summary": "Run short local shell commands on this host",
  "use_for": ["system toggles", "local automation", "file inspection"],
  "avoid_for": ["visual-only tasks", "untrusted destructive commands"],
  "availability": "ready"
}
```

This keeps the prompt readable while giving the planner enough evidence to distinguish "close Bluetooth with a shell route" from "open Obsidian and edit today's note through GUI."

### 2. Upgrade Plan Nodes From Capability Labels To Route Intent

The planner's atom nodes should remain capability-oriented, but they need optional route identity and fallback metadata. A representative atom shape is:

```json
{
  "type": "ATOM",
  "capability": "tool",
  "instruction": "Disable Bluetooth on the local macOS host",
  "route_id": "tool.exec_shell",
  "route_reason": "Local shell route can toggle host Bluetooth more directly than GUI automation",
  "fallback_route_ids": ["gui.desktop"]
}
```

This preserves the high-level planning vocabulary while making route choice explicit and debuggable.

### 3. Inject Memory As Routing Hints, Not Raw Memory Dumps

The planner should not read `memory.md` wholesale. Instead, add a `PlanningMemoryHints` extraction step that turns prior execution history into a small list of routing hints such as:

- task pattern: `"toggle bluetooth"`
- preferred route: `"tool.exec_shell"`
- evidence: `"Succeeded 3 times on darwin host"`
- confidence: `0.82`
- constraints: `"Falls back to GUI if shell route unavailable"`

These hints should be filtered to planning-relevant information only:

- previous route successes or failures
- host or OS-specific preferences
- explicit safety constraints
- known fallback guidance

They should exclude:

- unrelated conversational memory
- long narrative notes
- arbitrary user profile data

This keeps planning grounded in prior success without overwhelming the model.

### 4. Make Router Dispatch Route-Aware

Router execution should become a two-stage process:

1. Resolve route identity:
   - prefer the planner-provided `route_id`
   - otherwise use a constrained route resolver against the capability catalog
2. Execute the concrete route:
   - `tool` atoms invoke real local tools
   - `mcp` atoms invoke real MCP routes
   - `gui` atoms keep using the existing GUI execution path

The router should log both:

- planned route: what the planner intended
- resolved route: what actually ran after validation/fallback

If a route is unavailable or validation fails, the router should either:

- use a planner-declared fallback route, or
- fail with structured diagnostics that can be turned into future memory hints

### 5. Add A Lightweight Feedback Loop

After execution, store route outcomes in a normalized form suitable for planning reuse:

- task pattern
- selected route
- host/runtime conditions
- success/failure outcome
- fallback taken

This is the minimum data needed to support "we used shell last time and it worked" without turning the planner prompt into an execution transcript.

## Prompting Strategy

The planner prompt should change from:

- "Choose among coarse capabilities"

to:

- "Choose the best capability and route from this compact live catalog, using routing hints when available."

Prompt constraints should explicitly instruct the model to:

- prefer direct non-GUI routes for deterministic host operations when a trusted route exists
- reserve GUI for visual workflows, applications without direct routes, and fallback situations
- justify route choice in a short `route_reason`
- include a fallback route when the task touches a host-side toggle or operation that may vary by platform

## Why Memory Belongs In Planner Context

Yes, planner context should include memory-derived routing hints.

Reasoning:

- the main agent already benefits from prior execution knowledge
- route selection is one of the highest-leverage decisions for cost, speed, and reliability
- memory can encode stable preferences such as "Bluetooth toggle on macOS succeeds via shell route"
- putting this only in execution-time routing is too late; we want the planner to decompose tasks with the right route bias from the start

The key design rule is that memory must be summarized into route hints rather than passed through as unstructured notes.

## Example

User request:

> 帮我打开obsidian，在今天的记录中新建一个 task，内容为打卡；顺便帮我把蓝牙关了

Capability-aware plan:

```text
AND
  - GUI via gui.desktop: 打开 Obsidian 应用
  - GUI via gui.desktop: 在 Obsidian 中打开今天的日记记录
  - GUI via gui.desktop: 在今天的记录中新建一个 task，内容为“打卡”
  - TOOL via tool.exec_shell: 关闭本机蓝牙
    fallback -> gui.desktop
```

This is better than an all-GUI plan because the note editing remains visual while the host toggle uses a more direct route.

## Rollout Recommendation

### Phase 21: Capability Catalog And Planner Context

- build live capability catalog summaries from ToolRegistry, MCP inventory, and host/runtime availability
- inject bounded routing hints derived from memory into planner context
- update planner prompt and plan schema to express route identity and fallback metadata

### Phase 22: Route-Aware Tool And MCP Dispatch

- implement concrete route dispatch for `tool` atoms
- implement concrete route dispatch for `mcp` atoms
- validate route IDs before execution and preserve GUI fallback behavior

### Phase 23: Routing Memory Feedback And Verification

- persist normalized route outcome summaries as future planning hints
- add representative mixed-capability verification scenarios
- verify that capability-aware planning reduces unnecessary GUI choices

## Key Tradeoffs

### Why Not Give The Planner Full Schemas?

Because prompt cost and model confusion would grow quickly. The planner needs route intent, not the full call surface.

### Why Not Keep Route Resolution Entirely In The Router?

Because decomposition quality suffers if the planner cannot distinguish host toggles from visual application work. Route awareness is useful during planning, not just execution.

### Why Keep GUI As Fallback?

Because GUI remains the most general route and still matters when:

- no trusted direct route exists
- direct execution is unavailable in the current runtime
- the task requires visual confirmation inside an application

## Success Criteria

1. Planner can distinguish visual application work from direct host operations using live route summaries.
2. Mixed tasks produce plans that combine GUI and non-GUI routes where appropriate.
3. Router can execute planned `tool` and `mcp` routes with validation and fallback.
4. Memory-derived routing hints improve future route choice without inflating planner prompts uncontrollably.
5. Logs and traces show both human-readable plan structure and concrete route identity.
