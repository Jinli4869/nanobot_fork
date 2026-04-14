"""
Unit tests for the opengui skills module (TEST-03).

Covers:
  - SkillLibrary CRUD (add, get, remove, list_all, count) with JSON persistence
  - SkillLibrary hybrid BM25+FAISS search and BM25-only search
  - SkillLibrary deduplication: heuristic merge decision for near-duplicates
  - SkillExecutor per-step valid_state verification (pass, fail, no-validator)
  - SkillExtractor: LLM JSON response parsing into Skill and <2 steps edge case

All tests use tmp_path for file isolation.
No network calls, no real LLM, no real device (DryRunBackend + fakes only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from opengui.backends.dry_run import DryRunBackend
from opengui.interfaces import LLMResponse
from opengui.skills import Skill, SkillStep
from opengui.skills.executor import ExecutionState, SkillExecutor
from opengui.skills.extractor import SkillExtractor
from opengui.skills.library import SkillLibrary


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    """Deterministic fake EmbeddingProvider.

    Each text is hashed to a unique dimension slot so FAISS ranking is
    deterministic without a real embedding API.  Unit-vector embeddings (float32)
    satisfy the inner-product similarity used by FAISS IndexFlatIP.
    """

    DIM = 8

    async def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            slot = hash(text) % self.DIM
            vecs[i, slot] = 1.0
        return vecs


class _ScriptedLLM:
    """Returns canned LLMResponse objects in order.

    Used to drive SkillExtractor without a real LLM.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = [LLMResponse(content=r) for r in responses]
        self.messages: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        self.messages.append(messages)
        if not self._responses:
            raise AssertionError("_ScriptedLLM has no remaining scripted responses.")
        return self._responses.pop(0)


class _FakeValidator:
    """Pops boolean results from a pre-loaded list for per-step validation."""

    def __init__(self, returns: list[bool]) -> None:
        self._returns = list(returns)

    async def validate(
        self,
        valid_state: str,
        screenshot: Path | bytes | None = None,
    ) -> bool:
        if not self._returns:
            raise AssertionError("_FakeValidator has no remaining results.")
        return self._returns.pop(0)


class _CapturingRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record_event(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


# ---------------------------------------------------------------------------
# Skill factory helper
# ---------------------------------------------------------------------------


def _make_skill(
    skill_id: str,
    name: str,
    description: str,
    *,
    app: str = "com.example.app",
    platform: str = "android",
    action_types: list[str] | None = None,
    tags: tuple[str, ...] = (),
) -> Skill:
    """Factory for Skill with sensible defaults."""
    steps: tuple[SkillStep, ...] = ()
    if action_types:
        steps = tuple(
            SkillStep(action_type=at, target=f"element_{i}")
            for i, at in enumerate(action_types)
        )
    return Skill(
        skill_id=skill_id,
        name=name,
        description=description,
        app=app,
        platform=platform,
        steps=steps,
        tags=tags,
        created_at=1_700_000_000.0,
    )


# ---------------------------------------------------------------------------
# SkillLibrary — CRUD tests (sync)
# ---------------------------------------------------------------------------


def test_opengui_skills_module_exports_core_types() -> None:
    assert Skill.__name__ == "Skill"
    assert SkillStep.__name__ == "SkillStep"

    import opengui.skills as skills_pkg
    exported = set(skills_pkg.__all__)
    assert "Skill" in exported
    assert "SkillStep" in exported
    assert "SkillLibrary" in exported
    assert "SkillExtractor" in exported
    assert "SkillExecutor" in exported


def test_skill_library_crud(tmp_path: Path) -> None:
    """add() stores a skill; get() retrieves it; count reflects changes; remove() deletes it."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_crud")

    skill = _make_skill("s1", "Open Settings", "Navigates to the device settings screen")
    lib.add(skill)

    assert lib.count == 1
    retrieved = lib.get("s1")
    assert retrieved is not None
    assert retrieved.skill_id == "s1"
    assert retrieved.name == "Open Settings"

    removed = lib.remove("s1")
    assert removed is True
    assert lib.count == 0
    assert lib.get("s1") is None


def test_skill_library_remove_nonexistent_returns_false(tmp_path: Path) -> None:
    """remove() on a missing skill_id returns False without raising."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_remove")
    assert lib.remove("does-not-exist") is False


def test_skill_library_persists_to_disk(tmp_path: Path) -> None:
    """Skill added to one SkillLibrary instance is visible from a fresh instance at the same path."""
    store_path = tmp_path / "skills_persist"

    lib1 = SkillLibrary(store_dir=store_path)
    skill = _make_skill("s-persist", "Swipe Up", "Swipe the screen upward")
    lib1.add(skill)

    # Reload: __post_init__ calls load_all()
    lib2 = SkillLibrary(store_dir=store_path)
    reloaded = lib2.get("s-persist")

    assert reloaded is not None
    assert reloaded.name == "Swipe Up"
    assert reloaded.skill_id == "s-persist"


def test_skill_library_refresh_if_stale_sees_added_skill(tmp_path: Path) -> None:
    store_path = tmp_path / "skills_refresh_add"
    lib_a = SkillLibrary(store_dir=store_path)
    lib_b = SkillLibrary(store_dir=store_path)

    lib_b.add(_make_skill("s-new", "Open Calendar", "Launch the calendar app"))

    assert lib_a.get("s-new") is None
    assert lib_a.refresh_if_stale() is True
    refreshed = lib_a.get("s-new")
    assert refreshed is not None
    assert refreshed.skill_id == "s-new"


def test_skill_library_refresh_if_stale_returns_false_when_unchanged(tmp_path: Path) -> None:
    lib = SkillLibrary(store_dir=tmp_path / "skills_refresh_clean")

    assert lib.refresh_if_stale() is False


def test_skill_library_refresh_if_stale_sees_removed_skill(tmp_path: Path) -> None:
    store_path = tmp_path / "skills_refresh_remove"
    lib_a = SkillLibrary(store_dir=store_path)
    lib_b = SkillLibrary(store_dir=store_path)

    lib_b.add(_make_skill("s-gone", "Volume Down", "Lower the device volume"))
    assert lib_a.refresh_if_stale() is True
    assert lib_a.get("s-gone") is not None

    assert lib_b.remove("s-gone") is True
    assert lib_a.refresh_if_stale() is True
    assert lib_a.get("s-gone") is None


def test_skill_library_refresh_if_stale_handles_missing_store_dir(tmp_path: Path) -> None:
    lib = SkillLibrary(store_dir=tmp_path / "skills_missing_dir")

    assert lib.refresh_if_stale() is False


def test_skill_library_list_all_returns_all_skills(tmp_path: Path) -> None:
    """list_all() returns every stored skill when no filters are applied."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_list")

    skills = [
        _make_skill("la1", "Open Browser", "Launch the default browser"),
        _make_skill("la2", "Take Screenshot", "Capture current screen"),
        _make_skill("la3", "Volume Up", "Increase device volume"),
    ]
    for s in skills:
        lib.add(s)

    all_skills = lib.list_all()
    assert len(all_skills) == 3
    ids = {s.skill_id for s in all_skills}
    assert ids == {"la1", "la2", "la3"}


def test_skill_library_list_all_filters_by_platform(tmp_path: Path) -> None:
    """list_all(platform=...) filters to the requested platform."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_filter")

    android_skill = _make_skill("a1", "Open Settings", "Android settings", platform="android")
    ios_skill = _make_skill("i1", "Open Preferences", "iOS preferences", platform="ios")
    lib.add(android_skill)
    lib.add(ios_skill)

    android_only = lib.list_all(platform="android")
    assert len(android_only) == 1
    assert android_only[0].skill_id == "a1"


def test_skill_library_normalizes_app_filter_aliases(tmp_path: Path) -> None:
    """Package-name and natural-language app filters resolve to the same bucket."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_filter_normalized")

    lib.add(
        _make_skill(
            "settings-1",
            "Open Settings",
            "Android settings",
            app="Settings",
            platform="android",
        )
    )

    package_filtered = lib.list_all(platform="android", app="com.android.settings")
    name_filtered = lib.list_all(platform="android", app="settings")

    assert len(package_filtered) == 1
    assert len(name_filtered) == 1
    assert package_filtered[0].app == "com.android.settings"
    assert name_filtered[0].skill_id == "settings-1"


# ---------------------------------------------------------------------------
# SkillLibrary — search tests (async)
# ---------------------------------------------------------------------------


async def test_skill_library_search_bm25_only(tmp_path: Path) -> None:
    """BM25-only search (no embedding_provider) returns the most relevant skill first."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_bm25", embedding_provider=None)

    # Add three skills with clearly distinct keyword coverage
    lib.add(_make_skill("bm-vol", "Volume Control", "Adjust speaker volume level"))
    lib.add(_make_skill("bm-cam", "Camera Capture", "Take a photo with the camera"))
    lib.add(_make_skill("bm-wifi", "WiFi Toggle", "Enable or disable wireless network"))

    results = await lib.search("volume speaker adjust")

    assert len(results) > 0
    top_skill, top_score = results[0]
    assert top_skill.skill_id == "bm-vol"


async def test_skill_library_search_hybrid(tmp_path: Path) -> None:
    """Hybrid search (BM25+FAISS) returns results when embedding_provider is set."""
    embedder = _FakeEmbedder()
    lib = SkillLibrary(store_dir=tmp_path / "skills_hybrid", embedding_provider=embedder)

    lib.add(_make_skill("hyb-1", "Open Settings", "Navigate to device settings"))
    lib.add(_make_skill("hyb-2", "Play Music", "Start music playback in media player"))

    results = await lib.search("settings navigation")

    assert len(results) > 0
    assert all(isinstance(score, float) for _, score in results)


async def test_skill_library_search_empty_library(tmp_path: Path) -> None:
    """search() on an empty library returns an empty list."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_empty_search")
    results = await lib.search("anything")
    assert results == []


# ---------------------------------------------------------------------------
# SkillLibrary — deduplication tests (async)
# ---------------------------------------------------------------------------


async def test_skill_library_dedup_merges_similar(tmp_path: Path) -> None:
    """add_or_merge() with a near-duplicate skill triggers a merge decision (not ADD)."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_dedup_merge", merge_llm=None)

    # s1 and s2 share the same normalized name and similar action sequence
    s1 = _make_skill(
        "dup-1",
        "Open Settings",
        "Navigate to settings",
        action_types=["tap", "scroll"],
    )
    s2 = _make_skill(
        "dup-2",
        "Open Settings",
        "Go to the settings screen with updated description",
        action_types=["tap", "scroll"],
    )

    lib.add(s1)
    decision, result_id = await lib.add_or_merge(s2)

    # Near-duplicate with same name + similar action sequence triggers merge heuristic
    assert decision in ("MERGE", "KEEP_OLD", "KEEP_NEW")
    # Count must remain 1 (one canonical skill)
    assert lib.count == 1


async def test_skill_library_dedup_adds_distinct(tmp_path: Path) -> None:
    """add_or_merge() with a genuinely different skill adds it without merging."""
    lib = SkillLibrary(store_dir=tmp_path / "skills_dedup_add", merge_llm=None)

    s1 = _make_skill("dist-1", "Open Settings", "Navigate to settings", action_types=["tap"])
    s2 = _make_skill(
        "dist-2",
        "Record Screen Video",
        "Capture screen recording footage",
        action_types=["swipe", "input_text", "tap"],
    )

    lib.add(s1)
    decision, result_id = await lib.add_or_merge(s2)

    assert decision == "ADD"
    assert lib.count == 2


async def test_skill_library_merges_same_app_alias_into_one_bucket(tmp_path: Path) -> None:
    """Alias and package-name variants for the same app deduplicate into one normalized bucket."""
    store_dir = tmp_path / "skills_dedup_alias"
    lib = SkillLibrary(store_dir=store_dir, merge_llm=None)

    lib.add(
        _make_skill(
            "alias-old",
            "Open Settings",
            "Navigate to settings",
            app="Settings",
            platform="android",
            action_types=["tap", "scroll"],
        )
    )
    decision, result_id = await lib.add_or_merge(
        _make_skill(
            "alias-new",
            "Open Settings",
            "Navigate to Android settings",
            app="com.android.settings",
            platform="android",
            action_types=["tap", "scroll"],
        )
    )

    reloaded = SkillLibrary(store_dir=store_dir, merge_llm=None)
    normalized_bucket = store_dir / "android" / "skills.json"

    assert decision in ("MERGE", "KEEP_OLD", "KEEP_NEW")
    assert result_id is not None
    assert lib.count == 1
    assert normalized_bucket.is_file()
    assert len(reloaded.list_all(platform="android", app="Settings")) == 1
    assert reloaded.list_all(platform="android", app="com.android.settings")[0].app == "com.android.settings"


def test_load_all_reads_legacy_nested_skill_files_without_flat_platform_file(tmp_path: Path) -> None:
    store_dir = tmp_path / "gui_skills"
    legacy_bucket = store_dir / "android" / "com.android.settings"
    legacy_bucket.mkdir(parents=True)
    payload = {
        "skills": [
            _make_skill(
                "legacy-settings",
                "Open Settings",
                "Navigate to Android settings",
                app="Settings",
                platform="android",
                action_types=["tap"],
            ).to_dict()
        ]
    }
    (legacy_bucket / "skills.json").write_text(json.dumps(payload), encoding="utf-8")

    lib = SkillLibrary(store_dir=store_dir, merge_llm=None)

    assert lib.count == 1
    assert lib.list_all(platform="android", app="com.android.settings")[0].skill_id == "legacy-settings"


# ---------------------------------------------------------------------------
# SkillExecutor — tests (async)
# ---------------------------------------------------------------------------


async def test_executor_succeeds_on_valid_state(tmp_path: Path) -> None:
    """Executor returns SUCCEEDED when the state validator approves each step."""
    step = SkillStep(
        action_type="tap",
        target="Settings button",
        valid_state="Settings button is visible on the home screen",
    )
    skill = Skill(
        skill_id="exec-pass",
        name="Tap Settings",
        description="Tap the settings button",
        app="com.android.settings",
        platform="android",
        steps=(step,),
    )

    executor = SkillExecutor(
        backend=DryRunBackend(),
        state_validator=_FakeValidator(returns=[True]),
        stop_on_failure=True,
    )
    result = await executor.execute(skill)

    assert result.state == ExecutionState.SUCCEEDED
    assert len(result.step_results) == 1
    assert result.step_results[0].valid_state_check is True


async def test_executor_stops_on_failed_state_check(tmp_path: Path) -> None:
    """Executor returns FAILED and records the failed check when state validation fails."""
    step = SkillStep(
        action_type="tap",
        target="Submit button",
        valid_state="Form is fully filled in",
    )
    skill = Skill(
        skill_id="exec-fail",
        name="Submit Form",
        description="Submit the form",
        app="com.example.forms",
        platform="android",
        steps=(step,),
    )

    executor = SkillExecutor(
        backend=DryRunBackend(),
        state_validator=_FakeValidator(returns=[False]),
        stop_on_failure=True,
    )
    result = await executor.execute(skill)

    assert result.state == ExecutionState.FAILED
    assert len(result.step_results) == 1
    assert result.step_results[0].valid_state_check is False


async def test_executor_no_validator_skips_check(tmp_path: Path) -> None:
    """Executor with state_validator=None skips checks and still succeeds."""
    step = SkillStep(
        action_type="scroll",
        target="Content area",
        valid_state="Content area is scrollable",
    )
    skill = Skill(
        skill_id="exec-no-val",
        name="Scroll Down",
        description="Scroll the content area down",
        app="com.example.reader",
        platform="android",
        steps=(step,),
    )

    executor = SkillExecutor(
        backend=DryRunBackend(),
        state_validator=None,
        stop_on_failure=True,
    )
    result = await executor.execute(skill)

    assert result.state == ExecutionState.SUCCEEDED


async def test_executor_multi_step_all_pass(tmp_path: Path) -> None:
    """All steps pass state validation → SUCCEEDED with all step results successful."""
    steps = (
        SkillStep(action_type="tap", target="App icon", valid_state="Home screen visible"),
        SkillStep(action_type="input_text", target="Search box", valid_state="Search field visible"),
        SkillStep(action_type="tap", target="Search button", valid_state="Keyboard is open"),
    )
    skill = Skill(
        skill_id="exec-multi",
        name="Search For Item",
        description="Open app and search for an item",
        app="com.example.store",
        platform="android",
        steps=steps,
    )

    executor = SkillExecutor(
        backend=DryRunBackend(),
        state_validator=_FakeValidator(returns=[True, True, True]),
        stop_on_failure=True,
    )
    result = await executor.execute(skill)

    assert result.state == ExecutionState.SUCCEEDED
    assert len(result.step_results) == 3
    assert all(sr.valid_state_check is True for sr in result.step_results)


async def test_executor_records_skill_events(tmp_path: Path) -> None:
    step = SkillStep(
        action_type="tap",
        target="Settings button",
        valid_state="Settings button is visible on the home screen",
    )
    skill = Skill(
        skill_id="exec-telemetry",
        name="Tap Settings",
        description="Tap the settings button",
        app="com.android.settings",
        platform="android",
        steps=(step,),
    )
    recorder = _CapturingRecorder()
    executor = SkillExecutor(
        backend=DryRunBackend(),
        state_validator=_FakeValidator(returns=[True]),
        trajectory_recorder=recorder,
        stop_on_failure=True,
    )

    result = await executor.execute(skill)

    assert result.state == ExecutionState.SUCCEEDED
    event_names = [event for event, _ in recorder.events]
    assert event_names == [
        "skill_execution_start",
        "skill_step",
        "skill_execution_result",
    ]
    assert recorder.events[1][1]["skill_id"] == "exec-telemetry"
    assert recorder.events[1][1]["action_summary"] == "tap on Settings button"
    assert recorder.events[2][1]["state"] == "succeeded"


async def test_executor_records_skill_failure_events(tmp_path: Path) -> None:
    step = SkillStep(
        action_type="tap",
        target="Submit button",
        valid_state="Form is fully filled in",
    )
    skill = Skill(
        skill_id="exec-fail-telemetry",
        name="Submit Form",
        description="Submit the form",
        app="com.example.forms",
        platform="android",
        steps=(step,),
    )
    recorder = _CapturingRecorder()
    executor = SkillExecutor(
        backend=DryRunBackend(),
        state_validator=_FakeValidator(returns=[False]),
        trajectory_recorder=recorder,
        stop_on_failure=True,
    )

    result = await executor.execute(skill)

    assert result.state == ExecutionState.FAILED
    assert recorder.events[1][0] == "skill_step"
    assert recorder.events[1][1]["valid_state_check"] is False
    assert "valid_state not reached" in str(recorder.events[1][1]["error"])
    assert recorder.events[2][0] == "skill_execution_result"
    assert recorder.events[2][1]["state"] == "failed"
    assert "valid_state not reached" in str(recorder.events[2][1]["error"])


# ---------------------------------------------------------------------------
# SkillExtractor — tests (async)
# ---------------------------------------------------------------------------


async def test_skill_extractor_parses_llm_json() -> None:
    """SkillExtractor correctly parses a well-formed LLM JSON response into a Skill."""
    canned_json = json.dumps({
        "name": "open_settings",
        "description": "Navigate to the device settings screen",
        "app": "com.android.settings",
        "platform": "android",
        "parameters": [],
        "preconditions": ["Device is unlocked"],
        "steps": [
            {
                "action_type": "tap",
                "target": "Settings app icon",
                "parameters": {},
                "expected_state": "Settings app is open",
                "valid_state": "Home screen is visible",
            }
        ],
    })

    llm = _ScriptedLLM([canned_json])
    extractor = SkillExtractor(llm=llm)

    # extract_from_steps requires >= 2 step dicts
    raw_steps = [
        {"type": "step", "action": "tap", "target": "icon"},
        {"type": "step", "action": "scroll", "target": "list"},
    ]
    skill = await extractor.extract_from_steps(raw_steps, is_success=True)

    assert skill is not None
    assert skill.name == "open_settings"
    assert skill.platform == "android"
    assert skill.app == "com.android.settings"
    assert len(skill.steps) == 1
    assert skill.steps[0].action_type == "tap"


async def test_skill_extractor_normalizes_app_identifier() -> None:
    """SkillExtractor canonicalizes common app-name aliases before returning a skill."""
    canned_json = json.dumps({
        "name": "open_settings",
        "description": "Navigate to the device settings screen",
        "app": " Settings ",
        "platform": "android",
        "parameters": [],
        "preconditions": [],
        "steps": [
            {
                "action_type": "tap",
                "target": "Settings app icon",
                "parameters": {},
                "expected_state": "Settings app is open",
                "valid_state": "Home screen is visible",
            }
        ],
    })

    llm = _ScriptedLLM([canned_json])
    extractor = SkillExtractor(llm=llm)

    skill = await extractor.extract_from_steps(
        [
            {"type": "step", "action": "tap", "target": "icon"},
            {"type": "step", "action": "scroll", "target": "list"},
        ],
        is_success=True,
    )

    assert skill is not None
    assert skill.app == "com.android.settings"


async def test_skill_extractor_returns_none_for_single_step() -> None:
    """SkillExtractor returns None when fewer than 2 steps are provided (Pitfall 5)."""
    llm = _ScriptedLLM(["should not be called"])
    extractor = SkillExtractor(llm=llm)

    result = await extractor.extract_from_steps(
        [{"type": "step", "action": "tap", "target": "button"}],
        is_success=True,
    )

    assert result is None


async def test_skill_extractor_returns_none_for_zero_steps() -> None:
    """SkillExtractor returns None when the steps list is empty."""
    llm = _ScriptedLLM(["should not be called"])
    extractor = SkillExtractor(llm=llm)

    result = await extractor.extract_from_steps([], is_success=True)

    assert result is None


async def test_skill_extractor_handles_invalid_json() -> None:
    """SkillExtractor returns None when the LLM response is not valid JSON."""
    llm = _ScriptedLLM(["this is not valid json at all!"])
    extractor = SkillExtractor(llm=llm)

    result = await extractor.extract_from_steps(
        [
            {"type": "step", "action": "tap", "target": "icon"},
            {"type": "step", "action": "scroll", "target": "list"},
        ],
        is_success=True,
    )

    assert result is None


async def test_skill_extractor_prompt_prefers_observed_foreground_app() -> None:
    llm = _ScriptedLLM([
        json.dumps({
            "name": "open_settings",
            "description": "Navigate to Android settings",
            "app": "设置",
            "platform": "android",
            "parameters": [],
            "preconditions": [],
            "steps": [
                {
                    "action_type": "open_app",
                    "target": "Settings",
                    "parameters": {},
                    "expected_state": "Settings app is open",
                    "valid_state": "No need to verify",
                },
                {
                    "action_type": "tap",
                    "target": "Network & internet",
                    "parameters": {},
                    "expected_state": "Network settings visible",
                    "valid_state": "Settings app is open",
                },
            ],
        })
    ])
    extractor = SkillExtractor(llm=llm, include_screenshots=False)

    skill = await extractor.extract_from_steps(
        [
            {
                "type": "step",
                "action": {"action_type": "open_app", "text": "设置"},
                "observation": {"foreground_app": "com.android.settings"},
            },
            {
                "type": "step",
                "action": {"action_type": "tap"},
                "observation": {"foreground_app": "com.android.settings"},
            },
        ],
        is_success=True,
    )

    assert skill is not None
    prompt = llm.messages[0][0]["content"]
    assert isinstance(prompt, str)
    assert "observation.foreground_app" in prompt
    assert "strongest app identity signal" in prompt
    assert "com.android.settings" in prompt
