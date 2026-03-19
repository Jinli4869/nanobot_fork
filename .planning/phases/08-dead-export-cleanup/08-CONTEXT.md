# Phase 8: Dead Export Cleanup → Wire Orphaned Components - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Remove orphaned exports by wiring them into production code. Three components — TaskPlanner, TreeRouter, TrajectorySummarizer — are tested but never called from production. This phase wires all three into the agent loop and post-run pipeline, completing the remaining Phase 3 Plan 02 requirements (NANO-01, NANO-04, NANO-05) in the process. Upon completion, both Phase 3 and Phase 8 are marked complete.

</domain>

<decisions>
## Implementation Decisions

### TaskPlanner + TreeRouter Integration
- Wire TaskPlanner and TreeRouter into the nanobot agent loop
- **Conditional planning**: LLM decides whether a task needs decomposition via a lightweight assessment prompt before calling TaskPlanner
- If TaskPlanner is invoked, it decomposes the task into an AND/OR/ATOM tree with capability-typed ATOMs (gui, tool, mcp)
- TreeRouter dispatches ATOMs to the appropriate executor (GuiSubagentTool, nanobot tool registry, MCP servers)

### Tree Execution Semantics
- **AND nodes**: Independent children execute in parallel with a configurable concurrency limit (default 3)
- **OR nodes**: Priority order is mcp > tool > gui — GUI is the fallback of last resort
- **OR failure handling**: Auto-fallback — try next child automatically on failure, only report if all children fail
- **Plan visibility**: Log the decomposed plan tree before execution so user/developer can see the plan

### TrajectorySummarizer Wiring
- Auto-extract skills after every GUI run — both successful and failed trajectories
- Newly extracted skills are immediately available in SkillLibrary for the next run (no gating or review queue)
- This fulfills NANO-05 (main agent trajectory_summary skill for post-run skill extraction)

### Phase 3 Completion
- Phase 8 absorbs remaining Phase 3 Plan 02 work (NANO-01, NANO-04, NANO-05)
- Upon Phase 8 completion, both Phase 3 and Phase 8 are marked complete

### Claude's Discretion
- How the LLM complexity assessment prompt is structured
- Exact concurrency limit default and configuration mechanism
- Whether PlanNode/NodeResult/RouterContext are exported from nanobot.agent.__init__ alongside main classes
- Whether TrajectorySummarizer gets a top-level opengui re-export or stays in opengui.trajectory

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### TaskPlanner + TreeRouter
- `nanobot/agent/planner.py` — TaskPlanner class, PlanNode dataclass, AND/OR/ATOM tree decomposition
- `nanobot/agent/router.py` — TreeRouter class, NodeResult, RouterContext, capability dispatch logic
- `.planning/phases/02-agent-loop-integration/02-03-PLAN.md` — Original plan that created TaskPlanner + TreeRouter

### TrajectorySummarizer
- `opengui/trajectory/summarizer.py` — TrajectorySummarizer class, LLM-based trajectory summarization
- `opengui/trajectory/__init__.py` — Current export surface

### Phase 3 Remaining Work
- `.planning/phases/03-nanobot-subagent/03-02-PLAN.md` — Pending plan for NANO-01, NANO-04, NANO-05 (superseded by Phase 8)
- `.planning/phases/03-nanobot-subagent/03-CONTEXT.md` — Phase 3 context with GuiSubagentTool decisions

### Existing Tests
- `tests/test_opengui_p2_integration.py` — Integration tests importing TaskPlanner, TreeRouter
- `tests/test_opengui_p1_trajectory.py` — TrajectorySummarizer unit tests

### Agent Loop (Integration Target)
- `nanobot/agent/` — Agent loop where planner/router will be wired
- `opengui/agent.py` — GuiAgent.run() where trajectory summarizer post-run hook connects

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TaskPlanner` (nanobot/agent/planner.py): Fully implemented AND/OR/ATOM decomposition via single LLM call
- `TreeRouter` (nanobot/agent/router.py): Fully implemented tree walker with capability dispatch stubs
- `TrajectorySummarizer` (opengui/trajectory/summarizer.py): Fully implemented LLM-based summarization
- `GuiSubagentTool`: Already partially wired (Phase 3 Plan 01 complete) — the `gui` capability executor
- `SkillExtractor` (opengui/skills/extractor.py): Extracts skills from trajectories — downstream of summarizer

### Established Patterns
- Protocol-based architecture (LLMProvider + DeviceBackend) — opengui must not import nanobot code
- NanobotLLMAdapter bridges nanobot → opengui LLMProvider protocol
- NanobotEmbeddingAdapter bridges nanobot → opengui EmbeddingProvider protocol
- Existing tool registry pattern in nanobot for registering callable tools

### Integration Points
- Nanobot agent loop: where TaskPlanner complexity check + TreeRouter dispatch will be wired
- GuiSubagentTool.execute(): the `gui` capability handler for TreeRouter
- Post-run hook in GuiAgent or GuiSubagentTool: where TrajectorySummarizer + SkillExtractor chain runs
- nanobot/agent/__init__.py: needs TaskPlanner + TreeRouter exports added

</code_context>

<specifics>
## Specific Ideas

- OR nodes prioritize non-GUI capabilities (mcp > tool > gui) — GUI automation is the most expensive/fragile option and should be last resort
- Plan tree should be logged/printed before execution for transparency
- Real-LLM integration tests live in `opengui/test/` directory, using `~/.opengui/config.yaml` for provider credentials (base-url, api-key), not included in CI
- Skills extracted from failed trajectories teach what NOT to do — both success and failure extraction is valuable

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope (expanded scope was agreed upon before discussion began)

</deferred>

---

*Phase: 08-dead-export-cleanup*
*Context gathered: 2026-03-19*
