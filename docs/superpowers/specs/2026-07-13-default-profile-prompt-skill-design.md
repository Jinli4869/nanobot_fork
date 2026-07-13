# Default Profile Prompt-Selected Skill Design

## Goal

Make the `default` GUIClaw profile support the existing prompt-selected skill flow:
retrieve Top-K skills, show the catalog to the model, accept a native
`computer_use(action_type="use_skill")` call, and dispatch it through the existing
`SkillExecutor` path.

## Scope

The change is deliberately local:

- Keep `_build_prompt_skill_parts()` and its retrieval/filtering behavior unchanged.
- Keep `_execute_prompt_skill_action()` and `SkillExecutor` unchanged.
- Keep every non-default agent profile unchanged.
- Do not change GUI configuration semantics.
- Do not add a second native tool named `use_skill`.

## Design

Add `build_computer_use_tool(allow_use_skill=False)` in `guiclaw/tool_schemas.py`.
Without prompt-visible skills it returns the shared `COMPUTER_USE_TOOL` object unchanged.
With prompt-visible skills it returns a copy whose action enum includes `use_skill` and whose
properties include `skill_id` and `arguments`.

`GuiAgent._build_tools_list()` selects the expanded schema only when
`_prompt_skills_by_id` is non-empty. This keeps the provider-native schema synchronized with
the catalog that was actually retrieved for the current task.

`build_profile_messages()` passes `compact_prompt_parts` into `_build_default_messages()`.
The default builder uses the same conditional schema and appends the existing compact skill
instructions/catalog to its system prompt. The model therefore sees one consistent contract
in both the textual prompt and provider-native tool definition.

## Error Handling

Existing runtime validation remains authoritative:

- an absent `skill_id` is rejected;
- an ID not present in `_prompt_skills_by_id` is rejected;
- missing required skill parameters are rejected;
- state-contract and executor failures follow the existing skill result path.

No new fallback or implicit skill execution is introduced.

## Verification

Tests must prove:

1. default messages contain the retrieved catalog and conditional `use_skill` schema;
2. default messages without retrieved skills retain the original shared schema;
3. a native default-profile `use_skill` call executes the retrieved skill end-to-end;
4. existing strict-profile and GUIClaw focused tests still pass;
5. the same changed files and tests pass after content-only synchronization to
   `/Users/jinli/Documents/Personal/KnowAct/GUIClaw`.
