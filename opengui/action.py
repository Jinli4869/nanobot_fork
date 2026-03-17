"""
opengui.action
==============
Action dataclass, parsing, validation, and coordinate resolution.

* ``Action`` is frozen/immutable — safe to share across threads.
* ``parse_action`` is the sole normalisation boundary between LLM JSON and
  the rest of the framework.
* For ``scroll`` actions, direction is stored in ``Action.text``.
* ``resolve_coordinate`` maps [0,999] relative or absolute pixels to device px.
"""

from __future__ import annotations

import dataclasses
import typing

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ACTION_TYPES: frozenset[str] = frozenset({
    "tap", "long_press", "double_tap", "drag", "swipe", "scroll",
    "input_text", "hotkey", "screenshot", "wait",
    "open_app", "close_app", "back", "home", "done",
})

_ACTION_ALIASES: dict[str, str] = {
    "click": "tap",
    "type": "input_text",
    "key": "hotkey",
    "press": "hotkey",
    "long_click": "long_press",
    "double_click": "double_tap",
}

_RELATIVE_GRID_MAX: int = 999

_XY_REQUIRED: frozenset[str] = frozenset(
    {"tap", "long_press", "double_tap", "drag", "swipe"},
)
_XY2_REQUIRED: frozenset[str] = frozenset({"drag", "swipe"})
_VALID_SCROLL_DIRECTIONS: frozenset[str] = frozenset(
    {"up", "down", "left", "right"},
)


class ActionError(Exception):
    """Raised when an LLM payload cannot be converted into a valid Action."""


@dataclasses.dataclass(frozen=True)
class Action:
    """An immutable, validated representation of a single GUI automation step.

    Coordinates are stored in their original unit (relative or absolute).
    Call :func:`resolve_coordinate` at execution time to convert to device px.
    """

    action_type: str
    x: float | None = None
    y: float | None = None
    x2: float | None = None
    y2: float | None = None
    text: str | None = None
    key: list[str] | None = None
    pixels: int | None = None
    duration_ms: int | None = None
    relative: bool = False
    status: str | None = None


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def resolve_coordinate(value: float, extent: int, *, relative: bool) -> int:
    """Convert a coordinate value to an absolute device pixel.

    Returns a clamped int in ``[0, extent - 1]``.
    """
    if relative:
        pixel = round(value / _RELATIVE_GRID_MAX * (extent - 1))
    else:
        pixel = round(value)
    return max(0, min(pixel, extent - 1))


def parse_action(payload: dict[str, typing.Any]) -> Action:
    """Convert a raw LLM JSON payload into a validated :class:`Action`.

    Handles type aliases, field coercion, direction storage, and validation.
    """
    if not isinstance(payload, dict):
        raise ActionError(f"Expected dict payload, got {type(payload).__name__!r}.")

    # 1. Normalise action_type
    raw_type = payload.get("action_type") or payload.get("action") or ""
    if not raw_type:
        raise ActionError("Payload is missing the required 'action_type' field.")
    action_type = _ACTION_ALIASES.get(str(raw_type).strip().lower(), str(raw_type).strip().lower())
    if action_type not in VALID_ACTION_TYPES:
        raise ActionError(
            f"Unknown action type {raw_type!r}. "
            f"Valid: {', '.join(sorted(VALID_ACTION_TYPES))}."
        )

    # 2. Coordinates
    x = _optional_float(payload, "x", action_type)
    y = _optional_float(payload, "y", action_type)
    x2 = _optional_float(payload, "x2", action_type)
    y2 = _optional_float(payload, "y2", action_type)

    # 3. Text — for scroll, direction takes priority
    if action_type == "scroll":
        raw_dir = payload.get("direction") or payload.get("text")
        text: str | None = str(raw_dir).strip().lower() if raw_dir is not None else None
    else:
        text = _optional_str(payload, "text")

    # 4. Other fields
    key = _parse_key(payload.get("key"), action_type)
    pixels = _optional_int(payload, "pixels", action_type)
    duration_ms = _optional_int(payload, "duration_ms", action_type)
    relative = bool(payload.get("relative", False))
    status = _optional_str(payload, "status")

    # 5. Validate
    _validate(action_type=action_type, x=x, y=y, x2=x2, y2=y2,
              text=text, key=key, pixels=pixels)

    return Action(
        action_type=action_type, x=x, y=y, x2=x2, y2=y2,
        text=text, key=key, pixels=pixels, duration_ms=duration_ms,
        relative=relative, status=status,
    )


def describe_action(action: Action) -> str:
    """Return a concise, human-readable summary of *action*."""
    t = action.action_type

    if t in ("tap", "long_press", "double_tap"):
        coord = _fmt_coord(action)
        suffix = f" for {action.duration_ms} ms" if t == "long_press" and action.duration_ms else ""
        return f"{t.replace('_', ' ')} at {coord}{suffix}"
    if t in ("drag", "swipe"):
        return f"{t} from {_fmt_coord(action)} to ({action.x2}, {action.y2})"
    if t == "scroll":
        direction = action.text or "?"
        px = f" by {action.pixels} px" if action.pixels is not None else ""
        return f"scroll {direction}{px} at {_fmt_coord(action)}"
    if t == "input_text":
        preview = (action.text or "")[:40]
        if len(action.text or "") > 40:
            preview += "..."
        return f'type "{preview}"'
    if t == "hotkey":
        return f"hotkey {'+'.join(action.key or [])}"
    if t == "open_app":
        return f"open app {action.text!r}"
    if t == "close_app":
        return f"close app {action.text!r}"
    if t == "screenshot":
        return "take screenshot"
    if t == "wait":
        return f"wait {action.duration_ms} ms" if action.duration_ms else "wait"
    if t == "back":
        return "press back"
    if t == "home":
        return "press home"
    if t == "done":
        return f"task done – {action.status}" if action.status else "task done"
    return t


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fmt_coord(action: Action) -> str:
    if action.x is None or action.y is None:
        return "center"
    if action.relative:
        return f"({action.x}/{_RELATIVE_GRID_MAX}, {action.y}/{_RELATIVE_GRID_MAX})"
    return f"({action.x}, {action.y})"


def _optional_float(payload: dict, key: str, action_type: str) -> float | None:
    v = payload.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError) as exc:
        raise ActionError(f"Action {action_type!r}: {key!r} must be numeric, got {v!r}.") from exc


def _optional_int(payload: dict, key: str, action_type: str) -> int | None:
    v = payload.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError) as exc:
        raise ActionError(f"Action {action_type!r}: {key!r} must be int, got {v!r}.") from exc


def _optional_str(payload: dict, key: str) -> str | None:
    v = payload.get(key)
    return str(v) if v is not None else None


def _parse_key(raw: typing.Any, action_type: str) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        if not all(isinstance(k, str) for k in raw):
            raise ActionError(f"Action {action_type!r}: 'key' list must contain only strings.")
        return [k.strip() for k in raw if k]
    if isinstance(raw, str):
        for sep in ("+", " ", ","):
            if sep in raw:
                return [k.strip() for k in raw.split(sep) if k.strip()]
        return [raw.strip()]
    raise ActionError(f"Action {action_type!r}: 'key' must be str or list, got {type(raw).__name__!r}.")


def _validate(
    *, action_type: str, x: float | None, y: float | None,
    x2: float | None, y2: float | None, text: str | None,
    key: list[str] | None, pixels: int | None,
) -> None:
    if action_type in _XY_REQUIRED and (x is None or y is None):
        raise ActionError(f"Action {action_type!r} requires both 'x' and 'y' coordinates.")
    if action_type in _XY2_REQUIRED and (x2 is None or y2 is None):
        raise ActionError(f"Action {action_type!r} requires 'x2' and 'y2' end-point coordinates.")
    if action_type == "hotkey" and not key:
        raise ActionError("Action 'hotkey' requires the 'key' field.")
    if action_type == "input_text" and text is None:
        raise ActionError("Action 'input_text' requires the 'text' field.")
    if action_type == "scroll":
        if pixels is None:
            raise ActionError("Action 'scroll' requires the 'pixels' field.")
        if (x is None) != (y is None):
            raise ActionError("Action 'scroll' requires both 'x' and 'y' when either is set.")
        if text is not None and text not in _VALID_SCROLL_DIRECTIONS:
            raise ActionError(
                f"Action 'scroll' direction {text!r} invalid. "
                f"Use: {', '.join(sorted(_VALID_SCROLL_DIRECTIONS))}."
            )
    if action_type in ("open_app", "close_app") and not text:
        raise ActionError(f"Action {action_type!r} requires the 'text' field (app name).")
