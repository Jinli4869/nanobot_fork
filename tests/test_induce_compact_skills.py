"""Tests for scripts/induce_compact_skills.py compact post-processing."""

from __future__ import annotations

from pathlib import Path

from opengui.skills.data import Skill, SkillStep
from opengui.skills.flat import C, R

from scripts.induce_compact_skills import (
    _placeholder_names,
    cluster_compact_skills,
    compactify_skill,
    merge_into_output,
)


def _step(
    action_type: str,
    target: str = "button",
    *,
    valid_state: str | None = "field is visible",
    state_contract: dict | None = None,
    parameters: dict | None = None,
    fixed_values: dict | None = None,
) -> SkillStep:
    return SkillStep(
        action_type=action_type,
        target=target,
        parameters=parameters or {},
        valid_state=valid_state,
        state_contract=state_contract,
        fixed_values=fixed_values or {},
    )


def _skill(
    *steps: SkillStep,
    name: str = "fill_form",
    app: str = "com.gmailclone",
    skill_id: str = "flat:fill_form",
) -> Skill:
    return Skill(
        skill_id=skill_id,
        name=name,
        description="When to use: test",
        app=app,
        platform="android",
        steps=tuple(steps),
        parameters=(),
    )


# ---------------------------------------------------------------------------
# compactify_skill
# ---------------------------------------------------------------------------


class TestCompactifySkill:
    def test_accepts_and_retags(self):
        skill = _skill(
            _step("tap", "To field"),
            _step("input_text", "{{to_email}}"),
            _step("tap", "Subject field"),
            _step("input_text", "{{subject}}"),
        )
        out = compactify_skill(skill, max_steps=7, max_scroll_steps=1)
        assert out is not None
        assert out.tags == ("compact", "compact_extracted")
        assert out.skill_id == "compact:com.gmailclone:fill_form"
        # Guards are preserved verbatim; skipping NL validation is a runtime policy.
        assert [s.valid_state for s in out.steps] == ["field is visible"] * 4

    def test_preserves_step_guards(self):
        contract = C(app="com.gmailclone", required=[R(resource_id="to_field", visible=True)])
        skill = _skill(
            _step("tap", "To field", valid_state="To field is focused", state_contract=contract),
            _step("input_text", "{{to_email}}"),
        )
        out = compactify_skill(skill, max_steps=7, max_scroll_steps=1)
        assert out is not None
        # Both the deterministic contract and the prose valid_state survive intact.
        assert out.steps[0].state_contract == contract
        assert out.steps[0].valid_state == "To field is focused"

    def test_rejects_single_step(self):
        assert compactify_skill(_skill(_step("tap")), max_steps=7, max_scroll_steps=1) is None

    def test_rejects_too_many_steps(self):
        steps = [_step("tap", f"b{i}") for i in range(8)]
        assert compactify_skill(_skill(*steps), max_steps=7, max_scroll_steps=1) is None

    def test_accepts_open_app_as_first_step(self):
        skill = _skill(
            _step("open_app", "com.gmailclone"),
            _step("tap", "compose"),
            _step("input_text", "{{subject}}"),
        )
        assert compactify_skill(skill, max_steps=7, max_scroll_steps=1) is not None

    def test_rejects_open_app_in_middle(self):
        skill = _skill(
            _step("tap", "compose"),
            _step("open_app", "com.other"),
        )
        assert compactify_skill(skill, max_steps=7, max_scroll_steps=1) is None

    def test_scroll_budget(self):
        two_scrolls = _skill(
            _step("scroll", "list"),
            _step("scroll", "list"),
            _step("tap", "item"),
        )
        assert compactify_skill(two_scrolls, max_steps=7, max_scroll_steps=1) is None
        assert compactify_skill(two_scrolls, max_steps=7, max_scroll_steps=2) is not None


# ---------------------------------------------------------------------------
# placeholder extraction
# ---------------------------------------------------------------------------


class TestPlaceholderNames:
    def test_extracts_from_nested_structures(self):
        assert _placeholder_names("{{to}}") == frozenset({"to"})
        assert _placeholder_names({"text": "{{a}}", "k": "{{b}}"}) == frozenset({"a", "b"})
        assert _placeholder_names(["{{x}}", {"y": "{{y}}"}]) == frozenset({"x", "y"})
        assert _placeholder_names("literal") == frozenset()


# ---------------------------------------------------------------------------
# cross-trajectory clustering
# ---------------------------------------------------------------------------


class TestClustering:
    def _email_skill(self, skill_id: str) -> Skill:
        # Same structure, different literal targets — must still cluster.
        return _skill(
            _step("tap", "To"),
            _step("input_text", "{{to_email}}"),
            name="fill_email",
            skill_id=skill_id,
        )

    def test_identical_structure_clusters_with_support(self):
        skills = [
            compactify_skill(self._email_skill("flat:a"), max_steps=7, max_scroll_steps=1),
            compactify_skill(self._email_skill("flat:b"), max_steps=7, max_scroll_steps=1),
        ]
        clustered = cluster_compact_skills([s for s in skills if s], min_support=1)
        assert len(clustered) == 1
        assert clustered[0].success_count == 2
        assert clustered[0].success_streak == 2

    def test_min_support_filters_singletons(self):
        skill = compactify_skill(self._email_skill("flat:a"), max_steps=7, max_scroll_steps=1)
        assert cluster_compact_skills([skill], min_support=2) == []
        assert len(cluster_compact_skills([skill], min_support=1)) == 1

    def test_distinct_structures_do_not_cluster(self):
        a = compactify_skill(self._email_skill("flat:a"), max_steps=7, max_scroll_steps=1)
        b = compactify_skill(
            _skill(_step("tap", "search"), _step("input_text", "{{q}}"), _step("tap", "go"),
                   name="search_flow", skill_id="flat:c"),
            max_steps=7, max_scroll_steps=1,
        )
        clustered = cluster_compact_skills([a, b], min_support=1)
        assert len(clustered) == 2

    def test_same_sequence_different_literal_target_stays_apart(self):
        # Same app, same action sequence and placeholder name, but different
        # literal controls must NOT collapse (would inflate success_count).
        to_field = compactify_skill(
            _skill(_step("tap", "To", valid_state=None), _step("input_text", "{{value}}"),
                   name="fill_to", skill_id="flat:a"),
            max_steps=7, max_scroll_steps=1,
        )
        search = compactify_skill(
            _skill(_step("tap", "Search", valid_state=None), _step("input_text", "{{value}}"),
                   name="fill_search", skill_id="flat:b"),
            max_steps=7, max_scroll_steps=1,
        )
        clustered = cluster_compact_skills([to_field, search], min_support=1)
        assert len(clustered) == 2
        assert all(s.success_count == 1 for s in clustered)


# ---------------------------------------------------------------------------
# output merge
# ---------------------------------------------------------------------------


class TestMergeOutput:
    def test_writes_and_merges_monotonic_support(self, tmp_path: Path):
        out = tmp_path / "compact_skills.py"
        skill = compactify_skill(
            _skill(_step("tap", "To"), _step("input_text", "{{to_email}}"), name="fill_email"),
            max_steps=7, max_scroll_steps=1,
        )
        clustered = cluster_compact_skills([skill, skill], min_support=1)  # support=2
        added = merge_into_output(clustered, out)
        assert added == 1
        assert out.exists()

        # Re-merge a lower-support version of the same skill: support must not drop.
        weaker = cluster_compact_skills([skill], min_support=1)  # support=1
        added2 = merge_into_output(weaker, out)
        assert added2 == 0
        from opengui.skills.flat import compile_flat_skills

        compiled = compile_flat_skills(out.read_text(encoding="utf-8"))
        assert not compiled.errors
        assert len(compiled.skills) == 1
        assert compiled.skills[0].success_count == 2
