# Quick Task 260403-soi: 把 gui.agent_profile 配置项正式补上

**Status:** Completed
**Created:** 2026-04-03

## Goal

Make `gui.agent_profile` a first-class nanobot config field so GUI profile selection works through config loading, validation, runtime wiring, and user-facing documentation.

## Tasks

### Task 1
- files: `nanobot/config/schema.py`, `nanobot/agent/tools/gui.py`
- action: Add a formal `GuiConfig.agent_profile` field, validate it through the shared OpenGUI profile canonicalization seam, and remove runtime `getattr(...)` fallbacks in nanobot GUI wiring.
- verify: `GuiConfig` accepts `agentProfile` and `agent_profile`, rejects invalid values, and `GuiAgent` receives the configured profile.
- done: GUI profile selection is a supported config surface instead of an undocumented extra field.

### Task 2
- files: `tests/test_opengui_p3_nanobot.py`, `tests/test_gui_skill_executor_wiring.py`
- action: Add failing tests first for config defaults/validation and nanobot GUI-agent wiring.
- verify: New tests fail before implementation and pass after the schema/wiring changes.
- done: Regression coverage protects the config entry point and execution handoff.

### Task 3
- files: `opengui/README.md`, `opengui/README_CN.md`, `.planning/STATE.md`, `.planning/quick/260403-soi-gui-agent-profile/260403-soi-SUMMARY.md`
- action: Document `gui.agentProfile` in the config examples/reference tables and record the quick task outcome in planning artifacts.
- verify: README tables list `agentProfile`, summary exists, and `STATE.md` includes the quick-task row.
- done: The new config option is discoverable in both docs and planning history.
