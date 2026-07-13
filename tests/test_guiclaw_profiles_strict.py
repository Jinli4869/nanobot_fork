from __future__ import annotations

import pytest

from guiclaw.agent_profiles import (
    SUPPORTED_AGENT_PROFILES,
    canonicalize_agent_profile,
    coordinate_mode_for_profile,
    profile_tool_definition,
    profile_uses_native_tools,
)
from guiclaw.tool_schemas import COMPUTER_USE_TOOL


EXPECTED_PROFILES = (
    "default",
    "general_e2e",
    "gui_owl",
    "venus",
    "seed",
    "qwen3vl",
    "mai_ui",
    "gelab",
)


def test_supported_profiles_are_strict_public_whitelist() -> None:
    assert SUPPORTED_AGENT_PROFILES == EXPECTED_PROFILES
    assert canonicalize_agent_profile(None) == "default"
    assert canonicalize_agent_profile("") == "default"


@pytest.mark.parametrize(
    "legacy",
    [
        "mobileworld_general_e2e",
        "mobileworld_general_e2e_compact_skill",
        "planner_executor",
        "general",
        "general_e2e_compact_skill",
        "mw-general-e2e",
        "gui_owl_1_5",
        "gui-owl-1.5",
        "ui_venus",
    ],
)
def test_legacy_profile_names_are_rejected(legacy: str) -> None:
    with pytest.raises(ValueError, match="Unsupported agent profile"):
        canonicalize_agent_profile(legacy)


def test_default_is_the_only_native_tool_profile() -> None:
    assert profile_uses_native_tools("default") is True
    for profile in EXPECTED_PROFILES[1:]:
        assert profile_uses_native_tools(profile) is False
    assert profile_tool_definition("default") is COMPUTER_USE_TOOL
    assert profile_tool_definition("general_e2e") is None


def test_default_coordinate_mode_preserves_opencua_model_hints() -> None:
    assert coordinate_mode_for_profile("default", "gpt-4.1") == "absolute"
    assert coordinate_mode_for_profile("default", "qwen-vl-max") == "relative_999"
    assert coordinate_mode_for_profile("default", "gemini-2.5-pro") == "relative_999"
    assert coordinate_mode_for_profile("general_e2e", "qwen-vl-max") == "absolute"
