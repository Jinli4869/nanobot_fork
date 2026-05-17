from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opengui.observation import Observation
from opengui.skills.code_first import CodeSkillLibrary
from opengui.skills.deeplink import discover_deeplink_skills_from_trace
from opengui.skills.evolution import SkillEvolutionEngine, load_skill_feedback


class _ShortcutProbeBackend:
    platform = "android"

    def __init__(self, observation: Observation) -> None:
        self.observation = observation
        self.executed: list[Any] = []

    async def execute(self, action: Any, timeout: float = 5.0) -> str:
        del timeout
        self.executed.append(action)
        return "started"

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        del timeout
        self.observation.screenshot_path = str(screenshot_path)
        return self.observation


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding="utf-8",
    )


async def test_verified_deeplink_probe_writes_code_skill(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    final_observation = {
        "foreground_app": "com.example.app",
        "platform": "android",
        "extra": {
            "ui_tree": [
                {
                    "resource_id": "com.example.app:id/orders_title",
                    "text": "Orders",
                    "content_desc": "",
                    "visible": True,
                    "enabled": True,
                }
            ]
        },
    }
    _write_jsonl(trace_path, [
        {"type": "step", "note": "demo://orders"},
        {"type": "step", "observation": final_observation},
    ])

    backend = _ShortcutProbeBackend(Observation(
        screenshot_path=None,
        screen_width=1080,
        screen_height=1920,
        foreground_app="com.example.app",
        platform="android",
        extra=final_observation["extra"],
    ))
    result = await discover_deeplink_skills_from_trace(
        trace_path,
        backend=backend,
        task="Open orders",
        platform="android",
        is_success=True,
        store_root=tmp_path / "skills",
    )

    assert result.status == "processed_deeplink_code"
    assert result.compiled_skill_ids
    assert any(action.action_type == "open_deeplink" for action in backend.executed)
    assert (tmp_path / "deeplink_result.json").is_file()

    library = CodeSkillLibrary(store_dir=tmp_path / "skills", legacy_fallback=False)
    stored = library.get(result.compiled_skill_ids[0])
    assert stored is not None
    assert stored.steps[0].action_type == "open_deeplink"
    assert stored.steps[0].state_contract is not None


def test_failure_evolution_records_negative_feedback(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(trace_path, [
        {
            "type": "skill_step",
            "skill_id": "skill-1",
            "skill_name": "Pause Stopwatch",
            "step_index": 0,
            "target": "Pause",
            "state_contract": {"app": "com.android.deskclock", "must_exist": ["Pause"]},
            "contract_eval_detail": {"reason": "required_selector_failed"},
            "observation": {"foreground_app": "com.android.deskclock"},
            "error": "valid_state not reached",
        },
        {
            "type": "skill_execution_result",
            "skill_id": "skill-1",
            "skill_name": "Pause Stopwatch",
            "state": "failed",
            "error": "Step 0 valid_state not reached",
        },
    ])

    result = SkillEvolutionEngine(tmp_path / "skills").evolve_trace(
        trace_path,
        task="Run the stopwatch",
        platform="android",
    )

    assert result["status"] == "processed_evolution"
    assert (tmp_path / "skills" / "evolution" / "failure_cases.jsonl").is_file()
    feedback = load_skill_feedback(tmp_path / "skills")
    assert feedback["skills"]["skill-1"]["negative_tasks"] == ["Run the stopwatch"]
    assert feedback["skills"]["skill-1"]["failure_counts"]["wrong_skill_selected"] == 1
