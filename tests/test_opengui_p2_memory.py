"""Phase 2 memory test stubs — Wave 0.

These tests are xfail stubs created before production code.
Each will be replaced with a real implementation in plan 02-04 (Wave 3).
"""
from __future__ import annotations
import pytest


# MEM-05: POLICY entries always included regardless of relevance
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_policy_always_included(tmp_path):
    """POLICY memory entries should always appear in system prompt regardless of relevance score."""
    pytest.fail("Not implemented — awaiting plan 02-02 + 02-04")


# MEM-05: Memory context formatted correctly
@pytest.mark.xfail(reason="Wave 0 stub — implementation in 02-04", strict=False)
async def test_memory_context_formatted_in_system_prompt(tmp_path):
    """Memory context should be formatted and passed to build_system_prompt()."""
    pytest.fail("Not implemented — awaiting plan 02-02 + 02-04")
