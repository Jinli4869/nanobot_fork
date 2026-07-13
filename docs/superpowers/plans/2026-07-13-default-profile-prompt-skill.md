# Default Profile Prompt-Selected Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Top-K prompt-selected skills to the default profile's native `computer_use` contract.

**Architecture:** Build a conditional copy of the shared `computer_use` schema only when retrieval produced prompt-visible skill IDs. Pass the same compact prompt parts into the default message builder, then reuse the existing special-action dispatcher and `SkillExecutor` without changing retrieval or execution semantics.

**Tech Stack:** Python 3.11, dataclasses/dicts, pytest, Ruff.

---

### Task 1: Specify the default native skill contract

**Files:**
- Modify: `tests/test_guiclaw_profiles_strict.py`
- Modify: `tests/test_guiclaw.py`

- [ ] **Step 1: Add a failing prompt/schema test**

Create compact prompt parts with one retrieved skill, call `build_profile_messages("default", ...)`,
and assert that the system prompt includes the exact skill ID plus a `use_skill` action contract.

- [ ] **Step 2: Add a failing end-to-end test**

Adapt the existing `general_e2e` prompt-skill test to a native default response:

```python
LLMResponse(
    content="Action: Run the matching search skill",
    tool_calls=[
        ToolCall(
            id="skill-1",
            name="computer_use",
            arguments={
                "action_type": "use_skill",
                "skill_id": "shortcut:dl:dry:search",
                "arguments": {"query": "cats"},
                "intent": "Use the matching search shortcut",
                "summary": "A matching retrieved skill is available",
            },
        )
    ],
)
```

Assert that the LLM receives a tool enum containing `use_skill`, the prompt contains the listed
skill ID, and the fake executor receives the expected skill and arguments.

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```bash
uv run pytest tests/test_guiclaw_profiles_strict.py::test_default_prompt_includes_retrieved_skill_contract tests/test_guiclaw.py::test_default_prompt_skill_selection_dispatches_native_use_skill -q
```

Expected: failures because default currently drops `compact_prompt_parts` and the native schema
does not contain `use_skill`.

### Task 2: Add the conditional native schema

**Files:**
- Modify: `guiclaw/tool_schemas.py`
- Modify: `guiclaw/agent.py`
- Test: `tests/test_guiclaw_profiles_strict.py`

- [ ] **Step 1: Implement the schema builder**

Add `build_computer_use_tool(*, allow_use_skill: bool = False)` that returns
`COMPUTER_USE_TOOL` when false. When true, deep-copy the schema, append `use_skill` to the
action enum, and add:

```python
"skill_id": {
    "type": "string",
    "description": "Exact skill_id copied from the prompt-visible skill catalog.",
},
"arguments": {
    "type": "object",
    "description": "Arguments for the selected prompt-visible skill.",
},
```

- [ ] **Step 2: Select it from the agent**

Change `_build_tools_list()` to use
`build_computer_use_tool(allow_use_skill=bool(self._prompt_skills_by_id))` before appending
shortcut tools.

- [ ] **Step 3: Run the schema test**

Run:

```bash
uv run pytest tests/test_guiclaw_profiles_strict.py -q
```

Expected: the original default schema remains unchanged without skills; the new conditional
schema assertions pass after Task 3 completes.

### Task 3: Inject the catalog into the default prompt

**Files:**
- Modify: `guiclaw/agents/profiles.py`
- Test: `tests/test_guiclaw_profiles_strict.py`
- Test: `tests/test_guiclaw.py`

- [ ] **Step 1: Pass compact prompt parts to default**

Forward `compact_prompt_parts` from `build_profile_messages()` into `_build_default_messages()`.

- [ ] **Step 2: Use the conditional schema and catalog**

Build the prompt-side schema with
`allow_use_skill=bool(getattr(compact_prompt_parts, "skill_ids", ()))`. When
`compact_skill_instructions` is non-empty, append it as an `# Available Skills` system-prompt
section before the response format.

- [ ] **Step 3: Run the two RED tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_guiclaw_profiles_strict.py::test_default_prompt_includes_retrieved_skill_contract tests/test_guiclaw.py::test_default_prompt_skill_selection_dispatches_native_use_skill -q
```

Expected: `2 passed`.

### Task 4: Verify and synchronize

**Files:**
- Sync only files changed by Tasks 1-3 to `/Users/jinli/Documents/Personal/KnowAct/GUIClaw`

- [ ] **Step 1: Run source verification**

```bash
uv run pytest tests/test_guiclaw_profiles_strict.py tests/test_guiclaw_mobileworld_agents.py tests/test_guiclaw.py tests/test_guiclaw_p3_nanobot.py tests/test_guiclaw_p5_cli.py -q
uv run ruff check guiclaw/tool_schemas.py guiclaw/agent.py guiclaw/agents/profiles.py tests/test_guiclaw_profiles_strict.py tests/test_guiclaw.py
```

Expected: focused tests and Ruff pass.

- [ ] **Step 2: Content-sync the changed files**

Copy only `guiclaw/tool_schemas.py`, `guiclaw/agent.py`, `guiclaw/agents/profiles.py`,
`tests/test_guiclaw_profiles_strict.py`, and `tests/test_guiclaw.py`; do not transplant source
Git history.

- [ ] **Step 3: Verify target content and tests**

Hash-compare synchronized files, run the two new tests, then run the target's GUIClaw-focused
suite. Report target-only dependency failures separately from sync regressions.
