# GUIClaw Online Skill and Memory Induction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically induce compact GUI skills and GUI memory after configured `gui_task` runs without requiring users to invoke offline scripts.

**Architecture:** Extend the existing `PostRunProcessor` with an independent memory branch and make its skill branch use shared compact-induction helpers. Move reusable script logic into the packaged `guiclaw` namespace, keep both scripts as offline CLI entry points, and preserve one run directory with per-subtask result sections.

**Tech Stack:** Python 3.11, Pydantic v2, asyncio, pytest/pytest-asyncio, Ruff, Hatch/uv.

---

### Task 1: Configuration and Wiring

**Files:**
- Modify: `nanobot/config/schema.py`
- Modify: `nanobot/agent/tools/gui.py`
- Modify: `tests/test_gui_skill_executor_wiring.py`

- [ ] **Step 1: Write failing configuration tests**

Add tests asserting that `GuiConfig().enable_memory_extraction` is false and
that `GuiConfig.model_validate({"enableMemoryExtraction": True})` enables it.
Add a wiring assertion that `GuiSubagentTool` passes the value to
`PostRunProcessor`.

- [ ] **Step 2: Run tests and verify the missing field fails**

Run:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_gui_skill_executor_wiring.py -q
```

Expected: failure because `enable_memory_extraction` is not defined or wired.

- [ ] **Step 3: Add the minimal configuration field and constructor argument**

Add to `GuiConfig`:

```python
enable_memory_extraction: bool = False
```

Pass `gui_config.enable_memory_extraction` into `PostRunProcessor` alongside
`enable_skill_extraction`.

- [ ] **Step 4: Re-run the focused tests**

Expected: the new configuration and wiring tests pass.

### Task 2: Shared Compact-Skill Induction

**Files:**
- Create: `guiclaw/skills/induction.py`
- Modify: `guiclaw/postprocessing.py`
- Modify: `scripts/induce_compact_skills.py`
- Modify: `tests/test_induce_compact_skills.py`
- Modify: `tests/test_guiclaw_p1_skills.py`

- [ ] **Step 1: Write failing production-helper tests**

Test that the production helper:

```python
candidate = compactify_skill(skill, max_steps=7, max_scroll_steps=1, is_success=True)
assert candidate is not None
assert candidate.tags == ("compact", "compact_extracted")
assert candidate.success_count == 1
```

Also test step limits, scroll limits, non-leading `open_app`, failed terminal
actions, and `is_success=False` preserving `success_count == 0`.

- [ ] **Step 2: Run tests and verify import/behavior failures**

Run:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_induce_compact_skills.py tests/test_guiclaw_p1_skills.py -q
```

Expected: failure because `guiclaw.skills.induction` and online compact behavior
do not exist.

- [ ] **Step 3: Implement packaged compact helpers**

Create focused helpers:

```python
def compactify_skill(
    skill: Skill,
    *,
    max_steps: int = 7,
    max_scroll_steps: int = 1,
    is_success: bool,
) -> Skill | None:
    steps = tuple(skill.steps)
    if not 2 <= len(steps) <= max_steps:
        return None
    scroll_count = 0
    for index, step in enumerate(steps):
        action_type = normalize_action_type(step.action_type)
        if action_type == "open_app" and index != 0:
            return None
        if action_type in {"scroll", "swipe", "drag"}:
            scroll_count += 1
            if scroll_count > max_scroll_steps:
                return None
    if not is_success and has_terminal_action(skill):
        return None
    return replace(
        skill,
        skill_id=f"compact:{skill.app}:{skill.name}",
        tags=("compact", "compact_extracted"),
        success_count=1 if is_success else 0,
    )

async def induce_compact_skills_from_trace(
    extractor: SkillExtractor,
    trace_path: Path,
    *,
    is_success: bool,
    subtask_index: int = 1,
) -> list[Skill]:
    result = codegen_trajectory(trace_path, subtask_index=subtask_index)
    if result is None or not result.steps:
        return []
    skills = await extractor.extract_from_codegen_result_multi(result, is_success=is_success)
    return [
        candidate
        for skill in skills
        if (candidate := compactify_skill(skill, is_success=is_success)) is not None
    ]
```

The trace helper must call `codegen_trajectory()` followed by
`extract_from_codegen_result_multi()` so single-app runs are eligible.

- [ ] **Step 4: Replace online extraction and remove script duplication**

Change `PostRunProcessor._extract_skill()` to call the shared trace helper.
Change `scripts/induce_compact_skills.py` to import the shared policy and retain
only batch discovery, clustering, CLI filtering, and output handling.

- [ ] **Step 5: Re-run compact and postprocessor tests**

Expected: all focused tests pass and successful online skills carry compact tags
and one support count.

### Task 3: Packaged GUI-Memory Induction

**Files:**
- Create: `guiclaw/memory/induction.py`
- Modify: `scripts/induce_gui_memory.py`
- Modify: `tests/test_induce_gui_memory.py`
- Modify: `tests/test_gui_memory_item.py`

- [ ] **Step 1: Write failing tests against the packaged API**

Move imports in focused tests to `guiclaw.memory.induction` and add an LLM test:

```python
items = await induce_memory_items(
    llm=scripted_llm,
    trajectory_text="Task: open settings",
    task_outcome="success",
    app="Settings",
)
assert items[0].app == "Settings"
```

Test `append_to_memory_bank()` returns both added and duplicate counts through a
small result type used by the online path, while the CLI wrapper still reports
the added count.

- [ ] **Step 2: Run tests and verify the packaged module is missing**

Run:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_induce_gui_memory.py tests/test_gui_memory_item.py -q
```

Expected: failure importing `guiclaw.memory.induction`.

- [ ] **Step 3: Move reusable behavior into the packaged module**

Move trajectory formatting, prompt constants, response parsing, trace
outcome/app helpers, abnormal filtering, bank loading, and deduplication into
`guiclaw/memory/induction.py`. Implement the LLM call through the existing
`LLMProvider.chat()` interface:

```python
response = await llm.chat([
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": trajectory_text},
], max_tokens=2048)
```

- [ ] **Step 4: Make the script a consumer of packaged helpers**

Retain script-only CLI parsing, OpenAI-compatible adapter, task-directory
discovery, dry-run display, per-task budgeting, and custom output flags. Import
all reusable behavior from `guiclaw.memory.induction`.

- [ ] **Step 5: Re-run memory tests**

Expected: packaged API and the offline script both pass their existing behavior
tests.

### Task 4: Independent Memory Post-Run Branch

**Files:**
- Modify: `guiclaw/postprocessing.py`
- Modify: `tests/test_guiclaw_p1_skills.py`
- Modify: `tests/test_guiclaw_p3_nanobot.py`

- [ ] **Step 1: Write failing post-run tests**

Cover these observable behaviors:

- disabled memory extraction makes no memory LLM call;
- an eligible subtask writes memory and a compact `memory_extraction` result;
- short and abnormal trajectories are skipped;
- memory extraction still runs when evolution returns early;
- two routed subtasks pass distinct `subtask_index` values and share one bank.

- [ ] **Step 2: Run tests and verify missing branch failures**

Run:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_guiclaw_p1_skills.py tests/test_guiclaw_p3_nanobot.py -q
```

Expected: failure because `PostRunProcessor` has no memory switch or branch.

- [ ] **Step 3: Implement the independent background branch**

Extend the constructor with:

```python
enable_memory_extraction: bool = False,
memory_bank_path: Path | None = None,
```

Default the bank to `~/.guiclaw/memory/gui_memory_bank.jsonl`. Schedule memory
induction independently from evolution/extraction, guard writes with a bank lock,
and call `_write_result_section` with section name `memory_extraction` and a
payload containing only status, reason, added count, and duplicate count.

- [ ] **Step 4: Re-run post-run and router tests**

Expected: all focused tests pass and the existing single `traj.json` /
`result.json` layout remains unchanged.

### Task 5: Documentation and Static Checks

**Files:**
- Modify: `guiclaw/README.md`
- Modify: `guiclaw/README_CN.md`

- [ ] **Step 1: Document the new opt-in switch**

Add `enableMemoryExtraction` to configuration examples and tables, state that it
uses the configured GUI model/provider, and document the bank location.

- [ ] **Step 2: Run Ruff and focused tests**

Run:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run ruff check guiclaw nanobot/config/schema.py nanobot/agent/tools/gui.py scripts/induce_compact_skills.py scripts/induce_gui_memory.py tests/test_induce_compact_skills.py tests/test_induce_gui_memory.py tests/test_gui_skill_executor_wiring.py
UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_induce_compact_skills.py tests/test_induce_gui_memory.py tests/test_gui_memory_item.py tests/test_gui_skill_executor_wiring.py tests/test_guiclaw_p1_skills.py tests/test_guiclaw_p3_nanobot.py -q
```

Expected: Ruff exits zero and the focused suite has zero failures.

### Task 6: Regression Verification and Repository Sync

**Files:**
- Synchronize the completed source changes into: `/Users/jinli/Documents/Personal/KnowAct/GUIClaw`

- [ ] **Step 1: Run broader GUIClaw regression tests**

Run:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_guiclaw*.py tests/test_gui*.py tests/test_induce*.py -q
```

Expected: zero failures.

- [ ] **Step 2: Inspect source and target repository state**

Verify both repositories' current branches and dirty files. Do not overwrite
unrelated target changes.

- [ ] **Step 3: Synchronize only the implementation scope**

Copy the changed production files, scripts, tests, and English/Chinese README
files into the matching target paths. Preserve the target `.git`, upstream
configuration, and unrelated repository-specific files.

- [ ] **Step 4: Verify the target repository**

Run Ruff and the same focused pytest set from the target checkout. Compare the
source and target versions of every synchronized file with `cmp` or checksums.

- [ ] **Step 5: Report exact results**

Report changed functions/fields, source and target verification commands and
counts, any pre-existing dirty files left untouched, and whether commits were
created.
