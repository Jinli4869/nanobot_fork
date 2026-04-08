# Phase 32: Prefix-Only Shortcut Extraction and Canonicalization - Research

**Researched:** 2026-04-07
**Domain:** Deterministic shortening and normalization of promoted GUI shortcuts
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SXTR-05 | Long-horizon GUI traces promote only the concise reusable prefix of a task instead of persisting the full downstream task chain as one shortcut. | The current promotion pipeline already truncates with `_truncate_to_reusable_prefix()` in `opengui/skills/shortcut_promotion.py`, but it only stops on crude “long horizon” hints. Phase 32 should replace that with explicit stable-boundary detection that preserves reusable setup/opening steps and cuts at the first task-specific commit/fill/submit boundary. |
| SXTR-06 | Promoted shortcuts are canonicalized to remove redundant waits, repeated unchanged-UI actions, and other replay-like path noise before storage. | No canonicalization pass exists today. `ShortcutPromotionPipeline` filters rows and forwards them directly into `ExtractionPipeline.run()`. Phase 32 should add a deterministic canonicalizer before extraction so the stored shortcut is shorter than the raw replay trace. |
| SXTR-07 | Dynamic action arguments that can be grounded at runtime are emitted as placeholders/parameter slots rather than frozen recorded literals when that improves reuse stability. | `ShortcutSkillProducer` in `opengui/skills/shortcut_extractor.py` only generalizes `input_text.text` today. Pointer coordinates are dropped for some actions, but other dynamic fields still survive as literals. Phase 32 should widen placeholder inference for text/selectors/coordinates while preserving executor compatibility with Phase 30/31 grounding behavior. |

</phase_requirements>

## Summary

Phase 32 is not a new subsystem. The correct seam is the existing promotion path in `opengui/skills/shortcut_promotion.py` plus the generalization logic in `opengui/skills/shortcut_extractor.py`. Today the pipeline already filters to `type == "step"` rows, selects the final successful attempt, and applies a simple prefix rule, but it still has three concrete gaps: prefix cutting is heuristic and shallow, replay noise is preserved, and placeholder emission is mostly limited to `input_text`.

The safest design is a three-stage promotion flow: `trace rows -> promotable step rows -> canonicalized step rows -> reusable prefix -> ExtractionPipeline.run() -> ShortcutSkillStore.add_or_merge()`. Keep all Phase 32 policy inside the promotion/extractor seam. Do not spread canonicalization into `ShortcutExecutor`, `GuiAgent`, or store merge logic.

**Primary recommendation:** add a dedicated deterministic canonicalization layer inside `ShortcutPromotionPipeline`, then extend `ShortcutSkillProducer` to generalize more dynamic fields into placeholders while preserving the Phase 30 executor contract that merges `step.parameters`, grounding output, and caller params.

## Standard Stack

### Core
| Library / Module | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | `>=3.11` | Runtime baseline | Locked by workspace `pyproject.toml` |
| `opengui/skills/shortcut_promotion.py` | workspace current | Promotion orchestration | Already owns trace filtering, prefix truncation, and store write |
| `opengui/skills/shortcut_extractor.py` | workspace current | Step-to-shortcut conversion and placeholder inference | Already owns `SkillStep`, `ParameterSlot`, and condition extraction |
| `opengui/skills/shortcut_store.py` | workspace current | Canonical shortcut persistence and merge/versioning | Already handles dedup/version at the shortcut layer |
| `opengui/skills/shortcut.py` | workspace current | Stored shortcut schema | Existing additive schema is already backward-compatible |

### Supporting
| Library / Module | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | `>=9.0.0,<10.0.0` | Test runner | Phase validation and regression slices |
| `pytest-asyncio` | `>=1.3.0,<2.0.0` | Async test support | Promotion and execution seam tests |
| `opengui/skills/multi_layer_executor.py` | workspace current | Runtime grounding/execution contract | Reference target when deciding which fields should remain placeholders |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Canonicalize before extraction | Canonicalize stored `ShortcutSkill.steps` after extraction | Post-extraction loses row-level evidence like observation/app/state transitions and makes prefix decisions less reliable |
| Expand `ShortcutSkillProducer` generalization rules | Put placeholder rewriting into runtime grounding | Runtime-only rewriting would store brittle literals and fail SXTR-07 |
| Deterministic canonicalizer | LLM-based cleanup pass | Higher variance and weak determinism for a phase that explicitly needs regression-stable output |

**Installation:**
```bash
uv sync --extra dev
```

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
└── skills/
    ├── shortcut_promotion.py      # add canonicalize -> prefix-boundary flow
    ├── shortcut_extractor.py      # extend placeholder/dynamic field generalization
    └── shortcut.py                # only if additive metadata is needed for emitted slots/boundaries

tests/
├── test_opengui_p26_quality_gated_extraction.py
├── test_opengui_p28_shortcut_productionization.py
└── test_opengui_p31_shortcut_observability.py
```

### Pattern 1: Canonicalize Before Prefix Detection
**What:** Add `_canonicalize_steps()` before `_truncate_to_reusable_prefix()`.
**When to use:** Always, for successful promotion traces.
**Example:**
```python
# Source: workspace pattern derived from opengui/skills/shortcut_promotion.py
steps = self._filter_promotable_steps(attempt_rows)
steps = self._canonicalize_steps(steps)
steps = self._truncate_to_reusable_prefix(steps)
result = await ExtractionPipeline().run(steps, metadata)
```

### Pattern 2: Use Explicit Stable-Boundary Rules
**What:** Cut the prefix at the first step that commits task-specific intent rather than the first vaguely “long horizon” token.
**When to use:** Long traces with setup + body + commit phases.
**Prescriptive rule set:**
- Keep navigational/opening steps that move into the reusable surface.
- Cut before first dynamic content entry if the text is task payload rather than reusable routing.
- Cut before destructive/commit actions such as send, submit, confirm, pay, delete, share.
- Cut before branches whose expected state depends on task-specific downstream success.

### Pattern 3: Canonicalize by Effect, Not Just Action Type
**What:** Remove rows that do not change reusable state.
**When to use:** Duplicate waits, repeated taps on the same unchanged surface, and retry noise inside a successful attempt window.
**Deterministic heuristics to use:**
- Collapse consecutive `wait` actions to the last or longest effective wait.
- Remove consecutive identical actions when `action_type`, generalized parameters, and normalized target match and no state transition is observed.
- Drop taps/clicks repeated on unchanged UI when `valid_state`, `expected_state`, and app observation are unchanged.
- Keep repeated actions only if intervening state differs or the later step is the first one with stronger state evidence.

### Anti-Patterns to Avoid
- **Do not canonicalize in `ShortcutSkillStore.add_or_merge()`:** that layer should compare canonical shortcuts, not mutate them.
- **Do not use `model_output` text alone as the prefix boundary signal:** current hints are too weak and will over-truncate or under-truncate.
- **Do not freeze coordinates just because they appeared in the trace:** Phase 30 already expects live grounding to provide better coordinates at reuse time.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| New promotion subsystem | Separate extractor/promotion pipeline | Extend `ShortcutPromotionPipeline` | Current code already owns the right seam |
| Runtime-only parameter templating | Placeholder substitution inside executor only | `ShortcutSkillProducer` placeholder emission | Stored artifact must be reusable before runtime |
| Heuristic dedup as canonicalization | Let merge/versioning clean noisy steps | Pre-store canonicalization pass | Store merge solves duplicate shortcuts, not noisy internals |

**Key insight:** dedup/versioning and canonicalization are different problems. `ShortcutSkillStore` merges whole shortcuts; Phase 32 must normalize the step sequence before storage.

## Common Pitfalls

### Pitfall 1: Over-truncating after every `input_text`
**What goes wrong:** Useful prefixes such as “open compose, focus recipient field” disappear.
**Why it happens:** Current `_LONG_HORIZON_ACTIONS` treats all `input_text` as terminal.
**How to avoid:** Distinguish routing/setup text from payload text; only payload-bearing entry should terminate the reusable prefix.
**Warning signs:** Stored `source_step_indices` collapse to a single open/tap step for traces that clearly contain a reusable two-step setup.

### Pitfall 2: Canonicalizing away meaningful retries
**What goes wrong:** Real recovery actions are removed as “duplicates.”
**Why it happens:** Equality by action alone ignores state evidence.
**How to avoid:** Canonicalization should compare normalized target/params plus state/app evidence before dropping a step.
**Warning signs:** Postconditions/preconditions become weaker after cleanup or promoted shortcut can no longer reach the expected surface.

### Pitfall 3: Placeholder explosion
**What goes wrong:** Every literal becomes a slot, including stable identifiers or control keys.
**Why it happens:** Generalization rules are too broad.
**How to avoid:** Only parameterize fields that are expected to vary at reuse time: payload text, coordinates, selectors/targets derived from task data.
**Warning signs:** `parameter_slots` grows faster than meaningful task inputs, and executor calls need unnecessary bindings.

## Code Examples

Verified workspace patterns:

### Existing Runtime Merge Contract
```python
# Source: opengui/skills/multi_layer_executor.py
merged = {"action_type": step.action_type, **rendered_parameters}
for key, value in grounding.resolved_params.items():
    merged[key] = value
for key, value in params.items():
    merged[key] = value
```

### Existing Text Placeholder Generalization
```python
# Source: opengui/skills/shortcut_extractor.py
if action_type in _TEXTUAL_ACTIONS and key == "text":
    parameters[key] = f"{{{{{placeholder_name}}}}}"
```

### Recommended Canonicalization Hook
```python
# Source: recommended extension of opengui/skills/shortcut_promotion.py
steps = self._filter_promotable_steps(attempt_rows)
steps = self._canonicalize_steps(steps)
steps = self._truncate_to_reusable_prefix(steps)
if not steps:
    return None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Promote full filtered step list | Promote simple reusable prefix via `_truncate_to_reusable_prefix()` | Phase 28 | Good first guard, but still too crude for long traces |
| Freeze most recorded literals | Generalize `input_text.text`, drop some pointer coordinates | Phase 26 | Partial stability improvement, not enough for reusable promoted prefixes |
| Persist replay-like steps | No canonicalization pass yet | Current gap | Phase 32 must close this to stop shortcut bloat |

**Deprecated/outdated:**
- “Prefix-only” via `_LONG_HORIZON_ACTIONS` alone is insufficient for Phase 32.
- Relying on `model_output` strings alone for dynamic-field detection is too brittle.

## Open Questions

1. **Should repeated taps with unchanged UI always be dropped or sometimes collapsed into one kept step?**
   - What we know: replay noise exists and must be removed.
   - What's unclear: whether the last repeated step carries better `expected_state` than the first in some traces.
   - Recommendation: keep the richest-evidence instance, not blindly first or last.

2. **Do we need schema metadata for why a slot was emitted?**
   - What we know: current schema can already store `parameter_slots` and templated parameters.
   - What's unclear: whether later debugging would benefit from slot provenance like `source_field=text`.
   - Recommendation: start without schema expansion unless tests show debugging pain.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest >=9.0.0,<10.0.0` + `pytest-asyncio >=1.3.0,<2.0.0` |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p31_shortcut_observability.py -q` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SXTR-05 | Long traces truncate at deterministic reusable boundary | unit | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py -k reusable_prefix -q` | ✅ |
| SXTR-06 | Redundant waits/duplicate unchanged-UI actions are removed before storage | unit | `uv run pytest tests/test_opengui_p28_shortcut_productionization.py -k canonical -q` | ❌ Wave 0 |
| SXTR-07 | Dynamic fields emit placeholders/slots and executor still consumes them | unit | `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p31_shortcut_observability.py -k 'placeholder or param or render' -q` | ✅ |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p31_shortcut_observability.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p26_quality_gated_extraction.py tests/test_opengui_p28_shortcut_productionization.py tests/test_opengui_p31_shortcut_observability.py tests/test_opengui_p30_stable_shortcut_execution.py -q`
- **Phase gate:** `uv run pytest` before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_opengui_p28_shortcut_productionization.py` needs new canonicalization-specific cases for duplicate waits, repeated unchanged-UI taps, and richer prefix-boundary decisions.
- [ ] `tests/test_opengui_p26_quality_gated_extraction.py` needs broader placeholder inference cases beyond `input_text.text`.
- [ ] `tests/test_opengui_p31_shortcut_observability.py` needs an end-to-end seam asserting canonicalized promoted steps still execute with grounding.

## Sources

### Primary (HIGH confidence)
- Workspace source: `opengui/skills/shortcut_promotion.py` - current promotion flow, attempt selection, prefix truncation, enrichment
- Workspace source: `opengui/skills/shortcut_extractor.py` - placeholder inference, condition extraction, `ShortcutSkillProducer`
- Workspace source: `opengui/skills/shortcut_store.py` - merge/version semantics and provenance overlap behavior
- Workspace source: `opengui/skills/multi_layer_executor.py` - runtime merge and grounding contract
- Workspace tests: `tests/test_opengui_p26_quality_gated_extraction.py`, `tests/test_opengui_p28_shortcut_productionization.py`, `tests/test_opengui_p31_shortcut_observability.py`
- Workspace docs: `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/config.json`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all recommendations extend existing workspace modules rather than introducing uncertain external dependencies
- Architecture: HIGH - the current promotion/extractor/runtime seams make the insertion point explicit
- Pitfalls: HIGH - each pitfall is already visible in current heuristics or existing tests

**Research date:** 2026-04-07
**Valid until:** 2026-05-07
