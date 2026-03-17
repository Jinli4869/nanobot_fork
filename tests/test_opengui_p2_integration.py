"""Phase 2 integration test stubs — Wave 0.

These tests are xfail stubs created before production code.
Each will be replaced with a real implementation in plan 02-04 (Wave 3).
"""
from __future__ import annotations
import pytest


# AGENT-04: Memory entries appear in system prompt
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_memory_injected_into_system_prompt(tmp_path):
    """GuiAgent.run() should inject memory entries into the system prompt."""
    pytest.fail("Not implemented — awaiting plan 02-02 + 02-04")


# AGENT-05: Skill matched above threshold triggers SkillExecutor path
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_skill_path_chosen_above_threshold(tmp_path):
    """When a matching skill exists above threshold, GuiAgent should use SkillExecutor."""
    pytest.fail("Not implemented — awaiting plan 02-02 + 02-04")


# AGENT-05: No skill match falls through to free explore
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_free_explore_when_no_skill_match(tmp_path):
    """When no skill matches, GuiAgent should use free exploration."""
    pytest.fail("Not implemented — awaiting plan 02-02 + 02-04")


# AGENT-06 + TRAJ-03: Trajectory recording
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_trajectory_recorded_on_run(tmp_path):
    """Every agent run should produce a JSONL trajectory with metadata/step/result."""
    pytest.fail("Not implemented — awaiting plan 02-02 + 02-04")


# AGENT-04: TaskPlanner decomposes task
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_planner_decomposes_task(tmp_path):
    """TaskPlanner should decompose a task into an AND/OR/ATOM tree."""
    pytest.fail("Not implemented — awaiting plan 02-03 + 02-04")


# AGENT-04/05/06: Router dispatches atoms by capability type
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_router_dispatches_gui_and_tool_atoms(tmp_path):
    """TreeRouter should dispatch ATOM nodes to correct executor by capability."""
    pytest.fail("Not implemented — awaiting plan 02-03 + 02-04")


# AGENT-04: Router replans on AND-child failure
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_router_replans_on_and_child_failure(tmp_path):
    """On AND-child failure, the router should trigger replanning."""
    pytest.fail("Not implemented — awaiting plan 02-03 + 02-04")


# TEST-05: Full flow with mock LLM + memory + skills
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_full_flow_with_mock_llm(tmp_path):
    """Full flow with DryRunBackend + mock LLM + pre-seeded memory + skill runs to completion."""
    pytest.fail("Not implemented — awaiting plan 02-04")
