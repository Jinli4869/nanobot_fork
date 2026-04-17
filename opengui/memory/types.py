"""
opengui.memory.types
~~~~~~~~~~~~~~~~~~~~
Memory data models for the GUI agent's knowledge store.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_VALID_REVIEW_STATUSES = frozenset({"pending", "approved", "rejected"})


def _normalize_confidence(value: Any, default: float = 0.5) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _normalize_review_status(value: Any, default: str = "approved") -> str:
    text = str(value or "").strip().lower()
    return text if text in _VALID_REVIEW_STATUSES else default


def _normalize_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class MemoryType(Enum):
    OS_GUIDE = "os"
    APP_GUIDE = "app"
    ICON_GUIDE = "icon"
    POLICY = "policy"


@dataclass(frozen=True)
class MemoryEntry:
    """A single knowledge entry in the GUI agent's memory store."""

    entry_id: str
    memory_type: MemoryType
    platform: str
    content: str
    app: str | None = None
    tags: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    confidence: float = 0.5
    source: str = "manual"
    review_status: str = "approved"
    success_count: int = 0
    failure_count: int = 0
    last_verified_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "memory_type": self.memory_type.value,
            "platform": self.platform,
            "content": self.content,
            "app": self.app,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "access_count": self.access_count,
            "confidence": _normalize_confidence(self.confidence),
            "source": self.source,
            "review_status": _normalize_review_status(self.review_status),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_verified_at": self.last_verified_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        last_verified_at_raw = data.get("last_verified_at")
        try:
            last_verified_at = (
                float(last_verified_at_raw)
                if last_verified_at_raw is not None
                else None
            )
        except (TypeError, ValueError):
            last_verified_at = None
        return cls(
            entry_id=data.get("entry_id", str(uuid.uuid4())),
            memory_type=MemoryType(data["memory_type"]),
            platform=data.get("platform", "unknown"),
            content=data["content"],
            app=data.get("app"),
            tags=tuple(data.get("tags", ())),
            created_at=data.get("created_at", time.time()),
            access_count=_normalize_int(data.get("access_count", 0), 0),
            confidence=_normalize_confidence(data.get("confidence", 0.5)),
            source=str(data.get("source", "manual") or "manual"),
            review_status=_normalize_review_status(data.get("review_status", "approved")),
            success_count=_normalize_int(data.get("success_count", 0), 0),
            failure_count=_normalize_int(data.get("failure_count", 0), 0),
            last_verified_at=last_verified_at,
        )
