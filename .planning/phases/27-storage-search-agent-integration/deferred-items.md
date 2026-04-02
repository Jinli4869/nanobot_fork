# Deferred Items

Out-of-scope failures observed while running `uv run pytest -q` during `27-02` closeout on 2026-04-02:

- `tests/cli/test_commands.py::test_agent_uses_default_config_when_no_workspace_or_config_flags`
- `tests/test_gui_skill_executor_wiring.py::TestSkillExecutorWiringDisabled::test_skill_executor_is_none_when_disabled`
- `tests/test_gui_skill_executor_wiring.py::TestSkillExecutorWiringEnabled::test_skill_executor_is_passed_when_enabled`
- `tests/test_gui_skill_executor_wiring.py::TestSkillExecutorWiringEnabled::test_skill_executor_built_with_correct_backend`
- `tests/test_gui_skill_executor_wiring.py::TestSkillExecutorWiringEnabled::test_skill_executor_built_with_llm_state_validator`
- `tests/test_opengui.py::test_agent_waits_for_ui_to_settle_before_observing`
- `tests/test_opengui_agent_loop.py::test_router_dispatches_planner_atoms_by_capability`
- `tests/test_opengui_agent_loop.py::test_router_executes_uppercase_plan_node_types`
- `tests/test_opengui_p11_integration.py::test_gui_tool_returns_before_background_postprocessing_finishes`
- `tests/test_opengui_p3_nanobot.py::test_gui_tool_registered`
- `tests/test_opengui_p6_wiring.py::test_gui_tool_builds_memory_retriever_from_default_opengui_dir`
- `tests/test_opengui_p6_wiring.py::test_gui_tool_passes_memory_retriever_to_gui_agent`
- `tests/test_opengui_p8_planning.py::test_and_respects_max_concurrency`
- `tests/test_opengui_p8_planning.py::test_and_no_shared_list_mutation`

These failures were not introduced by the Phase 27 plan work. Plan-scoped verification remained green:

- `uv run pytest tests/test_opengui_p27_storage_search_agent.py -q`
- `uv run pytest tests/test_opengui_p24_schema_grounding.py tests/test_opengui_p25_multi_layer_execution.py tests/test_opengui_p26_quality_gated_extraction.py -q`
- `uv run python -c "from opengui.agent import GuiAgent; from nanobot.agent.tools.gui import GuiSubagentTool; print('OK')"`
