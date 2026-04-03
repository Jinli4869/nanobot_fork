# Quick Task 260403-rhj: 根据 /Users/jinli/Documents/Project/MobileWorld/src/mobile_world/agents/implementations 里的 general_e2e、qwen3vl、mai_ui、gelab、seed agent，为 opengui 适配不同 agent 的动作空间和 prompt

**Status:** In Progress
**Created:** 2026-04-03

## Goal

Add an explicit OpenGUI agent-profile layer so selected MobileWorld-style agent variants can customize prompt format, action schema, response parsing, and coordinate handling without branching the main `GuiAgent` loop.

## Tasks

### Task 1
- files: `opengui/agent.py`, `opengui/prompts/system.py`, `opengui/interfaces.py`, `opengui/cli.py`
- action: Introduce a configurable agent-profile seam that controls prompt/tool construction, response-to-action parsing, and coordinate normalization for `general_e2e`, `qwen3vl`, `mai_ui`, `gelab`, and `seed`.
- verify: Targeted unit tests cover profile selection, prompt/schema differences, and content-only parser fallbacks.
- done: `GuiAgent` can run with a named profile instead of assuming one hard-coded `computer_use` contract.

### Task 2
- files: `tests/test_opengui.py`, `tests/test_opengui_p5_cli.py`
- action: Add failing tests first for selected profile prompt wording, parser normalization, relative-coordinate behavior, and CLI/config profile plumbing.
- verify: New tests fail before implementation and pass after the code changes.
- done: Regression coverage demonstrates each supported profile maps MobileWorld-style output into OpenGUI `Action`s.

### Task 3
- files: `.planning/STATE.md`, `.planning/quick/260403-rhj-users-jinli-documents-project-mobileworl/260403-rhj-SUMMARY.md`
- action: Record the completed quick task, summarize implementation choices, and link the artifact directory in planning state.
- verify: Planning artifacts exist and `STATE.md` includes a new quick-task row.
- done: Quick-task bookkeeping is complete and ready for commit.
