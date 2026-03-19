# Phase 7: Phase 2 Retroactive Verification - Research

**Researched:** 2026-03-19
**Domain:** Retroactive verification of Phase 2 agent-loop integration requirements
**Confidence:** HIGH

## User Constraints

No `07-CONTEXT.md` exists. These constraints come from the phase description and current request:

- Focus only on Phase 7 planning inputs.
- Resolve the contradiction between the roadmap and the existing `.planning/phases/02-agent-loop-integration/VERIFICATION.md`.
- Verify exactly 7 requirements: `AGENT-04`, `AGENT-05`, `AGENT-06`, `MEM-05`, `SKILL-08`, `TRAJ-03`, `TEST-05`.
- Use code and tests as evidence.
- Include a `## Validation Architecture` section so a Phase 7 validation doc can be created.
- Preserve the success-criteria path: `.planning/phases/02-agent-loop-integration/VERIFICATION.md`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AGENT-04 | `GuiAgent.run()` integrates memory retrieval into system prompt | `opengui/agent.py` `_retrieve_memory()` and `_build_messages()`; `tests/test_opengui_p2_integration.py::test_memory_injected_into_system_prompt` |
| AGENT-05 | `GuiAgent.run()` integrates skill search -> execute matched skill or free explore | `opengui/agent.py` `_search_skill()` and `run()` skill branch; `tests/test_opengui_p2_integration.py::test_skill_path_chosen_above_threshold`; `::test_free_explore_when_no_skill_match` |
| AGENT-06 | `GuiAgent.run()` records trajectory via `TrajectoryRecorder` | `opengui/agent.py` `start()`, `record_step()`, `finish()` calls; `tests/test_opengui_p2_integration.py::test_trajectory_recorded_on_run` |
| MEM-05 | Memory context formatted and injected into system prompt | `opengui/agent.py` `_retrieve_memory()` plus `build_system_prompt(..., memory_context=...)`; `tests/test_opengui_p2_memory.py` |
| SKILL-08 | Skill execution integrated into agent loop | `opengui/agent.py` `self._skill_executor.execute(skill)` branch; `tests/test_opengui_p2_integration.py::test_skill_path_chosen_above_threshold` |
| TRAJ-03 | Trajectory recording integrated into agent loop | `opengui/agent.py` phase changes and `record_step()`; `tests/test_opengui_p2_integration.py::test_trajectory_recorded_on_run` |
| TEST-05 | Full agent loop integration test with DryRunBackend + mock LLM + memory + skills | `tests/test_opengui_p2_integration.py::test_full_flow_with_mock_llm` |
</phase_requirements>

## Summary

The roadmap wording is stale, not the filesystem. `.planning/phases/02-agent-loop-integration/VERIFICATION.md` already exists, but it is a legacy, minimal report. It does not match the current verification standard used in Phases 4-6: it lacks observable truths, required artifacts, key-link verification, explicit re-verification framing, line-anchored evidence, and a live test run section. Phase 7 should therefore **rewrite the existing file in place** as a current-style re-verification report, not create a second artifact and not pretend the file is missing.

The code surface for the seven requirements is concentrated in `opengui/agent.py`. The main tests are already present in `tests/test_opengui_p2_integration.py` and `tests/test_opengui_p2_memory.py`. Phase 6 remains a dependency because it fixed the embedding-backed host wiring in `nanobot/agent/tools/gui.py`; that dependency is covered by `tests/test_opengui_p6_wiring.py`. A live targeted run on the current branch succeeded with `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q` and produced `15 passed, 3 warnings in 1.91s`.

One caveat matters for planning: the seven requirements are clearly satisfied at the `GuiAgent` contract level, but `nanobot/agent/tools/gui.py` currently passes `skill_library` into `GuiAgent` and does not pass `memory_retriever` or `skill_executor`. The Phase 7 verification should not silently expand scope into fixing that wrapper behavior; it should verify the Phase 2 contract honestly and record the wrapper caveat if needed.

**Primary recommendation:** Replace `.planning/phases/02-agent-loop-integration/VERIFICATION.md` with a current-style re-verification report that maps each of the seven requirements to exact code anchors, exact test node IDs, and a fresh targeted `uv run pytest` result.

## Evidence Surface

### Code Anchors

| File | Lines | Why It Matters |
|------|-------|----------------|
| `opengui/agent.py` | 191-215 | `run()` starts trajectory recording, retrieves memory, searches skills, switches to skill phase, and falls back to agent phase |
| `opengui/agent.py` | 251-255, 343-355 | `finish()` and `record_step()` prove trajectory integration |
| `opengui/agent.py` | 539-547 | `build_system_prompt(..., memory_context=memory_context)` is the prompt injection seam |
| `opengui/agent.py` | 756-785 | `_retrieve_memory()` formats memory context and always includes `POLICY` entries |
| `opengui/agent.py` | 787-801 | `_search_skill()` gates skill execution by relevance × confidence threshold |
| `nanobot/agent/tools/gui.py` | 45, 185-189 | Phase 6 dependency: embedding adapter is passed to `SkillLibrary` in the nanobot wrapper |
| `nanobot/agent/tools/gui.py` | 93-102 | Wrapper caveat: `GuiAgent` receives `skill_library`, but not `memory_retriever` or `skill_executor` |

### Test Anchors

| File | Node ID / Test | Requirements |
|------|----------------|--------------|
| `tests/test_opengui_p2_integration.py` | `test_memory_injected_into_system_prompt` | `AGENT-04`, `MEM-05` |
| `tests/test_opengui_p2_integration.py` | `test_skill_path_chosen_above_threshold` | `AGENT-05`, `SKILL-08` |
| `tests/test_opengui_p2_integration.py` | `test_free_explore_when_no_skill_match` | `AGENT-05` |
| `tests/test_opengui_p2_integration.py` | `test_trajectory_recorded_on_run` | `AGENT-06`, `TRAJ-03` |
| `tests/test_opengui_p2_integration.py` | `test_full_flow_with_mock_llm` | `TEST-05` plus end-to-end corroboration for the other six |
| `tests/test_opengui_p2_memory.py` | `test_policy_always_included` | `MEM-05` |
| `tests/test_opengui_p2_memory.py` | `test_memory_context_formatted_in_system_prompt` | `MEM-05`, `AGENT-04` |
| `tests/test_opengui_p6_wiring.py` | `test_gui_tool_wires_embedding_adapter_when_configured` | Phase 6 dependency evidence for skill-search reachability in the nanobot path |

### Artifact to Upgrade

| File | Current State | Planning Conclusion |
|------|---------------|--------------------|
| `.planning/phases/02-agent-loop-integration/VERIFICATION.md` | Exists, dated `2026-03-18`, legacy PASS table only | Rewrite in place to current verification standard |
| `.planning/ROADMAP.md` | Still says “Create the missing VERIFICATION.md for Phase 2” | Treat as stale wording; do not delete or duplicate the existing file |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `uv` | `0.9.16` | Stable test runner entrypoint in this repo | `pytest` is not available on bare `PATH`; `uv run pytest` works in the current environment |
| `pytest` | `9.0.2` | Verification framework | Already configured and used across the repo |
| `pytest-asyncio` | `1.3.0` | Async test support | Required for the async `GuiAgent` tests |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `numpy` | `>=1.26.0` | Fake embedding vectors in tests | Needed by the `_FakeEmbedder` helpers in Phase 2 and Phase 6 tests |
| `faiss-cpu` | `>=1.9.0` | Memory/skill retrieval indexing | Needed whenever the retrieval-backed tests execute real indexing paths |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `uv run pytest ...` | bare `pytest ...` | Reject: `pytest` is not installed on bare `PATH` in the current shell |
| Rewriting evidence from memory | Ad hoc manual inspection | Reject: Phase 7 needs exact line anchors and live command output |

**Installation / execution baseline:**

```bash
uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q
```

**Version verification:** Local environment confirmed `Python 3.12.12`, `pytest 9.0.2`, `pytest-asyncio 1.3.0`, and `uv 0.9.16` on 2026-03-19.

## Architecture Patterns

### Recommended Project Structure

```text
.planning/phases/02-agent-loop-integration/
├── 02-CONTEXT.md
├── 02-RESEARCH.md
├── 02-VALIDATION.md
└── VERIFICATION.md        # rewrite this file in place

opengui/
└── agent.py               # primary code evidence surface

tests/
├── test_opengui_p2_integration.py
├── test_opengui_p2_memory.py
└── test_opengui_p6_wiring.py
```

### Pattern 1: Re-verify the Existing Artifact

**What:** Treat Phase 7 as an in-place retrofit of Phase 2 verification, not as net-new deliverable creation.
**When to use:** When the roadmap says an artifact is missing but the file already exists.
**Example:**

```md
---
phase: 02-agent-loop-integration
verified: 2026-03-19T...
status: passed
score: 7/7 requirements verified
re_verification:
  previous_status: pass
  ...
---
```

### Pattern 2: Requirement-First Evidence Matrix

**What:** Give each requirement a single row with verdict, code anchor, test anchor, and any caveat.
**When to use:** Retroactive verification where implementation already exists.
**Example:**

```md
| AGENT-05 | VERIFIED | `opengui/agent.py:197-215,787-801` | `test_skill_path_chosen_above_threshold`; `test_free_explore_when_no_skill_match` | Verified at `GuiAgent` layer; wrapper caveat noted separately |
```

### Anti-Patterns to Avoid

- **Treating the roadmap text as authoritative over the filesystem:** the file exists; Phase 7 is a rewrite.
- **Using unrelated planner/router tests as proof for the seven target requirements:** `test_planner_decomposes_task` and router tests are not core evidence for this phase.
- **Overstating wrapper reachability:** `GuiSubagentTool` does not currently pass all optional Phase 2 collaborators into `GuiAgent`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Requirement evidence | New one-off inspection scripts | Existing Phase 2 and Phase 6 pytest coverage plus static code anchors | The evidence surface already exists and is stable |
| Test execution | Bare `pytest` shell assumptions | `uv run pytest ...` | Works in this environment; bare `pytest` does not |
| Contradiction handling | New file path or duplicate verification artifact | Rewrite `.planning/phases/02-agent-loop-integration/VERIFICATION.md` | Avoids split truth and matches success criteria |

**Key insight:** Phase 7 is documentation-grade verification, not implementation-grade feature work. The planner should spend effort on evidence quality, not on inventing new machinery.

## Common Pitfalls

### Pitfall 1: Misclassifying the Contradiction
**What goes wrong:** The plan assumes the verification file is absent and schedules creation of a second artifact.
**Why it happens:** The roadmap still says “missing VERIFICATION.md”.
**How to avoid:** Start the plan by explicitly recording that the file already exists and must be upgraded in place.
**Warning signs:** The draft plan mentions `02-VERIFICATION.md` or a new Phase 7 verification file.

### Pitfall 2: Verifying the Wrong Scope
**What goes wrong:** The report claims all host integrations exercise memory and skill execution.
**Why it happens:** The `GuiAgent` contract is correct, but wrapper call sites differ.
**How to avoid:** Verify the seven requirements at the `GuiAgent` layer and add a caveat for wrapper reachability.
**Warning signs:** Evidence cites `nanobot/agent/tools/gui.py` as the primary proof for `AGENT-04` or `SKILL-08`.

### Pitfall 3: Using the Wrong Test Entry Point
**What goes wrong:** Verification instructions tell someone to run `pytest`, which fails immediately.
**Why it happens:** `pytest` is not installed in the bare shell environment.
**How to avoid:** Standardize on `uv run pytest`.
**Warning signs:** `zsh: command not found: pytest`.

### Pitfall 4: Treating the Legacy Phase 2 Verification as Already Good Enough
**What goes wrong:** Phase 7 gets skipped because the old file has a PASS table.
**Why it happens:** The file exists and superficially covers the requirements.
**How to avoid:** Compare it to Phase 4-6 verification reports; it is materially less detailed and not in the current standard format.
**Warning signs:** No observable truths section, no required artifacts section, no live test run section.

## Code Examples

Verified patterns from the current codebase:

### Phase 2 Integration Seam

```python
# Source: opengui/agent.py
self._trajectory_recorder.start(phase=ExecutionPhase.AGENT)
memory_context = await self._retrieve_memory(task)
skill_match = await self._search_skill(task)

if skill_match is not None and self._skill_executor is not None:
    self._trajectory_recorder.set_phase(ExecutionPhase.SKILL, reason=...)
    skill_result = await self._skill_executor.execute(skill)
```

### Prompt Injection Seam

```python
# Source: opengui/agent.py
{
    "role": "system",
    "content": build_system_prompt(
        platform=self.backend.platform,
        coordinate_mode=self._coordinate_mode(),
        tool_definition=_COMPUTER_USE_TOOL,
        memory_context=memory_context,
        installed_apps=self._installed_apps,
    ),
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Legacy Phase 2 `VERIFICATION.md` with a single PASS table | Current verification format used in Phases 4-6 with observable truths, artifacts, links, and live test runs | By 2026-03-18 to 2026-03-19 verification docs | Phase 7 should rewrite the existing file to match the current standard |
| Assuming “artifact missing” from roadmap text | Filesystem-first verification of actual artifact state | Required now | Prevents duplicate docs and wrong planning scope |

**Deprecated/outdated:**

- Roadmap phrase “Create the missing VERIFICATION.md for Phase 2”: outdated, because the file already exists.
- Legacy Phase 2 verification style: outdated relative to current project verification standards.

## Open Questions

1. **Should the rewritten Phase 2 verification explicitly call out the nanobot wrapper caveat?**
   - What we know: `opengui/agent.py` satisfies the seven requirements and the targeted tests pass.
   - What's unclear: whether planners want Phase 7 to mention that `GuiSubagentTool.execute()` currently omits `memory_retriever` and `skill_executor`.
   - Recommendation: Yes. Keep the verdicts scoped to the `GuiAgent` contract, and record the wrapper caveat in a non-blocking note.

2. **Should the artifact path remain `VERIFICATION.md` instead of being renamed to `02-VERIFICATION.md`?**
   - What we know: success criteria explicitly name `.planning/phases/02-agent-loop-integration/VERIFICATION.md`.
   - What's unclear: whether the planner prefers naming consistency with later phases.
   - Recommendation: Keep `VERIFICATION.md` for Phase 2 and avoid path churn in Phase 7.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.2` + `pytest-asyncio 1.3.0` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q` |
| Full suite command | `uv run pytest tests/ -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AGENT-04 | Memory retrieval is injected into the `GuiAgent` system prompt | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_memory_injected_into_system_prompt -q` | ✅ |
| AGENT-05 | Agent chooses skill execution when match is above threshold and free explore when not | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_skill_path_chosen_above_threshold tests/test_opengui_p2_integration.py::test_free_explore_when_no_skill_match -q` | ✅ |
| AGENT-06 | Agent run emits trajectory metadata, steps, and result | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_trajectory_recorded_on_run -q` | ✅ |
| MEM-05 | `POLICY` memories are always included and formatted into prompt context | integration | `uv run pytest tests/test_opengui_p2_memory.py::test_policy_always_included tests/test_opengui_p2_memory.py::test_memory_context_formatted_in_system_prompt -q` | ✅ |
| SKILL-08 | Skill execution branch is integrated into the agent loop | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_skill_path_chosen_above_threshold -q` | ✅ |
| TRAJ-03 | Trajectory recording is integrated into the loop and produces JSONL events | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_trajectory_recorded_on_run -q` | ✅ |
| TEST-05 | Full DryRun + mock LLM + memory + skill flow passes end-to-end | integration | `uv run pytest tests/test_opengui_p2_integration.py::test_full_flow_with_mock_llm -q` | ✅ |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q`
- **Per wave merge:** `uv run pytest tests/ -q`
- **Phase gate:** Full suite green and rewritten `.planning/phases/02-agent-loop-integration/VERIFICATION.md` reviewed before `/gsd:verify-work`

### Wave 0 Gaps

None — the required test files already exist and pass. The only execution constraint is to use `uv run pytest`, not bare `pytest`.

## Sources

### Primary (HIGH confidence)

- `opengui/agent.py` - exact implementation of memory injection, skill search/execution gating, and trajectory recording
- `tests/test_opengui_p2_integration.py` - main requirement evidence for `AGENT-04`, `AGENT-05`, `AGENT-06`, `SKILL-08`, `TRAJ-03`, `TEST-05`
- `tests/test_opengui_p2_memory.py` - main requirement evidence for `MEM-05`
- `tests/test_opengui_p6_wiring.py` - dependency evidence that Phase 6 closed the embedding search seam
- `.planning/phases/02-agent-loop-integration/VERIFICATION.md` - existing artifact that must be rewritten in place
- `.planning/phases/04-desktop-backend/04-VERIFICATION.md` - current verification format reference
- `.planning/phases/05-cli-extensions/05-VERIFICATION.md` - current verification format reference
- `.planning/phases/06-fix-integration-wiring/06-VERIFICATION.md` - current verification format reference and Phase 6 dependency context
- `.planning/phases/02-agent-loop-integration/02-VALIDATION.md` - prior validation contract showing `uv run pytest` as the expected entrypoint
- `.planning/ROADMAP.md` - stale phase wording that created the contradiction
- `.planning/REQUIREMENTS.md` - official requirement IDs and phase traceability
- `.planning/STATE.md` - decision history confirming Phase 6 completion and dependency order
- `pyproject.toml` - pytest config and dev dependency declarations
- `nanobot/agent/tools/gui.py` - host wrapper dependency and caveat surface

### Secondary (MEDIUM confidence)

- Live command result on 2026-03-19: `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q` -> `15 passed, 3 warnings in 1.91s`

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - local tool versions and pytest config were read directly from the environment and repo
- Architecture: HIGH - contradiction resolved from local files, and the current verification standard is visible in Phases 4-6
- Pitfalls: HIGH - all major risks are grounded in concrete file/state mismatches observed in this workspace

**Research date:** 2026-03-19
**Valid until:** 2026-04-18
