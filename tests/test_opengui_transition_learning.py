from __future__ import annotations

import json
from pathlib import Path

import pytest

from opengui.postprocessing import PostRunProcessor
from opengui.skills.graph import SkillGraphStore
from opengui.skills.transition_learning import sync_transition_evidence_from_trace


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def _observation(label: str, resource_id: str) -> dict[str, object]:
    return {
        "foreground_app": "com.example.app",
        "app": "com.example.app",
        "platform": "android",
        "extra": {
            "visible_text": [label],
            "clickable_text": [label],
            "resource_ids": [resource_id],
            "ui_tree": [
                {
                    "class": "android.widget.TextView",
                    "resource_id": resource_id,
                    "text": label,
                    "xpath": "/hierarchy/android.widget.FrameLayout[1]/android.widget.TextView[1]",
                }
            ],
        },
    }


def test_sync_transition_evidence_from_agent_trace(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            {"type": "metadata", "task": "open orders", "platform": "android"},
            {
                "type": "step",
                "phase": "agent",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": _observation("Home", "com.example:id/home"),
            },
            {
                "type": "step",
                "phase": "agent",
                "step_index": 1,
                "action": {"action_type": "tap", "text": "Orders"},
                "observation": _observation("Orders", "com.example:id/orders"),
            },
            {"type": "result", "success": True},
        ],
    )
    store = SkillGraphStore(store_dir=tmp_path / "graph")

    count = sync_transition_evidence_from_trace(store, trace_path)

    assert count == 1
    records = [
        json.loads(line)
        for line in (tmp_path / "graph" / "skill_graph_transition_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records[0]["edge_kind"] == "agent_step"
    assert records[0]["source_step_index"] == 0
    assert records[0]["target_step_index"] == 1
    assert records[0]["action_type"] == "tap"
    assert records[0]["success"] is True
    assert records[0]["source_structure_fingerprint"]
    assert records[0]["target_structure_fingerprint"]
    assert records[0]["source_contract"]["anchor"]["app_package"] == "com.example.app"
    assert records[0]["target_contract"]["anchor"]["app_package"] == "com.example.app"


def test_sync_transition_evidence_records_failed_step_reason(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            {"type": "metadata", "task": "open orders", "platform": "android"},
            {
                "type": "step",
                "phase": "agent",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": _observation("Home", "com.example:id/home"),
            },
            {
                "type": "step",
                "phase": "agent",
                "step_index": 1,
                "action": {"action_type": "tap", "text": "Orders"},
                "observation": _observation("Home", "com.example:id/home"),
                "error": "target_contract_miss",
            },
        ],
    )
    store = SkillGraphStore(store_dir=tmp_path / "graph")

    count = sync_transition_evidence_from_trace(store, trace_path)

    assert count == 1
    record = json.loads(
        (tmp_path / "graph" / "skill_graph_transition_evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert record["success"] is False
    assert record["failure_reason"] == "target_contract_miss"


@pytest.mark.asyncio
async def test_postprocessor_syncs_transition_evidence(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            {"type": "metadata", "task": "open orders", "platform": "android"},
            {
                "type": "step",
                "phase": "agent",
                "step_index": 0,
                "action": {"action_type": "open_app", "text": "com.example.app"},
                "observation": _observation("Home", "com.example:id/home"),
            },
            {
                "type": "step",
                "phase": "agent",
                "step_index": 1,
                "action": {"action_type": "tap", "text": "Orders"},
                "observation": _observation("Orders", "com.example:id/orders"),
            },
        ],
    )
    processor = PostRunProcessor(llm=None, skill_store_root=tmp_path / "graph")

    count = await processor._sync_transition_evidence(trace_path)

    assert count == 1
    assert (tmp_path / "graph" / "skill_graph_transition_evidence.jsonl").exists()
