"""Unit tests for the minimal flat OpenGUI skill stack."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pytest

from opengui.action import Action
from opengui.backends.dry_run import DryRunBackend
from opengui.interfaces import LLMResponse
from opengui.observation import Observation
from opengui.skills import Skill, SkillStep
from opengui.skills.executor import ExecutionState, SkillExecutor
from opengui.skills.extractor import SkillExtractor
from opengui.skills.flat import FlatSkillLibrary, compile_flat_skills
from opengui.skills.reuser import SkillReuser
from opengui.skills.state_contract import infer_focused_input_contract, infer_interaction_target
from opengui.skills.trajectory_codegen import codegen_trajectory


class _ScriptedLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = [LLMResponse(content=r) for r in responses]
        self.messages: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        del tools, tool_choice
        self.messages.append(messages)
        if not self._responses:
            raise AssertionError("_ScriptedLLM has no remaining responses.")
        return self._responses.pop(0)


class _FakeValidator:
    def __init__(self, returns: list[bool]) -> None:
        self._returns = list(returns)
        self.calls: list[str] = []

    async def validate(
        self,
        valid_state: str,
        screenshot: Path | bytes | None = None,
    ) -> bool:
        del screenshot
        self.calls.append(valid_state)
        if not self._returns:
            raise AssertionError("_FakeValidator has no remaining results.")
        return self._returns.pop(0)


class _RecordingBackend(DryRunBackend):
    def __init__(self) -> None:
        super().__init__(screen_width=496, screen_height=1080)
        self.actions: list[Action] = []

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        del timeout
        self.actions.append(action)
        return action.action_type


class _ObservationProvider:
    def __init__(self, observations: list[Observation]) -> None:
        self._observations = list(observations)

    async def get_observation(self) -> Observation | None:
        if not self._observations:
            return None
        return self._observations.pop(0)


class _FakeSkillLibrary:
    def __init__(self, results: list[tuple[Skill, float]]) -> None:
        self._results = results

    async def search(
        self,
        task: str,
        platform: str | None = None,
        top_k: int = 5,
    ) -> list[tuple[Skill, float]]:
        del task, platform, top_k
        return self._results


class _RecordingEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        return np.array([self._vector(text) for text in texts], dtype=np.float32)

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        return [
            float(lowered.count("settings")),
            float(lowered.count("camera")),
            float(lowered.count("selfie")),
            float(lowered.count("browser")),
            1.0,
        ]


class _ConstantEmbeddingProvider:
    async def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([[1.0, 0.0] for _text in texts], dtype=np.float32)


class _KeywordEmbeddingProvider:
    async def embed(self, texts: list[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            rows.append([
                float(lowered.count("messages")),
                float(lowered.count("camera")),
            ])
        return np.array(rows, dtype=np.float32)


def _make_skill(
    skill_id: str,
    name: str,
    description: str,
    *,
    app: str = "com.example.app",
    platform: str = "android",
    steps: tuple[SkillStep, ...] | None = None,
    success_count: int = 0,
    failure_count: int = 0,
    success_streak: int = 0,
    failure_streak: int = 0,
) -> Skill:
    return Skill(
        skill_id=skill_id,
        name=name,
        description=description,
        app=app,
        platform=platform,
        steps=steps
        or (
            SkillStep(
                action_type="tap",
                target="Settings",
                valid_state="Settings icon is visible",
            ),
        ),
        created_at=1_700_000_000.0,
        success_count=success_count,
        failure_count=failure_count,
        success_streak=success_streak,
        failure_streak=failure_streak,
    )


def _focused_input_extra() -> dict[str, Any]:
    return {
        "ui_tree": [
            {
                "resource_id": "com.zhihu.android:id/input_text",
                "class": "android.widget.EditText",
                "content_desc": "Search query",
                "focused": True,
                "enabled": True,
                "bounds": "[10,20][300,80]",
            }
        ]
    }


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(event) for event in events),
        encoding="utf-8",
    )


def test_opengui_skills_module_exports_flat_core_types() -> None:
    import opengui.skills as skills_pkg

    exported = set(skills_pkg.__all__)
    assert {"Skill", "SkillStep", "SkillExecutor", "SkillExtractor", "SkillLibrary"} <= exported
    assert skills_pkg.SkillLibrary is FlatSkillLibrary


def test_compile_flat_skills_supports_helpers_contracts_and_parameters() -> None:
    source = """
from opengui.skills.flat import C, R, action, skill

async def search_box(device, query):
    await action("tap", target="Search", state_contract=C(app="com.example", required=[R(text="Search", visible=True)]))
    await action("input_text", target=query, text=query, valid_state="Search box focused")

@skill(app="com.example", platform="android", skill_id="flat:search")
async def search_example(device, query):
    await search_box(device, query)
"""
    result = compile_flat_skills(source)

    assert result.errors == ()
    assert len(result.skills) == 1
    skill = result.skills[0]
    assert skill.skill_id == "flat:search"
    assert skill.parameters == ("query",)
    assert [step.action_type for step in skill.steps] == ["tap", "input_text"]
    assert skill.steps[0].state_contract is not None
    assert skill.steps[1].target == "{{query}}"


def test_flat_skill_library_crud_persists_to_skills_py(tmp_path: Path) -> None:
    store = tmp_path / "skills"
    lib = FlatSkillLibrary(store_dir=store)
    skill = _make_skill("s1", "Open Settings", "Open Android Settings")

    lib.add(skill)

    assert lib.count() == 1
    assert (store / "skills.py").is_file()
    assert not list(store.rglob("skills.json"))
    reloaded = FlatSkillLibrary(store_dir=store)
    assert reloaded.get("s1") == skill

    updated = _make_skill("s1", "Open Settings", "Updated")
    assert reloaded.update("s1", updated) is True
    assert FlatSkillLibrary(store_dir=store).get("s1").description == "Updated"
    assert reloaded.remove("s1") is True
    assert FlatSkillLibrary(store_dir=store).count() == 0


def test_infer_interaction_target_uses_pre_action_ui_node() -> None:
    observation = Observation(
        screenshot_path=None,
        screen_width=1080,
        screen_height=2400,
        foreground_app="com.example",
        platform="android",
        extra={
            "ui_tree": [
                {"text": "Root", "bounds": "[0,0][1080,2400]", "class": "FrameLayout"},
                {
                    "text": "Settings",
                    "resource_id": "com.example:id/settings_btn",
                    "class": "Button",
                    "clickable": True,
                    "bounds": "[100,200][300,260]",
                },
            ],
        },
    )

    target = infer_interaction_target(
        Action(action_type="tap", x=150, y=230),
        observation,
    )

    assert target is not None
    assert target["selector"] == {"resource_id": "com.example:id/settings_btn"}
    contract = target["state_contract"]
    assert contract["anchor"]["app_package"] == "com.example"
    assert contract["signature"]["required"][0]["selector"] == target["selector"]


@pytest.mark.asyncio
async def test_flat_skill_library_search_returns_relevant_skill(tmp_path: Path) -> None:
    lib = FlatSkillLibrary(store_dir=tmp_path / "skills")
    lib.add(_make_skill("settings", "Open Settings", "Navigate to Android settings"))
    lib.add(_make_skill("camera", "Open Camera", "Take a photo with the camera"))

    results = await lib.search("settings screen", platform="android", top_k=2)

    assert results
    assert results[0][0].skill_id == "settings"


@pytest.mark.asyncio
async def test_flat_skill_library_add_or_merge_deduplicates_semantic_conflict(tmp_path: Path) -> None:
    steps = (
        SkillStep(action_type="open_app", target="Launch WeChat", parameters={"text": "com.tencent.mm"}),
        SkillStep(action_type="tap", target="Messages", valid_state="Messages tab is visible"),
        SkillStep(action_type="tap", target="Verification code", valid_state="Verification message is visible"),
    )
    lib = FlatSkillLibrary(
        store_dir=tmp_path / "skills",
        embedding_provider=_RecordingEmbeddingProvider(),
        embedding_signature="sig-v1",
    )
    lib.add(_make_skill("read-code", "read_verification_code", "Open WeChat and read a login code", steps=steps))

    decision, skill_id = await lib.add_or_merge(
        _make_skill("otp", "get_otp_from_message", "Open WeChat and read a login code", steps=steps)
    )

    assert decision in {"MERGE", "KEEP_NEW"}
    assert skill_id is not None
    assert FlatSkillLibrary(store_dir=tmp_path / "skills").count() == 1


@pytest.mark.asyncio
async def test_flat_skill_library_rejects_unknown_app(tmp_path: Path) -> None:
    lib = FlatSkillLibrary(store_dir=tmp_path / "skills")

    decision, skill_id = await lib.add_or_merge(
        _make_skill("unknown-app", "Open Calendar", "Open Calendar", app="unknown")
    )

    assert decision == "REJECT_UNKNOWN_APP"
    assert skill_id is None
    assert FlatSkillLibrary(store_dir=tmp_path / "skills").count() == 0


@pytest.mark.asyncio
async def test_flat_skill_library_add_or_merge_uses_description_when_names_differ(tmp_path: Path) -> None:
    steps = (
        SkillStep(action_type="open_app", target="Launch WeChat", parameters={"text": "com.tencent.mm"}),
        SkillStep(action_type="tap", target="Messages", valid_state="Messages tab is visible"),
        SkillStep(action_type="tap", target="Verification code", valid_state="Verification message is visible"),
    )
    lib = FlatSkillLibrary(store_dir=tmp_path / "skills")
    lib.add(_make_skill("read-code", "read_code_from_sms", "Open WeChat and read a login code", steps=steps))

    decision, skill_id = await lib.add_or_merge(
        _make_skill("otp", "fetch_login_number", "Open WeChat and read a login code", steps=steps)
    )

    assert decision in {"MERGE", "KEEP_NEW"}
    assert skill_id is not None
    assert FlatSkillLibrary(store_dir=tmp_path / "skills").count() == 1


@pytest.mark.asyncio
async def test_flat_skill_library_does_not_merge_same_embedding_for_different_targets(tmp_path: Path) -> None:
    lib = FlatSkillLibrary(
        store_dir=tmp_path / "skills",
        embedding_provider=_ConstantEmbeddingProvider(),
        embedding_signature="constant",
    )
    lib.add(_make_skill(
        "settings",
        "open_entry",
        "Open the requested entry",
        steps=(SkillStep(action_type="tap", target="Settings", valid_state="Settings icon visible"),),
    ))

    decision, skill_id = await lib.add_or_merge(_make_skill(
        "camera",
        "open_entry_variant",
        "Open the requested entry",
        steps=(SkillStep(action_type="tap", target="Camera", valid_state="Camera icon visible"),),
    ))

    assert decision == "ADD"
    assert skill_id == "camera"
    assert FlatSkillLibrary(store_dir=tmp_path / "skills").count() == 2


@pytest.mark.asyncio
async def test_flat_skill_library_migrates_feedback_when_incoming_skill_merges(tmp_path: Path) -> None:
    steps = (
        SkillStep(action_type="tap", target="Messages", valid_state="Messages tab visible"),
    )
    lib = FlatSkillLibrary(store_dir=tmp_path / "skills")
    lib.add(_make_skill("existing", "open_messages", "Open messages", steps=steps))
    lib.record_feedback(
        "incoming",
        task="Open messages",
        failure_case={"execution_error": "popup blocked action", "failed_target": "Messages"},
        status="failure_detected",
    )

    decision, skill_id = await lib.add_or_merge(
        _make_skill("incoming", "messages_shortcut", "Open messages", steps=steps)
    )

    assert decision == "MERGE"
    assert skill_id == "existing"
    feedback = lib.feedback_for_skill("existing")
    assert feedback["negative_tasks"] == ["Open messages"]
    assert feedback["failure_counts"]["popup blocked action"] == 1
    assert lib.feedback_for_skill("incoming") == {}


@pytest.mark.asyncio
async def test_flat_skill_library_keeps_proven_old_skill_for_weaker_unproven_conflict(tmp_path: Path) -> None:
    store = tmp_path / "skills"
    lib = FlatSkillLibrary(
        store_dir=store,
        embedding_provider=_ConstantEmbeddingProvider(),
        embedding_signature="constant",
    )
    old = _make_skill(
        "old",
        "open_settings",
        "Open settings",
        steps=(SkillStep(action_type="tap", target="Settings", valid_state="Settings icon visible"),),
        success_count=3,
        success_streak=2,
    )
    lib.add(old)

    decision, skill_id = await lib.add_or_merge(_make_skill(
        "new",
        "open_settings_variant",
        "Open settings",
        steps=(SkillStep(action_type="tap", target="Settings gear", valid_state="Settings icon visible"),),
    ))

    assert decision == "KEEP_OLD"
    assert skill_id == "old"
    reloaded = FlatSkillLibrary(store_dir=store)
    assert reloaded.count() == 1
    assert reloaded.get("old") == old


@pytest.mark.asyncio
async def test_flat_skill_library_replaces_unproven_old_when_new_has_success(tmp_path: Path) -> None:
    store = tmp_path / "skills"
    lib = FlatSkillLibrary(store_dir=store)
    lib.add(_make_skill(
        "old",
        "open_messages",
        "Open messages",
        steps=(SkillStep(action_type="tap", target="Messages", valid_state="Messages visible"),),
    ))

    decision, skill_id = await lib.add_or_merge(_make_skill(
        "new",
        "open_messages_verified",
        "Open messages",
        steps=(SkillStep(action_type="tap", target="Messages", valid_state="Messages visible"),),
        success_count=2,
        success_streak=2,
    ))

    assert decision == "KEEP_NEW"
    assert skill_id == "new"
    reloaded = FlatSkillLibrary(store_dir=store)
    assert reloaded.get("old") is None
    assert reloaded.get("new") is not None


@pytest.mark.asyncio
async def test_flat_skill_library_merge_preserves_streaks(tmp_path: Path) -> None:
    steps = (SkillStep(action_type="tap", target="Messages", valid_state="Messages visible"),)
    lib = FlatSkillLibrary(store_dir=tmp_path / "skills")
    lib.add(_make_skill(
        "old",
        "open_messages",
        "Open messages",
        steps=steps,
        success_count=1,
        failure_count=1,
        success_streak=2,
    ))

    decision, skill_id = await lib.add_or_merge(_make_skill(
        "new",
        "open_messages_again",
        "Open messages",
        steps=steps,
        success_count=1,
        failure_count=2,
        failure_streak=3,
    ))

    assert decision == "MERGE"
    merged = FlatSkillLibrary(store_dir=tmp_path / "skills").get(skill_id or "")
    assert merged is not None
    assert merged.success_count == 2
    assert merged.failure_count == 3
    assert merged.success_streak == 2
    assert merged.failure_streak == 3


@pytest.mark.asyncio
async def test_flat_skill_library_cleanup_removes_zero_success_superseded_prefix(tmp_path: Path) -> None:
    prefix = _make_skill(
        "prefix",
        "open_search",
        "Open search",
        steps=(
            SkillStep(action_type="open_app", target="Launch Store", parameters={"text": "com.example.app"}),
            SkillStep(action_type="tap", target="Search", valid_state="Search button visible"),
        ),
    )
    longer = _make_skill(
        "longer",
        "search_store",
        "Search store for an item",
        steps=(
            *prefix.steps,
            SkillStep(action_type="input_text", target="{{query}}", valid_state="Search field focused"),
        ),
        success_count=3,
    )
    lib = FlatSkillLibrary(store_dir=tmp_path / "skills")
    lib.add(prefix)

    decision, skill_id = await lib.add_or_merge(longer)

    assert decision == "ADD"
    assert skill_id == "longer"
    reloaded = FlatSkillLibrary(store_dir=tmp_path / "skills")
    assert reloaded.get("prefix") is None
    assert reloaded.get("longer") is not None


@pytest.mark.asyncio
async def test_flat_skill_library_cleanup_prunes_feedback_for_removed_prefix(tmp_path: Path) -> None:
    prefix = _make_skill(
        "prefix",
        "open_search",
        "Open search",
        steps=(
            SkillStep(action_type="open_app", target="Launch Store", parameters={"text": "com.example.app"}),
            SkillStep(action_type="tap", target="Search", valid_state="Search button visible"),
        ),
    )
    longer = _make_skill(
        "longer",
        "search_store",
        "Search store for an item",
        steps=(
            *prefix.steps,
            SkillStep(action_type="input_text", target="{{query}}", valid_state="Search field focused"),
        ),
        success_count=3,
    )
    lib = FlatSkillLibrary(store_dir=tmp_path / "skills")
    lib.add(prefix)
    lib.record_feedback(
        "prefix",
        task="Search store",
        failure_case={"execution_error": "stopped too early"},
        status="failure_detected",
    )

    await lib.add_or_merge(longer)

    assert lib.feedback_for_skill("prefix") == {}
    assert lib.feedback_for_skill("longer") == {}


@pytest.mark.asyncio
async def test_flat_skill_library_caches_skill_embeddings_and_only_embeds_query_on_hit(tmp_path: Path) -> None:
    store = tmp_path / "skills"
    embedder = _RecordingEmbeddingProvider()
    lib = FlatSkillLibrary(store_dir=store, embedding_provider=embedder, embedding_signature="sig-v1")
    lib.add(_make_skill("settings", "Open Settings", "Navigate to Android settings"))
    lib.add(_make_skill("camera", "Open Camera", "Take a photo with the camera"))

    results = await lib.search("settings screen", platform="android", top_k=2)

    assert results[0][0].skill_id == "settings"
    assert (store / "skills_embeddings.npy").is_file()
    assert (store / "skills_embeddings_meta.json").is_file()
    assert len(embedder.calls) == 2
    assert len(embedder.calls[0]) == 2
    assert embedder.calls[1] == ["settings screen"]

    embedder.calls.clear()
    results = await lib.search("camera", platform="android", top_k=2)

    assert results[0][0].skill_id == "camera"
    assert embedder.calls == [["camera"]]


@pytest.mark.asyncio
async def test_flat_skill_library_reuses_unchanged_skill_embeddings_when_skills_py_changes(tmp_path: Path) -> None:
    store = tmp_path / "skills"
    embedder = _RecordingEmbeddingProvider()
    lib = FlatSkillLibrary(store_dir=store, embedding_provider=embedder, embedding_signature="sig-v1")
    lib.add(_make_skill("settings", "Open Settings", "Navigate to Android settings"))
    lib.add(_make_skill("camera", "Open Camera", "Take a photo with the camera"))
    await lib.search("settings screen", platform="android", top_k=2)

    embedder.calls.clear()
    lib.update("camera", _make_skill("camera", "Open Camera", "Take a camera selfie"))
    results = await lib.search("camera selfie", platform="android", top_k=2)

    assert results[0][0].skill_id == "camera"
    assert len(embedder.calls) == 2
    rebuilt_skill_texts = embedder.calls[0]
    assert len(rebuilt_skill_texts) == 1
    assert "Take a camera selfie" in rebuilt_skill_texts[0]
    assert "Open Settings" not in rebuilt_skill_texts[0]
    assert embedder.calls[1] == ["camera selfie"]


@pytest.mark.asyncio
async def test_flat_skill_library_rebuilds_skill_embeddings_when_signature_changes(tmp_path: Path) -> None:
    store = tmp_path / "skills"
    first_embedder = _RecordingEmbeddingProvider()
    lib = FlatSkillLibrary(store_dir=store, embedding_provider=first_embedder, embedding_signature="sig-v1")
    lib.add(_make_skill("settings", "Open Settings", "Navigate to Android settings"))
    lib.add(_make_skill("camera", "Open Camera", "Take a photo with the camera"))
    await lib.search("settings screen", platform="android", top_k=2)

    second_embedder = _RecordingEmbeddingProvider()
    reloaded = FlatSkillLibrary(store_dir=store, embedding_provider=second_embedder, embedding_signature="sig-v2")
    await reloaded.search("camera", platform="android", top_k=2)

    assert len(second_embedder.calls) == 2
    assert len(second_embedder.calls[0]) == 2
    assert second_embedder.calls[1] == ["camera"]


@pytest.mark.asyncio
async def test_postprocessor_uses_add_or_merge_for_extracted_flat_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opengui.postprocessing import PostRunProcessor
    from opengui.skills.extractor import SkillExtractor

    store = tmp_path / "skills"
    existing = _make_skill(
        "existing",
        "open_settings",
        "Open Android settings",
        steps=(SkillStep(action_type="tap", target="Settings", valid_state="Settings icon visible"),),
    )
    incoming = _make_skill(
        "incoming",
        "open_settings",
        "Open Android settings",
        steps=(SkillStep(action_type="tap", target="Settings", valid_state="Settings icon visible"),),
    )
    FlatSkillLibrary(store_dir=store).add(existing)

    async def fake_extract_from_file_multi(
        self: SkillExtractor,
        trajectory_path: Path,
        *,
        is_success: bool = True,
    ) -> list[Skill]:
        del self, trajectory_path, is_success
        return [incoming]

    monkeypatch.setattr(SkillExtractor, "extract_from_file_multi", fake_extract_from_file_multi)
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text('{"type":"result","success":true,"total_steps":1}\n', encoding="utf-8")

    processor = PostRunProcessor(
        llm=_ScriptedLLM([]),
        skill_store_root=store,
        enable_skill_extraction=True,
    )

    result_id = await processor._extract_skill(trace_path, True, "android", task="Open settings")

    assert result_id == "existing"
    assert FlatSkillLibrary(store_dir=store).count() == 1
    extraction_result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert extraction_result["skills"][0]["decision"] == "MERGE"
    assert extraction_result["compiled_skill_ids"] == ["existing"]


@pytest.mark.asyncio
async def test_postprocessor_evolves_failed_reused_skill_instead_of_extracting_new(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opengui.postprocessing import PostRunProcessor
    from opengui.skills.extractor import SkillExtractor

    store = tmp_path / "skills"
    FlatSkillLibrary(store_dir=store).add(
        _make_skill(
            "skill-1",
            "open_messages",
            "Open messages",
            steps=(SkillStep(action_type="tap", target="Messages", valid_state="Messages tab visible"),),
        )
    )
    evolved_payload = json.dumps({
        "name": "open_messages",
        "description": "Open messages and dismiss popup when present",
        "app": "com.example.app",
        "platform": "android",
        "parameters": [],
        "preconditions": [],
        "steps": [
            {
                "action_type": "tap",
                "target": "Close",
                "parameters": {"optional": True},
                "valid_state": "popup close button is visible",
                "expected_state": "popup dismissed",
            },
            {
                "action_type": "tap",
                "target": "Messages",
                "valid_state": "Messages tab visible",
                "expected_state": "messages page is open",
            },
        ],
    })
    extractor = monkeypatch.setattr(
        SkillExtractor,
        "extract_from_file_multi",
        pytest.fail,
    )
    del extractor
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join([
            json.dumps({
                "type": "skill_step",
                "skill_id": "skill-1",
                "skill_name": "open_messages",
                "step_index": 0,
                "target": "Messages",
                "valid_state": "Messages tab visible",
                "valid_state_check": False,
                "error": "valid_state not reached: popup visible",
                "observation": {"foreground_app": "com.example.app", "platform": "android"},
            }),
            json.dumps({
                "type": "skill_execution_result",
                "skill_id": "skill-1",
                "skill_name": "open_messages",
                "state": "failed",
                "error": "Step 0 valid_state not reached",
            }),
            json.dumps({"type": "result", "success": True, "total_steps": 2}),
        ]),
        encoding="utf-8",
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([evolved_payload]),
        skill_store_root=store,
        enable_skill_extraction=True,
    )
    monkeypatch.setattr(processor, "_summarize_trajectory", AsyncMock(return_value=""))

    await processor._run_all(trace_path, is_success=True, platform="android", task="Open messages")

    evolved = FlatSkillLibrary(store_dir=store).get("skill-1")
    assert evolved is not None
    assert evolved.description == "Open messages and dismiss popup when present"
    assert evolved.steps[0].parameters["optional"] is True
    evolution_result = json.loads((tmp_path / "evolution_result.json").read_text(encoding="utf-8"))
    assert evolution_result["status"] == "processed_evolution"
    extraction_result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert extraction_result["status"] == "processed_evolution"
    assert extraction_result["ordinary_code_extraction_skipped"] is True
    feedback = FlatSkillLibrary(store_dir=store).feedback_for_skill("skill-1")
    assert feedback["negative_tasks"] == ["Open messages"]
    assert feedback["failure_counts"]["Step 0 valid_state not reached"] == 1
    assert feedback["last_evolution_status"] == "processed_evolution"
    assert feedback["evolution_count"] == 1


@pytest.mark.asyncio
async def test_postprocessor_evolution_injects_focused_input_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opengui.postprocessing import PostRunProcessor
    from opengui.skills.extractor import SkillExtractor

    store = tmp_path / "skills"
    FlatSkillLibrary(store_dir=store).add(
        _make_skill(
            "skill-1",
            "search_zhihu",
            "Search Zhihu",
            app="com.zhihu.android",
            steps=(
                SkillStep(action_type="input_text", target="{{query}}", valid_state="Search field focused"),
            ),
        )
    )
    evolved_payload = json.dumps({
        "name": "search_zhihu",
        "description": "Search Zhihu",
        "app": "com.zhihu.android",
        "platform": "android",
        "parameters": ["query"],
        "preconditions": [],
        "steps": [
            {
                "action_type": "input_text",
                "target": "{{query}}",
                "valid_state": "Search field focused",
            }
        ],
    })
    monkeypatch.setattr(SkillExtractor, "extract_from_file_multi", pytest.fail)
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join([
            json.dumps({
                "type": "skill_step",
                "skill_id": "skill-1",
                "skill_name": "search_zhihu",
                "step_index": 0,
                "target": "{{query}}",
                "valid_state": "Search field focused",
                "valid_state_check": False,
                "error": "valid_state not reached: Search field focused",
            }),
            json.dumps({
                "type": "skill_execution_result",
                "skill_id": "skill-1",
                "skill_name": "search_zhihu",
                "state": "failed",
                "error": "Step 0 valid_state not reached",
            }),
            json.dumps({
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "tap", "x": 100, "y": 40},
                "observation": {
                    "platform": "android",
                    "foreground_app": "com.zhihu.android",
                    "extra": _focused_input_extra(),
                },
            }),
            json.dumps({
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "input_text", "text": "强化学习"},
                "observation": {
                    "platform": "android",
                    "foreground_app": "com.zhihu.android",
                    "extra": {"ui_tree": []},
                },
            }),
            json.dumps({"type": "result", "success": True, "total_steps": 2}),
        ]),
        encoding="utf-8",
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([evolved_payload]),
        skill_store_root=store,
        enable_skill_extraction=True,
    )
    monkeypatch.setattr(processor, "_summarize_trajectory", AsyncMock(return_value=""))

    await processor._run_all(trace_path, is_success=True, platform="android", task="Search Zhihu")

    evolved = FlatSkillLibrary(store_dir=store).get("skill-1")
    assert evolved is not None
    required = evolved.steps[0].state_contract["signature"]["required"]
    assert required[0]["selector"] == {
        "resource_id": "com.zhihu.android:id/input_text",
        "class": "android.widget.EditText",
    }
    assert required[0]["state"] == ["visible", "enabled", "focused"]


@pytest.mark.asyncio
async def test_postprocessor_rejects_evolved_skill_that_drifts_from_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opengui.postprocessing import PostRunProcessor
    from opengui.skills.extractor import SkillExtractor

    store = tmp_path / "skills"
    original = _make_skill(
        "skill-1",
        "open_messages",
        "Open messages",
        steps=(SkillStep(action_type="tap", target="Messages", valid_state="Messages tab visible"),),
    )
    FlatSkillLibrary(store_dir=store).add(original)
    drifted_payload = json.dumps({
        "name": "open_camera",
        "description": "Open camera",
        "app": "com.example.app",
        "platform": "android",
        "parameters": [],
        "preconditions": [],
        "steps": [
            {
                "action_type": "tap",
                "target": "Camera",
                "valid_state": "Camera icon visible",
            },
        ],
    })
    monkeypatch.setattr(SkillExtractor, "extract_from_file_multi", pytest.fail)
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join([
            json.dumps({
                "type": "skill_step",
                "skill_id": "skill-1",
                "skill_name": "open_messages",
                "step_index": 0,
                "target": "Messages",
                "valid_state": "Messages tab visible",
                "valid_state_check": False,
                "error": "valid_state not reached: camera visible",
            }),
            json.dumps({
                "type": "skill_execution_result",
                "skill_id": "skill-1",
                "skill_name": "open_messages",
                "state": "failed",
                "error": "Step 0 valid_state not reached",
            }),
            json.dumps({"type": "result", "success": True, "total_steps": 2}),
        ]),
        encoding="utf-8",
    )
    processor = PostRunProcessor(
        llm=_ScriptedLLM([drifted_payload]),
        skill_store_root=store,
        enable_skill_extraction=True,
        embedding_provider=_KeywordEmbeddingProvider(),
        embedding_signature="keywords",
    )
    monkeypatch.setattr(processor, "_summarize_trajectory", AsyncMock(return_value=""))

    await processor._run_all(trace_path, is_success=True, platform="android", task="Open messages")

    unchanged = FlatSkillLibrary(store_dir=store).get("skill-1")
    assert unchanged == original
    evolution_result = json.loads((tmp_path / "evolution_result.json").read_text(encoding="utf-8"))
    assert evolution_result["status"] == "evolution_rejected"
    assert evolution_result["reason"] == "low_embedding_similarity"
    extraction_result = json.loads((tmp_path / "extraction_result.json").read_text(encoding="utf-8"))
    assert extraction_result["status"] == "evolution_error"
    feedback = FlatSkillLibrary(store_dir=store).feedback_for_skill("skill-1")
    assert feedback["last_evolution_status"] == "rejected:low_embedding_similarity"


def test_build_failure_case_ignores_failed_result_without_skill_id(tmp_path: Path) -> None:
    from opengui.skills.evolution import _build_failure_case

    failure_case = _build_failure_case(
        [
            {
                "type": "skill_execution_result",
                "state": "failed",
                "error": "Skill failed without metadata",
            },
        ],
        trace_path=tmp_path / "trace.jsonl",
        task="Open messages",
        platform="android",
    )

    assert failure_case is None


@pytest.mark.asyncio
async def test_skill_executor_runs_validated_steps() -> None:
    skill = _make_skill(
        "s1",
        "Wait",
        "Wait for a moment",
        steps=(SkillStep(action_type="wait", target="pause", parameters={"duration_ms": 1}, valid_state="ready"),),
    )
    executor = SkillExecutor(
        backend=DryRunBackend(),
        state_validator=_FakeValidator([True]),
    )

    result = await executor.execute(skill)

    assert result.state == ExecutionState.SUCCEEDED
    assert result.step_results[0].valid_state_check is True


@pytest.mark.asyncio
async def test_skill_executor_falls_back_to_valid_state_when_contract_unknown() -> None:
    validator = _FakeValidator([True])
    skill = _make_skill(
        "s1",
        "Tap Settings",
        "Tap Settings",
        steps=(
            SkillStep(
                action_type="wait",
                target="Settings",
                valid_state="Settings button is visible",
                state_contract={
                    "anchor": {"app_package": "com.example"},
                    "signature": {
                        "required": [
                            {
                                "selector": {"resource_id": "com.example:id/settings_btn"},
                                "state": ["visible", "clickable"],
                            }
                        ],
                        "forbidden": [],
                    },
                    "mask_rules": [],
                },
            ),
        ),
    )
    executor = SkillExecutor(backend=DryRunBackend(), state_validator=validator)

    result = await executor.execute(skill)

    assert result.state == ExecutionState.SUCCEEDED
    assert validator.calls == ["Settings button is visible"]


@pytest.mark.asyncio
async def test_skill_executor_dismisses_post_open_app_skip_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    import opengui.skills.executor as executor_module

    monkeypatch.setattr(executor_module, "_OPEN_APP_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(executor_module, "_POST_ACTION_SETTLE_SECONDS", 0.0)
    backend = _RecordingBackend()
    skill = _make_skill(
        "s1",
        "Open Bilibili",
        "Open Bilibili",
        steps=(SkillStep(action_type="open_app", target="tv.danmaku.bili", valid_state="No need to verify"),),
    )
    provider = _ObservationProvider([
        Observation(None, 496, 1080, foreground_app="tv.danmaku.bili", platform="android"),
        Observation(
            None,
            496,
            1080,
            foreground_app="tv.danmaku.bili",
            platform="android",
            extra={
                "ui_tree": [
                    {"class": "FrameLayout", "enabled": True, "bounds": "[0,0][1440,3120]"},
                    {
                        "text": "Skip 2",
                        "class": "TextView",
                        "clickable": True,
                        "enabled": True,
                        "bounds": "[1062,2775][1384,2936]",
                    },
                ],
            },
        ),
    ])
    executor = SkillExecutor(backend=backend, screenshot_provider=provider)

    result = await executor.execute(skill)

    assert result.state == ExecutionState.SUCCEEDED
    assert [action.action_type for action in backend.actions] == ["open_app", "tap"]
    assert backend.actions[1].x == pytest.approx(421.4, abs=1.0)
    assert backend.actions[1].y == pytest.approx(988.4, abs=1.0)


@pytest.mark.asyncio
async def test_skill_executor_ignores_center_close_after_open_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import opengui.skills.executor as executor_module

    monkeypatch.setattr(executor_module, "_OPEN_APP_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(executor_module, "_POST_ACTION_SETTLE_SECONDS", 0.0)
    backend = _RecordingBackend()
    skill = _make_skill(
        "s1",
        "Open App",
        "Open App",
        steps=(SkillStep(action_type="open_app", target="com.example", valid_state="No need to verify"),),
    )
    provider = _ObservationProvider([
        Observation(None, 496, 1080, foreground_app="com.example", platform="android"),
        Observation(
            None,
            496,
            1080,
            foreground_app="com.example",
            platform="android",
            extra={
                "ui_tree": [
                    {"class": "FrameLayout", "enabled": True, "bounds": "[0,0][1440,3120]"},
                    {
                        "text": "关闭",
                        "class": "TextView",
                        "clickable": True,
                        "enabled": True,
                        "bounds": "[620,1400][820,1500]",
                    },
                ],
            },
        ),
    ])
    executor = SkillExecutor(backend=backend, screenshot_provider=provider)

    result = await executor.execute(skill)

    assert result.state == ExecutionState.SUCCEEDED
    assert [action.action_type for action in backend.actions] == ["open_app"]


@pytest.mark.asyncio
async def test_skill_extractor_parses_llm_json_response() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="com.android.settings", platform="android", name="open_settings", description="Open settings")
async def open_settings(device):
    await action("open_app", target="Settings", fixed=True, fixed_values={"text": "com.android.settings"}, valid_state="No need to verify")
    await action("tap", target="Search", fixed=True, fixed_values={"text": "Search"}, valid_state="Search button is visible")
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skill = await extractor.extract_from_steps(
        [
            {
                "action": {"action_type": "open_app", "text": "com.android.settings"},
                "observation": {"platform": "android", "foreground_app": "com.android.settings"},
            },
            {
                "action": {"action_type": "done"},
                "observation": {"platform": "android", "foreground_app": "com.android.settings"},
            },
        ],
        is_success=True,
    )

    assert skill is not None
    assert skill.name == "open_settings"
    assert skill.steps[0].fixed is True
    assert skill.steps[1].action_type == "tap"


@pytest.mark.asyncio
async def test_skill_extractor_splits_segments_by_foreground_app() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="com.netease.cloudmusic", platform="android", name="open_netease", description="Open Netease")
async def open_netease(device):
    await action("open_app", target="Netease", fixed=True, fixed_values={"text": "com.netease.cloudmusic"}, valid_state="No need to verify")
    await action("tap", target="Daily", fixed=True, fixed_values={"x": 100, "y": 200}, valid_state="Daily icon is visible")
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skills = await extractor.extract_from_steps_multi([
        {"action": {"action_type": "open_app", "text": "com.netease.cloudmusic"}, "observation": {"platform": "android", "foreground_app": "com.netease.cloudmusic"}},
        {"action": {"action_type": "tap", "x": 100, "y": 200}, "observation": {"platform": "android", "foreground_app": "com.netease.cloudmusic"}},
    ], is_success=True)

    assert len(skills) == 1
    assert skills[0].app == "com.netease.cloudmusic"
    assert skills[0].steps[1].action_type == "tap"


@pytest.mark.asyncio
async def test_skill_extractor_resolves_unknown_app_from_open_app_text() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="unknown", platform="android", name="open_calendar", description="Open Calendar")
async def open_calendar(device):
    await action("open_app", target="Calendar", fixed=True, fixed_values={"text": "Calendar"}, valid_state="No need to verify")
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skills = await extractor.extract_from_steps_multi([
        {"action": {"action_type": "open_app", "text": "Calendar"}, "observation": {"platform": "android"}},
    ], is_success=True)

    assert len(skills) == 1
    assert skills[0].app == "com.android.calendar"


@pytest.mark.asyncio
async def test_skill_extractor_falls_back_to_trace_app_when_open_app_is_unknown() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="unknown", platform="android", name="open_calendar", description="Open Calendar")
async def open_calendar(device):
    await action("open_app", target="unknown", fixed=True, fixed_values={"text": "unknown"}, valid_state="No need to verify")
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skills = await extractor.extract_from_steps_multi([
        {
            "action": {"action_type": "open_app", "text": "unknown"},
            "observation": {"platform": "android", "foreground_app": "com.google.android.calendar"},
        },
    ], is_success=True)

    assert len(skills) == 1
    assert skills[0].app == "com.google.android.calendar"


@pytest.mark.asyncio
async def test_skill_extractor_rejects_unknown_app_without_fallback() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="unknown", platform="android", name="open_unknown", description="Open unknown")
async def open_unknown(device):
    await action("open_app", target="unknown", fixed=True, fixed_values={"text": "unknown"}, valid_state="No need to verify")
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skills = await extractor.extract_from_steps_multi([
        {"action": {"action_type": "open_app", "text": "unknown"}, "observation": {"platform": "android"}},
    ], is_success=True)

    assert skills == []


@pytest.mark.asyncio
async def test_skill_extractor_prefers_interaction_target_contract() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="com.example", platform="android", name="open_details", description="Open details")
async def open_details(device):
    await action("tap", target="Details", fixed=True, fixed_values={"x": 150, "y": 230},
                 valid_state="Details button is visible",
                 state_contract=C(app="com.example", required=[R(resource_id="com.example:id/details_btn", visible=True, clickable=True)]))
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skill = await extractor.extract_from_steps(
        [{"action": {"action_type": "tap", "x": 150, "y": 230}, "observation": {"platform": "android", "foreground_app": "com.example"}}],
        is_success=True,
    )

    assert skill is not None
    required = skill.steps[0].state_contract["signature"]["required"]
    assert required[0]["selector"] == {"resource_id": "com.example:id/details_btn"}


@pytest.mark.asyncio
async def test_skill_extractor_infers_interaction_target_from_trace_step() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="com.zhihu.android", platform="android", name="search_box", description="Tap Zhihu search box")
async def search_box(device):
    await action("tap", target="Search box", fixed=True, fixed_values={"x": 436, "y": 76, "relative": True},
                 valid_state="Home screen is visible with search bar at the top",
                 state_contract=C(app="com.zhihu.android", required=[R(resource_id="com.zhihu.android:id/query_container", visible=True, clickable=True)]))
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skill = await extractor.extract_from_steps(
        [{"action": {"action_type": "tap", "x": 436.0, "y": 76.0, "relative": True}, "observation": {"platform": "android", "foreground_app": "com.zhihu.android"}}],
        is_success=True,
    )

    assert skill is not None
    assert skill.steps[0].state_contract is not None
    required = skill.steps[0].state_contract["signature"]["required"]
    assert required[0]["selector"] == {"resource_id": "com.zhihu.android:id/query_container"}


@pytest.mark.asyncio
async def test_skill_extractor_uses_previous_observation_for_pre_action_target() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="com.zhihu.android", platform="android", name="search_box_recover", description="Tap search box")
async def search_box_recover(device):
    await action("tap", target="Home", fixed=True, fixed_values={"x": 607, "y": 243, "relative": True}, valid_state="No need to verify")
    await action("tap", target="Search box", fixed=True, fixed_values={"x": 436, "y": 76, "relative": True},
                 valid_state="Search bar is visible",
                 state_contract=C(app="com.zhihu.android", required=[R(resource_id="com.zhihu.android:id/query_container", visible=True, clickable=True)]))
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skill = await extractor.extract_from_steps([
        {"action": {"action_type": "tap", "x": 607.0, "y": 243.0, "relative": True}, "observation": {"platform": "android", "foreground_app": "com.zhihu.android"}},
        {"action": {"action_type": "tap", "x": 436.0, "y": 76.0, "relative": True}, "observation": {"platform": "android", "foreground_app": "com.zhihu.android"}},
    ], is_success=True)

    assert skill is not None
    assert skill.steps[1].state_contract is not None
    required = skill.steps[1].state_contract["signature"]["required"]
    assert required[0]["selector"] == {"resource_id": "com.zhihu.android:id/query_container"}


@pytest.mark.asyncio
async def test_skill_extractor_input_text_uses_previous_observation_for_state_contract() -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="com.zhihu.android", platform="android", name="zhihu_search_text", description="Enter search text")
async def zhihu_search_text(device):
    await action("input_text", target="com.zhihu.android:id/input_text",
                 fixed_values={"text": "强化学习"},
                 valid_state="Search input field is visible and focused",
                 state_contract=C(app="com.zhihu.android", required=[R(resource_id="com.zhihu.android:id/input_text", visible=True, enabled=True)]))
"""
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skill = await extractor.extract_from_steps([
        {"action": {"action_type": "input_text", "text": "强化学习"}, "observation": {"platform": "android", "foreground_app": "com.zhihu.android"}},
    ], is_success=True)

    assert skill is not None
    assert skill.steps[0].action_type == "input_text"
    assert skill.steps[0].state_contract is not None
    required = skill.steps[0].state_contract["signature"]["required"]
    assert required[0]["selector"] == {"resource_id": "com.zhihu.android:id/input_text"}


def test_infer_focused_input_contract_prefers_resource_id_and_class() -> None:
    contract = infer_focused_input_contract(_focused_input_extra(), app="com.zhihu.android")

    assert contract is not None
    required = contract["signature"]["required"]
    assert required[0]["selector"] == {
        "resource_id": "com.zhihu.android:id/input_text",
        "class": "android.widget.EditText",
    }
    assert required[0]["state"] == ["visible", "enabled", "focused"]


def test_codegen_scales_coordinates_and_prefers_previous_observation_for_tap(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(trace_path, [
        {"type": "metadata", "task": "Open first result", "platform": "android"},
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "wait"},
            "observation": {
                "platform": "android",
                "foreground_app": "com.example",
                "screen_width": 496,
                "screen_height": 1080,
                "extra": {
                    "ui_tree": [
                        {"class": "android.widget.FrameLayout", "enabled": True, "bounds": "[0,0][1440,3120]"},
                        {
                            "resource_id": "com.example:id/search_results_list",
                            "class": "androidx.recyclerview.widget.RecyclerView",
                            "enabled": True,
                            "bounds": "[0,460][1440,3036]",
                        },
                        {
                            "class": "android.view.ViewGroup",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[0,460][1440,1024]",
                        },
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 248, "y": 235},
            "observation": {
                "platform": "android",
                "foreground_app": "com.example",
                "screen_width": 496,
                "screen_height": 1080,
                "extra": {
                    "ui_tree": [
                        {"class": "android.widget.FrameLayout", "enabled": True, "bounds": "[0,0][1440,3120]"},
                        {
                            "text": "query",
                            "resource_id": "com.example:id/search_fake_text",
                            "class": "android.widget.TextView",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[225,179][1030,284]",
                        },
                    ],
                },
            },
        },
    ])

    result = codegen_trajectory(trace_path)

    assert result is not None
    contract = json.loads(result.steps[1].contract_json)
    required = contract["signature"]["required"]
    assert required[0]["selector"] == {"resource_id": "com.example:id/search_results_list"}


def test_codegen_does_not_use_post_action_focused_input_as_tap_contract(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(trace_path, [
        {"type": "metadata", "task": "Tap search", "platform": "android"},
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "x": 206, "y": 81},
            "observation": {
                "platform": "android",
                "foreground_app": "tv.danmaku.bili",
                "screen_width": 496,
                "screen_height": 1080,
                "extra": {
                    "ui_tree": [
                        {"class": "android.widget.FrameLayout", "enabled": True, "bounds": "[0,0][1440,3120]"},
                        {
                            "resource_id": "tv.danmaku.bili:id/search_bar",
                            "class": "android.widget.FrameLayout",
                            "enabled": True,
                            "bounds": "[225,172][1156,291]",
                        },
                        {
                            "text": "Search for videos, series, or UPs",
                            "content_desc": "Search query",
                            "resource_id": "tv.danmaku.bili:id/search_src_text",
                            "class": "android.widget.EditText",
                            "clickable": True,
                            "focused": True,
                            "enabled": True,
                            "bounds": "[225,179][1156,284]",
                        },
                    ],
                },
            },
        },
    ])

    result = codegen_trajectory(trace_path)

    assert result is not None
    assert result.steps[0].control_info == "post-action focused input; omit state_contract"
    assert result.steps[0].contract_json == ""


@pytest.mark.asyncio
async def test_skill_extractor_keeps_pre_action_tap_contract_before_focused_input(
    tmp_path: Path,
) -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="tv.danmaku.bili", platform="android", name="search_bilibili", description="Search Bilibili")
async def search_bilibili(device, query):
    await action("open_app", target="Bilibili", valid_state="No need to verify")
    await action("tap", target="search bar", valid_state="search bar is visible",
                 state_contract=C(app="tv.danmaku.bili", required=[R(resource_id="tv.danmaku.bili:id/expand_search", visible=True, clickable=True)]))
    await action("input_text", target=query, valid_state="search input is focused")
"""
    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(trace_path, [
        {"type": "metadata", "task": "Search Bilibili", "platform": "android"},
        {
            "type": "step",
            "step_index": 0,
            "action": {"action_type": "tap", "x": 400, "y": 800},
            "observation": {
                "platform": "android",
                "foreground_app": "tv.danmaku.bili",
                "screen_width": 496,
                "screen_height": 1080,
                "extra": {
                    "ui_tree": [
                        {"class": "android.widget.FrameLayout", "enabled": True, "bounds": "[0,0][1440,3120]"},
                        {
                            "content_desc": "Search bar, button",
                            "resource_id": "tv.danmaku.bili:id/expand_search",
                            "class": "android.widget.LinearLayout",
                            "clickable": True,
                            "enabled": True,
                            "bounds": "[249,182][1076,301]",
                        },
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 1,
            "action": {"action_type": "tap", "x": 206, "y": 81},
            "observation": {
                "platform": "android",
                "foreground_app": "tv.danmaku.bili",
                "screen_width": 496,
                "screen_height": 1080,
                "extra": {
                    "ui_tree": [
                        {"class": "android.widget.FrameLayout", "enabled": True, "bounds": "[0,0][1440,3120]"},
                        {
                            "resource_id": "tv.danmaku.bili:id/search_src_text",
                            "class": "android.widget.EditText",
                            "clickable": True,
                            "focused": True,
                            "enabled": True,
                            "bounds": "[225,179][1156,284]",
                        },
                    ],
                },
            },
        },
        {
            "type": "step",
            "step_index": 2,
            "action": {"action_type": "input_text", "text": "Never Gonna Give You Up MV"},
            "observation": {
                "platform": "android",
                "foreground_app": "tv.danmaku.bili",
                "extra": {"ui_tree": []},
            },
        },
    ])
    extractor = SkillExtractor(_ScriptedLLM([response]))

    skill = await extractor.extract_from_file(trace_path)

    assert skill is not None
    tap_step = [step for step in skill.steps if step.action_type == "tap"][0]
    assert tap_step.state_contract is not None
    tap_required = tap_step.state_contract["signature"]["required"]
    assert tap_required[0]["selector"] == {"resource_id": "tv.danmaku.bili:id/expand_search"}
    input_step = [step for step in skill.steps if step.action_type == "input_text"][0]
    assert input_step.state_contract is not None
    input_required = input_step.state_contract["signature"]["required"]
    assert input_required[0]["selector"]["resource_id"] == "tv.danmaku.bili:id/search_src_text"
    assert "focused" in input_required[0]["state"]


@pytest.mark.asyncio
async def test_skill_extractor_injects_focused_input_contract_when_llm_omits_it(
    tmp_path: Path,
) -> None:
    response = """from opengui.skills.flat import C, R, action, skill, tag

@skill(app="com.zhihu.android", platform="android", name="zhihu_search_text", description="Enter search text")
async def zhihu_search_text(device, query):
    await action("tap", target="Search box", valid_state="Search box is visible")
    await action("input_text", target=query, valid_state="Search input field is focused")
"""
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join([
            json.dumps({"type": "metadata", "task": "Search Zhihu", "platform": "android"}),
            json.dumps({
                "type": "step",
                "step_index": 0,
                "action": {"action_type": "tap", "x": 100, "y": 40},
                "observation": {
                    "platform": "android",
                    "foreground_app": "com.zhihu.android",
                    "extra": _focused_input_extra(),
                },
            }),
            json.dumps({
                "type": "step",
                "step_index": 1,
                "action": {"action_type": "input_text", "text": "强化学习"},
                "observation": {
                    "platform": "android",
                    "foreground_app": "com.zhihu.android",
                    "extra": {"ui_tree": []},
                },
            }),
        ]),
        encoding="utf-8",
    )

    extractor = SkillExtractor(_ScriptedLLM([response]))
    skill = await extractor.extract_from_file(trace_path)

    assert skill is not None
    input_step = [step for step in skill.steps if step.action_type == "input_text"][0]
    required = input_step.state_contract["signature"]["required"]
    assert required[0]["selector"] == {
        "resource_id": "com.zhihu.android:id/input_text",
        "class": "android.widget.EditText",
    }
    assert required[0]["state"] == ["visible", "enabled", "focused"]


@pytest.mark.asyncio
async def test_skill_reuser_selects_llm_chosen_prefix() -> None:
    skill = _make_skill(
        "s1",
        "Search Settings",
        "Open settings and tap search",
        steps=(
            SkillStep(action_type="open_app", target="Settings", parameters={"text": "com.android.settings"}),
            SkillStep(action_type="tap", target="Search"),
        ),
    )
    llm = _ScriptedLLM([
        '{"selected_skill_id": "s1", "end_step": 1, "reason": "opening settings helps"}'
    ])
    reuser = SkillReuser(llm, threshold=0.1, auto_accept_threshold=2.0)

    selected = await reuser.find(
        "Open Settings",
        _FakeSkillLibrary([(skill, 0.9)]),
        platform="android",
    )

    assert selected is not None
    selected_skill, score = selected
    assert score == 0.9
    assert selected_skill.skill_id == "s1"
    assert len(selected_skill.steps) == 1
