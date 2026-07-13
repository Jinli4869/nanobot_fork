# GUIClaw Profile Strict Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict GUIClaw to eight canonical agent profiles and make `default` use the native `computer_use` function-call contract from `feat/opencua`.

**Architecture:** Keep profile selection, profile-specific prompt construction, and textual response parsing in `guiclaw/agents/profiles.py`. Add a default-only native-tool message path and reuse `guiclaw.tool_schemas.COMPUTER_USE_TOOL`; do not restore the deleted unified Prompt Builder. Update the existing thin re-export modules and consumers to use profile-neutral helper names.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, Ruff, GUIClaw's `LLMResponse`, `Observation`, and shared tool schemas.

---

### Task 1: Enforce the strict profile registry

**Files:**
- Create: `tests/test_guiclaw_profiles_strict.py`
- Modify: `guiclaw/agents/profiles.py:1-170`

- [ ] **Step 1: Write the failing strict-registry tests**

```python
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
```

- [ ] **Step 2: Run the tests and verify the expected failures**

Run:

```bash
/Users/jinli/Documents/Personal/nanobot_fork/.venv/bin/python -m pytest tests/test_guiclaw_profiles_strict.py -q
```

Expected: failures showing the current registry lacks `default`, accepts legacy aliases, disables native tools, and returns the MobileWorld placeholder schema.

- [ ] **Step 3: Implement the strict registry and native default metadata**

In `guiclaw/agents/profiles.py`, import `COMPUTER_USE_TOOL`, remove `planner_executor` and `PLANNER_EXECUTOR_PROMPT_TEMPLATE`, and replace the registry helpers with:

```python
from guiclaw.tool_schemas import COMPUTER_USE_TOOL

SUPPORTED_AGENT_PROFILES: tuple[str, ...] = (
    "default",
    "general_e2e",
    "gui_owl",
    "venus",
    "seed",
    "qwen3vl",
    "mai_ui",
    "gelab",
)

_MODEL_RELATIVE_GRID_HINTS = ("qwen", "gemini")


def canonicalize_agent_profile(profile_name: str | None) -> str:
    key = "default" if profile_name in (None, "") else profile_name
    if key not in SUPPORTED_AGENT_PROFILES:
        raise ValueError(
            f"Unsupported agent profile {profile_name!r}. "
            f"Expected one of: {', '.join(SUPPORTED_AGENT_PROFILES)}."
        )
    return key


def profile_uses_native_tools(profile_name: str | None) -> bool:
    return canonicalize_agent_profile(profile_name) == "default"


def coordinate_mode_for_profile(profile_name: str | None, model_name: str = "") -> str:
    profile = canonicalize_agent_profile(profile_name)
    if profile != "default":
        return "absolute"
    model = model_name.lower()
    if any(hint in model for hint in _MODEL_RELATIVE_GRID_HINTS):
        return "relative_999"
    return "absolute"


def profile_tool_definition(profile_name: str | None) -> dict[str, Any] | None:
    if canonicalize_agent_profile(profile_name) == "default":
        return COMPUTER_USE_TOOL
    return None
```

Limit `_is_general_e2e_profile()` to `general_e2e`, change dispatch keys from `gui_owl_1_5` to `gui_owl` and from `ui_venus` to `venus`, and remove the `planner_executor` branches.

- [ ] **Step 4: Run the strict-registry tests and verify they pass**

Run the Step 2 command. Expected: all tests in `test_guiclaw_profiles_strict.py` pass.

- [ ] **Step 5: Commit the strict registry**

```bash
git add guiclaw/agents/profiles.py tests/test_guiclaw_profiles_strict.py
git commit -m "refactor(gui): enforce strict agent profiles"
```

### Task 2: Add the native default prompt and response path

**Files:**
- Modify: `tests/test_guiclaw_profiles_strict.py`
- Modify: `guiclaw/agents/profiles.py:160-430`

- [ ] **Step 1: Write failing tests for default prompt construction and normalization**

Append tests that create a one-pixel PNG and an `Observation`:

```python
from pathlib import Path

from PIL import Image

from guiclaw.agent_profiles import (
    build_profile_messages,
    normalize_profile_response_for_screen,
)
from guiclaw.interfaces import LLMResponse, ToolCall
from guiclaw.observation import Observation


def _observation(path: Path) -> Observation:
    Image.new("RGB", (8, 12), "white").save(path)
    return Observation(
        screenshot_path=str(path),
        screen_width=8,
        screen_height=12,
        foreground_app="Settings",
        platform="android",
    )


def test_default_messages_use_native_opencua_contract(tmp_path: Path) -> None:
    messages = build_profile_messages(
        "default",
        task="Open Settings",
        current_observation=_observation(tmp_path / "screen.png"),
        history=[],
        model_name="gpt-4.1",
        history_image_window=3,
    )
    assert messages[0]["role"] == "system"
    assert "native tool-calling mechanism" in messages[0]["content"]
    assert "computer_use" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["text"] == "Instruction: Open Settings"
    assert messages[1]["content"][-1]["type"] == "image_url"


def test_default_normalization_preserves_native_call_with_text() -> None:
    response = LLMResponse(
        content="Action: Tap Settings",
        tool_calls=[
            ToolCall(
                id="call-1",
                name="computer_use",
                arguments={
                    "action_type": "tap",
                    "x": 100,
                    "y": 200,
                    "intent": "Open Settings",
                    "summary": "Settings icon is visible",
                },
            )
        ],
    )
    assert normalize_profile_response_for_screen(
        "default", response, screen_width=1080, screen_height=1920
    ) is response
```

- [ ] **Step 2: Run the two tests and verify import/behavior failures**

Run:

```bash
/Users/jinli/Documents/Personal/nanobot_fork/.venv/bin/python -m pytest \
  tests/test_guiclaw_profiles_strict.py::test_default_messages_use_native_opencua_contract \
  tests/test_guiclaw_profiles_strict.py::test_default_normalization_preserves_native_call_with_text -q
```

Expected: collection fails because `build_profile_messages` does not exist, or behavior fails until the default branch is implemented.

- [ ] **Step 3: Implement profile-neutral dispatch and the default-only prompt builder**

Rename `build_mobileworld_messages` to `build_profile_messages` and `parse_mobileworld_action` to `parse_profile_action`. Add a `default` dispatch before the textual profiles:

```python
def build_profile_messages(...):
    profile = canonicalize_agent_profile(profile_name)
    if profile == "default":
        return _build_default_messages(
            task=task,
            current_observation=current_observation,
            history=history,
        )
    # existing seven profile branches follow
```

Build the default system prompt from the `feat/opencua` contract and the shared schema:

```python
def _build_default_messages(
    *, task: str, current_observation: Observation, history: list[Any]
) -> list[dict[str, Any]]:
    schema = json.dumps(COMPUTER_USE_TOOL, ensure_ascii=False)
    contract = prompt_contract_for_profile("default")
    system_lines = [
        "# Tools",
        "",
        "You may call one function to assist with the user query.",
        "You are provided with function signatures within <tools></tools> XML tags:",
        "<tools>",
        schema,
        "</tools>",
        "",
        "# Environment",
        "",
        "- You are operating on a GUI screen and can only act through the available native tools.",
        "- Use the latest screenshot as the source of truth.",
        "- Execute one action per step.",
        "",
        "# Response format",
        "",
        *contract["format"],
        "",
        "Rules:",
        *contract["rules"],
    ]
    progress = [turn.action_summary for turn in history[-3:] if turn.action_summary.strip()]
    user_lines = [f"Instruction: {task}"]
    if progress:
        user_lines.extend(["", "Recent progress:", *[f"- {item}" for item in progress]])
    return [
        {"role": "system", "content": "\n".join(system_lines)},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "\n".join(user_lines)},
                _image_content(current_observation),
            ],
        },
    ]
```

Make the `default` prompt contract match `feat/opencua`, including one `Action:` line, exactly one native call, `intent`, `summary`, `done`, and `request_intervention` rules. In normalization, return the response immediately when the canonical profile is `default`; textual profiles continue through `parse_profile_action()`.

Delete `_build_planner_executor_messages()` and the planner parser branch.

- [ ] **Step 4: Run the Task 2 tests and full strict test file**

Run:

```bash
/Users/jinli/Documents/Personal/nanobot_fork/.venv/bin/python -m pytest tests/test_guiclaw_profiles_strict.py -q
```

Expected: all strict/default tests pass.

- [ ] **Step 5: Commit the default prompt path**

```bash
git add guiclaw/agents/profiles.py tests/test_guiclaw_profiles_strict.py
git commit -m "feat(gui): restore native default profile"
```

### Task 3: Migrate consumers and exercise GuiAgent native calling

**Files:**
- Modify: `guiclaw/agent_profiles.py`
- Modify: `guiclaw/agents/__init__.py`
- Modify: `guiclaw/agent.py:20-40,2182-2205`
- Modify: `guiclaw/skills/subgoal_runner.py:20-32`
- Modify: `tests/test_guiclaw_profiles_strict.py`
- Modify: `tests/test_guiclaw_mobileworld_agents.py`

- [ ] **Step 1: Add a failing GuiAgent native-call test**

Add an async recording provider that returns `done` through `computer_use` and assert the call contract:

```python
@pytest.mark.asyncio
async def test_gui_agent_default_uses_required_native_tool_call(tmp_path: Path) -> None:
    class RecordingLLM:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def chat(self, **kwargs):  # noqa: ANN003, ANN202
            self.calls.append(kwargs)
            return LLMResponse(
                content="Action: Finish the completed task",
                tool_calls=[
                    ToolCall(
                        id="done-1",
                        name="computer_use",
                        arguments={
                            "action_type": "done",
                            "status": "success",
                            "text": "Task completed",
                            "intent": "Finish",
                            "summary": "Task is complete",
                        },
                    )
                ],
            )

    llm = RecordingLLM()
    agent = GuiAgent(
        llm,
        DryRunBackend(),
        TrajectoryRecorder(output_dir=tmp_path / "traj", task="native default"),
        artifacts_root=tmp_path / "runs",
        max_steps=1,
        agent_profile="default",
    )
    result = await agent.run("Finish", max_retries=1)
    assert result.success is True
    assert llm.calls[0]["tool_choice"] == "required"
    assert llm.calls[0]["tools"][0]["function"]["name"] == "computer_use"
    assert "native tool-calling mechanism" in llm.calls[0]["messages"][0]["content"]
```

Import `GuiAgent`, `DryRunBackend`, and `TrajectoryRecorder` in the test file.

- [ ] **Step 2: Run the GuiAgent test and verify the old helper import/default path fails**

Run the single new test with pytest. Expected: failure until all consumer imports and `_build_messages()` call `build_profile_messages`.

- [ ] **Step 3: Update all consumers and re-exports**

Replace imports and `__all__` entries for:

```python
build_mobileworld_messages -> build_profile_messages
parse_mobileworld_action -> parse_profile_action
```

Update `GuiAgent._build_messages()` and `SubgoalRunner` to call `build_profile_messages`. Keep the existing task/memory/compact-skill arguments intact. Update the existing MobileWorld-oriented agent test so its textual-history case explicitly selects `agent_profile="general_e2e"` rather than relying on the old default alias.

- [ ] **Step 4: Run consumer/profile regression tests**

Run:

```bash
/Users/jinli/Documents/Personal/nanobot_fork/.venv/bin/python -m pytest \
  tests/test_guiclaw_profiles_strict.py \
  tests/test_guiclaw_mobileworld_agents.py \
  tests/test_guiclaw.py -q
```

Expected: all tests pass after obsolete default/alias assertions in the existing tests are updated to the strict contract.

- [ ] **Step 5: Commit consumer migration**

```bash
git add guiclaw/agent_profiles.py guiclaw/agents/__init__.py guiclaw/agent.py \
  guiclaw/skills/subgoal_runner.py tests/test_guiclaw_profiles_strict.py \
  tests/test_guiclaw_mobileworld_agents.py tests/test_guiclaw.py
git commit -m "refactor(gui): migrate profile consumers"
```

### Task 4: Align configuration, CLI documentation, and final verification

**Files:**
- Modify: `tests/test_guiclaw_p3_nanobot.py`
- Modify: `tests/test_guiclaw.py`
- Modify: `tests/test_guiclaw_mobileworld_agents.py`
- Modify: `guiclaw/README.md`
- Modify: `guiclaw/README_CN.md`

- [ ] **Step 1: Replace the old config acceptance test with strict validation**

Change the assertion that accepts `mobileworld_general_e2e_compact_skill` to:

```python
def test_gui_config_uses_strict_agent_profile_whitelist() -> None:
    assert GuiConfig(agent_profile=None).agent_profile is None
    assert GuiConfig(agent_profile="default").agent_profile == "default"
    assert GuiConfig(agent_profile="gui_owl").agent_profile == "gui_owl"
    with pytest.raises(ValueError, match="Unsupported agent profile"):
        GuiConfig(agent_profile="mobileworld_general_e2e_compact_skill")
```

- [ ] **Step 2: Run the config test and verify it fails before expectation cleanup**

Run the exact new test. Expected: it fails until the registry and old assertions are consistently migrated.

- [ ] **Step 3: Update English and Chinese profile documentation**

Make both README profile tables list exactly the eight canonical values. Document `default` as native `computer_use`; remove `planner_executor`, MobileWorld aliases, `gui_owl_1_5`, and `ui_venus` configuration examples. Retain provenance descriptions only where useful for the seven model-specific implementations.

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```bash
/Users/jinli/Documents/Personal/nanobot_fork/.venv/bin/python -m pytest \
  tests/test_guiclaw_profiles_strict.py \
  tests/test_guiclaw_mobileworld_agents.py \
  tests/test_guiclaw.py \
  tests/test_guiclaw_p3_nanobot.py \
  tests/test_guiclaw_p5_cli.py -q

/Users/jinli/Documents/Personal/nanobot_fork/.venv/bin/ruff check \
  guiclaw/agents/profiles.py guiclaw/agent_profiles.py guiclaw/agents/__init__.py \
  guiclaw/agent.py guiclaw/skills/subgoal_runner.py \
  tests/test_guiclaw_profiles_strict.py tests/test_guiclaw_mobileworld_agents.py \
  tests/test_guiclaw.py tests/test_guiclaw_p3_nanobot.py
```

Expected: all focused tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 5: Run broader GUIClaw regression coverage**

Run:

```bash
/Users/jinli/Documents/Personal/nanobot_fork/.venv/bin/python -m pytest tests -q
```

If unrelated baseline failures remain, compare them with the documented baseline and report them separately. Any profile/config/agent regression must be fixed before completion.

- [ ] **Step 6: Commit documentation and verification cleanup**

```bash
git add guiclaw/README.md guiclaw/README_CN.md tests/test_guiclaw_p3_nanobot.py
git commit -m "docs(gui): document strict agent profiles"
```

### Task 5: Integrate the verified feature branch

**Files:**
- No source edits expected.

- [ ] **Step 1: Confirm the worktree is clean and inspect the commit range**

```bash
git status --short --branch
git log --oneline lychee_guiclaw..HEAD
```

Expected: clean `codex/guiclaw-strict-profiles` worktree with the plan and implementation commits.

- [ ] **Step 2: Fast-forward `lychee_guiclaw` from the primary workspace**

```bash
git -C /Users/jinli/Documents/Personal/nanobot_fork merge --ff-only codex/guiclaw-strict-profiles
```

- [ ] **Step 3: Re-run the focused test and Ruff commands from the primary workspace**

Expected: the same passing counts and clean lint output as the feature worktree.

- [ ] **Step 4: Remove the worktree and feature branch after successful verification**

```bash
git -C /Users/jinli/Documents/Personal/nanobot_fork worktree remove \
  /Users/jinli/Documents/Personal/nanobot_fork/.worktrees/guiclaw-strict-profiles
git -C /Users/jinli/Documents/Personal/nanobot_fork branch -d codex/guiclaw-strict-profiles
```
