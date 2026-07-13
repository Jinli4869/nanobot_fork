# GUIClaw Online Skill and Memory Induction Design

## Goal

Make compact-skill and GUI-memory induction automatic after a `gui_task` run so
installed users do not need to run `scripts/induce_compact_skills.py` or
`scripts/induce_gui_memory.py` manually.

The change must remain opt-in, reuse the existing post-run lifecycle, preserve
the single-run artifact layout, and work for both direct GUI tasks and routed
multi-subtask workflows.

## Current State

`GuiConfig.enable_skill_extraction` already enables background extraction in
`PostRunProcessor`. The current online path uses
`SkillExtractor.extract_from_file_multi()` and `FlatSkillLibrary.add_or_merge()`.
It is not equivalent to the compact-skill script:

- single-foreground-app traces are skipped by the online file entry point;
- the compact step and scroll envelope is not applied;
- extracted skills do not receive the `compact` and `compact_extracted` tags;
- successful online observations start with `success_count == 0` rather than
  contributing support.

GUI-memory induction currently exists only in `scripts/induce_gui_memory.py`.
The runtime retriever already reads
`~/.guiclaw/memory/gui_memory_bank.jsonl`, but no post-run path writes it.

The project wheel includes `nanobot/` and `guiclaw/`, but excludes `scripts/`.
Production code therefore cannot import either script.

## Configuration Contract

Keep the existing skill switch and add one independent memory switch:

```json
{
  "gui": {
    "enableSkillExtraction": true,
    "enableMemoryExtraction": true
  }
}
```

The Python fields are:

```python
enable_skill_extraction: bool = False
enable_memory_extraction: bool = False
```

Both remain disabled by default. Memory induction reuses the configured GUI
model and provider through `NanobotLLMAdapter`; it does not add API-key, model,
temperature, threshold, or path settings.

## Architecture

### Shared post-run lifecycle

`GuiSubagentTool` continues to own one `PostRunProcessor`. It passes both
configuration booleans to that processor. No second scheduler, subprocess, or
script invocation is introduced.

For each recorded subtask, post-processing performs these independent jobs:

1. trajectory summary and optional evaluation;
2. GUI-memory induction when `enable_memory_extraction` is true;
3. failed reused-skill evolution, or compact-skill extraction when
   `enable_skill_extraction` is true.

Memory induction is independent of the evolution branch. A failed reused skill
may be evolved while the same subtask still contributes a failure memory.

### Compact-skill extraction

Move the reusable compact policy out of the CLI script and into the production
skills package. The online path will:

- code-generate the selected subtask directly, including single-app traces;
- reuse `SkillExtractor.extract_from_codegen_result_multi()`;
- accept only skills with 2 through 7 steps;
- allow at most one `scroll`, `swipe`, or `drag` step;
- reject `open_app` outside the first position;
- retain the failed-trajectory terminal-action safety check;
- assign `compact` and `compact_extracted` tags;
- contribute `success_count=1` for a successful source and zero for a failed
  prefix source;
- store results through the existing `FlatSkillLibrary.add_or_merge()` path.

`FlatSkillLibrary` remains the online clustering and conflict-resolution layer.
This avoids maintaining an additional batch accumulator during a long-running
gateway process. The offline script retains its cross-directory clustering and
minimum-support CLI features, but imports the shared compact policy rather than
duplicating it.

The existing evolution-first rule is preserved: a qualifying failed
`skill_execution_result` evolves that reused skill and suppresses ordinary
skill extraction for that subtask.

### GUI-memory induction

Move the reusable memory-induction implementation into
`guiclaw/memory/induction.py`. It owns:

- compact trajectory formatting;
- success and failure prompts;
- `GuiMemoryItem` response parsing;
- abnormal and short-trajectory filtering;
- app resolution;
- same-app Jaccard duplicate detection;
- locked append to `~/.guiclaw/memory/gui_memory_bank.jsonl`.

The production inducer accepts the existing GUIClaw `LLMProvider` interface and
calls `chat()` with the current GUI model. The CLI script may keep its
OpenAI-compatible adapter, but it passes that adapter into the same production
inducer.

An eligible subtask must have more than two recorded steps and must not be an
abnormal zero-progress termination. It may produce at most three parsed memory
items. Existing same-app items and duplicates created concurrently by sibling
subtasks are skipped.

### Routed multi-subtask runs

The current run boundary is retained:

- one router invocation creates one run directory;
- the run directory contains one `traj.json` and one `result.json`;
- `PostRunProcessor.schedule()` is called once for each subtask index;
- each extraction reads only that subtask from the shared trajectory;
- skill and memory stores are shared and protected by their respective locks.

No router-level duplicate extraction is added after the per-subtask jobs.

## Result Recording

Keep learned content in the canonical stores rather than copying it into run
artifacts. `result.json` records only compact diagnostics per subtask.

The existing `extraction` and `evolution` sections remain. Memory induction adds
a `memory_extraction` section containing only fields needed to understand the
outcome, such as:

```json
{
  "status": "processed",
  "added_count": 2,
  "duplicate_count": 1
}
```

Skipped and error results contain a short `status` and `reason`. Full prompts,
model responses, memory bodies, and duplicate token-usage records are not added
to `result.json` or `traj.json`.

## Failure Handling

Both induction paths remain background best-effort operations:

- extraction failures are logged and summarized in `result.json`;
- they do not change the already returned GUI task result;
- a memory failure does not suppress skill evolution or extraction;
- a skill failure does not suppress memory induction;
- malformed model output produces zero stored items rather than a partial file;
- locked writes prevent sibling subtasks from interleaving JSONL records.

## Script Boundary

The two scripts remain supported offline entry points:

- `scripts/induce_compact_skills.py` keeps batch discovery, dry-run output,
  filtering flags, clustering, and output selection;
- `scripts/induce_gui_memory.py` keeps batch discovery, dry-run output, CLI model
  settings, item budgeting, and custom bank selection.

Reusable production behavior is imported from `guiclaw/`; installed runtime
code never imports from `scripts/`.

## Verification

Focused tests will cover:

- `GuiConfig` default, snake_case field, and `enableMemoryExtraction` alias;
- disabled memory induction making no LLM call or file write;
- an eligible success subtask appending deduplicated memory;
- failure-memory extraction and abnormal/short-run skips;
- memory extraction continuing when evolution consumes the skill branch;
- routed subtasks reading their own indices and writing one shared bank safely;
- single-app online compact-skill extraction;
- compact step/scroll/terminal-action filters, tags, and `success_count`;
- scripts using the shared production helpers;
- compact `result.json` status sections without prompt or response payloads.

After focused tests, Ruff will run on touched Python files and the broader
GUIClaw test subset will verify post-run, router, skill, memory, and configuration
contracts.

## Non-Goals

- No migration or compatibility alias for an `enable_extract` field that does
  not currently exist.
- No automatic enabling of skill execution or prompt skill selection.
- No new model/provider configuration for induction.
- No new JSON/JSONL artifact outside the existing stores and `result.json`.
- No synchronous wait before returning the GUI task result.
- No removal of either offline induction script.
