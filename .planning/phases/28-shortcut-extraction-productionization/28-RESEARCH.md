# Phase 28: Shortcut Extraction Productionization - Research

**Researched:** 2026-04-03
**Domain:** Production promotion of trace-derived shortcuts into the v1.5 shortcut store
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SXTR-01 | Successful GUI runs can promote shortcut candidates from trace step events only, excluding summary/result noise and malformed artifacts. | `TrajectoryRecorder` already emits typed JSONL events (`metadata`, `phase_change`, `step`, `result`). The current legacy path still reads the whole trace through `SkillExtractor.extract_from_file()` in [`opengui/skills/extractor.py`](../../../../opengui/skills/extractor.py), but Phase 28 can cut over to a promotion pipeline that explicitly filters `type == "step"` and rejects malformed or underspecified events before extraction. |
| SXTR-02 | Each promoted shortcut records normalized app/platform identifiers, reusable parameter slots, structured state conditions, and provenance back to the source trace. | `ShortcutSkillProducer` in [`opengui/skills/shortcut_extractor.py`](../../../../opengui/skills/shortcut_extractor.py) already normalizes app IDs and produces `parameter_slots`, `preconditions`, and `postconditions`, but there is no provenance field yet in [`opengui/skills/shortcut.py`](../../../../opengui/skills/shortcut.py). Phase 28 must add backward-compatible provenance metadata to the shortcut schema or an adjacent promotion envelope. |
| SXTR-03 | The promotion pipeline rejects brittle shortcuts using explicit gates for minimum usable steps, unsupported patterns, and low-quality evidence. | `ExtractionPipeline` already rejects trajectories with fewer than two steps and exposes structured rejection results, but the default critics are always-pass. Phase 28 needs real gating at the promotion seam for unsupported action patterns, low-signal steps, and traces that do not provide stable state evidence. |
| SXTR-04 | Duplicate or near-duplicate shortcut candidates are merged, versioned, or rejected instead of being stored as repeated library entries. | `ShortcutSkillStore` in [`opengui/skills/shortcut_store.py`](../../../../opengui/skills/shortcut_store.py) only supports direct `add/remove/get/search`; dedup/version behavior exists only in the legacy `SkillLibrary.add_or_merge()` path in [`opengui/skills/library.py`](../../../../opengui/skills/library.py). Phase 28 must bring merge/version semantics into the shortcut-layer production path without regressing Phase 27 retrieval/search behavior. |

</phase_requirements>

## Summary

Phase 28 is the production bridge between the v1.5 shortcut architecture and the still-legacy post-run extraction path. The gap is concrete in the current codebase:

1. [`nanobot/agent/tools/gui.py`](../../../../nanobot/agent/tools/gui.py) background postprocessing still calls `_extract_skill()`.
2. `_extract_skill()` instantiates the legacy `SkillExtractor` from [`opengui/skills/extractor.py`](../../../../opengui/skills/extractor.py).
3. The extracted object is written through `skill_library.add_or_merge(...)`, which targets the legacy `SkillLibrary`, not `ShortcutSkillStore`.
4. Meanwhile, Phase 26 already shipped `ExtractionPipeline` and `ShortcutSkillProducer`, and Phase 27 already shipped `ShortcutSkillStore`, `TaskSkillStore`, and `UnifiedSkillSearch`.

So Phase 28 should not invent a second extraction system. It should add a thin, production-focused promotion layer that:

- reads the recorded trace safely,
- filters to valid `step` events only,
- runs explicit critics/gates before promotion,
- enriches the shortcut with provenance and version metadata,
- persists through the shortcut-layer store with merge/version decisions,
- and leaves the legacy `SkillLibrary` path out of the new shortcut promotion flow.

The cleanest split remains the roadmap's three-plan shape:

1. **Cut over the GUI postprocessing seam** from legacy `SkillExtractor -> SkillLibrary` to a new `trace -> ExtractionPipeline -> Shortcut promotion` path.
2. **Add metadata, gating, and merge/version behavior** at the shortcut-layer contract/store seam.
3. **Lock it down with regression coverage** around malformed traces, summary/result noise, low-quality candidates, and duplicate handling.

**Primary recommendation:** introduce a dedicated promotion module such as `opengui/skills/shortcut_promotion.py` that owns trace parsing, gate application, provenance assembly, and `ShortcutSkillStore` integration. Keep `shortcut_extractor.py` focused on Phase 26 extraction primitives and keep `nanobot/agent/tools/gui.py` as a caller, not as the place where promotion policy lives.

## Standard Stack

### Core

| Library / Module | Version | Purpose | Why Standard |
|------------------|---------|---------|--------------|
| Python stdlib `json`, `dataclasses`, `pathlib`, `time`, `uuid` | `>=3.11` | Trace parsing, metadata, schema evolution | Matches current OpenGUI patterns |
| [`opengui/trajectory/recorder.py`](../../../../opengui/trajectory/recorder.py) | workspace current | Source-of-truth event format (`metadata`, `phase_change`, `step`, `result`) | Defines the exact typed trace surface Phase 28 must consume |
| [`opengui/skills/shortcut_extractor.py`](../../../../opengui/skills/shortcut_extractor.py) | workspace current | `ExtractionPipeline`, critics, `ShortcutSkillProducer` | Phase 26 already solved the candidate-production core |
| [`opengui/skills/shortcut.py`](../../../../opengui/skills/shortcut.py) | workspace current | `ShortcutSkill`, `ParameterSlot`, `StateDescriptor` | Shortcut schema contract that later phases search and execute |
| [`opengui/skills/shortcut_store.py`](../../../../opengui/skills/shortcut_store.py) | workspace current | Persistent shortcut storage and search | Phase 27 storage/search target that Phase 28 must populate |
| [`opengui/skills/normalization.py`](../../../../opengui/skills/normalization.py) | workspace current | App normalization and store-root helpers | Existing platform/app identity normalization |
| [`nanobot/agent/tools/gui.py`](../../../../nanobot/agent/tools/gui.py) | workspace current | GUI post-run postprocessing seam | Current production caller that needs cutover |

### Supporting

| Library / Module | Version | Purpose | When to Use |
|------------------|---------|---------|-------------|
| [`opengui/skills/library.py`](../../../../opengui/skills/library.py) | workspace current | Legacy merge heuristics and conflict detection | Reference for duplicate/merge/version logic only; do not keep as the production shortcut sink |
| `pytest`, `pytest-asyncio` | workspace locked | Regression tests for productionized extraction | All Phase 28 automated coverage |
| [`tests/test_opengui_p8_trajectory.py`](../../../../tests/test_opengui_p8_trajectory.py) | workspace current | Existing background-postprocessing expectations | Extend to preserve non-blocking post-run behavior after cutover |
| [`tests/test_opengui_p27_storage_search_agent.py`](../../../../tests/test_opengui_p27_storage_search_agent.py) | workspace current | Existing store/search contract coverage | Use as a compatibility backstop while adding promotion semantics |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New promotion module | Inline promotion logic inside `GuiSubagentTool._extract_skill()` | Inline is fast but mixes policy, trace parsing, gating, storage, and logging into an already busy tool module |
| Extend `SkillExtractor` to return `ShortcutSkill` | Reuse legacy extractor prompt path | This keeps legacy assumptions (summary-orientated extraction, legacy `Skill` output, no provenance/store semantics) in the new path and couples Phase 28 to code it is supposed to replace |
| Direct `ShortcutSkillStore.add()` | Add raw candidates with no dedup/versioning | Fails SXTR-04 and guarantees store growth with repeated brittle shortcuts |

## Architecture Patterns

### Recommended Project Structure

```text
opengui/
└── skills/
    ├── shortcut.py                 # extend schema with backward-compatible provenance/version metadata
    ├── shortcut_extractor.py       # keep Phase 26 primitives focused on candidate production
    ├── shortcut_store.py           # add shortcut-layer merge/version/promotion API
    └── shortcut_promotion.py       # NEW: trace parsing + gates + provenance + store integration

nanobot/
└── agent/tools/gui.py              # call promotion module during background postprocessing

tests/
├── test_opengui_p8_trajectory.py   # preserve async/non-blocking postprocessing behavior
├── test_opengui_p27_storage_search_agent.py
└── test_opengui_p28_shortcut_productionization.py   # NEW focused Phase 28 coverage
```

### Pattern 1: Dedicated Promotion Seam From Typed Trace Events

**What:** Build a `ShortcutPromotionPipeline` that reads JSONL trace events, filters to `type == "step"`, validates metadata/platform/app context, runs gates, and only then calls the producer/store.

**Why:** The current legacy extractor path is coupled to the entire trace file and does not encode the new store/provenance semantics. Phase 28 needs a production seam, not another prompt wrapper.

**Concrete fit in current codebase:**

- Caller remains [`GuiSubagentTool._run_trajectory_postprocessing()`](../../../../nanobot/agent/tools/gui.py).
- Trace shape comes from [`TrajectoryRecorder`](../../../../opengui/trajectory/recorder.py).
- Candidate production comes from [`ExtractionPipeline.run()`](../../../../opengui/skills/shortcut_extractor.py).
- Persistence lands in [`ShortcutSkillStore`](../../../../opengui/skills/shortcut_store.py).

### Pattern 2: Backward-Compatible Provenance Metadata

**What:** Add optional provenance/version metadata to `ShortcutSkill` or a store-owned promotion envelope without breaking Phase 24/27 round-trip compatibility.

**Minimum metadata to lock before planning:**

- `source_trace_path` or stable trace identifier
- `source_run_id` derived from the run directory
- `source_step_range` or explicit tuple of promoted `step_index` values
- `promotion_timestamp`
- `promotion_version` or `shortcut_version`
- normalized `app` and `platform` persisted on the promoted artifact
- gate evidence summary such as `step_count`, `trajectory_verdict_reason`, and rejection/merge reason

**Important constraint:** new fields must deserialize safely from older shortcut JSON files. That means additive fields with defaults in `to_dict()/from_dict()` rather than a breaking rewrite of existing Phase 27 stores.

### Pattern 3: Promotion Gates Before Storage, Not After

**What:** Treat Phase 26's `ExtractionPipeline` as the candidate generator, then apply production gates before any write:

- reject traces with fewer than two usable `step` events,
- reject traces whose actionable steps are dominated by unsupported action types,
- reject candidates missing stable app/platform identity,
- reject candidates with empty or low-value target/state evidence,
- reject traces where only summary/result events would have produced meaning.

**Why:** SXTR-01 and SXTR-03 are about protecting the store from noise. Once noisy shortcuts are persisted, later retrieval/applicability routing becomes harder to trust.

**Concrete pitfall already visible:** the current `ShortcutSkillProducer._to_skill_step()` uses `model_output` as the `SkillStep.target`, which is often descriptive text rather than a stable UI target. Phase 28 planning should explicitly decide whether promotion uses `model_output`, action payload, or a stricter extracted target source, because low-quality target text is a major brittleness source.

### Pattern 4: Shortcut-Layer Merge / Version API

**What:** Add a shortcut-specific `add_or_merge` / `promote_candidate` path to `ShortcutSkillStore` instead of writing raw `add()`.

**Why:** SXTR-04 requires duplicate handling in the new store, and the existing shortcut store has no conflict detection.

**Best current reference:** [`SkillLibrary.add_or_merge()`](../../../../opengui/skills/library.py) already has:

- normalized app bucketing,
- best-conflict selection,
- heuristic or LLM merge decisions,
- deterministic merge behavior.

That logic should be adapted, not copied blindly, because the shortcut schema differs from legacy `Skill`. The shortcut-layer version must compare:

- normalized app/platform,
- action sequence signature from `ShortcutSkill.steps`,
- parameter slot names,
- condition sets (`preconditions`, `postconditions`),
- provenance overlap (same trace/run/step span),
- and freshness/version preference.

### Pattern 5: Preserve Non-Blocking Background Postprocessing

**What:** Keep promotion in the same asynchronous background-postprocessing slot used today by summarization and optional evaluation.

**Why:** [`tests/test_opengui_p8_trajectory.py`](../../../../tests/test_opengui_p8_trajectory.py) and [`tests/test_opengui_p11_integration.py`](../../../../tests/test_opengui_p11_integration.py) already assert that GUI tool results return before postprocessing finishes and that postprocessing failures are non-fatal.

**Implication for planning:** promotion failures should log structured reasons and write usage/diagnostic artifacts, but they must not block or poison the user-visible GUI task result.

## Contract Decisions To Lock Before Planning

1. **Where provenance lives**
   - Preferred: optional fields directly on `ShortcutSkill` so later retrieval/applicability logic can see them without sidecar lookups.
   - Acceptable fallback: a versioned promotion envelope in `shortcut_skills.json` if adding schema fields would create too much churn.

2. **What counts as a promotable trace**
   - Recommended: successful runs only for the first production cutover.
   - Exclude `metadata`, `phase_change`, and `result` events from extraction input entirely.
   - Ignore malformed `step` events missing `action.action_type`.

3. **How to version duplicates**
   - Recommended: preserve one canonical shortcut ID per stable behavior, attach version/provenance history, and only replace the canonical when the new candidate is clearly better.
   - Avoid uncontrolled `ADD` on near-duplicates.

4. **How much legacy behavior remains**
   - Recommended: Phase 28 cuts over the GUI post-run shortcut path only.
   - Keep `SkillLibrary` available for legacy retrieval compatibility during transition, but do not keep writing newly promoted shortcuts into it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Trace event taxonomy | Ad hoc JSON shape guesses | [`TrajectoryRecorder`](../../../../opengui/trajectory/recorder.py) event format | It already defines the production trace contract |
| Candidate production | New LLM extraction prompt path | [`ExtractionPipeline` and `ShortcutSkillProducer`](../../../../opengui/skills/shortcut_extractor.py) | Phase 26 already solved the schema conversion core |
| Store root resolution | Inline path concatenation | `get_gui_skill_store_root()` in normalization helpers | Preserves current workspace-aware store layout |
| Duplicate heuristics | Fresh heuristic invented from scratch | Adapt `SkillLibrary` conflict/merge patterns | Existing code already encodes app-aware merge behavior that users depend on |

## Common Pitfalls

### Pitfall 1: Accidentally promoting non-step events

**What goes wrong:** `metadata`, `phase_change`, `result`, or future lifecycle events leak into extraction input and become fake shortcut steps.

**Why it happens:** The current legacy extractor reads the whole trace file and then filters internally; a new promotion seam might regress if it assumes every line is action-bearing.

**How to avoid:** Parse JSONL once, keep only `event.get("type") == "step"`, and explicitly test traces containing summary/result noise.

### Pitfall 2: Shipping provenance as logs only

**What goes wrong:** Promotion logs mention source trace/run details, but the stored shortcut object does not retain them. Phase 29 then lacks stable metadata for applicability/routing or debugging.

**How to avoid:** Persist provenance on the stored artifact or in its versioned envelope, not just in logger output.

### Pitfall 3: Reusing `ShortcutSkillStore.add()` as the final write path

**What goes wrong:** Duplicate candidates are appended forever because the store has no merge/version decision step.

**How to avoid:** Add a promotion API with conflict detection before any write; reserve `add()` for trusted/internal cases only.

### Pitfall 4: Letting always-pass critics stay in production

**What goes wrong:** Phase 26 tests remain green, but SXTR-03 is not actually satisfied because all candidates pass by default.

**How to avoid:** Phase 28 must either ship concrete critics or add explicit gate objects/configured validators at the promotion seam. Planning should not assume the Phase 26 defaults are production-safe.

### Pitfall 5: Breaking existing Phase 27 store/search compatibility

**What goes wrong:** Provenance/version fields are added in a way that breaks `ShortcutSkill.from_dict()`, store reload, or Phase 27 search tests.

**How to avoid:** Make schema changes additive with safe defaults and extend tests to prove older files still load.

## Validation Architecture

### Test Framework

- **Framework:** `pytest` + `pytest-asyncio`
- **Config:** [`pyproject.toml`](../../../../pyproject.toml)
- **Quick run:** `uv run pytest tests/test_opengui_p8_trajectory.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p28_shortcut_productionization.py`
- **Full slice:** `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p27_storage_search_agent.py tests/test_opengui_p8_trajectory.py tests/test_opengui_p11_integration.py tests/test_opengui_p28_shortcut_productionization.py`

### Phase Requirements -> Test Map

| Requirement | Automated Coverage Needed |
|-------------|---------------------------|
| SXTR-01 | Trace parser ignores `metadata`, `phase_change`, `result`; malformed or non-step-only traces produce rejection and no store write |
| SXTR-02 | Promoted shortcut persists normalized `app`/`platform`, `parameter_slots`, `preconditions`/`postconditions`, and provenance fields round-trip through store reload |
| SXTR-03 | Gate tests reject low-step, unsupported-action, or low-evidence candidates and log structured rejection reasons |
| SXTR-04 | Duplicate promotions merge/version/reject deterministically instead of creating repeated shortcut entries |

### Sampling Rate

- After every task commit: run the targeted Phase 28 + adjacent seam tests
- After every plan wave: rerun the full extraction/storage/postprocessing slice
- Before verification: full slice must be green

### Wave 0 Gaps

- New test file required: `tests/test_opengui_p28_shortcut_productionization.py`
- Existing infrastructure otherwise already covers async tool behavior, extraction primitives, and store/search reload

## Sources

### Primary (HIGH confidence)

- [`nanobot/agent/tools/gui.py`](../../../../nanobot/agent/tools/gui.py) — current production post-run extraction seam
- [`opengui/skills/extractor.py`](../../../../opengui/skills/extractor.py) — legacy extraction path still used in production
- [`opengui/skills/shortcut_extractor.py`](../../../../opengui/skills/shortcut_extractor.py) — Phase 26 candidate pipeline
- [`opengui/skills/shortcut_store.py`](../../../../opengui/skills/shortcut_store.py) — Phase 27 shortcut/task stores and unified search
- [`opengui/skills/shortcut.py`](../../../../opengui/skills/shortcut.py) — current shortcut schema
- [`opengui/trajectory/recorder.py`](../../../../opengui/trajectory/recorder.py) — typed trace event contract
- [`opengui/skills/library.py`](../../../../opengui/skills/library.py) — legacy merge/dedup logic reference

### Secondary (MEDIUM confidence)

- [`tests/test_opengui_p8_trajectory.py`](../../../../tests/test_opengui_p8_trajectory.py) — postprocessing behavior guarantees
- [`tests/test_opengui_p11_integration.py`](../../../../tests/test_opengui_p11_integration.py) — GUI tool integration expectations
- [`tests/test_opengui_p27_storage_search_agent.py`](../../../../tests/test_opengui_p27_storage_search_agent.py) — store/search compatibility constraints
- `.planning/phases/26-quality-gated-extraction/26-RESEARCH.md` — prior phase design rationale
- `.planning/phases/27-storage-search-agent-integration/27-RESEARCH.md` — prior phase storage/search rationale

## Metadata

- No `28-CONTEXT.md` existed for this run; research is grounded in roadmap/requirements/state plus live code inspection.
- Phase 28 is the first v1.6 phase and should preserve already-shipped v1.5 schema/store/search behavior while cutting over the production extraction seam.
