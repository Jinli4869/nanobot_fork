"""
opengui.skills.state_contract
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Deterministic helpers for machine-checkable GUI state contracts.

Canonical contracts use the v5 shape:

``anchor``
    Strong identity fields. ``app_package`` is required when known; optional
    ``activity_class`` / ``fragment_class`` are exact-match hints.
``signature``
    Stable UI selectors split into ``required`` and ``forbidden`` elements.
``mask_rules``
    Explicit dynamic-content masks used during extraction/versioning.
``fingerprint``
    ``sha256(canonical_json(normalized_contract_without_fingerprint))``.  It
    is used for dedup/version/cache only, never as the runtime match itself.

Legacy contracts shaped as ``{"app": ..., "must_exist": ...}`` are accepted
and normalized into the canonical schema.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from opengui.skills.static_selector_filter import (
    filter_static_resource_ids,
    filter_static_texts,
    selector_is_static,
    static_selector_from_node,
)


_SELECTOR_KEYS = frozenset({
    "text",
    "content_desc",
    "resource_id",
    "class",
    "xpath",
})
_STATE_FLAGS = ("visible", "clickable", "enabled", "focused", "scrollable")
_STATE_FLAG_SET = frozenset(_STATE_FLAGS)
_SELECTOR_MATCH_THRESHOLD = 0.72
_EXTRA_HINT_KEYS = frozenset({
    "visible_text",
    "content_desc",
    "resource_ids",
    "clickable_text",
    "focused_text",
    "enabled_text",
    "class_names",
    "xpaths",
    "ui_tree",
    "ui_tree_node_count",
    "screen_width",
    "screen_height",
    "scrollable_present",
    "enabled_present",
})


def normalize_state_contract(contract: Any) -> dict[str, Any] | None:
    """Return a canonical v5 state contract or ``None`` when empty/invalid."""
    if not isinstance(contract, dict):
        return None

    anchor = _normalize_anchor(contract)
    required, forbidden = _normalize_signature(contract)
    mask_rules = _normalize_mask_rules(contract.get("mask_rules"))

    if not anchor and not required and not forbidden:
        return None

    normalized: dict[str, Any] = {
        "anchor": anchor,
        "signature": {
            "required": required,
            "forbidden": forbidden,
        },
        "mask_rules": mask_rules,
    }
    normalized["fingerprint"] = _compute_fingerprint(normalized)
    return normalized


def state_contract_fingerprint(contract: Any) -> str:
    """Return the canonical SHA-256 fingerprint for *contract*.

    The stored ``fingerprint`` field, when present, is ignored and recomputed
    from normalized content.
    """
    normalized = normalize_state_contract(contract)
    if not normalized:
        return ""
    return str(normalized["fingerprint"])


def state_contract_overlap(left: Any, right: Any) -> float:
    """Return selector overlap in ``[0, 1]`` for version-trigger decisions."""
    lnorm = normalize_state_contract(left)
    rnorm = normalize_state_contract(right)
    if not lnorm or not rnorm:
        return 0.0
    if _anchor_key(lnorm.get("anchor")) != _anchor_key(rnorm.get("anchor")):
        return 0.0
    left_elements = list(lnorm.get("signature", {}).get("required", []))
    right_elements = list(rnorm.get("signature", {}).get("required", []))
    if not left_elements and not right_elements:
        return 1.0
    if not left_elements or not right_elements:
        return 0.0
    scores: list[float] = []
    for left_element in left_elements:
        scores.append(max(
            (_element_similarity(left_element, right_element) for right_element in right_elements),
            default=0.0,
        ))
    return sum(scores) / max(len(left_elements), len(right_elements))


def merge_state_contracts(base: Any, inferred: Any) -> dict[str, Any] | None:
    """Merge an LLM-provided contract with a rule-inferred supplement."""
    left = normalize_state_contract(base) or {}
    right = normalize_state_contract(inferred) or {}
    if not left:
        return right or None
    if not right:
        return left or None

    anchor: dict[str, Any] = dict(right.get("anchor", {}))
    anchor.update(left.get("anchor", {}))

    signature = {
        "required": _dedupe_elements(
            list(left.get("signature", {}).get("required", []))
            + list(right.get("signature", {}).get("required", []))
        ),
        "forbidden": _dedupe_elements(
            list(left.get("signature", {}).get("forbidden", []))
            + list(right.get("signature", {}).get("forbidden", []))
        ),
    }
    mask_rules = _dedupe_mask_rules(
        list(left.get("mask_rules", [])) + list(right.get("mask_rules", []))
    )
    return normalize_state_contract({
        "anchor": anchor,
        "signature": signature,
        "mask_rules": mask_rules,
    })


def score_state_contract(
    contract: Any,
    *,
    observation: Any | None = None,
    foreground_app: str | None = None,
    observation_extra: dict[str, Any] | None = None,
    selector_threshold: float = _SELECTOR_MATCH_THRESHOLD,
) -> float | None:
    """Score a contract against the current observation.

    Returns ``None`` when there is not enough structured evidence, ``0.0`` for
    deterministic mismatch, otherwise a confidence score in ``[0, 1]``.
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

    checked: list[float] = []
    unknown = False

    anchor = normalized.get("anchor", {})
    expected_app = _clean_string(anchor.get("app_package"))
    if expected_app:
        if actual_app:
            if _normalize_app(actual_app) != _normalize_app(expected_app):
                return 0.0
            checked.append(1.0)

    for key in ("activity_class", "fragment_class"):
        expected = _clean_string(anchor.get(key))
        if not expected:
            continue
        actual = _clean_string(
            _dict_get(extra, key)
            or _dict_get(extra, key.replace("_class", ""))
            or _dict_get(observation, key)
        )
        if actual:
            if _normalize_text(actual) != _normalize_text(expected):
                return 0.0
            checked.append(1.0)
        else:
            unknown = True

    signature = normalized.get("signature", {})
    for element in signature.get("required", []):
        score = _element_score(element, index)
        if score is None:
            unknown = True
            continue
        if score < selector_threshold:
            return 0.0
        checked.append(score)

    for element in signature.get("forbidden", []):
        score = _element_score(element, index)
        if score is None:
            unknown = True
            continue
        if score >= selector_threshold:
            return 0.0
        checked.append(1.0)

    if unknown:
        return None
    if checked:
        return sum(checked) / len(checked)
    return None


def evaluate_state_contract(
    contract: Any,
    *,
    observation: Any | None = None,
    foreground_app: str | None = None,
    observation_extra: dict[str, Any] | None = None,
) -> bool | None:
    """Evaluate a state contract against an observation.

    Returns:
        ``True`` when all deterministic checks pass.
        ``False`` when any deterministic check fails.
        ``None`` when there is not enough structured evidence.
    """
    score = score_state_contract(
        contract,
        observation=observation,
        foreground_app=foreground_app,
        observation_extra=observation_extra,
    )
    if score is None:
        return None
    return score >= _SELECTOR_MATCH_THRESHOLD


def infer_state_contract(
    step_payload: dict[str, Any],
    *,
    trajectory: dict[str, Any] | None = None,
    app: str | None = None,
) -> dict[str, Any] | None:
    """Infer a conservative canonical contract from observed UI metadata."""
    action_type = str(step_payload.get("action_type") or "").strip().lower()
    valid_state = step_payload.get("valid_state")
    if action_type in {"open_app", "wait", "done", "request_intervention"}:
        return None
    if _should_skip_valid_state(valid_state):
        return None

    clean_app = _clean_string(app)
    anchor: dict[str, Any] = {}
    if clean_app and clean_app.lower() not in {"unknown", "app_package_or_name"}:
        anchor["app_package"] = clean_app

    selector = _find_selector_for_step(
        step_payload,
        trajectory=trajectory or {},
        action_type=action_type,
    )
    required: list[dict[str, Any]] = []
    if selector:
        state = ["visible"]
        if action_type in {"tap", "long_press", "double_tap"}:
            state.append("clickable")
        if action_type == "input_text":
            state.append("focused")
        required.append({
            "selector": {k: v for k, v in selector.items() if k in _SELECTOR_KEYS},
            "state": state,
        })

    if not required:
        return None

    return normalize_state_contract({
        "anchor": anchor,
        "signature": {"required": required, "forbidden": []},
        "mask_rules": _infer_mask_rules(trajectory or {}),
    })


def _normalize_anchor(contract: dict[str, Any]) -> dict[str, Any]:
    raw = contract.get("anchor") if isinstance(contract.get("anchor"), dict) else {}
    anchor: dict[str, Any] = {}

    app = (
        raw.get("app_package")
        or raw.get("app")
        or contract.get("app_package")
        or contract.get("app")
    )
    app_text = _clean_string(app)
    if app_text and app_text.lower() not in {"unknown", "app_package_or_name"}:
        anchor["app_package"] = app_text

    activity = (
        raw.get("activity_class")
        or raw.get("activity")
        or contract.get("activity_class")
        or contract.get("activity")
    )
    activity_text = _clean_string(activity)
    if activity_text:
        anchor["activity_class"] = activity_text

    fragment = (
        raw.get("fragment_class")
        or raw.get("fragment")
        or contract.get("fragment_class")
        or contract.get("fragment")
    )
    fragment_text = _clean_string(fragment)
    if fragment_text:
        anchor["fragment_class"] = fragment_text

    return anchor


def _normalize_signature(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signature = contract.get("signature") if isinstance(contract.get("signature"), dict) else {}
    required = _normalize_elements(
        signature.get("required")
        or signature.get("required_elements")
        or contract.get("required_elements")
        or contract.get("must_exist")
    )
    forbidden = _normalize_elements(
        signature.get("forbidden")
        or signature.get("forbidden_elements")
        or contract.get("forbidden_elements")
        or contract.get("must_not_exist")
        or contract.get("must_not_exist")
    )
    return _dedupe_elements(required), _dedupe_elements(forbidden)


def _normalize_elements(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    elements: list[dict[str, Any]] = []
    for item in raw_items:
        element = _normalize_element(item)
        if element:
            elements.append(element)
    return elements


def _normalize_element(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        text = _clean_string(value)
        return {"selector": {"text": text}, "state": ["visible"]} if text else None
    if not isinstance(value, dict):
        return None

    if isinstance(value.get("selector"), dict):
        selector_raw = dict(value["selector"])
        state_raw = value.get("state")
    else:
        selector_raw = dict(value)
        state_raw = value.get("state")

    selector, selector_state = _normalize_selector(selector_raw)
    state = _normalize_state_flags(state_raw)
    if not state:
        state = selector_state
    if selector and "visible" not in state:
        state = [*state, "visible"]

    if not selector and not state:
        return None
    return {"selector": selector, "state": _sort_state_flags(state)}


def _normalize_selector(value: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    selector: dict[str, Any] = {}
    state: list[str] = []
    for key in _SELECTOR_KEYS:
        text = _clean_string(value.get(key))
        if text:
            selector[key] = text
    for key in _STATE_FLAGS:
        if key in value and bool(value.get(key)):
            state.append(key)
    return selector, _sort_state_flags(state)


def _normalize_state_flags(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = [value] if isinstance(value, str) else value
    if not isinstance(raw_items, list):
        return []
    flags = [
        str(item).strip().lower()
        for item in raw_items
        if str(item).strip().lower() in _STATE_FLAG_SET
    ]
    return _sort_state_flags(flags)


def _sort_state_flags(flags: list[str]) -> list[str]:
    order = {name: i for i, name in enumerate(_STATE_FLAGS)}
    return sorted(set(flags), key=lambda item: order.get(item, len(order)))


def _normalize_mask_rules(value: Any) -> list[Any]:
    if value is None:
        return []
    raw_items = [value] if isinstance(value, (str, dict)) else value
    if not isinstance(raw_items, list):
        return []
    out: list[Any] = []
    for item in raw_items:
        if isinstance(item, str):
            text = _clean_string(item)
            if text:
                out.append(text)
        elif isinstance(item, dict):
            cleaned = {
                str(k): _clean_string(v)
                for k, v in sorted(item.items())
                if _clean_string(v)
            }
            if cleaned:
                out.append(cleaned)
    return _dedupe_mask_rules(out)


def _compute_fingerprint(normalized: dict[str, Any]) -> str:
    payload = {
        "anchor": normalized.get("anchor", {}),
        "signature": normalized.get("signature", {"required": [], "forbidden": []}),
        "mask_rules": normalized.get("mask_rules", []),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _dedupe_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for element in elements:
        key = _element_key(element)
        if key in seen:
            continue
        out.append(element)
        seen.add(key)
    return sorted(out, key=_element_key)


def _dedupe_mask_rules(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        key = _canonical_json(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return sorted(out, key=_canonical_json)


def _element_key(element: dict[str, Any]) -> str:
    return _canonical_json({
        "selector": element.get("selector", {}),
        "state": element.get("state", []),
    })


def _element_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    lsel = left.get("selector") if isinstance(left.get("selector"), dict) else {}
    rsel = right.get("selector") if isinstance(right.get("selector"), dict) else {}
    selector_score = 0.0
    for key in ("resource_id", "content_desc", "text", "class", "xpath"):
        lval = _clean_string(lsel.get(key))
        rval = _clean_string(rsel.get(key))
        if lval and rval:
            selector_score = max(selector_score, _best_text_score(lval, [rval]))
    lstates = set(left.get("state") or [])
    rstates = set(right.get("state") or [])
    state_score = 1.0 if not lstates and not rstates else (
        len(lstates & rstates) / len(lstates | rstates) if (lstates or rstates) else 0.0
    )
    return 0.80 * selector_score + 0.20 * state_score


def _anchor_key(anchor: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(anchor, dict):
        return ()
    return tuple(sorted((str(k), _normalize_text(v)) for k, v in anchor.items() if v))


def _element_score(element: dict[str, Any], index: "_UiIndex") -> float | None:
    if not index.has_evidence:
        return None

    selector = element.get("selector") if isinstance(element.get("selector"), dict) else {}
    states = set(element.get("state") or [])
    scores: list[float] = []

    selector_score = _selector_value_score(selector, index)
    if selector:
        if selector_score is None:
            return None
        scores.append(selector_score)

    for state in states:
        if state == "visible":
            scores.append(selector_score if selector else 1.0)
        elif state == "clickable":
            score = _state_text_score(selector, index.clickable_text, index)
            if score is None:
                return None
            scores.append(score)
        elif state == "focused":
            score = _state_text_score(selector, index.focused_text, index)
            if score is None:
                return None
            scores.append(score)
        elif state == "scrollable":
            scores.append(1.0 if index.has_scrollable else 0.0)
        elif state == "enabled":
            if not index.has_enabled_evidence:
                return None
            score = _state_text_score(selector, index.enabled_text, index)
            if score is None:
                return None
            scores.append(score)

    if not scores:
        return None
    return min(scores)


def _selector_value_score(selector: dict[str, Any], index: "_UiIndex") -> float | None:
    fields = _selector_fields(selector)
    if not fields:
        return 1.0

    node_score = _selector_node_score(fields, index)
    if node_score is not None:
        return node_score

    scores: list[float] = []
    for key, value in fields:
        score = _selector_field_score(key, value, index)
        if score is None:
            return None
        scores.append(score)
    return min(scores) if scores else 1.0


def _state_text_score(
    selector: dict[str, Any],
    state_haystack: list[str],
    index: "_UiIndex",
) -> float | None:
    if not selector:
        return 1.0 if state_haystack or index.has_scrollable else 0.0
    best = 0.0
    for key in ("text", "content_desc", "resource_id", "class", "xpath"):
        needle = _clean_string(selector.get(key))
        if not needle:
            continue
        best = max(best, _best_text_score(needle, state_haystack))
    return best


def _selector_fields(selector: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for key in ("resource_id", "content_desc", "text", "class", "xpath"):
        value = _clean_string(selector.get(key))
        if value:
            fields.append((key, value))
    return fields


def _selector_node_score(fields: list[tuple[str, str]], index: "_UiIndex") -> float | None:
    if not index.ui_nodes:
        return None
    best = 0.0
    for node in index.ui_nodes:
        scores: list[float] = []
        for key, value in fields:
            if key in {"resource_id", "class", "xpath"}:
                score = _exact_selector_score(value, [_clean_string(node.get(key))])
            else:
                score = _best_text_score(value, [_clean_string(node.get(key))])
            if score <= 0:
                scores = []
                break
            scores.append(score)
        if scores:
            best = max(best, min(scores))
    return best


def _selector_field_score(key: str, value: str, index: "_UiIndex") -> float | None:
    if key == "text":
        return _best_text_score(value, index.visible_text + index.all_text)
    if key == "content_desc":
        return _best_text_score(value, index.content_desc + index.all_text)
    if key == "resource_id":
        return _exact_selector_score(value, index.resource_ids)
    if key == "class":
        return _exact_selector_score(value, index.class_names)
    if key == "xpath":
        return _exact_selector_score(value, index.xpath_values)
    return None


def _exact_selector_score(needle: str, haystack: list[str]) -> float:
    needle_norm = _normalize_text(needle)
    if not needle_norm:
        return 0.0
    for item in haystack:
        if _normalize_text(item) == needle_norm:
            return 1.0
    return 0.0


def _best_text_score(needle: str, haystack: list[str]) -> float:
    needle_norm = _normalize_text(needle)
    if not needle_norm:
        return 0.0
    best = 0.0
    needle_tokens = set(re.findall(r"\w+", needle_norm))
    for item in haystack:
        item_norm = _normalize_text(item)
        if not item_norm:
            continue
        if needle_norm == item_norm:
            return 1.0
        if needle_norm in item_norm or item_norm in needle_norm:
            if min(len(needle_norm), len(item_norm)) >= 2:
                best = max(best, 0.92)
            continue
        item_tokens = set(re.findall(r"\w+", item_norm))
        if needle_tokens and item_tokens:
            overlap = len(needle_tokens & item_tokens) / len(needle_tokens | item_tokens)
            if overlap:
                best = max(best, 0.55 + 0.35 * overlap)
    return best


def _find_selector_for_step(
    step_payload: dict[str, Any],
    *,
    trajectory: dict[str, Any],
    action_type: str,
) -> dict[str, Any] | None:
    target_norm = _normalize_text(step_payload.get("target"))
    if len(target_norm) < 2:
        return None

    selector = _vote_for_selectors(
        _candidate_selectors(target_norm, extra, action_type)
        for extra in _iter_observation_extras(trajectory)
    )
    if selector:
        return selector

    selector = _vote_for_selectors(
        _context_grounded_selectors(step_payload, extra, action_type)
        for extra in _iter_observation_extras(trajectory)
    )
    if selector:
        return selector

    return _vote_for_selectors(
        _coordinate_grounded_selectors(step_payload, extra, action_type)
        for extra in _iter_observation_extras(trajectory)
    )


def _find_selector_for_target(
    target: str,
    *,
    trajectory: dict[str, Any],
    action_type: str,
) -> dict[str, Any] | None:
    target_norm = _normalize_text(target)
    if len(target_norm) < 2:
        return None
    return _vote_for_selectors(
        _candidate_selectors(target_norm, extra, action_type)
        for extra in _iter_observation_extras(trajectory)
    )


def _vote_for_selectors(selector_groups: Any) -> dict[str, Any] | None:
    votes: dict[tuple[tuple[str, Any], ...], tuple[int, dict[str, Any]]] = {}
    for selectors in selector_groups:
        selectors = [selector for selector in selectors if selector_is_static(selector)]
        group_keys = {_selector_identity_key(selector) for selector in selectors}
        if len(group_keys) > 1:
            continue
        for selector in selectors:
            marker = _selector_identity_key(selector)
            count, _ = votes.get(marker, (0, selector))
            votes[marker] = (count + 1, selector)

    if not votes:
        return None
    best_count = max(count for count, _ in votes.values())
    winners = [selector for count, selector in votes.values() if count == best_count]
    if len({_selector_identity_key(selector) for selector in winners}) != 1:
        return None
    return winners[0]


def _candidate_selectors(
    target_norm: str,
    extra: dict[str, Any],
    action_type: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    node_candidates = _node_selectors_for_target(target_norm, extra)
    if node_candidates:
        return node_candidates
    clickable_text = filter_static_texts(extra.get("clickable_text"), limit=80)
    visible_text = filter_static_texts(extra.get("visible_text"), limit=80)
    content_desc = filter_static_texts(extra.get("content_desc"), limit=80)
    resource_ids = filter_static_resource_ids(extra.get("resource_ids"), limit=80)

    resource_match = _exact_target_match(target_norm, resource_ids)
    if resource_match:
        selector: dict[str, Any] = {"resource_id": resource_match}
        if len(content_desc) == 1:
            selector["content_desc"] = content_desc[0]
        return [selector]

    content_match = _exact_target_match(target_norm, content_desc)
    if content_match:
        selector = {"content_desc": content_match}
        if len(resource_ids) == 1:
            selector["resource_id"] = resource_ids[0]
        if action_type in {"tap", "long_press", "double_tap"} and content_match in clickable_text:
            selector["clickable"] = True
        return [selector]

    match = _exact_target_match(target_norm, visible_text)
    if match:
        selector = {"text": match}
        if len(resource_ids) == 1:
            selector["resource_id"] = resource_ids[0]
        if action_type in {"tap", "long_press", "double_tap"} and match in clickable_text:
            selector["clickable"] = True
        return [selector]

    if action_type in {"tap", "long_press", "double_tap"}:
        clickable_match = _exact_target_match(target_norm, clickable_text)
        if clickable_match:
            candidates.append({"text": clickable_match, "clickable": True})
    return candidates


def _context_grounded_selectors(
    step_payload: dict[str, Any],
    extra: dict[str, Any],
    action_type: str,
) -> list[dict[str, Any]]:
    context = _step_context_text(step_payload)
    if not context:
        return []
    selectors: list[dict[str, Any]] = []
    for selector, labels in _structured_selector_labels(extra, action_type):
        if any(_context_mentions_label(context, label) for label in labels):
            selectors.append(selector)
    return selectors


def _coordinate_grounded_selectors(
    step_payload: dict[str, Any],
    extra: dict[str, Any],
    action_type: str,
) -> list[dict[str, Any]]:
    if action_type not in {"tap", "long_press", "double_tap"}:
        return []
    point = _step_point(step_payload, extra)
    if point is None:
        return []

    matches: list[tuple[float, dict[str, Any]]] = []
    for node in extra.get("ui_tree") or []:
        if not isinstance(node, dict):
            continue
        bounds = _parse_bounds(node.get("bounds"))
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        x, y = point
        if not (left <= x <= right and top <= y <= bottom):
            continue
        selector = _selector_from_node(node)
        if not selector:
            continue
        area = max(1.0, (right - left) * (bottom - top))
        matches.append((area, selector))

    if not matches:
        return []
    matches.sort(key=lambda item: item[0])
    smallest_area = matches[0][0]
    smallest = [selector for area, selector in matches if area == smallest_area]
    if len({_selector_key(selector) for selector in smallest}) != 1:
        return []
    return smallest


def _structured_selector_labels(
    extra: dict[str, Any],
    action_type: str,
) -> list[tuple[dict[str, Any], list[str]]]:
    selectors: list[tuple[dict[str, Any], list[str]]] = []
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if not isinstance(node, dict):
                continue
            selector = _selector_from_node(node)
            labels = _node_labels(node)
            if selector and labels:
                selectors.append((selector, labels))
        if selectors:
            return selectors

    clickable = action_type in {"tap", "long_press", "double_tap"}
    clickable_text = filter_static_texts(extra.get("clickable_text"), limit=80)
    for value in filter_static_resource_ids(extra.get("resource_ids"), limit=80):
        selectors.append(({"resource_id": value}, [value]))
    for value in filter_static_texts(extra.get("content_desc"), limit=80):
        selector = {"content_desc": value}
        if clickable and value in clickable_text:
            selector["clickable"] = True
        selectors.append((selector, [value]))
    if clickable:
        for value in clickable_text:
            selectors.append(({"text": value, "clickable": True}, [value]))
    for value in filter_static_texts(extra.get("visible_text"), limit=80):
        selectors.append(({"text": value}, [value]))
    return selectors


def _selector_from_node(node: dict[str, Any]) -> dict[str, Any]:
    return static_selector_from_node(node) or {}


def _node_labels(node: dict[str, Any]) -> list[str]:
    return _dedupe(
        value
        for value in (
            node.get("resource_id"),
            node.get("content_desc"),
            node.get("text"),
            node.get("xpath"),
        )
        if value
    )


def _step_context_text(step_payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "valid_state",
        "expected_state",
        "description",
        "action_summary",
        "summary",
        "intent",
    ):
        value = step_payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    params = step_payload.get("parameters")
    if isinstance(params, dict):
        for key in ("text", "label", "content_desc", "resource_id"):
            value = params.get(key)
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts).casefold()


def _context_mentions_label(context: str, label: str) -> bool:
    text = _clean_string(label).casefold()
    return bool(text) and text in context


def _step_point(step_payload: dict[str, Any], extra: dict[str, Any]) -> tuple[float, float] | None:
    params = step_payload.get("parameters")
    if not isinstance(params, dict):
        params = step_payload
    x = _float_value(params.get("x"))
    y = _float_value(params.get("y"))
    if x is None or y is None:
        return None
    if params.get("relative"):
        width = _float_value(extra.get("screen_width"))
        height = _float_value(extra.get("screen_height"))
        if width is None or height is None:
            return None
        x = x / 1000.0 * width
        y = y / 1000.0 * height
    return x, y


def _parse_bounds(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        coords = [_float_value(item) for item in value]
        if all(coord is not None for coord in coords):
            left = float(coords[0])
            top = float(coords[1])
            right = float(coords[2])
            bottom = float(coords[3])
            return left, top, right, bottom
        return None
    text = _clean_string(value)
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", text)
    if not match:
        return None
    left, top, right, bottom = (float(item) for item in match.groups())
    return left, top, right, bottom


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _node_selectors_for_target(target_norm: str, extra: dict[str, Any]) -> list[dict[str, Any]]:
    selectors: list[dict[str, Any]] = []
    ui_tree = extra.get("ui_tree")
    if not isinstance(ui_tree, list):
        return selectors
    for node in ui_tree:
        if not isinstance(node, dict):
            continue
        text = _clean_string(node.get("text"))
        content_desc = _clean_string(node.get("content_desc"))
        resource_id = _clean_string(node.get("resource_id"))
        xpath = _clean_string(node.get("xpath"))
        if not any(_normalize_text(value) == target_norm for value in (text, content_desc, resource_id, xpath)):
            continue
        selector = static_selector_from_node(node)
        if selector:
            selectors.append(selector)
    return selectors


def _iter_observation_extras(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []

    def add_mapping(value: Any) -> None:
        extra = _extra_from_mapping(value)
        if extra:
            extras.append(extra)

    def add_from_observation(obs: Any) -> None:
        add_mapping(obs)

    add_mapping(trajectory)

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


def _extra_from_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    nested_extra = value.get("extra")
    if isinstance(nested_extra, dict):
        out.update(nested_extra)
    for key in _EXTRA_HINT_KEYS:
        if key in value and key != "extra":
            out[key] = value[key]
    tree_extra = out.get("ui_tree")
    if isinstance(tree_extra, dict):
        out.pop("ui_tree", None)
        for key, item in tree_extra.items():
            if key in _EXTRA_HINT_KEYS:
                out.setdefault(key, item)
    return out or None


def _infer_mask_rules(trajectory: dict[str, Any]) -> list[str]:
    rules: set[str] = set()
    for extra in _iter_observation_extras(trajectory):
        values: list[str] = []
        for key in ("visible_text", "content_desc", "clickable_text", "focused_text"):
            values.extend(_string_list(extra.get(key)))
        for value in values:
            lower = value.lower()
            if re.search(r"\b\d{1,2}:\d{2}\b", value):
                rules.add("timestamp")
            if re.search(r"\d+", value):
                rules.add("counter")
            if any(word in lower for word in ("recommend", "for you", "猜你喜欢", "推荐")):
                rules.add("temporary_recommendation")
            if any(word in lower for word in ("personal", "个性化", "为你")):
                rules.add("personalized_text")
    return sorted(rules)


@dataclass
class _UiIndex:
    visible_text: list[str] = field(default_factory=list)
    content_desc: list[str] = field(default_factory=list)
    resource_ids: list[str] = field(default_factory=list)
    clickable_text: list[str] = field(default_factory=list)
    focused_text: list[str] = field(default_factory=list)
    enabled_text: list[str] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)
    xpath_values: list[str] = field(default_factory=list)
    ui_nodes: list[dict[str, str]] = field(default_factory=list)
    all_text: list[str] = field(default_factory=list)
    has_scrollable: bool = False
    has_enabled_evidence: bool = False
    has_evidence: bool = False

    @classmethod
    def from_extra(cls, extra: dict[str, Any]) -> "_UiIndex":
        index = cls(
            visible_text=_string_list(extra.get("visible_text")),
            content_desc=_string_list(extra.get("content_desc")),
            resource_ids=_string_list(extra.get("resource_ids")),
            clickable_text=_string_list(extra.get("clickable_text")),
            focused_text=_string_list(extra.get("focused_text")),
            enabled_text=_string_list(extra.get("enabled_text")),
            class_names=_string_list(extra.get("class_names")),
            xpath_values=_string_list(extra.get("xpaths")),
            has_scrollable=_truthy(extra.get("scrollable_present")),
            has_enabled_evidence=(
                "enabled_text" in extra
                or "enabled_present" in extra
            ),
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
            xpath = _clean_string(node.get("xpath"))
            label = text or content_desc or resource_id
            node_labels = _dedupe(
                value
                for value in (text, content_desc, resource_id, class_name, xpath)
                if value
            )
            ui_node = {
                key: value
                for key, value in (
                    ("text", text),
                    ("content_desc", content_desc),
                    ("resource_id", resource_id),
                    ("class", class_name),
                    ("xpath", xpath),
                )
                if value
            }
            if ui_node:
                index.ui_nodes.append(ui_node)
            if text:
                index.visible_text.append(text)
            if content_desc:
                index.content_desc.append(content_desc)
            if resource_id:
                index.resource_ids.append(resource_id)
            if class_name:
                index.class_names.append(class_name)
            if xpath:
                index.xpath_values.append(xpath)
            if node.get("clickable"):
                index.clickable_text.extend(node_labels or ([label] if label else []))
            if node.get("focused"):
                index.focused_text.extend(node_labels or ([label] if label else []))
            if "enabled" in node:
                index.has_enabled_evidence = True
                if node.get("enabled"):
                    index.enabled_text.extend(node_labels or ([label] if label else []))
            if node.get("scrollable"):
                index.has_scrollable = True

        index.visible_text = _dedupe(index.visible_text)
        index.content_desc = _dedupe(index.content_desc)
        index.resource_ids = _dedupe(index.resource_ids)
        index.clickable_text = _dedupe(index.clickable_text)
        index.focused_text = _dedupe(index.focused_text)
        index.enabled_text = _dedupe(index.enabled_text)
        index.class_names = _dedupe(index.class_names)
        index.xpath_values = _dedupe(index.xpath_values)
        index.ui_nodes = _dedupe_dicts(index.ui_nodes)
        index.all_text = _dedupe(
            index.all_text
            + index.visible_text
            + index.content_desc
            + index.resource_ids
            + index.clickable_text
            + index.focused_text
            + index.enabled_text
            + index.class_names
            + index.xpath_values
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
    best: tuple[float, str] | None = None
    for candidate in candidates:
        score = _best_text_score(target_norm, [candidate])
        if score <= 0:
            continue
        marker = (score, candidate)
        if best is None or marker > best:
            best = marker
    return best[1] if best else None


def _exact_target_match(target_norm: str, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if _normalize_text(candidate) == target_norm:
            return candidate
    return None


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


def _dedupe_dicts(values: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        item = {
            str(key): text
            for key, raw in value.items()
            if (text := _clean_string(raw))
        }
        marker = tuple(sorted((key, value.casefold()) for key, value in item.items()))
        if not item or marker in seen:
            continue
        out.append(item)
        seen.add(marker)
    return out


def _selector_key(selector: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted(selector.items()))


def _selector_identity_key(selector: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((key, value) for key, value in selector.items() if key in _SELECTOR_KEYS))


def _dict_get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _should_skip_valid_state(valid_state: Any) -> bool:
    text = _normalize_text(valid_state)
    if not text:
        return True
    return any(hint in text for hint in ("no need to verify", "return true", "skip", "none", "n/a"))
