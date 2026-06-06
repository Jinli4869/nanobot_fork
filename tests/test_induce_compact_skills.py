"""Tests for induce_compact_skills.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# format_trajectory_for_skill
# ---------------------------------------------------------------------------

def _write_trace(path: Path, events: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
        encoding="utf-8",
    )


class TestFormatForSkill:
    def test_includes_ui_and_params(self, tmp_path):
        from scripts.induce_compact_skills import format_trajectory_for_skill

        trace = tmp_path / "t.jsonl"
        _write_trace(trace, [
            {"type": "metadata", "task": "Send email"},
            {
                "type": "step", "step_index": 0,
                "action": {"action_type": "tap", "action_params": {"x": 100, "y": 200}},
                "observation": {
                    "foreground_app": "Mail",
                    "extra": {"clickable_text": ["To", "Subject", "Compose"]},
                },
                "model_output": "Thought: Open the To field. Action: {}",
            },
            {"type": "result", "success": True},
        ])

        text = format_trajectory_for_skill(trace)
        assert text is not None
        assert "Step 0 [tap] (Mail)" in text
        assert "UI: To, Subject, Compose" in text
        assert "pos=(100, 200)" in text

    def test_empty_trace(self, tmp_path):
        from scripts.induce_compact_skills import format_trajectory_for_skill
        trace = tmp_path / "t.jsonl"
        _write_trace(trace, [
            {"type": "metadata", "task": "No steps"},
            {"type": "result"},
        ])
        assert format_trajectory_for_skill(trace) is None

    def test_truncates_long(self, tmp_path):
        from scripts.induce_compact_skills import format_trajectory_for_skill
        trace = tmp_path / "t.jsonl"
        events = [{"type": "metadata", "task": "Long"}]
        for i in range(40):
            events.append({
                "type": "step", "step_index": i,
                "action": {"action_type": "tap"},
                "observation": {"foreground_app": "App"},
                "model_output": f"Thought: step {i}. Action: {{}}",
            })
        events.append({"type": "result"})
        _write_trace(trace, events)
        text = format_trajectory_for_skill(trace)
        assert "steps omitted" in text
        assert "Step 39" in text


# ---------------------------------------------------------------------------
# clean_skill_code
# ---------------------------------------------------------------------------

class TestCleanSkillCode:
    def test_strips_fences(self):
        from scripts.induce_compact_skills import clean_skill_code
        result = clean_skill_code("```python\n@skill(...)\ndef f(): pass\n```")
        assert "```" not in result
        assert "from opengui.skills.flat import" in result

    def test_adds_header(self):
        from scripts.induce_compact_skills import clean_skill_code
        result = clean_skill_code("")
        assert "from opengui.skills.flat import" in result

    def test_preserves_code(self):
        from scripts.induce_compact_skills import clean_skill_code
        code = (
            "from opengui.skills.flat import C, R, action, skill, tag\n\n"
            "@skill(app='x', platform='android')\n"
            "async def f(device):\n    await action('tap', target='x')\n"
        )
        result = clean_skill_code(code)
        assert "async def f(device)" in result


# ---------------------------------------------------------------------------
# filter_skills
# ---------------------------------------------------------------------------

# -- shared test dataclasses for skill-like objects ---------------------------

from dataclasses import dataclass


@dataclass
class _FakeStep:
    action_type: str = "tap"
    target: str = "button"
    valid_state: str = "No need to verify"


@dataclass
class _FakeSkill:
    skill_id: str = "compact:test:x"
    name: str = "test_skill"
    steps: tuple = ()
    parameters: tuple = ()
    description: str = "When to use: test"
    tags: tuple = ("compact", "compact_extracted")


class TestFilterSkills:
    def test_accepts_good_skill(self):
        from scripts.induce_compact_skills import filter_skills
        skill = _FakeSkill(
            skill_id="compact:test:fill",
            name="fill_form",
            steps=(
                _FakeStep("tap", "To field"),
                _FakeStep("input_text", "{{to_email}}"),
                _FakeStep("tap", "Subject field"),
                _FakeStep("input_text", "{{subject}}"),
            ),
            parameters=("to_email", "subject"),
        )
        accepted, report = filter_skills([skill], max_steps=4)
        assert len(accepted) == 1
        assert report == {}

    def test_rejects_single_step(self):
        from scripts.induce_compact_skills import filter_skills
        skill = _FakeSkill(steps=(_FakeStep(),))
        accepted, report = filter_skills([skill], max_steps=4)
        assert len(accepted) == 0
        assert "single_step_skill" in str(report.get("compact:test:x", ""))

    def test_rejects_open_app(self):
        from scripts.induce_compact_skills import filter_skills
        skill = _FakeSkill(steps=(
            _FakeStep("open_app", "com.app"),
            _FakeStep("tap", "button"),
        ))
        accepted, report = filter_skills([skill], max_steps=4)
        assert len(accepted) == 0
        assert "contains_open_app" in str(report.get("compact:test:x", ""))

    def test_rejects_scroll(self):
        from scripts.induce_compact_skills import filter_skills
        skill = _FakeSkill(steps=(
            _FakeStep("tap", "header"),
            _FakeStep("scroll", "list"),
        ))
        accepted, report = filter_skills([skill], max_steps=4)
        assert "contains_scroll" in str(report.get("compact:test:x", ""))

    def test_flags_verbose_valid_state(self):
        from scripts.induce_compact_skills import filter_skills
        skill = _FakeSkill(steps=(
            _FakeStep("tap", "X", "field is visible"),
            _FakeStep("input_text", "{{x}}", "text entered"),
        ))
        accepted, report = filter_skills([skill], max_steps=4)
        assert "verbose_valid_state" in str(report.get("compact:test:x", ""))
