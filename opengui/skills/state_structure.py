"""
opengui.skills.state_structure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Stable UI-tree structure profiles for graph state reuse.

These helpers intentionally ignore dynamic visible text and coordinates.  The
profile is a compact identity supplement for graph nodes, not a replacement for
machine-checkable state contracts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from opengui.skills.static_selector_filter import (
    filter_static_resource_ids,
    filter_static_texts,
)

_STRUCTURE_PROFILE_VERSION = 1


def build_structure_profile(observation_extra: Any) -> dict[str, Any] | None:
    """Return a stable UI structure profile from ``Observation.extra``."""
    if not isinstance(observation_extra, dict):
        return None

    ui_tree = observation_extra.get("ui_tree")
    nodes = [node for node in ui_tree if isinstance(node, dict)] if isinstance(ui_tree, list) else []

    class_paths: list[str] = []
    resource_id_paths: list[str] = []
    resource_ids: list[str] = []
    content_descs: list[str] = []
    clickable_class_counts: dict[str, int] = {}

    for index, node in enumerate(nodes):
        class_name = _clean(node.get("class"))
        resource_id = _clean(node.get("resource_id"))
        content_desc = _clean(node.get("content_desc"))
        path = _shape_path(node.get("xpath")) or str(index)

        if class_name:
            class_paths.append(f"{path}:{class_name}")
            if node.get("clickable"):
                clickable_class_counts[class_name] = clickable_class_counts.get(class_name, 0) + 1

        if resource_id:
            filtered = filter_static_resource_ids([resource_id], limit=1)
            if filtered:
                stable_resource = filtered[0]
                resource_ids.append(stable_resource)
                resource_id_paths.append(f"{path}:{stable_resource}")

        if content_desc:
            filtered_text = filter_static_texts([content_desc], limit=1)
            if filtered_text:
                content_descs.append(filtered_text[0])

    if not nodes:
        resource_ids.extend(filter_static_resource_ids(observation_extra.get("resource_ids"), limit=80))
        content_descs.extend(filter_static_texts(observation_extra.get("content_desc"), limit=80))
        for class_name in _string_list(observation_extra.get("class_names")):
            class_paths.append(class_name)

    profile = {
        "version": _STRUCTURE_PROFILE_VERSION,
        "class_paths": _dedupe_sorted(class_paths),
        "resource_id_paths": _dedupe_sorted(resource_id_paths),
        "resource_id_set": _dedupe_sorted(resource_ids),
        "content_desc_set": _dedupe_sorted(content_descs),
        "clickable_class_counts": dict(sorted(clickable_class_counts.items())),
        "node_count_bucket": _node_count_bucket(len(nodes) or int(observation_extra.get("ui_tree_node_count") or 0)),
    }
    if not any(
        profile.get(key)
        for key in ("class_paths", "resource_id_paths", "resource_id_set", "content_desc_set", "clickable_class_counts")
    ):
        return None
    return profile


def normalize_structure_profile(profile: Any) -> dict[str, Any] | None:
    """Canonicalize a stored structure profile."""
    if not isinstance(profile, dict):
        return None
    normalized = {
        "version": int(profile.get("version") or _STRUCTURE_PROFILE_VERSION),
        "class_paths": _dedupe_sorted(_string_list(profile.get("class_paths"))),
        "resource_id_paths": _dedupe_sorted(_string_list(profile.get("resource_id_paths"))),
        "resource_id_set": _dedupe_sorted(_string_list(profile.get("resource_id_set"))),
        "content_desc_set": _dedupe_sorted(_string_list(profile.get("content_desc_set"))),
        "clickable_class_counts": _int_count_map(profile.get("clickable_class_counts")),
        "node_count_bucket": _clean(profile.get("node_count_bucket")) or "0",
    }
    if not any(
        normalized.get(key)
        for key in ("class_paths", "resource_id_paths", "resource_id_set", "content_desc_set", "clickable_class_counts")
    ):
        return None
    return normalized


def structure_fingerprint(profile: Any) -> str:
    normalized = normalize_structure_profile(profile)
    if not normalized:
        return ""
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def structure_similarity(left: Any, right: Any) -> float:
    """Return structural similarity in ``[0, 1]``."""
    lnorm = normalize_structure_profile(left)
    rnorm = normalize_structure_profile(right)
    if not lnorm or not rnorm:
        return 0.0
    scores = [
        0.35 * _jaccard(lnorm["resource_id_set"], rnorm["resource_id_set"]),
        0.25 * _jaccard(lnorm["resource_id_paths"], rnorm["resource_id_paths"]),
        0.25 * _jaccard(lnorm["class_paths"], rnorm["class_paths"]),
        0.10 * _count_cosine(lnorm["clickable_class_counts"], rnorm["clickable_class_counts"]),
        0.05 * _jaccard(lnorm["content_desc_set"], rnorm["content_desc_set"]),
    ]
    return max(0.0, min(1.0, sum(scores)))


def _shape_path(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    text = re.sub(r"\[\d+\]", "[]", text)
    return text


def _node_count_bucket(count: int) -> str:
    count = max(0, int(count or 0))
    if count <= 1:
        return str(count)
    if count <= 5:
        return "2-5"
    if count <= 10:
        return "6-10"
    if count <= 20:
        return "11-20"
    if count <= 50:
        return "21-50"
    if count <= 100:
        return "51-100"
    return "100+"


def _jaccard(left: list[str], right: list[str]) -> float:
    lset = set(left)
    rset = set(right)
    if not lset and not rset:
        return 1.0
    if not lset or not rset:
        return 0.0
    return len(lset & rset) / len(lset | rset)


def _count_cosine(left: dict[str, int], right: dict[str, int]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 1.0
    dot = sum(left.get(key, 0) * right.get(key, 0) for key in keys)
    lnorm = math.sqrt(sum(value * value for value in left.values()))
    rnorm = math.sqrt(sum(value * value for value in right.values()))
    if lnorm <= 0 or rnorm <= 0:
        return 0.0
    return dot / (lnorm * rnorm)


def _int_count_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for key, item in value.items():
        text = _clean(key)
        if not text:
            continue
        try:
            count = int(item)
        except (TypeError, ValueError):
            continue
        if count > 0:
            out[text] = count
    return dict(sorted(out.items()))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _clean(item)
        if text:
            out.append(text)
    return out


def _dedupe_sorted(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

