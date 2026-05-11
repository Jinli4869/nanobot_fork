"""Structured UI-tree grounding helpers for reusable GUI skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from opengui.observation import Observation

_POINT_ACTIONS = frozenset({"tap", "long_press", "double_tap"})
_BOUNDS_RE = re.compile(r"\[(?P<left>-?\d+(?:\.\d+)?),(?P<top>-?\d+(?:\.\d+)?)\]"
                        r"\[(?P<right>-?\d+(?:\.\d+)?),(?P<bottom>-?\d+(?:\.\d+)?)\]")


@dataclass(frozen=True)
class UiGrounding:
    x: float
    y: float
    relative: bool = False
    selector: dict[str, Any] | None = None


def ground_target_from_observation(
    *,
    action_type: str,
    target: str | None,
    observation: Observation | None,
) -> UiGrounding | None:
    """Return a point action target from structured observation metadata.

    Android UIAutomator bounds are often reported in input-display pixels while
    screenshots can be downscaled.  When bounds exceed the observation
    screenshot size, scale them into the screenshot coordinate space so the
    backend's normal coordinate mapper can tap the intended element.
    """
    if action_type not in _POINT_ACTIONS:
        return None
    target_norm = _normalize(target)
    if not target_norm or observation is None:
        return None
    ui_tree = observation.extra.get("ui_tree") if isinstance(observation.extra, dict) else None
    if not isinstance(ui_tree, list):
        return None

    bounds_by_node: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
    for node in ui_tree:
        if not isinstance(node, dict):
            continue
        bounds = _parse_bounds(node.get("bounds"))
        if bounds is None:
            continue
        bounds_by_node.append((node, bounds))
    if not bounds_by_node:
        return None

    matches = [
        (node, bounds)
        for node, bounds in bounds_by_node
        if _node_matches_target(node, target_norm)
    ]
    if not matches:
        return None

    node, bounds = sorted(matches, key=_grounding_rank)[0]
    left, top, right, bottom = bounds
    x = (left + right) / 2.0
    y = (top + bottom) / 2.0

    max_right = max(item_bounds[2] for _, item_bounds in bounds_by_node)
    max_bottom = max(item_bounds[3] for _, item_bounds in bounds_by_node)
    if observation.screen_width > 0 and max_right > observation.screen_width:
        x *= observation.screen_width / max_right
    if observation.screen_height > 0 and max_bottom > observation.screen_height:
        y *= observation.screen_height / max_bottom

    return UiGrounding(
        x=x,
        y=y,
        selector=_selector_for_node(node),
    )


def _node_matches_target(node: dict[str, Any], target_norm: str) -> bool:
    for key in ("resource_id", "content_desc", "text"):
        if _normalize(node.get(key)) == target_norm:
            return True
    return False


def _grounding_rank(item: tuple[dict[str, Any], tuple[float, float, float, float]]) -> tuple[int, int, float]:
    node, bounds = item
    left, top, right, bottom = bounds
    area = max(0.0, right - left) * max(0.0, bottom - top)
    clickable_rank = 0 if bool(node.get("clickable")) else 1
    stable_rank = 0 if node.get("resource_id") or node.get("content_desc") else 1
    return (clickable_rank, stable_rank, area)


def _selector_for_node(node: dict[str, Any]) -> dict[str, Any]:
    selector: dict[str, Any] = {}
    for key in ("resource_id", "content_desc", "text"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            selector[key] = value.strip()
    if node.get("clickable"):
        selector["clickable"] = True
    return selector


def _parse_bounds(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            left, top, right, bottom = (float(item) for item in value)
        except (TypeError, ValueError):
            return None
        if right > left and bottom > top:
            return (left, top, right, bottom)
        return None
    if not isinstance(value, str):
        return None
    match = _BOUNDS_RE.fullmatch(value.strip())
    if match is None:
        return None
    left = float(match.group("left"))
    top = float(match.group("top"))
    right = float(match.group("right"))
    bottom = float(match.group("bottom"))
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())
