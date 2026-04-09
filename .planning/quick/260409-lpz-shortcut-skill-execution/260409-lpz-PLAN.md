---
phase: quick-260409-lpz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - nanobot/agent/tools/gui.py
  - opengui/agent.py
  - opengui/postprocessing.py
autonomous: true
must_haves:
  truths:
    - "Shortcut executor, shortcut applicability router, and unified skill search are never instantiated or passed to GuiAgent"
    - "Original SkillExecutor still works: when enable_skill_execution=True, skill_executor is created and used by GuiAgent"
    - "Postprocessing extracts skills via SkillExtractor but does NOT promote to shortcut store"
    - "No shortcut candidate retrieval or applicability evaluation occurs during agent.run()"
  artifacts:
    - path: "nanobot/agent/tools/gui.py"
      provides: "GuiAgent construction without shortcut objects"
    - path: "opengui/agent.py"
      provides: "Agent run loop without shortcut evaluation/execution block"
    - path: "opengui/postprocessing.py"
      provides: "Post-processing with skill extraction only, no shortcut promotion"
  key_links:
    - from: "nanobot/agent/tools/gui.py"
      to: "opengui/agent.py GuiAgent.__init__"
      via: "constructor args shortcut_executor=None, unified_skill_search=None, shortcut_applicability_router=None"
---

<objective>
Disable the shortcut system while preserving the original skill extraction (SkillExtractor) and skill execution (SkillExecutor) functionality.

Purpose: The shortcut system (ShortcutExecutor, ShortcutApplicabilityRouter, UnifiedSkillSearch, ShortcutPromotionPipeline) adds complexity that is not needed. The original skill system (SkillExtractor for learning, SkillExecutor for replay) is sufficient.

Output: Three modified files with shortcut code paths disabled.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@nanobot/agent/tools/gui.py (lines 220-310 — GuiAgent construction)
@opengui/agent.py (lines 492-541 — GuiAgent.__init__, lines 570-725 — run() skill/shortcut block)
@opengui/postprocessing.py (lines 118-200 — _run_all and _promote_shortcut)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Remove shortcut object creation in gui.py and shortcut code paths in agent.py</name>
  <files>nanobot/agent/tools/gui.py, opengui/agent.py</files>
  <action>
**In `nanobot/agent/tools/gui.py` (lines 220-300):**

1. Remove the `unified_skill_search` variable assignment at line 221. Do NOT call `self._get_unified_skill_search()`.
2. Inside the `if self._gui_config.enable_skill_execution:` block (line 232):
   - Remove the imports of `ShortcutExecutor`, `LLMConditionEvaluator` (from `opengui.skills.multi_layer_executor`), and `ShortcutApplicabilityRouter` (from `opengui.skills.shortcut_router`).
   - Remove `condition_evaluator` creation (line 247: `condition_evaluator = LLMConditionEvaluator(state_validator)`).
   - Remove lines 271-281 that create `shortcut_screenshot_dir`, `shortcut_executor`, and `shortcut_applicability_router`.
   - Keep ALL of the `skill_executor` creation (lines 248-270) exactly as is.
3. In the `GuiAgent(...)` constructor call (line 283):
   - Remove `shortcut_executor=shortcut_executor` (or set to None explicitly).
   - Remove `unified_skill_search=unified_skill_search` (or set to None explicitly).
   - Remove `shortcut_applicability_router=shortcut_applicability_router` (or set to None explicitly).
   - Keep `skill_executor=skill_executor` and `skill_library=skill_library`.

**In `opengui/agent.py` (lines 570-725 in the `run()` method):**

1. Remove lines 579-582 entirely — the `shortcut_candidates = await self._retrieve_shortcut_candidates(...)` call.
2. Remove the entire shortcut applicability + execution block (lines 635-717). This is the `if attempt == 0 and shortcut_candidates:` block that does screenshot-based applicability check and runs ShortcutExecutor.
3. Remove `_shortcut_attempted` variable initialization (line 623) and the stale-context clearing block (lines 719-723: `if attempt > 0 and _shortcut_attempted:`).
4. Update the comment at line 584-586 to remove the reference to "Shortcut candidates from step 3b". The comment should just say: "If skill matched, attempt skill execution first."
5. Keep the ENTIRE original skill execution path (lines 584-611) — the `if matched_skill is not None and self._skill_executor is not None` block — completely untouched.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "
import ast, sys
# Check gui.py has no shortcut references in the relevant function
with open('nanobot/agent/tools/gui.py') as f:
    src = f.read()
assert 'ShortcutExecutor' not in src or 'ShortcutExecutor' in src.split('def _run_gui')[0], 'ShortcutExecutor still referenced in _run_gui'
assert 'shortcut_applicability_router=' not in src.split('GuiAgent(')[1].split(')')[0] if 'shortcut_applicability_router=' in src else True

# Check agent.py run() no longer has shortcut execution
with open('opengui/agent.py') as f:
    agent_src = f.read()
# The _retrieve_shortcut_candidates call should not be in run()
assert '_retrieve_shortcut_candidates' not in agent_src.split('async def run(')[1].split('async def ')[0], 'shortcut retrieval still in run()'
print('Shortcut removal verified')
"</automated>
  </verify>
  <done>
    - ShortcutExecutor, ShortcutApplicabilityRouter, UnifiedSkillSearch are not instantiated in gui.py
    - GuiAgent receives None for shortcut_executor, unified_skill_search, shortcut_applicability_router
    - agent.py run() method no longer retrieves shortcut candidates or evaluates shortcut applicability
    - Original SkillExecutor creation and execution path is fully preserved
  </done>
</task>

<task type="auto">
  <name>Task 2: Replace shortcut promotion with plain skill extraction in postprocessing.py</name>
  <files>opengui/postprocessing.py</files>
  <action>
**In `opengui/postprocessing.py`:**

1. Replace the `_promote_shortcut` method (lines 154-200) with a simpler `_extract_skill` method that:
   - Has the same signature: `async def _extract_skill(self, trace_path: Path, is_success: bool, platform: str) -> str | None`
   - Returns early if `not self._enable_skill_extraction` or `not trace_path.exists()` (same guards as before)
   - Imports only `SkillExtractor` from `opengui.skills.extractor` (NOT ShortcutPromotionPipeline, NOT ShortcutSkillStore)
   - Creates a `SkillExtractor(llm=self._llm)` and calls `await extractor.extract_from_file(trace_path, is_success=is_success)`
   - Calls `self._write_extraction_usage(trace_path, extractor.total_usage)` to record usage
   - If skill is None, logs info and returns None
   - If skill is extracted, stores it in the original SkillLibrary:
     ```python
     from opengui.skills.library import SkillLibrary
     library = SkillLibrary(
         store_dir=self._skill_store_root,
         embedding_provider=self._embedding_provider,
     )
     decision, skill_id = await library.add_or_merge(skill)
     logger.info("Extracted skill %s from %s via %s", skill_id or skill.skill_id, trace_path, decision)
     return skill_id or skill.skill_id
     ```
   - Wraps everything in try/except Exception with `logger.warning("Skill extraction failed for %s", trace_path, exc_info=True)` and returns None

2. In `_run_all` (line 126-130), replace `self._promote_shortcut(trace_path, is_success, platform)` with `self._extract_skill(trace_path, is_success, platform)`.

Note: The `_legacy_skill_to_shortcut` static method (line 282+) can remain in the file — it will simply be dead code. Do not delete it to minimize diff size.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "
import ast
with open('opengui/postprocessing.py') as f:
    src = f.read()
tree = ast.parse(src)

# Find PostProcessor class methods
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and 'PostProcessor' in node.name:
        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert '_extract_skill' in methods, f'_extract_skill not found, methods: {methods}'
        assert '_promote_shortcut' not in methods, '_promote_shortcut still exists'
        break
else:
    raise AssertionError('PostProcessor class not found')

# Check _run_all calls _extract_skill not _promote_shortcut
assert '_extract_skill' in src
assert '_promote_shortcut' not in src.split('def _run_all')[1].split('def ')[0] if '_promote_shortcut' in src else True
print('Postprocessing replacement verified')
"</automated>
  </verify>
  <done>
    - _promote_shortcut is replaced by _extract_skill
    - _run_all calls _extract_skill instead of _promote_shortcut
    - Skill extraction uses SkillExtractor + SkillLibrary (original system), not ShortcutPromotionPipeline + ShortcutSkillStore
    - No imports of ShortcutPromotionPipeline or ShortcutSkillStore in the active code paths
  </done>
</task>

</tasks>

<verification>
Run the full verification:

```bash
cd /Users/jinli/Documents/Personal/nanobot_fork

# 1. Syntax check all modified files
python -m py_compile nanobot/agent/tools/gui.py
python -m py_compile opengui/agent.py
python -m py_compile opengui/postprocessing.py

# 2. Grep to confirm no shortcut imports in active code paths
python -c "
with open('nanobot/agent/tools/gui.py') as f:
    src = f.read()
assert 'ShortcutExecutor(' not in src, 'ShortcutExecutor still instantiated'
assert 'ShortcutApplicabilityRouter(' not in src, 'ShortcutApplicabilityRouter still instantiated'

with open('opengui/agent.py') as f:
    src = f.read()
# run() method should not call shortcut retrieval
run_body = src.split('async def run(')[1]
assert '_retrieve_shortcut_candidates' not in run_body.split('async def ')[0]

with open('opengui/postprocessing.py') as f:
    src = f.read()
assert 'ShortcutPromotionPipeline' not in src or 'ShortcutPromotionPipeline' in src.split('_legacy_skill_to_shortcut')[1] if '_legacy_skill_to_shortcut' in src else 'ShortcutPromotionPipeline' not in src
print('All checks passed')
"

# 3. Run existing tests if available
python -m pytest tests/ -x -q --timeout=60 2>/dev/null || echo "No tests or test failures"
```
</verification>

<success_criteria>
- All three files compile without syntax errors
- ShortcutExecutor, ShortcutApplicabilityRouter, UnifiedSkillSearch are not instantiated anywhere in active code
- Original SkillExecutor is still created and passed to GuiAgent when enable_skill_execution=True
- Original SkillExtractor is still used in postprocessing to extract skills from trajectories
- Extracted skills are stored in SkillLibrary (original system), not ShortcutSkillStore
- agent.py run() method only uses the original skill execution path (SkillExecutor), no shortcut evaluation
</success_criteria>

<output>
After completion, create `.planning/quick/260409-lpz-shortcut-skill-execution/260409-lpz-SUMMARY.md`
</output>
