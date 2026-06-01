from __future__ import annotations

import pytest

from opengui.skills.data import Skill, SkillStep
from opengui.skills.flat import FlatSkillLibrary
from opengui.test import general_e2e_compact_skill_smoke as smoke


def test_shortcut_skill_catalog_includes_id_transport_and_parameters() -> None:
    skill = Skill(
        skill_id="shortcut:dl:tv.danmaku.bili:search",
        name="bili_search",
        description="B站搜索视频",
        app="tv.danmaku.bili",
        platform="android",
        tags=("shortcut", "deeplink", "validated"),
        parameters=("query",),
        steps=(
            SkillStep(
                action_type="open_deeplink",
                target="bilibili://search?keyword={{query}}",
                parameters={
                    "text": "bilibili://search?keyword={{query}}",
                    "package": "tv.danmaku.bili",
                },
                valid_state="B站搜索视频",
            ),
        ),
    )

    catalog = smoke.build_catalog([smoke.skill_info_from_flat_skill(skill, score=1.5)], limit=None)

    assert "skill_id=shortcut:dl:tv.danmaku.bili:search" in catalog
    assert "first_action=open_deeplink" in catalog
    assert "parameters=query" in catalog
    assert "bilibili://search?keyword={{query}}" in catalog


@pytest.mark.asyncio
async def test_retrieve_skill_infos_can_filter_to_shortcut_skills(tmp_path) -> None:
    library = FlatSkillLibrary(store_dir=tmp_path)
    library.add(
        Skill(
            skill_id="manual:tap:tv.danmaku.bili",
            name="manual_bili_step",
            description="B站普通点击步骤",
            app="tv.danmaku.bili",
            platform="android",
            steps=(SkillStep(action_type="tap", target="搜索按钮"),),
        )
    )
    library.add(
        Skill(
            skill_id="shortcut:dl:tv.danmaku.bili:search",
            name="bili_search",
            description="B站搜索视频",
            app="tv.danmaku.bili",
            platform="android",
            tags=("shortcut", "deeplink", "validated"),
            parameters=("query",),
            steps=(
                SkillStep(
                    action_type="open_deeplink",
                    target="bilibili://search?keyword={{query}}",
                    parameters={
                        "text": "bilibili://search?keyword={{query}}",
                        "package": "tv.danmaku.bili",
                    },
                    valid_state="B站搜索视频",
                ),
            ),
        )
    )

    results = await smoke.retrieve_skill_infos(
        store_root=tmp_path,
        task="在B站搜索敢杀我的马",
        platform="android",
        app="tv.danmaku.bili",
        top_k=3,
        shortcut_only=True,
    )

    assert [result.skill_id for result in results] == ["shortcut:dl:tv.danmaku.bili:search"]


def test_summarize_skill_selection_checks_expected_skill_id() -> None:
    parsed = {
        "action_type": "use_skill",
        "skill_id": "shortcut:di:com.android.chrome:incognito",
        "skill_name": "chrome_incognito",
    }

    summary = smoke.summarize_skill_selection(
        parsed,
        expected_skill="shortcut:di:com.android.chrome:incognito",
    )

    assert summary["used_skill"] is True
    assert summary["expected_match"] is True
