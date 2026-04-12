"""Production shortcut promotion from recorder traces."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.shortcut import ShortcutSkill
from opengui.skills.shortcut_extractor import ExtractionPipeline, ExtractionSuccess

logger = logging.getLogger(__name__)
_SUPPORTED_ACTION_TYPES = frozenset({
    "tap",
    "click",
    "input_text",
    "hotkey",
    "scroll",
    "swipe",
    "press",
    "wait",
    "open_app",
})
_COMMIT_HINTS = (
    "send",
    "submit",
    "post",
    "publish",
    "confirm",
    "checkout",
    "pay",
    "delete",
    "share",
)
_BRANCH_HINTS = (
    "if ",
    "else",
    "otherwise",
    "retry",
    "fail",
    "failed",
    "success",
    "succeeded",
)


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
        steps = self._canonicalize_steps(steps)
        if not steps:
            return None
        steps = self._collapse_app_opening_prefix(steps)
        if not steps:
            return None
        steps = self._truncate_to_reusable_prefix(steps)
        if not steps:
            return None

        metadata_row = self._find_metadata_row(rows)
        metadata = {
            "task": str(metadata_row.get("task", "")),
            "platform": self._platform or str(metadata_row.get("platform", "unknown")),
            "app": self._derive_app_hint(steps),
        }
        metadata["app"] = normalize_app_identifier(
            str(metadata["platform"]),
            str(metadata["app"]),
        )

        gate_reason = self._gate_candidate_rows(steps, metadata)
        if gate_reason is not None:
            logger.info("Skipping shortcut promotion for %s: %s", trace_path, gate_reason)
            return None

        result = await ExtractionPipeline().run(steps, metadata)
        if not isinstance(result, ExtractionSuccess):
            logger.info("Skipping shortcut promotion for %s: %s", trace_path, result.reason)
            return None

        enriched = self._enrich_candidate(result.candidate, trace_path, steps, metadata)
        decision, skill_id = await store.add_or_merge(enriched)
        logger.info(
            "Promoted shortcut %s from %s via %s",
            skill_id or enriched.skill_id,
            trace_path,
            decision,
        )
        return skill_id

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

    def _gate_candidate_rows(
        self,
        steps: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> str | None:
        if not steps:
            return "too_few_promotable_steps"
        if str(metadata.get("app", "unknown")) == "unknown":
            return "unknown_app"
        if all(not str(step.get("model_output", "")).strip() for step in steps):
            return "empty_model_output"
        unsupported = [
            str(step.get("action", {}).get("action_type", "")).strip()
            for step in steps
            if str(step.get("action", {}).get("action_type", "")).strip()
            not in _SUPPORTED_ACTION_TYPES
        ]
        if unsupported:
            return f"unsupported_action_type:{unsupported[0]}"
        return None

    def _truncate_to_reusable_prefix(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        boundary = self._find_reusable_boundary(steps)
        if boundary is None:
            return list(steps)
        return list(steps[:boundary])

    def _canonicalize_steps(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not steps:
            return []

        canonicalized: list[dict[str, Any]] = []
        for step in steps:
            if canonicalized and self._is_duplicate_wait(canonicalized[-1], step):
                canonicalized[-1] = step
                continue
            if canonicalized and self._is_duplicate_interaction(canonicalized[-1], step):
                canonicalized[-1] = self._prefer_richer_step(canonicalized[-1], step)
                continue
            canonicalized.append(step)
        return canonicalized

    _OPENING_ACTIONS = frozenset({"tap", "click", "scroll", "swipe", "wait"})

    def _collapse_app_opening_prefix(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace app-launching preamble steps with a single ``open_app`` step."""
        if not steps:
            return steps
        if self._action_type(steps[0]) == "open_app":
            return steps

        target_app = self._derive_app_hint(steps)
        if not target_app or target_app == "unknown":
            return steps

        prefix_end: int | None = None
        for i, step in enumerate(steps[:5]):
            if self._action_type(step) not in self._OPENING_ACTIONS:
                break
            obs = step.get("observation", {})
            if isinstance(obs, dict):
                fg = obs.get("foreground_app") or obs.get("app") or ""
                if self._normalize_text(fg) == self._normalize_text(target_app):
                    prefix_end = i
                    break

        if prefix_end is None:
            return steps

        last_prefix_step = steps[prefix_end]
        synthetic: dict[str, Any] = {
            **last_prefix_step,
            "action": {"action_type": "open_app", "text": target_app},
            "model_output": f"open_app({target_app})",
            "valid_state": "No need to verify",
            "expected_state": f"{target_app} is open and in the foreground",
        }
        return [synthetic] + steps[prefix_end + 1:]

    def _find_reusable_boundary(self, steps: list[dict[str, Any]]) -> int | None:
        for index, step in enumerate(steps):
            if self._is_task_specific_payload_step(step):
                return index
            if self._is_commit_or_branch_step(step):
                return index
        return None

    def _is_task_specific_payload_step(self, step: dict[str, Any]) -> bool:
        action = step.get("action", {})
        action_type = str(action.get("action_type", "")).strip().lower()
        if action_type != "input_text":
            return False
        text = str(action.get("text", "")).strip()
        if not text:
            return False
        return "{{" not in text or "}}" not in text

    def _is_commit_or_branch_step(self, step: dict[str, Any]) -> bool:
        combined = " ".join(
            part
            for part in (
                str(step.get("model_output", "")).strip().lower(),
                str(step.get("expected_state", "")).strip().lower(),
            )
            if part
        )
        if any(hint in combined for hint in _COMMIT_HINTS):
            return True
        return any(hint in combined for hint in _BRANCH_HINTS)

    def _is_duplicate_wait(self, previous: dict[str, Any], current: dict[str, Any]) -> bool:
        return (
            self._action_type(previous) == "wait"
            and self._action_type(current) == "wait"
            and self._state_signature(previous) == self._state_signature(current)
        )

    def _is_duplicate_interaction(self, previous: dict[str, Any], current: dict[str, Any]) -> bool:
        if self._action_type(previous) not in {"tap", "click"}:
            return False
        if self._action_type(previous) != self._action_type(current):
            return False
        if self._interaction_signature(previous) != self._interaction_signature(current):
            return False
        return self._states_match_or_one_is_richer(previous, current)

    @staticmethod
    def _action_type(step: dict[str, Any]) -> str:
        action = step.get("action", {})
        return str(action.get("action_type", "")).strip().lower()

    def _interaction_signature(self, step: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            self._action_type(step),
            self._normalize_text(step.get("model_output")),
            self._normalize_params(step.get("action")),
            self._normalize_app(step),
        )

    def _state_signature(self, step: dict[str, Any]) -> tuple[str, str, str]:
        return (
            self._normalize_app(step),
            self._normalize_text(step.get("valid_state")),
            self._normalize_text(step.get("expected_state")),
        )

    def _states_match_or_one_is_richer(self, previous: dict[str, Any], current: dict[str, Any]) -> bool:
        previous_valid = self._normalize_text(previous.get("valid_state"))
        current_valid = self._normalize_text(current.get("valid_state"))
        previous_expected = self._normalize_text(previous.get("expected_state"))
        current_expected = self._normalize_text(current.get("expected_state"))
        return self._compatible_state_value(previous_valid, current_valid) and self._compatible_state_value(
            previous_expected,
            current_expected,
        )

    @staticmethod
    def _compatible_state_value(previous: str, current: str) -> bool:
        return previous == current or not previous or not current

    def _prefer_richer_step(self, previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        if self._state_richness(current) >= self._state_richness(previous):
            return current
        return previous

    def _state_richness(self, step: dict[str, Any]) -> tuple[int, int]:
        valid_state = self._normalize_text(step.get("valid_state"))
        expected_state = self._normalize_text(step.get("expected_state"))
        values = [value for value in (valid_state, expected_state) if value]
        return (len(values), sum(len(value) for value in values))

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().lower().split())

    def _normalize_params(self, action: Any) -> str:
        if not isinstance(action, dict):
            return ""
        params = {
            key: value
            for key, value in action.items()
            if key not in {"action_type", "x", "y", "x2", "y2"}
        }
        return json.dumps(params, sort_keys=True, separators=(",", ":"))

    def _normalize_app(self, step: dict[str, Any]) -> str:
        observation = step.get("observation", {})
        if isinstance(observation, dict):
            app = observation.get("app")
            if app is not None:
                return self._normalize_text(app)
        return self._normalize_text(step.get("app"))

    def _enrich_candidate(
        self,
        candidate: ShortcutSkill,
        trace_path: Path,
        steps: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> ShortcutSkill:
        return ShortcutSkill(
            skill_id=candidate.skill_id,
            name=candidate.name,
            description=candidate.description,
            app=candidate.app,
            platform=candidate.platform,
            steps=candidate.steps,
            parameter_slots=candidate.parameter_slots,
            preconditions=candidate.preconditions,
            postconditions=candidate.postconditions,
            tags=candidate.tags,
            source_task=str(metadata.get("task", "")).strip() or None,
            source_trace_path=str(trace_path),
            source_run_id=trace_path.parent.name or None,
            source_step_indices=tuple(
                int(step["step_index"])
                for step in steps
                if step.get("step_index") is not None
            ),
            promotion_version=1,
            shortcut_version=max(candidate.shortcut_version, 1),
            merged_from_ids=candidate.merged_from_ids,
            promoted_at=time.time(),
            created_at=candidate.created_at,
        )

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
