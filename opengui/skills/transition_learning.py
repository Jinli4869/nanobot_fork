"""
opengui.skills.transition_learning
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Derive graph transition evidence from ordinary agent trajectories.

This module records observations as evidence only.  It does not promote
observed transitions into active graph edges; later verification/promotion
steps decide whether an edge is reliable enough to execute.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opengui.skills.state_contract import infer_state_contract, normalize_state_contract
from opengui.skills.state_structure import build_structure_profile, structure_fingerprint
from opengui.skills.static_selector_filter import (
    filter_static_resource_ids,
    filter_static_texts,
    static_selector_from_node,
)

_TRANSITION_PHASES = {None, "agent", "retry", "recovery"}
_SKIPPED_ACTIONS = {"done", "screenshot"}


def sync_transition_evidence_from_trace(store: Any, trace_path: Path | str) -> int:
    """Append ordinary step transition evidence from *trace_path* to *store*."""
    path = Path(trace_path)
    records = derive_transition_evidence(path)
    for record in records:
        store.append_transition_evidence(record)
    return len(records)


def derive_transition_evidence(trace_path: Path | str) -> list[dict[str, Any]]:
    path = Path(trace_path)
    events = _load_jsonl(path)
    metadata = next((event for event in events if event.get("type") == "metadata"), {})
    steps = [
        event for event in events
        if event.get("type") == "step"
        and (event.get("phase") in _TRANSITION_PHASES)
        and isinstance(event.get("observation"), dict)
        and isinstance(event.get("action"), dict)
    ]
    records: list[dict[str, Any]] = []
    for previous, current in zip(steps, steps[1:]):
        action = current.get("action") if isinstance(current.get("action"), dict) else {}
        action_type = _action_type(action)
        if not action_type or action_type in _SKIPPED_ACTIONS:
            continue
        source_observation = previous.get("observation")
        target_observation = current.get("observation")
        if not isinstance(source_observation, dict) or not isinstance(target_observation, dict):
            continue
        source_contract = _source_contract(action, source_observation)
        target_contract = _observation_contract(target_observation)
        source_extra = _observation_extra(source_observation)
        target_extra = _observation_extra(target_observation)
        source_structure = build_structure_profile(source_extra)
        target_structure = build_structure_profile(target_extra)
        failure_reason = _failure_reason(current)
        app = (
            _observation_app(target_observation)
            or _observation_app(source_observation)
            or metadata.get("app")
        )
        platform = (
            target_observation.get("platform")
            or source_observation.get("platform")
            or metadata.get("platform")
        )
        record: dict[str, Any] = {
            "platform": platform,
            "app": app,
            "source_node_id": None,
            "target_node_id": None,
            "action_type": action_type,
            "edge_kind": "agent_step",
            "reason": failure_reason or "observed_agent_transition",
            "candidate_node_ids": [],
            "source_step_index": previous.get("step_index"),
            "target_step_index": current.get("step_index"),
            "action": dict(action),
            "success": failure_reason is None,
            "failure_reason": failure_reason,
            "source_contract": source_contract,
            "target_contract": target_contract,
            "source_structure_fingerprint": structure_fingerprint(source_structure),
            "target_structure_fingerprint": structure_fingerprint(target_structure),
            "source_structure_profile": source_structure,
            "target_structure_profile": target_structure,
            "trace_ref": {
                "path": str(path),
                "source_step_index": previous.get("step_index"),
                "target_step_index": current.get("step_index"),
            },
        }
        if isinstance(target_contract, dict):
            anchor = target_contract.get("anchor")
            if isinstance(anchor, dict):
                record["anchor"] = anchor
        records.append(record)
    return records


def _source_contract(action: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any] | None:
    extra = _observation_extra(observation)
    contract = infer_state_contract(
        action,
        observation_extra=extra,
        app=_observation_app(observation) or "",
    )
    return contract or _observation_contract(observation)


def _observation_contract(observation: dict[str, Any]) -> dict[str, Any] | None:
    app = _observation_app(observation)
    if not app:
        return None
    extra = _observation_extra(observation)
    selector = _first_static_selector(extra)
    anchor: dict[str, Any] = {"app_package": app}
    activity = extra.get("activity_class") or extra.get("activity")
    if isinstance(activity, str) and activity.strip():
        anchor["activity_class"] = activity.strip()
    if not selector:
        return normalize_state_contract({
            "anchor": anchor,
            "signature": {"required": [], "forbidden": []},
            "mask_rules": [],
        })
    return normalize_state_contract({
        "anchor": anchor,
        "signature": {
            "required": [{"selector": selector, "state": ["visible"]}],
            "forbidden": [],
        },
        "mask_rules": [],
    })


def _first_static_selector(extra: dict[str, Any]) -> dict[str, str] | None:
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if not isinstance(node, dict):
                continue
            selector = static_selector_from_node(node)
            if selector:
                return {
                    key: str(value)
                    for key, value in selector.items()
                    if key in {"resource_id", "content_desc", "text", "xpath"}
                }
    resource_ids = filter_static_resource_ids(extra.get("resource_ids"), limit=1)
    if resource_ids:
        return {"resource_id": resource_ids[0]}
    content_desc = filter_static_texts(extra.get("content_desc"), limit=1)
    if content_desc:
        return {"content_desc": content_desc[0]}
    visible_text = filter_static_texts(extra.get("visible_text"), limit=1)
    if visible_text:
        return {"text": visible_text[0]}
    return None


def _observation_extra(observation: dict[str, Any]) -> dict[str, Any]:
    extra = observation.get("extra")
    return extra if isinstance(extra, dict) else {}


def _observation_app(observation: dict[str, Any]) -> str | None:
    value = observation.get("foreground_app") or observation.get("app")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _action_type(action: dict[str, Any]) -> str:
    value = action.get("action_type") or action.get("type")
    return str(value or "").strip().lower()


def _failure_reason(event: dict[str, Any]) -> str | None:
    for key in ("failure_reason", "error"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    action = event.get("action")
    if isinstance(action, dict) and _action_type(action) == "request_intervention":
        return "request_intervention"
    return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except OSError:
        return []
    return events

