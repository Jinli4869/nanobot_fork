"""Rule-based trajectory preprocessing for flat skill code extraction."""

from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image

from opengui.skills.data import Skill, SkillStep
from opengui.skills.static_selector_filter import static_selector_from_node
from opengui.skills.state_contract import infer_focused_input_contract

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_ACTION_PARAM_KEYS = ("x", "y", "x2", "y2", "text", "key", "pixels", "direction")
_COORDLESS_ACTIONS = frozenset({
    "wait", "back", "home", "enter", "app_switch", "done",
    "request_intervention", "hotkey", "screenshot",
})
_STATE_FLAGS = ("visible", "clickable", "enabled", "focused", "scrollable")


@dataclass
class CodeStep:
    step_index: int
    intent: str
    action_type: str
    action_params: dict
    control_info: str
    contract_json: str
    screenshot_b64: str
    succeeded: bool | None = None  # None=unknown, True=succeeded, False=failed
    suppress_extracted_contract: bool = False


@dataclass
class CodegenResult:
    task: str
    platform: str
    app: str
    steps: list[CodeStep]
    screenshots_b64: list[str]


def codegen_trajectory(trace_path: Path) -> CodegenResult | None:
    events = _load_jsonl(trace_path)
    if not events:
        return None

    meta = _find_metadata(events)
    task = str(meta.get("task") or trace_path.stem)
    platform = str(meta.get("platform") or _first_platform(events) or "unknown")
    app = str(meta.get("foreground_app") or meta.get("app") or _first_foreground_app(events) or "")

    steps: list[CodeStep] = []
    screenshots_b64: list[str] = []
    seen: set[str] = set()
    previous_observation: dict[str, Any] | None = None
    skill_failed = False  # boundary signal from skill_execution_result

    for event in events:
        event_type = event.get("type")
        if event_type == "skill_execution_result" and event.get("state") == "failed":
            skill_failed = True
            continue
        if event_type not in ("step", "skill_step"):
            continue

        # Normalize action extraction for both event types
        if event_type == "skill_step":
            action = _skill_step_action(event)
            error = event.get("error")
            succeeded = None if error is None else False
            if succeeded is False:
                skill_failed = True
        else:
            action = event.get("action") or {}
            succeeded = None  # agent steps don't encode success

        observation = event.get("observation") or {}
        action_type = str(action.get("action_type") or "")
        if not app:
            app = str(observation.get("foreground_app") or observation.get("app") or "")

        b64 = _screenshot_b64(event, trace_path)
        if b64 and b64 not in seen:
            seen.add(b64)
            screenshots_b64.append(b64)

        control_info = ""
        contract_json = ""
        # For skill_step, prefer serialized state_contract directly
        if event_type == "skill_step" and event.get("state_contract"):
            contract_json = json.dumps(
                event["state_contract"], ensure_ascii=False, separators=(",", ":")
            )
            control_info = _describe_contract_selector(event["state_contract"])
        elif action_type == "input_text" and previous_observation is not None:
            contract = infer_focused_input_contract(
                (previous_observation.get("extra") or {}),
                app=app,
            )
            if contract:
                contract_json = json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
                control_info = _describe_contract_selector(contract)
        if not contract_json and action_type not in _COORDLESS_ACTIONS:
            target_observation = _target_observation_for_action(
                action_type,
                observation,
                previous_observation,
            )
            pt = _action_point(action, target_observation)
            suppress_extracted_contract = False
            if pt is not None:
                target_nodes = _ui_tree(target_observation)
                suppress_extracted_contract = (
                    action_type == "tap"
                    and _point_hits_focused_text_input(target_nodes, *pt)
                )
                node = _target_node_at(target_nodes, *pt, action_type=action_type)
                if node is not None:
                    control_info = _describe_control(node)
                    contract_json = _build_contract_json(
                        node,
                        app,
                        allow_class_fallback=action_type != "tap",
                    )
                elif suppress_extracted_contract:
                    control_info = "post-action focused input; omit state_contract"
        else:
            suppress_extracted_contract = False

        steps.append(CodeStep(
            step_index=int(event.get("step_index", len(steps))),
            intent=_step_intent(event, action_type),
            action_type=action_type,
            action_params=_extract_params(action, action_type),
            control_info=control_info,
            contract_json=contract_json,
            screenshot_b64=b64,
            succeeded=succeeded if succeeded is False else (
                None if skill_failed else None
            ),
            suppress_extracted_contract=suppress_extracted_contract,
        ))
        previous_observation = observation if isinstance(observation, dict) else None

    return CodegenResult(
        task=task, platform=platform, app=app,
        steps=steps, screenshots_b64=screenshots_b64,
    )


def codegen_to_extraction_text(result: CodegenResult) -> str:
    lines = [
        f"Task: {result.task}",
        f"App: {result.app}",
        f"Platform: {result.platform}",
        "",
        "Action sequence:",
    ]
    for step in result.steps:
        status = ""
        if step.succeeded is False:
            status = "[FAILED] "
        elif step.succeeded is True:
            status = "[OK] "
        parts = [
            f"  [{step.step_index}] {status}{step.intent}",
            f"type={step.action_type}",
        ]
        params = _format_params(step.action_params)
        if params:
            parts.append(params)
        parts.append(f"control: {step.control_info}")
        parts.append(f"contract: {step.contract_json}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _skill_step_action(event: dict[str, Any]) -> dict[str, Any]:
    """Extract action-like dict from a skill_step event."""
    action = event.get("action") or {}
    if isinstance(action, dict):
        return action
    # Fallback: reconstruct from top-level event fields
    return {
        "action_type": event.get("action_type") or event.get("action_summary", ""),
    }


# ---- internal helpers ----

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _find_metadata(events: list[dict[str, Any]]) -> dict[str, Any]:
    for e in events:
        if e.get("type") == "metadata":
            return e
    return {}


def _first_platform(events: list[dict[str, Any]]) -> str:
    for e in events:
        obs = e.get("observation") or {}
        p = obs.get("platform")
        if p:
            return str(p)
    return ""


def _first_foreground_app(events: list[dict[str, Any]]) -> str:
    for e in events:
        obs = e.get("observation") or {}
        app = obs.get("foreground_app") or obs.get("app")
        if app:
            return str(app)
    return ""


def _step_intent(event: dict[str, Any], action_type: str) -> str:
    if event.get("action_intent"):
        return str(event["action_intent"])
    if event.get("model_output"):
        return str(event["model_output"])[:200]
    if event.get("action_summary"):
        return str(event["action_summary"])
    return action_type


def _extract_params(action: dict[str, Any], action_type: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key in _ACTION_PARAM_KEYS:
        if key == "direction":
            value = action.get("direction") or (action.get("text") if action_type == "scroll" else None)
        else:
            value = action.get(key)
        if value is not None:
            params[key] = value
    return params


def _format_params(params: dict[str, Any]) -> str:
    return ", ".join(f"{key}={_format_value(value)}" for key, value in params.items())


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _action_point(action: dict[str, Any], observation: dict[str, Any]) -> tuple[int, int] | None:
    if action.get("x") is None or action.get("y") is None:
        return None
    x = float(action["x"])
    y = float(action["y"])
    if action.get("relative"):
        w = int(observation.get("screen_width") or 0)
        h = int(observation.get("screen_height") or 0)
        if w and h:
            x = x / 999 * (w - 1)
            y = y / 999 * (h - 1)
    return _scale_point_to_ui_tree(round(x), round(y), observation)


def _target_observation_for_action(
    action_type: str,
    observation: dict[str, Any],
    previous_observation: dict[str, Any] | None,
) -> dict[str, Any]:
    if (
        action_type != "input_text"
        and previous_observation is not None
        and _ui_tree(previous_observation)
        and _same_foreground_app(previous_observation, observation)
    ):
        return previous_observation
    return observation


def _same_foreground_app(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_app = str(left.get("foreground_app") or left.get("app") or "")
    right_app = str(right.get("foreground_app") or right.get("app") or "")
    return bool(left_app and right_app and left_app == right_app)


def _scale_point_to_ui_tree(x: int, y: int, observation: dict[str, Any]) -> tuple[int, int]:
    screen_width = int(observation.get("screen_width") or 0)
    screen_height = int(observation.get("screen_height") or 0)
    bounds_width, bounds_height = _ui_tree_extent(_ui_tree(observation))
    if not screen_width or not screen_height or not bounds_width or not bounds_height:
        return x, y
    if x > screen_width or y > screen_height:
        return x, y
    if _similar_extent(screen_width, bounds_width) and _similar_extent(screen_height, bounds_height):
        return x, y
    return round(x * bounds_width / screen_width), round(y * bounds_height / screen_height)


def _similar_extent(left: int, right: int) -> bool:
    return abs(left - right) <= max(left, right) * 0.1


def _ui_tree_extent(nodes: list[dict[str, Any]]) -> tuple[int, int]:
    max_x = 0
    max_y = 0
    for node in nodes:
        bounds = _parse_bounds(node)
        if bounds is None:
            continue
        max_x = max(max_x, bounds[2])
        max_y = max(max_y, bounds[3])
    return max_x, max_y


def _ui_tree(observation: dict[str, Any]) -> list[dict[str, Any]]:
    extra = observation.get("extra") or {}
    return list(extra.get("ui_tree") or [])


def _target_node_at(
    nodes: list[dict[str, Any]],
    x: int,
    y: int,
    *,
    action_type: str,
) -> dict[str, Any] | None:
    matches = _nodes_at(nodes, x, y)
    if not matches:
        return None
    if action_type == "tap" and any(_is_focused_text_input(node) for _, node in matches):
        return None
    if action_type == "tap":
        for _, node in matches:
            if static_selector_from_node(node):
                return node
        return None
    return matches[0][1]


def _point_hits_focused_text_input(nodes: list[dict[str, Any]], x: int, y: int) -> bool:
    return any(_is_focused_text_input(node) for _, node in _nodes_at(nodes, x, y))


def _nodes_at(nodes: list[dict[str, Any]], x: int, y: int) -> list[tuple[int, dict[str, Any]]]:
    matches: list[tuple[int, dict[str, Any]]] = []
    for node in nodes:
        bounds = _parse_bounds(node)
        if bounds is None:
            continue
        x1, y1, x2, y2 = bounds
        if x1 <= x <= x2 and y1 <= y <= y2:
            matches.append(((x2 - x1) * (y2 - y1), node))
    return sorted(matches, key=lambda item: item[0])


def _is_focused_text_input(node: dict[str, Any]) -> bool:
    class_name = str(node.get("class") or "")
    focused = node.get("focused") is True or str(node.get("focused")).lower() == "true"
    return focused and class_name == "android.widget.EditText"


def _parse_bounds(node: dict[str, Any]) -> tuple[int, int, int, int] | None:
    m = _BOUNDS_RE.search(str(node.get("bounds") or ""))
    if not m:
        return None
    return tuple(int(v) for v in m.groups())


def _describe_control(node: dict[str, Any]) -> str:
    parts = []
    for key in ("resource_id", "content_desc", "class"):
        val = node.get(key)
        if val:
            parts.append(f"{key}={val}")
    return " ".join(parts)


def _describe_contract_selector(contract: dict[str, Any]) -> str:
    required = (contract.get("signature") or {}).get("required") or []
    if not required:
        return ""
    selector = required[0].get("selector") or {}
    parts = []
    for key in ("resource_id", "content_desc", "class"):
        val = selector.get(key)
        if val:
            parts.append(f"{key}={val}")
    return " ".join(parts)


def _build_contract_json(node: dict[str, Any], app: str, *, allow_class_fallback: bool = True) -> str:
    selector = static_selector_from_node(node) or _fallback_selector(
        node,
        allow_class=allow_class_fallback,
    )
    if not selector:
        return ""
    selector = dict(selector)
    state = _extract_state(node)
    for flag in _STATE_FLAGS:
        if selector.pop(flag, None) and flag not in state:
            state.append(flag)
    contract = {
        "anchor": {"app_package": app},
        "signature": {
            "required": [{"selector": selector, "state": state}],
            "forbidden": [],
        },
    }
    return json.dumps(contract, ensure_ascii=False, separators=(",", ":"))


def _fallback_selector(node: dict[str, Any], *, allow_class: bool = True) -> dict[str, str] | None:
    if node.get("resource_id"):
        return {"resource_id": str(node["resource_id"])}
    if allow_class and node.get("class"):
        return {"class": str(node["class"])}
    return None


def _extract_state(node: dict[str, Any]) -> list[str]:
    state = ["visible"]
    for flag in _STATE_FLAGS[1:]:
        val = node.get(flag)
        if val is True or str(val).lower() == "true":
            state.append(flag)
    return state


def _screenshot_b64(event: dict[str, Any], trace_path: Path) -> str:
    obs = event.get("observation") or {}
    raw = event.get("screenshot_path") or obs.get("screenshot_path")
    if not raw:
        return ""
    path = Path(str(raw))
    path = path if path.is_absolute() else trace_path.parent / path
    if not path.is_file():
        return ""
    return _scale_png(path)


def _scale_png(path: Path) -> str:
    with Image.open(path) as img:
        w, h = img.size
        max_edge = max(w, h)
        if max_edge > 1000:
            scale = 1000 / max_edge
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def apply_focused_input_contracts(skill: Skill, contracts: list[dict[str, Any]]) -> Skill:
    if not contracts:
        return skill
    changed = False
    next_contract = 0
    steps: list[SkillStep] = []
    for step in skill.steps:
        if step.action_type != "input_text" or next_contract >= len(contracts):
            steps.append(step)
            continue
        contract = contracts[next_contract]
        next_contract += 1
        if contract_requires_focused(step.state_contract):
            steps.append(step)
            continue
        changed = True
        steps.append(replace(step, state_contract=contract))
    return replace(skill, steps=tuple(steps)) if changed else skill


def contract_requires_focused(contract: dict[str, Any] | None) -> bool:
    if not isinstance(contract, dict):
        return False
    for item in (contract.get("signature") or {}).get("required") or []:
        if "focused" in (item.get("state") or []):
            return True
    return False


def _load_contract(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def apply_focused_contracts_from_codegen(skill: Skill, result: CodegenResult) -> Skill:
    contracts = [
        _load_contract(step.contract_json)
        for step in result.steps
        if step.action_type == "input_text" and step.contract_json
    ]
    contracts = [c for c in contracts if c]
    return apply_focused_input_contracts(skill, contracts) if contracts else skill


def apply_contract_constraints_from_codegen(skill: Skill, result: CodegenResult) -> Skill:
    aligned = _align_skill_steps_to_codegen(skill, result)
    if not aligned:
        return skill
    changed = False
    steps: list[SkillStep] = []
    for step, code_step in aligned:
        if code_step is not None and code_step.suppress_extracted_contract and step.state_contract is not None:
            changed = True
            steps.append(replace(step, state_contract=None))
        else:
            steps.append(step)
    return replace(skill, steps=tuple(steps)) if changed else skill


def _align_skill_steps_to_codegen(
    skill: Skill,
    result: CodegenResult,
) -> list[tuple[SkillStep, CodeStep | None]]:
    code_steps = list(result.steps)
    if (
        skill.steps
        and skill.steps[0].action_type == "open_app"
        and code_steps
        and code_steps[0].action_type in {"tap", "open_app"}
    ):
        code_steps = code_steps[1:]

    aligned: list[tuple[SkillStep, CodeStep | None]] = []
    cursor = 0
    for step in skill.steps:
        if step.action_type == "open_app":
            aligned.append((step, None))
            continue
        match: CodeStep | None = None
        while cursor < len(code_steps):
            candidate = code_steps[cursor]
            cursor += 1
            if candidate.action_type == step.action_type:
                match = candidate
                break
        aligned.append((step, match))
    return aligned
