"""Production shortcut promotion from recorder traces."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from opengui.skills.shortcut_extractor import ExtractionPipeline, ExtractionSuccess

logger = logging.getLogger(__name__)


class ShortcutPromotionPipeline:
    """Promote valid recorder step rows into shortcut storage."""

    def __init__(self, *, platform: str | None = None) -> None:
        self._platform = platform

    async def promote_from_trace(
        self,
        trace_path: Path,
        *,
        is_success: bool,
        store: Any,
    ) -> str | None:
        if not is_success or not trace_path.exists():
            return None

        rows = self._load_trace_rows(trace_path)
        if not rows:
            return None

        attempt_rows = self._select_final_successful_attempt(rows)
        if not attempt_rows:
            return None

        steps = self._filter_promotable_steps(attempt_rows)
        if not steps:
            return None

        metadata_row = self._find_metadata_row(rows)
        metadata = {
            "task": str(metadata_row.get("task", "")),
            "platform": self._platform or str(metadata_row.get("platform", "unknown")),
            "app": self._derive_app_hint(steps),
        }

        result = await ExtractionPipeline().run(steps, metadata)
        if not isinstance(result, ExtractionSuccess):
            logger.info("Skipping shortcut promotion for %s: %s", trace_path, result.reason)
            return None

        store.add(result.candidate)
        logger.info("Promoted shortcut %s from %s", result.candidate.skill_id, trace_path)
        return result.candidate.skill_id

    def _load_trace_rows(self, trace_path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with open(trace_path, encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed trace row %s:%s", trace_path, line_number)
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    def _select_final_successful_attempt(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        attempt_start_indexes: dict[Any, int] = {}
        latest_start_index: int | None = None
        latest_success_window: list[dict[str, Any]] | None = None
        saw_attempt_markers = False

        for index, row in enumerate(rows):
            row_type = row.get("type")
            if row_type == "attempt_start":
                saw_attempt_markers = True
                latest_start_index = index
                attempt_start_indexes[row.get("attempt", index)] = index
                continue
            if row_type != "attempt_result":
                continue

            saw_attempt_markers = True
            if not self._attempt_succeeded(row):
                continue

            attempt_key = row.get("attempt", index)
            start_index = attempt_start_indexes.get(attempt_key, latest_start_index)
            if start_index is None:
                continue
            latest_success_window = rows[start_index : index + 1]

        if latest_success_window is not None:
            return latest_success_window
        if saw_attempt_markers:
            return []

        terminal_result = self._find_terminal_result(rows)
        if terminal_result is not None and terminal_result.get("success") is True:
            return rows
        return []

    def _filter_promotable_steps(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        promotable_steps: list[dict[str, Any]] = []
        for row in rows:
            if row.get("type") != "step":
                continue
            if row.get("phase") != "agent":
                continue
            action = row.get("action")
            if not isinstance(action, dict):
                continue
            action_type = str(action.get("action_type", "")).strip()
            if not action_type:
                continue
            if row.get("step_index") is None:
                continue
            promotable_steps.append(row)
        return promotable_steps

    @staticmethod
    def _attempt_succeeded(row: dict[str, Any]) -> bool:
        if row.get("success") is True:
            return True
        return str(row.get("status", "")).lower() == "succeeded"

    @staticmethod
    def _find_metadata_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
        for row in rows:
            if row.get("type") == "metadata":
                return row
        return {}

    @staticmethod
    def _find_terminal_result(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        for row in reversed(rows):
            if row.get("type") == "result":
                return row
        return None

    @staticmethod
    def _derive_app_hint(rows: list[dict[str, Any]]) -> str:
        for row in reversed(rows):
            direct_app = str(row.get("app", "")).strip()
            if direct_app:
                return direct_app

            observation = row.get("observation")
            if isinstance(observation, dict):
                for key in ("app", "foreground_app"):
                    value = str(observation.get(key, "")).strip()
                    if value:
                        return value

            execution = row.get("execution")
            if isinstance(execution, dict):
                for key in ("app", "foreground_app"):
                    value = str(execution.get(key, "")).strip()
                    if value:
                        return value
                nested_observation = execution.get("observation")
                if isinstance(nested_observation, dict):
                    for key in ("app", "foreground_app"):
                        value = str(nested_observation.get(key, "")).strip()
                        if value:
                            return value
        return "unknown"
