"""
opengui.skills.state_contract
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Small deterministic helpers for machine-checkable skill preconditions.

The contract is intentionally narrow:

``app``
    Expected foreground app/package.
``must_exist`` / ``must_not_exist``
    Lists of selectors over compact UI-tree metadata. Selectors support
    ``text``, ``content_desc``, ``resource_id``, ``class``, ``clickable``,
    ``focused``, and ``scrollable``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_SELECTOR_KEYS = frozenset({
    "text",
    "content_desc",
    "resource_id",
    "class",
    "clickable",
    "focused",
    "scrollable",
})


def normalize_state_contract(contract: Any) -> dict[str, Any] | None:
    """Return a compact normalized contract or ``None`` when empty/invalid."""
    if not isinstance(contract, dict):
        return None

    out: dict[str, Any] = {}
    app = _clean_string(contract.get("app"))
    if app:
        out["app"] = app

    for key in ("must_exist", "must_not_exist"):
        selectors = _normalize_selectors(contract.get(key))
        if selectors:
            out[key] = selectors

    return out or None


def merge_state_contracts(base: Any, inferred: Any) -> dict[str, Any] | None:
    """Merge an LLM-provided contract with a rule-inferred supplement."""
    left = normalize_state_contract(base) or {}
    right = normalize_state_contract(inferred) or {}
    if not left:
        return right or None
    if not right:
        return left or None

    merged: dict[str, Any] = dict(left)
    if "app" not in merged and right.get("app"):
        merged["app"] = right["app"]
    for key in ("must_exist", "must_not_exist"):
        existing = list(merged.get(key, []))
        seen = {_selector_key(sel) for sel in existing}
        for selector in right.get(key, []):
            marker = _selector_key(selector)
            if marker not in seen:
                existing.append(selector)
                seen.add(marker)
        if existing:
            merged[key] = existing
    return normalize_state_contract(merged)


def evaluate_state_contract(
    contract: Any,
    *,
    observation: Any | None = None,
    foreground_app: str | None = None,
    observation_extra: dict[str, Any] | None = None,
) -> bool | None:
    """Evaluate a state contract against an observation.

    Returns:
        ``True`` when all available deterministic checks pass.
        ``False`` when any deterministic check fails.
        ``None`` when the observation does not contain enough structured
        evidence and the caller should fall back to a validator.
    """
    normalized = normalize_state_contract(contract)
    if not normalized:
        return None

    actual_app = (
        foreground_app
        or getattr(observation, "foreground_app", None)
        or _dict_get(observation, "foreground_app")
        or _dict_get(observation, "app")
    )
    extra = (
        observation_extra
        if observation_extra is not None
        else getattr(observation, "extra", None)
        or _dict_get(observation, "extra")
        or {}
    )
    index = _UiIndex.from_extra(extra if isinstance(extra, dict) else {})

    checked = False
    unknown = False

    expected_app = normalized.get("app")
    if expected_app:
        checked = True
        if actual_app:
            if _normalize_app(actual_app) != _normalize_app(expected_app):
                return False
        else:
            unknown = True

    for selector in normalized.get("must_exist", []):
        checked = True
        matched = _selector_matches(selector, index)
        if matched is None:
            unknown = True
        elif not matched:
            return False

    for selector in normalized.get("must_not_exist", []):
        checked = True
        matched = _selector_matches(selector, index)
        if matched is None:
            unknown = True
        elif matched:
            return False

    if unknown:
        return None
    return True if checked else None


def infer_state_contract(
    step_payload: dict[str, Any],
    *,
    trajectory: dict[str, Any] | None = None,
    app: str | None = None,
) -> dict[str, Any] | None:
    """Infer a conservative contract from observed UI-tree metadata."""
    action_type = str(step_payload.get("action_type") or "").strip().lower()
    valid_state = step_payload.get("valid_state")
    if action_type in {"open_app", "wait", "done", "request_intervention"}:
        return None
    if _should_skip_valid_state(valid_state):
        return None

    contract: dict[str, Any] = {}
    clean_app = _clean_string(app)
    if clean_app and clean_app.lower() not in {"unknown", "app_package_or_name"}:
        contract["app"] = clean_app

    selector = _find_selector_for_target(
        str(step_payload.get("target") or ""),
        trajectory=trajectory or {},
        action_type=action_type,
    )
    if selector:
        contract["must_exist"] = [selector]

    return normalize_state_contract(contract)


def _normalize_selectors(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    selectors: list[dict[str, Any]] = []
    for item in raw_items:
        selector = _normalize_selector(item)
        if selector:
            selectors.append(selector)
    return selectors


def _normalize_selector(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        text = _clean_string(value)
        return {"text": text} if text else None
    if not isinstance(value, dict):
        return None

    selector: dict[str, Any] = {}
    for key in ("text", "content_desc", "resource_id", "class"):
        text = _clean_string(value.get(key))
        if text:
            selector[key] = text
    for key in ("clickable", "focused", "scrollable"):
        if key in value:
            selector[key] = bool(value.get(key))
    return selector or None


def _selector_matches(selector: dict[str, Any], index: "_UiIndex") -> bool | None:
    if not index.has_evidence:
        return None

    checks: list[bool] = []
    text = selector.get("text")
    content_desc = selector.get("content_desc")
    resource_id = selector.get("resource_id")
    class_name = selector.get("class")

    if text:
        haystack = index.clickable_text if selector.get("clickable") else index.visible_text
        if selector.get("focused"):
            haystack = index.focused_text
        if selector.get("clickable") or selector.get("focused"):
            checks.append(_contains_text(haystack, text))
        else:
            checks.append(_contains_text(haystack or index.all_text, text))

    if content_desc:
        haystack = index.clickable_text if selector.get("clickable") else index.content_desc
        if selector.get("focused"):
            haystack = index.focused_text
        if selector.get("clickable") or selector.get("focused"):
            checks.append(_contains_text(haystack, content_desc))
        else:
            checks.append(_contains_text(haystack or index.all_text, content_desc))

    if resource_id:
        checks.append(_contains_text(index.resource_ids, resource_id))

    if class_name:
        checks.append(_contains_text(index.class_names, class_name))

    if selector.get("focused") is True and not (text or content_desc):
        checks.append(bool(index.focused_text))

    if selector.get("clickable") is True and not (text or content_desc):
        checks.append(bool(index.clickable_text))

    if selector.get("scrollable") is True:
        checks.append(index.has_scrollable)

    if not checks:
        return None
    return all(checks)


def _find_selector_for_target(
    target: str,
    *,
    trajectory: dict[str, Any],
    action_type: str,
) -> dict[str, Any] | None:
    target_norm = _normalize_text(target)
    if len(target_norm) < 2:
        return None

    for extra in _iter_observation_extras(trajectory):
        clickable_text = _string_list(extra.get("clickable_text"))
        visible_text = _string_list(extra.get("visible_text"))
        content_desc = _string_list(extra.get("content_desc"))
        resource_ids = _string_list(extra.get("resource_ids"))

        if action_type in {"tap", "long_press", "double_tap"}:
            match = _best_target_match(target_norm, clickable_text)
            if match:
                return {"text": match, "clickable": True}

        match = _best_target_match(target_norm, visible_text)
        if match:
            return {"text": match}

        match = _best_target_match(target_norm, content_desc)
        if match:
            selector: dict[str, Any] = {"content_desc": match}
            if action_type in {"tap", "long_press", "double_tap"} and match in clickable_text:
                selector["clickable"] = True
            return selector

        match = _best_target_match(target_norm, resource_ids)
        if match:
            return {"resource_id": match}

    return None


def _iter_observation_extras(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []

    def add_from_observation(obs: Any) -> None:
        if not isinstance(obs, dict):
            return
        extra = obs.get("extra")
        if isinstance(extra, dict):
            extras.append(extra)

    for step in trajectory.get("agent_phase", []) or []:
        if isinstance(step, dict):
            add_from_observation(step.get("observation"))

    skill_phase = trajectory.get("skill_phase")
    if isinstance(skill_phase, dict):
        for step in skill_phase.get("steps", []) or []:
            if isinstance(step, dict):
                add_from_observation(step.get("observation"))
                for substep in step.get("subgoal_recovery_attempts", []) or []:
                    if isinstance(substep, dict):
                        add_from_observation(substep.get("observation"))

    return extras


@dataclass
class _UiIndex:
    visible_text: list[str] = field(default_factory=list)
    content_desc: list[str] = field(default_factory=list)
    resource_ids: list[str] = field(default_factory=list)
    clickable_text: list[str] = field(default_factory=list)
    focused_text: list[str] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)
    all_text: list[str] = field(default_factory=list)
    has_scrollable: bool = False
    has_evidence: bool = False

    @classmethod
    def from_extra(cls, extra: dict[str, Any]) -> "_UiIndex":
        index = cls(
            visible_text=_string_list(extra.get("visible_text")),
            content_desc=_string_list(extra.get("content_desc")),
            resource_ids=_string_list(extra.get("resource_ids")),
            clickable_text=_string_list(extra.get("clickable_text")),
            focused_text=_string_list(extra.get("focused_text")),
            class_names=_string_list(extra.get("class_names")),
            has_scrollable=_truthy(extra.get("scrollable_present")),
        )
        for node in extra.get("ui_tree") or []:
            if not isinstance(node, dict):
                if isinstance(node, str):
                    index.all_text.append(node)
                continue
            text = _clean_string(node.get("text"))
            content_desc = _clean_string(node.get("content_desc"))
            resource_id = _clean_string(node.get("resource_id"))
            class_name = _clean_string(node.get("class"))
            label = text or content_desc
            if text:
                index.visible_text.append(text)
            if content_desc:
                index.content_desc.append(content_desc)
            if resource_id:
                index.resource_ids.append(resource_id)
            if class_name:
                index.class_names.append(class_name)
            if node.get("clickable") and label:
                index.clickable_text.append(label)
            if node.get("focused") and label:
                index.focused_text.append(label)
            if node.get("scrollable"):
                index.has_scrollable = True

        index.visible_text = _dedupe(index.visible_text)
        index.content_desc = _dedupe(index.content_desc)
        index.resource_ids = _dedupe(index.resource_ids)
        index.clickable_text = _dedupe(index.clickable_text)
        index.focused_text = _dedupe(index.focused_text)
        index.class_names = _dedupe(index.class_names)
        index.all_text = _dedupe(
            index.all_text
            + index.visible_text
            + index.content_desc
            + index.resource_ids
            + index.clickable_text
            + index.focused_text
            + index.class_names
        )
        index.has_evidence = bool(
            index.all_text
            or extra.get("ui_tree_node_count")
            or index.has_scrollable
        )
        return index


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    return _dedupe(text for item in items if (text := _clean_string(item)))


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _best_target_match(target_norm: str, candidates: list[str]) -> str | None:
    best: tuple[int, str] | None = None
    for candidate in candidates:
        cand_norm = _normalize_text(candidate)
        if len(cand_norm) < 2:
            continue
        if cand_norm == target_norm or cand_norm in target_norm or target_norm in cand_norm:
            score = len(cand_norm)
            if best is None or score > best[0]:
                best = (score, candidate)
    return best[1] if best else None


def _contains_text(haystack: list[str], needle: str) -> bool:
    needle_norm = _normalize_text(needle)
    if not needle_norm:
        return False
    for item in haystack:
        item_norm = _normalize_text(item)
        if needle_norm == item_norm or needle_norm in item_norm or item_norm in needle_norm:
            return True
    return False


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


def _normalize_text(value: Any) -> str:
    return _clean_string(value).casefold()


def _normalize_app(value: Any) -> str:
    return _normalize_text(value)


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_string(value)
        if not text:
            continue
        marker = text.casefold()
        if marker in seen:
            continue
        out.append(text)
        seen.add(marker)
    return out


def _selector_key(selector: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted(selector.items()))


def _dict_get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _should_skip_valid_state(valid_state: Any) -> bool:
    text = _normalize_text(valid_state)
    if not text:
        return True
    return any(hint in text for hint in ("no need to verify", "return true", "skip", "none", "n/a"))
