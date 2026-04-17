from __future__ import annotations

import json
from pathlib import Path

from opengui.memory.review import MemoryReviewService
from opengui.memory.store import MemoryStore
from opengui.memory.types import MemoryType


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _candidate(entry_id: str, *, confidence: float = 0.9, step_count: int = 6) -> dict:
    return {
        "entry_id": entry_id,
        "memory_type": "app",
        "platform": "android",
        "app": "com.example.calendar",
        "tags": ["online_learning"],
        "created_at": 123.0,
        "access_count": 0,
        "confidence": confidence,
        "source": "online_learning",
        "review_status": "pending",
        "success_count": 1,
        "failure_count": 0,
        "last_verified_at": None,
        "content": "Task: create calendar event. Reliable path found.",
        "candidate_meta": {"step_count": step_count},
    }


def test_review_service_list_candidates_uses_last_record(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.jsonl"
    store = tmp_path / "memory"
    _append_jsonl(
        queue,
        [
            _candidate("c-1"),
            {**_candidate("c-1"), "review_status": "rejected"},
            _candidate("c-2"),
        ],
    )

    svc = MemoryReviewService(store_dir=store, queue_path=queue)
    pending = svc.list_candidates(status="pending")
    approved = svc.list_candidates(status="approved")
    rejected = svc.list_candidates(status="rejected")

    assert [row["entry_id"] for row in pending] == ["c-2"]
    assert approved == []
    assert [row["entry_id"] for row in rejected] == ["c-1"]


def test_review_service_approve_promotes_to_memory_store(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.jsonl"
    store_dir = tmp_path / "memory"
    _append_jsonl(queue, [_candidate("c-approve")])

    svc = MemoryReviewService(store_dir=store_dir, queue_path=queue)
    decision = svc.approve("c-approve", reviewer="tester", note="looks good")

    assert decision.status == "approved"
    assert decision.changed is True

    store = MemoryStore(store_dir)
    entries = store.list_all(memory_type=MemoryType.APP_GUIDE, app="com.example.calendar", platform="android")
    assert len(entries) == 1
    assert entries[0].entry_id == "c-approve"
    assert entries[0].review_status == "approved"

    approved = svc.list_candidates(status="approved")
    assert any(row["entry_id"] == "c-approve" for row in approved)


def test_review_service_reject_does_not_promote(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.jsonl"
    store_dir = tmp_path / "memory"
    _append_jsonl(queue, [_candidate("c-reject")])

    svc = MemoryReviewService(store_dir=store_dir, queue_path=queue)
    decision = svc.reject("c-reject", reviewer="tester", note="unsafe")

    assert decision.status == "rejected"
    assert decision.changed is True

    store = MemoryStore(store_dir)
    assert store.get("c-reject") is None


def test_review_service_auto_approve_threshold(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.jsonl"
    store_dir = tmp_path / "memory"
    _append_jsonl(
        queue,
        [
            _candidate("c-fast-good", confidence=0.92, step_count=5),
            _candidate("c-low-confidence", confidence=0.6, step_count=5),
            _candidate("c-too-long", confidence=0.93, step_count=20),
        ],
    )

    svc = MemoryReviewService(store_dir=store_dir, queue_path=queue)
    decisions = svc.auto_approve(min_confidence=0.85, max_step_count=10)

    assert [d.entry_id for d in decisions] == ["c-fast-good"]
    store = MemoryStore(store_dir)
    assert store.get("c-fast-good") is not None
    assert store.get("c-low-confidence") is None
    assert store.get("c-too-long") is None

