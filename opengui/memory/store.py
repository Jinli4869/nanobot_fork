"""
opengui.memory.store
~~~~~~~~~~~~~~~~~~~~
JSON-based persistent memory store.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from opengui.memory.types import MemoryEntry, MemoryType


class MemoryStore:
    """Persistent key-value store for :class:`MemoryEntry` objects.

    Entries are persisted as a single JSON file at ``{store_dir}/memory.json``.
    """

    def __init__(self, store_dir: Path | str) -> None:
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "memory.json"
        self._entries: dict[str, MemoryEntry] = {}
        self.load()

    @property
    def count(self) -> int:
        return len(self._entries)

    def add(self, entry: MemoryEntry) -> None:
        self._entries[entry.entry_id] = entry
        self.save()

    def remove(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            self.save()
            return True
        return False

    def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def list_all(
        self,
        *,
        memory_type: MemoryType | None = None,
        platform: str | None = None,
        app: str | None = None,
    ) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        for entry in self._entries.values():
            if memory_type is not None and entry.memory_type != memory_type:
                continue
            if platform is not None and entry.platform != platform:
                continue
            if app is not None and entry.app != app:
                continue
            results.append(entry)
        return results

    def save(self) -> None:
        payload = {
            "entries": {eid: e.to_dict() for eid, e in self._entries.items()},
        }
        # Atomic write via tempfile
        tmp_fd = tempfile.NamedTemporaryFile(
            mode="w", dir=self._dir, suffix=".tmp", delete=False, encoding="utf-8",
        )
        try:
            json.dump(payload, tmp_fd, ensure_ascii=False, indent=2)
            tmp_fd.close()
            Path(tmp_fd.name).replace(self._path)
        except BaseException:
            Path(tmp_fd.name).unlink(missing_ok=True)
            raise

    def load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)
        self._entries.clear()
        for eid, entry_data in data.get("entries", {}).items():
            self._entries[eid] = MemoryEntry.from_dict(entry_data)
