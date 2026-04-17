"""
opengui.memory.review
~~~~~~~~~~~~~~~~~~~~~
Review workflow for online-learned memory candidates.

This module closes the loop:
1. Post-run emits pending memory candidates into a review queue JSONL.
2. Reviewer (human or rule-based) approves/rejects candidates.
3. Approved candidates are promoted into MemoryStore as first-class entries.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opengui.memory.store import MemoryStore
from opengui.memory.types import MemoryEntry, MemoryType
from opengui.postprocessing import DEFAULT_MEMORY_REVIEW_QUEUE

_VALID_STATUSES = frozenset({"pending", "approved", "rejected"})


def _normalize_status(value: Any, default: str = "pending") -> str:
    text = str(value or "").strip().lower()
    return text if text in _VALID_STATUSES else default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ReviewDecision:
    entry_id: str
    status: str
    changed: bool
    reason: str | None = None


class MemoryReviewService:
    """Queue-backed review service for online memory candidates."""

    def __init__(
        self,
        *,
        store_dir: Path | str,
        queue_path: Path | str = DEFAULT_MEMORY_REVIEW_QUEUE,
    ) -> None:
        self._store_dir = Path(store_dir)
        self._queue_path = Path(queue_path)

    def list_candidates(self, *, status: str | None = None) -> list[dict[str, Any]]:
        by_id = self._load_latest_by_id()
        items = list(by_id.values())
        if status is not None:
            normalized = _normalize_status(status, default="pending")
            items = [item for item in items if _normalize_status(item.get("review_status")) == normalized]
        items.sort(key=lambda item: _to_float(item.get("created_at"), 0.0))
        return items

    def approve(
        self,
        entry_id: str,
        *,
        reviewer: str = "human",
        note: str = "",
    ) -> ReviewDecision:
        by_id = self._load_latest_by_id()
        candidate = by_id.get(entry_id)
        if candidate is None:
            return ReviewDecision(entry_id=entry_id, status="missing", changed=False, reason="candidate_not_found")

        existing_status = _normalize_status(candidate.get("review_status"))
        if existing_status == "approved":
            # Idempotent behavior: ensure entry exists in store.
            self._promote_candidate(candidate)
            return ReviewDecision(entry_id=entry_id, status="approved", changed=False, reason="already_approved")

        candidate = dict(candidate)
        candidate["review_status"] = "approved"
        candidate["reviewed_at"] = time.time()
        candidate["reviewed_by"] = reviewer
        candidate["review_note"] = note
        self._append_queue_record(candidate)
        self._promote_candidate(candidate)
        return ReviewDecision(entry_id=entry_id, status="approved", changed=True, reason=None)

    def reject(
        self,
        entry_id: str,
        *,
        reviewer: str = "human",
        note: str = "",
    ) -> ReviewDecision:
        by_id = self._load_latest_by_id()
        candidate = by_id.get(entry_id)
        if candidate is None:
            return ReviewDecision(entry_id=entry_id, status="missing", changed=False, reason="candidate_not_found")

        existing_status = _normalize_status(candidate.get("review_status"))
        if existing_status == "rejected":
            return ReviewDecision(entry_id=entry_id, status="rejected", changed=False, reason="already_rejected")

        candidate = dict(candidate)
        candidate["review_status"] = "rejected"
        candidate["reviewed_at"] = time.time()
        candidate["reviewed_by"] = reviewer
        candidate["review_note"] = note
        self._append_queue_record(candidate)
        return ReviewDecision(entry_id=entry_id, status="rejected", changed=True, reason=None)

    def auto_approve(
        self,
        *,
        min_confidence: float = 0.85,
        max_step_count: int = 12,
        reviewer: str = "auto",
    ) -> list[ReviewDecision]:
        decisions: list[ReviewDecision] = []
        for candidate in self.list_candidates(status="pending"):
            confidence = _to_float(candidate.get("confidence"), 0.0)
            meta = candidate.get("candidate_meta")
            if not isinstance(meta, dict):
                meta = {}
            step_count = int(_to_float(meta.get("step_count"), 999))
            if confidence < min_confidence or step_count > max_step_count:
                continue
            decisions.append(
                self.approve(
                    str(candidate.get("entry_id", "")),
                    reviewer=reviewer,
                    note=f"auto_approved(confidence>={min_confidence},step_count<={max_step_count})",
                )
            )
        return decisions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_latest_by_id(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        if not self._queue_path.exists():
            return latest
        try:
            with open(self._queue_path, encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    entry_id = str(row.get("entry_id", "")).strip()
                    if not entry_id:
                        continue
                    row = dict(row)
                    row["review_status"] = _normalize_status(row.get("review_status"))
                    latest[entry_id] = row
        except OSError:
            return latest
        return latest

    def _append_queue_record(self, row: dict[str, Any]) -> None:
        self._queue_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._queue_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _promote_candidate(self, candidate: dict[str, Any]) -> MemoryEntry:
        entry = self._candidate_to_memory_entry(candidate)
        store = MemoryStore(self._store_dir)
        store.add(entry)
        return entry

    @staticmethod
    def _candidate_to_memory_entry(candidate: dict[str, Any]) -> MemoryEntry:
        memory_type_raw = str(candidate.get("memory_type", "os"))
        try:
            memory_type = MemoryType(memory_type_raw)
        except ValueError:
            memory_type = MemoryType.OS_GUIDE

        data: dict[str, Any] = {
            "entry_id": str(candidate.get("entry_id", "")),
            "memory_type": memory_type.value,
            "platform": str(candidate.get("platform", "unknown")),
            "content": str(candidate.get("content", "")).strip(),
            "app": candidate.get("app"),
            "tags": list(candidate.get("tags", [])),
            "created_at": _to_float(candidate.get("created_at"), time.time()),
            "access_count": int(_to_float(candidate.get("access_count"), 0)),
            "confidence": _to_float(candidate.get("confidence"), 0.5),
            "source": str(candidate.get("source", "online_learning")),
            "review_status": "approved",
            "success_count": int(_to_float(candidate.get("success_count"), 0)),
            "failure_count": int(_to_float(candidate.get("failure_count"), 0)),
            "last_verified_at": candidate.get("last_verified_at"),
        }
        if not data["content"]:
            data["content"] = "Auto-promoted memory candidate"
        return MemoryEntry.from_dict(data)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review opengui memory candidates.")
    parser.add_argument("--store-dir", default=str(Path.home() / ".opengui" / "memory"))
    parser.add_argument("--queue-path", default=str(DEFAULT_MEMORY_REVIEW_QUEUE))
    parser.add_argument("--status", default="pending", choices=["pending", "approved", "rejected", "all"])
    parser.add_argument("--approve", default=None, help="Candidate entry_id to approve.")
    parser.add_argument("--reject", default=None, help="Candidate entry_id to reject.")
    parser.add_argument("--note", default="", help="Optional review note.")
    parser.add_argument("--reviewer", default="cli", help="Reviewer label.")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve by thresholds.")
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--max-step-count", type=int, default=12)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    service = MemoryReviewService(
        store_dir=Path(args.store_dir),
        queue_path=Path(args.queue_path),
    )

    if args.approve:
        decision = service.approve(args.approve, reviewer=args.reviewer, note=args.note)
        print(json.dumps(decision.__dict__, ensure_ascii=False))
        return 0

    if args.reject:
        decision = service.reject(args.reject, reviewer=args.reviewer, note=args.note)
        print(json.dumps(decision.__dict__, ensure_ascii=False))
        return 0

    if args.auto_approve:
        decisions = service.auto_approve(
            min_confidence=args.min_confidence,
            max_step_count=args.max_step_count,
            reviewer=args.reviewer,
        )
        print(json.dumps([decision.__dict__ for decision in decisions], ensure_ascii=False))
        return 0

    status = None if args.status == "all" else args.status
    items = service.list_candidates(status=status)
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    raise SystemExit(main())

