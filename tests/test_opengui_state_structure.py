from __future__ import annotations

from opengui.skills.state_structure import (
    build_structure_profile,
    structure_fingerprint,
    structure_similarity,
)
from opengui.skills.graph import GraphNode, SkillGraphStore
from opengui.skills.state_contract import normalize_state_contract


def _extra(dynamic_text: str) -> dict[str, object]:
    return {
        "ui_tree": [
            {
                "class": "android.widget.FrameLayout",
                "resource_id": "com.example:id/root",
                "xpath": "/hierarchy/android.widget.FrameLayout[1]",
            },
            {
                "class": "android.widget.TextView",
                "resource_id": "com.example:id/title",
                "text": dynamic_text,
                "xpath": "/hierarchy/android.widget.FrameLayout[1]/android.widget.TextView[1]",
            },
            {
                "class": "android.widget.Button",
                "resource_id": "com.example:id/submit",
                "text": "Submit",
                "clickable": True,
                "xpath": "/hierarchy/android.widget.FrameLayout[1]/android.widget.Button[1]",
            },
        ],
        "visible_text": [dynamic_text, "Submit"],
        "resource_ids": [
            "com.example:id/root",
            "com.example:id/title",
            "com.example:id/submit",
        ],
    }


def test_structure_fingerprint_ignores_dynamic_text() -> None:
    first = build_structure_profile(_extra("Order #123"))
    second = build_structure_profile(_extra("Order #456"))

    assert first is not None
    assert second is not None
    assert structure_fingerprint(first) == structure_fingerprint(second)
    assert structure_similarity(first, second) == 1.0


def test_structure_fingerprint_changes_for_structural_change() -> None:
    first = build_structure_profile(_extra("Order #123"))
    changed = _extra("Order #123")
    changed["ui_tree"] = list(changed["ui_tree"]) + [
        {
            "class": "android.widget.EditText",
            "resource_id": "com.example:id/search",
            "xpath": "/hierarchy/android.widget.FrameLayout[1]/android.widget.EditText[1]",
        }
    ]
    second = build_structure_profile(changed)

    assert first is not None
    assert second is not None
    assert structure_fingerprint(first) != structure_fingerprint(second)
    assert 0.0 < structure_similarity(first, second) < 1.0


def test_graph_node_round_trip_preserves_structure_profile(tmp_path) -> None:
    profile = build_structure_profile(_extra("Order #123"))
    assert profile is not None
    contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {
                    "selector": {"resource_id": "com.example:id/submit"},
                    "state": ["visible", "clickable"],
                }
            ],
            "forbidden": [],
        },
        "mask_rules": [],
    })
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    saved = store.upsert_node(
        GraphNode(
            node_id="",
            app="com.example.app",
            platform="android",
            description="Submit page",
            state_contract=contract,
            structure_profile=profile,
        )
    )

    reloaded = SkillGraphStore(store_dir=tmp_path / "graph")
    node = reloaded.get_node(saved.node_id)

    assert node is not None
    assert node.structure_profile == profile
    assert node.structure_fingerprint == structure_fingerprint(profile)
