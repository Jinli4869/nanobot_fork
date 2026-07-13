# GUIClaw Agent Profile Strict Migration Design

**Date:** 2026-07-13

## Goal

Reduce GUIClaw's public agent-profile surface to eight canonical profiles and restore the
provider-native `default` profile contract from `feat/opencua` without bringing back the deleted
unified Prompt Builder.

The only supported profile names will be:

- `default`
- `general_e2e`
- `gui_owl`
- `venus`
- `seed`
- `qwen3vl`
- `mai_ui`
- `gelab`

## Strict Compatibility Boundary

Omitting `agent_profile`, or supplying an empty value at the internal API boundary, selects
`default`. Every non-empty profile value must exactly match one of the eight canonical names.

The following legacy names and aliases will no longer be accepted:

- `mobileworld_general_e2e`
- `mobileworld_general_e2e_compact_skill`
- `planner_executor`
- `general`
- `general_e2e_compact_skill`
- `mw_general_e2e` and spelling variants
- `gui_owl_1_5` and `gui-owl-1.5`
- `ui_venus`

This is an intentional breaking cleanup. Configuration validation and CLI choices will expose the
same strict list.

## Default Profile Contract

`default` will be a distinct profile rather than an alias for `general_e2e`.

It will:

1. Use provider-native function calling.
2. Pass the existing shared `guiclaw.tool_schemas.COMPUTER_USE_TOOL` schema to the provider.
3. Require a tool choice on each decision call.
4. Require the `computer_use` arguments `action_type`, `intent`, and `summary`.
5. Preserve the `feat/opencua` response contract: one concise `Action:` line plus one native tool
   call, with one GUI action per step.
6. Pass native tool-call responses through normalization unchanged, including responses that also
   contain assistant text.
7. Use absolute coordinates by default, while retaining the existing Qwen/Gemini relative-grid
   model hint behavior from `feat/opencua`.

The default system text and current-screen message will be built by a small default-only helper in
`guiclaw/agents/profiles.py`. This avoids recreating `prompts/system.py` or a cross-profile Prompt
Builder. Existing runtime tool expansion for shortcuts remains owned by `GuiAgent`.

## Non-default Profiles

The seven non-default profiles retain their current dedicated prompt construction and response
parsing behavior. Their canonical public names become `gui_owl` and `venus`, while the internal
implementation modules may remain named `gui_owl_1_5.py` and `ui_venus_agent.py`.

`planner_executor` will be removed from `guiclaw/agents/profiles.py`, including its import, prompt
template, message builder, parser branch, supported-profile entry, and aliases. Vendored
implementation modules are outside this change and may be audited for deletion separately after
the profile migration is verified.

## API and Data Flow

The profile message and action helpers will use profile-neutral names. `GuiAgent`, subgoal/action
grounding code, re-export modules, CLI/config validation, and tests will import those canonical
helpers directly.

For a `default` step:

1. `GuiAgent` canonicalizes the profile to `default`.
2. The profile message helper emits the default native-tool system contract, compact textual
   progress, and the current screenshot.
3. `GuiAgent` calls the provider with its current native tool list and
   `tool_choice="required"`.
4. Profile normalization returns the native tool call without textual parsing.
5. Existing action parsing, policy checks, execution, and trajectory recording continue unchanged.

For a non-default step, the current profile-specific text format is parsed into a synthetic
`computer_use` tool call before entering the same downstream action path.

## Files in Scope

- `guiclaw/agents/profiles.py`
- `guiclaw/agent.py`
- `guiclaw/agent_profiles.py`
- `guiclaw/agents/__init__.py`
- `guiclaw/skills/subgoal_runner.py` if helper imports require renaming
- profile/config/agent tests that encode the removed aliases or old default behavior
- GUIClaw README profile tables and examples that still advertise removed names

No backend, skill-extraction, memory-extraction, router, or trajectory format changes are included.

## Test Strategy

Implementation will follow a red-green-refactor loop. Tests will first assert:

1. The supported profile tuple contains exactly the eight canonical names.
2. Omitted or empty profiles resolve to `default`.
3. Every removed legacy name raises `ValueError`.
4. `default` enables native tools and exposes the shared `computer_use` schema.
5. Default responses with native calls survive normalization unchanged.
6. `GuiAgent` sends native tools with a required tool choice and uses the default prompt contract.
7. `general_e2e`, `gui_owl`, `venus`, `seed`, `qwen3vl`, `mai_ui`, and `gelab` continue to build and
   parse their expected formats.
8. Configuration validation and CLI choices match the strict whitelist.

Verification will include the focused profile/agent/config tests and Ruff over every touched Python
file. Broader GUIClaw tests will be run after the focused suite is green, with unrelated baseline
failures reported separately rather than hidden.

## Acceptance Criteria

- No MobileWorld benchmark-specific profile setting or alias remains in the public registry.
- `default` performs GUI actions through native `computer_use` function calls.
- Only the eight approved profile names are accepted.
- The deleted unified Prompt Builder is not restored.
- All focused tests and lint checks pass.
