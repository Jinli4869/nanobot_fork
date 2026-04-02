# Phase 28: Shortcut Extraction Productionization - Research

**Researched:** 2026-04-03
**Domain:** Production trace-to-shortcut promotion on the existing OpenGUI shortcut architecture
**Confidence:** HIGH

## User Constraints

No phase-specific `28-CONTEXT.md` exists.

Locked constraints derived from `ROADMAP.md`, `REQUIREMENTS.md`, and `PROJECT.md`:

- Productionize the shipped `ShortcutSkill` / `ShortcutSkillStore` architecture instead of building a parallel shortcut system.
- Replace the legacy GUI post-run extraction path with trace-backed promotion into `ShortcutSkillStore`.
- Preserve existing CLI, nanobot, and background execution flows while Phase 28 lands.
- Keep v1.6 local-first: no Neo4j, Pinecone, OmniParser-first rewrite, or mandatory human review.
- Scope this phase to `SXTR-01` through `SXTR-04`; applicability routing belongs to Phase 29.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SXTR-01 | Successful GUI runs can promote shortcut candidates from trace step events only, excluding summary/result noise and malformed artifacts | Use `GuiSubagentTool._run_trajectory_postprocessing()` as the single production seam, but replace `_extract_skill()` with a trace loader that reads the `TrajectoryRecorder` JSONL, skips malformed lines, selects the final successful attempt window, and keeps only valid `type == "step"` rows. |
| SXTR-02 | Each promoted shortcut records normalized app/platform identifiers, reusable parameter slots, structured state conditions, and provenance back to the source trace | Extend `ShortcutSkill` with backward-compatible optional provenance/lineage fields and derive `task`, `platform`, and normalized `app` from `metadata` plus `step.observation.foreground_app`. |
| SXTR-03 | The promotion pipeline rejects brittle shortcuts using explicit gates for minimum usable steps, unsupported patterns, and low-quality evidence | Reuse `ExtractionPipeline`, but do not rely on its default always-pass critics. Add a production promotion service that enforces minimum step count, supported action types, readable screenshots, non-empty semantic targets, and attempt-window filtering before store writes. |
| SXTR-04 | Duplicate or near-duplicate shortcut candidates are merged, versioned, or rejected instead of being stored as repeated library entries | Add merge/version support to `ShortcutSkillStore` or a tightly coupled promotion helper, borrowing `SkillLibrary`'s conflict heuristics pattern while avoiding the legacy `Skill` schema and confidence counters. |
</phase_requirements>

## Summary

Phase 28 is a brownfield cutover, not a new extraction design. The live seam is `nanobot/agent/tools/gui.py`: after `GuiAgent.run()` returns, `_run_trajectory_postprocessing()` still summarizes the trajectory and then calls `_extract_skill()`, which instantiates the legacy `SkillExtractor` and writes into the legacy `SkillLibrary` via `add_or_merge()`. None of the Phase 26/27 shortcut promotion pieces are used in production today.

The shipped Phase 26/27 pieces are necessary but not sufficient for productionization. `ExtractionPipeline` can turn step dicts plus metadata into a `ShortcutSkill`, but it is not wired anywhere and its default critics always pass. More importantly, the current `TrajectoryRecorder` trace does not record `app` in the metadata event, and `ShortcutSkillProducer` falls back to `"Extracted from trajectory"` when task text is not present in step rows. A naive call to `ExtractionPipeline.run(steps, metadata)` from the current post-run seam would therefore produce shortcuts with weak descriptions, missing provenance, and no dedup/version behavior.

The main planning implication is that Phase 28 needs one new production adapter layer, not changes scattered across the host and executor stack. Keep `shortcut_extractor.py` as the pure Phase 26 primitive layer. Add a dedicated promotion service that: parses the recorder trace, extracts canonical metadata, applies hard gates, enriches the shortcut with provenance/lineage, and writes through `ShortcutSkillStore` with merge/version handling. Then cut `GuiSubagentTool` over to that service while leaving trajectory summarization and optional evaluation as sibling background tasks.

**Primary recommendation:** Add a dedicated `opengui/skills/shortcut_promotion.py` service and make `GuiSubagentTool._run_trajectory_postprocessing()` call it instead of the legacy `_extract_skill()` path.

## Standard Stack

### Core

| Library / Module | Version | Purpose | Why Standard |
|------------------|---------|---------|--------------|
| `nanobot/agent/tools/gui.py` | workspace current | Production post-run seam | Already owns trace resolution, background postprocessing, and optional evaluation |
| `opengui/trajectory/recorder.py` | workspace current | Canonical trace artifact contract | The recorder JSONL is the only trace format with `type`, `step_index`, `phase`, `observation`, and lifecycle events |
| `opengui/skills/shortcut_extractor.py` | workspace current | Step/trajectory gating primitives and `ShortcutSkill` production | Shipped in Phase 26; should remain the pure extraction core |
| `opengui/skills/shortcut.py` | workspace current | Canonical `ShortcutSkill` schema | Shipped in Phase 24; safest place for backward-compatible provenance/version fields |
| `opengui/skills/shortcut_store.py` | workspace current | Persistent shortcut store and search | Shipped in Phase 27; production promotion should write here, not to `SkillLibrary` |
| `opengui/skills/normalization.py` | workspace current | App/platform normalization and store-root resolution | Already normalizes Android/iOS app identifiers and defines the skill-store root |

### Supporting

| Library / Module | Version | Purpose | When to Use |
|------------------|---------|---------|-------------|
| `nanobot/utils/gui_evaluation.py` | workspace current | Robust line-by-line JSONL loading and step-row filtering pattern | Reuse or extract its malformed-line handling for trace ingestion |
| `opengui/skills/library.py` | workspace current | Conflict-detection and merge heuristic reference | Reuse the heuristic pattern only; do not reuse the legacy `Skill` store directly |
| `pytest` | `>=9.0.0,<10.0.0` | Unit and seam integration tests | Already configured in `pyproject.toml` |
| `pytest-asyncio` | `>=1.3.0,<2.0.0` | Async postprocessing and promotion tests | Already configured in `pyproject.toml` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New `shortcut_promotion.py` adapter | Extend `shortcut_extractor.py` directly | Extending `shortcut_extractor.py` mixes pure extraction primitives with trace parsing and store writes, increasing Phase 26 regression risk |
| Extend `ShortcutSkill` with optional provenance fields | Store a second metadata envelope beside each shortcut | A second envelope forces store/search changes everywhere; optional schema fields keep `ShortcutSkillStore` and `UnifiedSkillSearch` stable |
| Add merge/version behavior to `ShortcutSkillStore` | Reuse `SkillLibrary.add_or_merge()` directly | `SkillLibrary` is coupled to legacy `Skill`, precondition strings, and confidence counters; direct reuse would reintroduce the legacy path |

**Installation:**
```bash
uv sync --extra dev
```

No new dependencies are required for Phase 28.

## Architecture Patterns

### Recommended Project Structure

```text
nanobot/
└── agent/tools/gui.py                 # keep background scheduler; replace legacy extraction call

opengui/
└── skills/
    ├── shortcut_extractor.py          # keep pure pipeline primitives
    ├── shortcut_promotion.py          # NEW: trace loader + gates + provenance + store write
    ├── shortcut.py                    # extend with optional provenance/version fields
    ├── shortcut_store.py              # add merge/update/list helpers for promoted shortcuts
    └── normalization.py               # reuse app normalization

tests/
├── test_opengui_p28_shortcut_productionization.py
└── test_opengui_p8_trajectory.py      # extend existing postprocessing seam coverage
```

### Pattern 1: Separate the Production Adapter From the Pure Pipeline

**What:** Keep `ExtractionPipeline` as a pure `steps + metadata -> candidate` primitive and add a separate production service that handles trace parsing, metadata extraction, gates, and store writes.

**When to use:** Everywhere the live GUI path promotes shortcuts.

**Why:** `shortcut_extractor.py` currently knows nothing about JSONL artifacts, attempt windows, provenance, or persistence. That separation is good and should survive Phase 28.

**Example:**
```python
# Source: recommended adapter around the shipped Phase 26/27 primitives
rows = load_trace_rows(trace_path)
metadata, steps = extract_promotable_attempt(rows, trace_path=trace_path)
result = await pipeline.run(steps, metadata)
if isinstance(result, ExtractionSuccess):
    enriched = enrich_candidate(result.candidate, metadata)
    decision = await shortcut_store.add_or_merge(enriched)
```

### Pattern 2: Promote Only the Final Successful Attempt Window

**What:** Select the final successful attempt bounded by `attempt_start` / `attempt_result` events, then keep only valid `type == "step"` rows inside that window.

**When to use:** Every automatic promotion from `TrajectoryRecorder` output.

**Why:** The recorder contains `metadata`, `phase_change`, `memory_retrieval`, `attempt_start`, `attempt_result`, `retry`, `intervention_*`, `step`, and `result` rows in one file. A successful run may also contain failed-attempt steps from earlier retries.

**Canonical filter rules:**

- Read the recorder JSONL line-by-line and skip malformed JSON rows.
- Prefer the recorder trace chosen by `_resolve_trace_path()`; reject fallback files that do not contain recorder-style `type` rows.
- If `attempt_start` / `attempt_result` rows exist, choose the last `attempt_result` with `success == true` and keep only rows after its matching `attempt_start`.
- Inside that window, keep only rows where:
  - `row["type"] == "step"`
  - `row["phase"] == "agent"`
  - `row["action"]` is a dict with non-empty `action_type`
  - `row["model_output"]` is non-empty after trimming
  - `row["step_index"]` is present
- Drop `metadata`, `phase_change`, `memory_retrieval`, `attempt_*`, `retry`, `result`, and any malformed rows entirely.

**Example:**
```python
# Source: recorder event types in opengui/trajectory/recorder.py plus attempt events from opengui.agent
step_rows = [
    row for row in attempt_rows
    if row.get("type") == "step"
    and row.get("phase") == "agent"
    and isinstance(row.get("action"), dict)
    and str(row["action"].get("action_type", "")).strip()
    and str(row.get("model_output", "")).strip()
]
```

### Pattern 3: Lock the Metadata That Phase 29 Will Need

**What:** Persist promoted shortcuts with stable task/app/provenance metadata now, before Phase 29 retrieval and applicability routing depend on it.

**When to use:** During candidate enrichment, before store write.

**Recommended fields to lock in Phase 28:**

| Field | Source | Why Phase 28 Must Lock It |
|-------|--------|---------------------------|
| `app` | normalized consensus of `step.observation.foreground_app` via `normalize_app_identifier()` | Phase 29 retrieval needs current app/platform context |
| `platform` | `metadata.platform` from recorder start event | Phase 29 retrieval needs platform-scoped lookup |
| `description` | recorder `metadata.task` | `ShortcutSkillStore.search()` indexes `description`; current producer default is too generic |
| `tags` | task-derived tags plus normalized app alias if useful | Improves retrieval without changing store semantics |
| `parameter_slots` | `ShortcutSkillProducer` | Required by later grounding/binding |
| `preconditions` | `ShortcutSkillProducer` | Required by Phase 29 applicability checks and Phase 30 execution guards |
| `postconditions` | `ShortcutSkillProducer` | Required by later execution verification |
| `source_task` | recorder metadata task | Human/audit provenance and better search context |
| `source_trace_path` | relative path to the recorder trace | Stable backlink from shortcut to artifact |
| `source_run_id` | `trace_path.parent.name` | Stable run-level provenance that matches existing evaluation artifacts |
| `source_step_indices` | retained step indices after filtering | Needed to inspect exact source evidence |
| `source_foreground_app` | raw consensus foreground app before normalization | Useful for diagnostics when normalization collapses aliases |
| `promotion_version` | constant integer, start at `1` | Lets later code recognize the Phase 28 promotion contract |
| `shortcut_version` | per-skill lineage version, start at `1` | Satisfies `SXTR-04` without relying on file-envelope versioning |
| `supersedes_skill_id` / `merged_from_ids` | merge decision output | Gives operators lineage when duplicates are merged or replaced |
| `promoted_at` | current timestamp | Auditability and later health scoring |

**Recommendation:** Put these on `ShortcutSkill` as optional fields with defaults rather than inventing a second store envelope. `ShortcutSkillStore` already persists `ShortcutSkill.to_dict()` payloads directly.

### Pattern 4: Gate Unsupported or Low-Evidence Steps Before Store Write

**What:** Add a production step critic and trajectory critic that are stricter than Phase 26's test defaults.

**When to use:** Before any write to `ShortcutSkillStore`.

**Recommended default gates:**

- Reject candidates with fewer than 2 promotable steps.
- Reject any step whose `action_type` is in `{done, wait, screenshot, request_intervention}`.
- Reject candidates whose retained steps contain only coordinate-only actions with blank semantic `model_output`.
- Reject candidates when all retained steps resolve to `app == "unknown"`.
- Reject candidates when any retained step has a missing `screenshot_path` or unreadable screenshot file.
- Reject candidates when the final `result` event says `success == false`.

**Why:** `ExtractionPipeline` currently defaults to `_AlwaysPassStepCritic` and `_AlwaysPassTrajectoryCritic`, which is correct for Phase 26 primitives but not safe for automatic production promotion.

### Anti-Patterns to Avoid

- **Calling `SkillExtractor` and `ShortcutSkillStore` in parallel from the same post-run hook:** that creates two production meanings of a "promoted" skill.
- **Treating all `type == "step"` rows as one sequence across retries:** successful runs can contain failed-attempt steps.
- **Leaving `ShortcutSkill.description` at `"Extracted from trajectory"`:** the current shortcut store indexes `description`; generic descriptions will degrade search and dedup quality.
- **Depending on file-envelope `version: 1` as the shortcut lineage version:** that version is only the JSON file schema version from Phase 27, not the candidate lineage/version required by `SXTR-04`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| App normalization | Inline string munging in the promotion path | `normalize_app_identifier()` from `opengui/skills/normalization.py` | Already handles Android/iOS alias and identifier forms |
| Trace JSONL parsing | `read_text().splitlines()` with no malformed-line handling | Reuse the `load_traj_rows()` pattern from `nanobot/utils/gui_evaluation.py` or extract a shared helper | Current legacy extractor crashes on malformed JSON; evaluation already solved that |
| Shortcut persistence | A new DB or sidecar storage model | `ShortcutSkillStore` | Already versioned, persisted, and integrated with unified search |
| Dedup heuristics | Ad hoc string-equality checks | Adapt the conflict-detection pattern from `SkillLibrary` | Existing heuristics already combine name and action-sequence similarity |
| Runtime gating metadata | A new applicability schema | Existing `preconditions`, `postconditions`, and `parameter_slots` on `ShortcutSkill` | Phase 29/30 are already designed around these contracts |

**Key insight:** Phase 28 should not invent a new shortcut authoring system. It should make the current recorder artifacts and current shortcut schema/store trustworthy enough to be the only production promotion path.

## Common Pitfalls

### Pitfall 1: Using the Wrong Trace File

**What goes wrong:** Promotion reads the fallback `run_dir/trace.jsonl` attempt log instead of the recorder trace. That file uses `event`, not recorder-style `type`, so step extraction silently yields zero valid candidates or malformed metadata.

**Why it happens:** `_resolve_trace_path()` can fall back to an arbitrary `.jsonl` under the run directory when the recorder path is missing.

**How to avoid:** Accept only recorder-style rows with a `metadata` event and `type == "step"` records. If the fallback file lacks that shape, reject promotion instead of guessing.

**Warning signs:** Promotion reports "too few steps" on clearly successful runs or sees rows with `event == "step"` but no `type`.

### Pitfall 2: Promoting Steps From Earlier Failed Attempts

**What goes wrong:** The shortcut contains a mix of failed-attempt steps and final-attempt steps from one trace, producing brittle or contradictory sequences.

**Why it happens:** `GuiAgent` logs attempt lifecycle events into the same recorder trace across retries.

**How to avoid:** Slice to the final successful attempt window before filtering step rows.

**Warning signs:** Promoted step indices are not contiguous near the end of the trace, or the trace contains `retry` / earlier `attempt_result(success=false)` before the retained steps.

### Pitfall 3: Missing App and Task Metadata in the Produced Shortcut

**What goes wrong:** The promoted shortcut gets `app="unknown"` and `description="Extracted from trajectory"`, making later retrieval weak and provenance poor.

**Why it happens:** Recorder metadata stores `task` and `platform`, but not `app`; `ShortcutSkillProducer._build_description()` only looks inside step rows.

**How to avoid:** Promote through an adapter that passes task/app metadata explicitly and enriches the produced `ShortcutSkill` before persisting.

**Warning signs:** Stored shortcuts all share generic descriptions or `unknown` app identifiers.

### Pitfall 4: Assuming Phase 26 Critics Are Production-Safe

**What goes wrong:** Low-value candidates are promoted because the default critics in `ExtractionPipeline` always pass.

**Why it happens:** Phase 26 intentionally shipped testable primitives, not production policy.

**How to avoid:** Add real Phase 28 critics or gate helpers and never instantiate the pipeline without them in the production path.

**Warning signs:** The production code constructs `ExtractionPipeline()` with no arguments.

### Pitfall 5: Adding Duplicate Shortcuts Because the Store Has No Merge API

**What goes wrong:** Every successful run adds another near-identical shortcut because `ShortcutSkillStore` currently only has `add`, `remove`, and `get`.

**Why it happens:** Phase 27 scoped the store to persistence/search, not promotion lifecycle.

**How to avoid:** Add `list_all` + `update` + `add_or_merge` style support to `ShortcutSkillStore`, or colocate equivalent logic in a promotion service that can update the store atomically.

**Warning signs:** `shortcut_skills.json` grows quickly with the same name/app/action signature repeated.

## Code Examples

Verified patterns from repo sources:

### Current Production Post-Run Seam
```python
# Source: nanobot/agent/tools/gui.py
async def _run_trajectory_postprocessing(self, trace_path, is_success, skill_library, task):
    trajectory_summary = await self._summarize_trajectory(trace_path)
    if trajectory_summary:
        logger.info("Trajectory summary: %s", trajectory_summary[:200])
    await self._extract_skill(trace_path, is_success, skill_library)
    await self._maybe_run_evaluation(task=task, trace_path=trace_path, is_success=is_success)
```

### Recorder Event Types That Must Be Filtered
```python
# Source: opengui/trajectory/recorder.py
self._write_event({"type": "metadata", ...})
self._write_event({"type": "phase_change", ...})
self._write_event({"type": event_type, ...})  # memory_retrieval, attempt_start, attempt_result, retry, ...

event = {
    "type": "step",
    "step_index": self._step_count,
    "phase": (phase or self._current_phase).value,
    "action": action,
    "model_output": model_output,
    "screenshot_path": screenshot_path,
    "observation": observation,
}

self._write_event({"type": "result", "success": success, ...})
```

### Current Phase 26 Pipeline Entry
```python
# Source: opengui/skills/shortcut_extractor.py
result = await pipeline.run(
    steps,
    {"app": "com.example.app", "platform": "android", "success": True},
)
```

### Existing Step-Only Filtering Pattern Worth Reusing
```python
# Source: nanobot/utils/gui_evaluation.py
def load_traj_rows(traj_path: Path) -> list[dict[str, Any]]:
    rows = []
    with traj_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows

def filter_step_rows(traj_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in traj_rows if row.get("type") == "step"]
```

### Store/Search Fields That Must Not Regress
```python
# Source: opengui/skills/shortcut_store.py
parts = [skill.name, skill.description, skill.app, skill.platform]
parts.extend(skill.tags)
parts.extend(slot.name for slot in skill.parameter_slots)
parts.extend(state.value for state in skill.preconditions)
parts.extend(state.value for state in skill.postconditions)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `GuiSubagentTool` post-run calls legacy `SkillExtractor` and writes to `SkillLibrary` | Phase 28 should call a trace-backed shortcut promotion service and write to `ShortcutSkillStore` | v1.6 Phase 28 | Closes the main production gap |
| Legacy extraction filters `type == "step"` but ignores malformed JSON, retry boundaries, provenance, and shortcut schema | Shipped Phase 26 pipeline plus Phase 28 adapter/service | v1.5 Phase 26, hardened in v1.6 Phase 28 | Enables trustworthy shortcut promotion |
| `ShortcutSkillStore` is only file-versioned (`version: 1` envelope) | Phase 28 must add per-shortcut lineage/version semantics | v1.5 Phase 27 -> v1.6 Phase 28 | Needed for `SXTR-04` |

**Deprecated/outdated:**

- `nanobot/agent/tools/gui.py::_extract_skill()` as the production promotion path.
- `SkillLibrary.add_or_merge()` as the target write path for newly promoted shortcuts.
- Treating `ShortcutSkillStore`'s file-envelope version as equivalent to shortcut lineage/version.

## Open Questions

1. **Where should provenance and lineage live?**
   - What we know: `ShortcutSkillStore` persists raw `ShortcutSkill.to_dict()` payloads and search reads `ShortcutSkill` objects directly.
   - What's unclear: Whether to extend `ShortcutSkill` or introduce a second entry envelope.
   - Recommendation: Extend `ShortcutSkill` with optional provenance/version fields. It is the lowest-risk path and preserves store/search behavior.

2. **Should merge behavior be a store method or a promotion-service responsibility?**
   - What we know: `ShortcutSkillStore` has no `update`, `list_all`, or `add_or_merge`.
   - What's unclear: Whether the repo wants merge policy owned by the store or by a higher-level promotion service.
   - Recommendation: Put conflict detection and decision logic in the promotion service, and add only minimal `list_all` / `update` helpers to `ShortcutSkillStore`.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest >=9.0.0,<10.0.0` + `pytest-asyncio >=1.3.0,<2.0.0` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p8_trajectory.py -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SXTR-01 | Mixed recorder traces promote only final-attempt `type == "step"` rows; malformed JSON, `metadata`, `phase_change`, `attempt_*`, `memory_retrieval`, and `result` rows are ignored | unit | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py -q -k step_filter` | ❌ Wave 0 |
| SXTR-02 | Promoted shortcut stores normalized `app`/`platform`, parameter slots, structured conditions, and provenance fields (`source_task`, `source_trace_path`, `source_step_indices`, `source_run_id`) | unit | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py -q -k provenance` | ❌ Wave 0 |
| SXTR-03 | Promotion rejects too-few-step traces, unsupported action patterns, missing screenshots, unknown app identity, and low-quality semantic targets | unit | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py -q -k gates` | ❌ Wave 0 |
| SXTR-04 | Near-duplicate promoted shortcuts merge, version, or reject without growing `shortcut_skills.json` into repeated entries; search still returns stable results | unit | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p27_storage_search_agent.py -q -k merge` | ❌ Wave 0 |
| Seam lock | `GuiSubagentTool._run_trajectory_postprocessing()` writes to the new shortcut path and no longer calls the legacy extractor | integration | `uv run pytest tests/test_opengui_p8_trajectory.py -q -k postprocessing` | ✅ existing |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p8_trajectory.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p8_trajectory.py tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p27_storage_search_agent.py -q`
- **Phase gate:** `uv run pytest -q`

### Wave 0 Gaps

- [ ] `opengui/skills/shortcut_promotion.py` — trace loader, metadata extraction, production critics/gates, provenance enrichment, merge/version decision
- [ ] `tests/test_opengui_p28_shortcut_productionization.py` — new unit coverage for `SXTR-01..04`
- [ ] Extend `tests/test_opengui_p8_trajectory.py` — assert post-run cutover uses shortcut promotion instead of the legacy extractor
- [ ] Extend `tests/test_opengui_p27_storage_search_agent.py` or add focused store tests — ensure new provenance/version fields round-trip through `ShortcutSkillStore`
- [ ] Extend `opengui/skills/shortcut.py` round-trip coverage — prove optional provenance/version fields remain backward-compatible

## Plan Split Recommendation

### `28-01-PLAN.md` - Cut over GUI postprocessing from legacy extraction to the new shortcut promotion pipeline

Scope:

- Add `shortcut_promotion.py` with robust trace loading and final-attempt step filtering.
- Wire `GuiSubagentTool._run_trajectory_postprocessing()` to the new promotion service.
- Keep summarization and evaluation as sibling background tasks.
- Do not add merge/version complexity here beyond a temporary direct add path that is clearly isolated behind the new service boundary.

Why this is low-coupling:

- Touches only the live seam plus the new adapter module.
- Leaves schema/store evolution for plan 02.
- Gives Phase 28 a single production entrypoint early.

### `28-02-PLAN.md` - Add provenance, gating, and merge/version handling for promoted shortcuts

Scope:

- Extend `ShortcutSkill` with optional provenance/lineage fields.
- Add stricter production critics and quality gates.
- Add `ShortcutSkillStore` helpers or promotion-service logic for merge/version/reject decisions.
- Preserve `ShortcutSkillStore.search()` semantics and file format compatibility.

Why this is low-coupling:

- Isolated to the shortcut model/store/promotion service.
- No host-entrypoint changes beyond the cutover already made in plan 01.
- Produces the stable metadata contract Phase 29 will consume.

### `28-03-PLAN.md` - Lock the productionized extraction path with focused regression coverage

Scope:

- Add dedicated Phase 28 unit tests.
- Extend the existing postprocessing seam tests in `tests/test_opengui_p8_trajectory.py`.
- Add regression cases for malformed traces, noise rows, low-quality candidates, and duplicate promotions.

Why this is low-coupling:

- Pure verification wave.
- Protects both the new promotion service and the existing Phase 26/27 contracts.
- Gives the planner a clean validation target for `VALIDATION.md`.

## Sources

### Primary (HIGH confidence)

- `.planning/ROADMAP.md` — Phase 28 goal, success criteria, and three-plan split
- `.planning/REQUIREMENTS.md` — `SXTR-01..04`
- `.planning/PROJECT.md` — v1.6 production-gap framing and milestone constraints
- `nanobot/agent/tools/gui.py` — current production seam, trace resolution, background postprocessing, legacy `_extract_skill()` path
- `opengui/trajectory/recorder.py` — canonical recorder event types and metadata/step/result contract
- `opengui/skills/shortcut_extractor.py` — shipped Phase 26 primitives and current gaps
- `opengui/skills/shortcut.py` — current `ShortcutSkill` schema and missing provenance/version fields
- `opengui/skills/shortcut_store.py` — store/search behavior and current lack of merge/update helpers
- `opengui/skills/library.py` — merge/conflict heuristic reference
- `opengui/skills/normalization.py` — app normalization and store-root helpers
- `nanobot/utils/gui_evaluation.py` — robust malformed-line handling and step-only filtering pattern
- `tests/test_opengui_p8_trajectory.py` — existing post-run seam coverage
- `tests/test_opengui_p26_quality_gated_extraction.py` — current extraction-pipeline contract tests
- `tests/test_opengui_p27_storage_search_agent.py` — current store/search contract tests

### Secondary (MEDIUM confidence)

- `.planning/research/SUMMARY.md` — milestone-level v1.6 framing
- `.planning/research/ARCHITECTURE.md` — milestone-level architecture direction
- `.planning/research/STACK.md` — milestone-level stack direction
- `.planning/research/PITFALLS.md` — milestone-level risk framing

### Tertiary (LOW confidence)

- None

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - all recommendations are grounded in shipped repo modules and current tests
- Architecture: HIGH - the production seam and the missing adapter layer are directly visible in current code
- Pitfalls: HIGH - each pitfall maps to concrete current code behavior or an explicit gap in the shipped schema/store path

**Research date:** 2026-04-03
**Valid until:** 2026-05-03
