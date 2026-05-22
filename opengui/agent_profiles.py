"""
opengui.agent_profiles
======================
Agent-profile abstractions for prompt shaping and content-only response parsing.
"""

from __future__ import annotations

import json
import re
from typing import Any

import json_repair

from opengui.interfaces import LLMResponse, ToolCall

SUPPORTED_AGENT_PROFILES: tuple[str, ...] = (
    "default",
    "general_e2e",
    "qwen3vl",
    "mai_ui",
    "gelab",
    "seed",
)

_PROFILE_ALIASES: dict[str | None, str] = {
    None: "default",
    "": "default",
    "planner_executor": "general_e2e",
}

_DEFAULT_SCROLL_PIXELS = 420
_MODEL_RELATIVE_GRID_HINTS = ("qwen", "gemini")
_SUMMARY_KEYS = ("summary", "intent")


def canonicalize_agent_profile(profile_name: str | None) -> str:
    key = (profile_name or "").strip().lower()
    key = _PROFILE_ALIASES.get(key, key or "default")
    if key not in SUPPORTED_AGENT_PROFILES:
        raise ValueError(
            f"Unsupported agent profile {profile_name!r}. "
            f"Expected one of: {', '.join(SUPPORTED_AGENT_PROFILES)}."
        )
    return key


def profile_uses_native_tools(profile_name: str | None) -> bool:
    return canonicalize_agent_profile(profile_name) == "default"


def coordinate_mode_for_profile(profile_name: str | None, model_name: str = "") -> str:
    profile = canonicalize_agent_profile(profile_name)
    if profile != "default":
        return "relative_999"
    model = model_name.lower()
    return "relative_999" if any(hint in model for hint in _MODEL_RELATIVE_GRID_HINTS) else "absolute"


def profile_tool_definition(profile_name: str | None) -> dict[str, Any]:
    profile = canonicalize_agent_profile(profile_name)
    if profile == "default":
        return {
            "type": "function",
            "function": {
                "name": "computer_use",
                "description": "Perform one GUI action on the current device screen.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "enum": [
                                "tap", "double_tap", "long_press", "swipe", "drag",
                                "input_text", "hotkey", "scroll",
                                "wait", "open_app", "close_app",
                                "back", "home", "done", "request_intervention",
                            ],
                        },
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "x2": {"type": "number"},
                        "y2": {"type": "number"},
                        "text": {"type": "string"},
                        "key": {"type": "array", "items": {"type": "string"}},
                        "pixels": {"type": "integer"},
                        "duration_ms": {"type": "integer"},
                        "relative": {"type": "boolean"},
                        "status": {"type": "string", "enum": ["success", "failure"]},
                        "intent": {
                            "type": "string",
                            "description": "The purpose of the selected next action.",
                        },
                        "summary": {
                            "type": "string",
                            "description": "The current task progress and visible UI state.",
                        },
                    },
                    "required": ["action_type", "intent", "summary"],
                },
            },
        }
    if profile == "general_e2e":
        return {
            "type": "object",
            "name": "action_payload",
            "description": "Non-native profile. Emit one JSON action after `Action:`.",
        }
    if profile == "qwen3vl":
        return {
            "type": "function",
            "function": {
                "name": "mobile_use",
                "description": "Use a touchscreen to interact with a mobile device.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "click", "long_press", "swipe", "type", "answer",
                                "system_button", "wait", "ask_user", "terminate",
                            ],
                        },
                        "coordinate": {"type": "array", "items": {"type": "number"}},
                        "coordinate2": {"type": "array", "items": {"type": "number"}},
                        "text": {"type": "string"},
                        "time": {"type": "number"},
                        "button": {
                            "type": "string",
                            "enum": ["Back", "Home", "Menu", "Enter"],
                        },
                        "status": {
                            "type": "string",
                            "enum": ["success", "failure"],
                        },
                    },
                    "required": ["action"],
                },
            },
        }
    if profile == "mai_ui":
        return {
            "type": "function",
            "function": {
                "name": "mobile_use",
                "description": "Use a touchscreen to interact with a mobile device.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "click", "long_press", "type", "swipe", "open",
                                "drag", "system_button", "wait", "terminate",
                                "answer", "ask_user", "double_click",
                            ],
                        },
                        "coordinate": {"type": "array", "items": {"type": "number"}},
                        "start_coordinate": {"type": "array", "items": {"type": "number"}},
                        "end_coordinate": {"type": "array", "items": {"type": "number"}},
                        "text": {"type": "string"},
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "left", "right"],
                        },
                        "button": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        }
    if profile == "gelab":
        return {
            "type": "object",
            "name": "gelab_action",
            "description": "Non-native profile. Emit one tab-separated Gelab action line after `</THINK>`.",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["CLICK", "TYPE", "LONGPRESS", "SLIDE", "AWAKE", "WAIT", "COMPLETE", "INFO", "ABORT"],
                },
                "point": {"type": "string"},
                "point1": {"type": "string"},
                "point2": {"type": "string"},
                "value": {"type": "string"},
                "summary": {"type": "string"},
                "intent": {"type": "string"},
            },
        }
    return {
        "type": "object",
        "name": "seed_action",
        "description": "Emit one Seed XML function block inside <tool_call>.",
        "properties": {
            "function": {
                "type": "string",
                "enum": [
                    "click", "left_double", "drag", "scroll", "type",
                    "press_home", "press_back", "wait", "finished", "call_user",
                ],
            },
            "summary": {"type": "string"},
            "intent": {"type": "string"},
        },
    }


def prompt_contract_for_profile(profile_name: str | None) -> dict[str, tuple[str, ...]]:
    profile = canonicalize_agent_profile(profile_name)
    if profile == "default":
        return {
            "environment": (),
            "format": (
                "1) `Action:` followed by one short imperative describing the next UI move.",
                "2) Call the `computer_use` tool exactly once using the provider's native tool-calling mechanism.",
            ),
            "rules": (
                "- Output exactly one short `Action:` line in assistant text.",
                "- Put structured arguments only in the native tool call, not in assistant text.",
                "- Execute one action per step.",
                "- Set the tool-call `intent` argument to one short natural-language description of why this next action is selected now; do not include raw coordinates.",
                "- Set the tool-call `summary` argument to one short natural-language description of the current task progress and visible UI state before the action.",
                "- If the task is complete, call `computer_use` with `action_type=\"done\"`, the appropriate status, and a `text` field containing a brief completion summary. The summary should include: (1) what was accomplished or why it failed; (2) the current screen state (which app/page is showing); (3) if the task involved retrieving information, include the key findings (e.g. prices, messages, search results). Keep the summary concise but informative — the caller depends on it to understand what happened.",
                "- If the task reaches a sensitive, blocked, or unsafe state, call `computer_use` with `action_type=\"request_intervention\"` and a short reason instead of continuing or using `done`.",
            ),
        }
    if profile == "general_e2e":
        return {
            "environment": (
                "- This profile mirrors MobileWorld general_e2e / planner_executor style.",
                "- Do not use native tool calling.",
            ),
            "format": (
                "1) `Thought:` followed by brief reasoning.",
                '2) `Action:` with one JSON object describing the next action.',
                'Example: `Action: {"action_type": "click", "coordinate": [500, 250]}`.',
            ),
            "rules": (
                "- Supported action_type values: click, double_tap, long_press, drag, scroll, input_text, open_app, navigate_back, navigate_home, keyboard_enter, wait, status, ask_user.",
                "- Coordinates should use the 0-999 relative grid in `coordinate`, `start_coordinate`, and `end_coordinate` fields.",
                "- Return exactly one JSON action object after `Action:`.",
                "- Include a `summary` field when possible: one short natural-language description of what the action intends to do.",
            ),
        }
    if profile == "qwen3vl":
        return {
            "environment": (
                "- This profile mirrors MobileWorld qwen3vl style.",
                "- Do not use native tool calling.",
            ),
            "format": (
                "1) `Thought:` followed by brief reasoning.",
                "2) `Action:` followed by one short imperative sentence.",
                '3) A single `<tool_call>...</tool_call>` block containing JSON: `{"name":"mobile_use","arguments":{...}}`.',
            ),
            "rules": (
                "- Supported mobile `action` values: click, long_press, swipe, type, system_button, wait, terminate, answer, ask_user.",
                "- Use `coordinate` and `coordinate2` with the 0-999 relative grid when coordinates are needed.",
                "- Output exactly in the order: Thought, Action, <tool_call>.",
                "- Keep exactly one `<tool_call>` block per step.",
                "- `<tool_call>` must use tool name `mobile_use`.",
            ),
        }
    if profile == "mai_ui":
        return {
            "environment": (
                "- This profile mirrors MobileWorld MAI-UI style.",
                "- Do not use native tool calling.",
            ),
            "format": (
                "1) `<thinking>...</thinking>` with the reasoning and next-action summary.",
                '2) A single `<tool_call>...</tool_call>` block containing JSON: `{"name":"mobile_use","arguments":{...}}`.',
            ),
            "rules": (
                "- Supported `action` values: click, double_click, long_press, drag, swipe, type, open, system_button, wait, answer, ask_user, terminate.",
                "- Swipe with `direction` is treated as a scroll; supply `coordinate` only when scrolling from a specific area.",
                "- Use 0-999 relative coordinates in `coordinate`, `start_coordinate`, and `end_coordinate`.",
                "- Keep exactly one `<tool_call>` block per step.",
                "- `<tool_call>` must use tool name `mobile_use`.",
            ),
        }
    if profile == "gelab":
        return {
            "environment": (
                "- This profile mirrors Gelab style.",
                "- Do not use native tool calling.",
            ),
            "format": (
                '1) Use `<THINK>` and `</THINK>` tags for reasoning.',
                "2) Output one action line using tab-separated key-value pairs, for example: `explain:...\\taction:CLICK\\tpoint:500,250\\tsummary:...`.",
            ),
            "rules": (
                "- Supported action values: CLICK, TYPE, LONGPRESS, SLIDE, AWAKE, WAIT, COMPLETE, INFO, ABORT.",
                "- Coordinate points use a 0-1000 style relative grid; keep values within the visible screen.",
                "- Use `summary` to describe the intent before the next action.",
            ),
        }
    return {
        "environment": (
            "- This profile mirrors Seed GUI XML action style.",
            "- Do not use native tool calling.",
        ),
        "format": (
            '1) Use `<think>` and `</think>` for reasoning text.',
            '2) `<tool_call>` block in XML-like form, for example: `<tool_call><function=click><parameter=point>500 250</parameter></function></tool_call>`.',
        ),
        "rules": (
            "- Supported functions: click, left_double, drag, scroll, type, press_home, press_back, wait, finished, call_user.",
            "- Use 0-1000 style relative coordinates in point parameters.",
            "- Avoid extra commentary outside the required tags when possible.",
        ),
    }


def _with_action_summary(payload: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    for key in _SUMMARY_KEYS:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            payload["summary"] = text
            break
    return payload


def normalize_profile_response(profile_name: str | None, response: LLMResponse) -> LLMResponse:
    profile = canonicalize_agent_profile(profile_name)
    if profile == "default":
        return response

    content = response.content or ""
    if content.strip():
        try:
            arguments = _parse_content_action(profile, content)
        except ValueError:
            if response.tool_calls:
                return LLMResponse(
                    content=response.content,
                    tool_calls=_normalize_profile_tool_calls(profile, response.tool_calls),
                    raw=response.raw,
                    usage=response.usage,
                )
            raise
        synthetic = ToolCall(
            id="content-tool-call-0",
            name="computer_use",
            arguments=arguments,
        )
        return LLMResponse(
            content=response.content,
            tool_calls=[synthetic],
            raw=response.raw,
            usage=response.usage,
        )

    if response.tool_calls:
        return LLMResponse(
            content=response.content,
            tool_calls=_normalize_profile_tool_calls(profile, response.tool_calls),
            raw=response.raw,
            usage=response.usage,
        )

    return response


def _parse_content_action(profile_name: str, content: str) -> dict[str, Any]:
    if profile_name == "general_e2e":
        action_json = _extract_action_json(content)
        return _with_action_summary(_normalize_general_e2e_action(action_json), action_json)
    if profile_name == "qwen3vl":
        tool_call = _extract_tool_call_json(content)
        arguments = tool_call.get("arguments", {})
        return _with_action_summary(_normalize_qwen3vl_action(arguments), arguments)
    if profile_name == "mai_ui":
        tool_call = _extract_mai_ui_tool_call(content)
        tool_name = tool_call.get("name", "mobile_use")
        if tool_name != "mobile_use":
            return _request_intervention_payload(f"Unsupported MAI-UI tool: {tool_name}")
        arguments = tool_call.get("arguments", {})
        return _with_action_summary(_normalize_mai_ui_action(arguments), arguments)
    if profile_name == "gelab":
        return _normalize_gelab_action(content)
    if profile_name == "seed":
        return _normalize_seed_action(content)
    raise ValueError(f"Content parsing not defined for profile {profile_name!r}.")


def _normalize_profile_tool_calls(profile_name: str, tool_calls: list[ToolCall]) -> list[ToolCall]:
    normalized: list[ToolCall] = []
    for tool_call in tool_calls:
        arguments = tool_call.arguments
        name = tool_call.name

        if profile_name == "qwen3vl":
            if name == "mobile_use" or (name == "computer_use" and "action_type" not in arguments):
                arguments = _normalize_qwen3vl_action(arguments)
                name = "computer_use"
        elif profile_name == "general_e2e":
            if name == "mobile_use" or (name == "computer_use" and "action_type" not in arguments):
                arguments = _normalize_general_e2e_action(arguments)
                name = "computer_use"
        elif profile_name == "mai_ui":
            if name == "mobile_use" or (name == "computer_use" and "action_type" not in arguments):
                arguments = _normalize_mai_ui_action(arguments)
                name = "computer_use"

        arguments = _with_action_summary(arguments, tool_call.arguments)
        normalized.append(
            ToolCall(
                id=tool_call.id,
                name=name,
                arguments=arguments,
            )
        )
    return normalized


def _extract_action_json(content: str) -> dict[str, Any]:
    match = re.search(r"Action:\s*(.*)", content, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError("Expected an `Action:` section in the response.")
    action_payload = match.group(1).strip()

    # Prefer the Action payload when a tool-call block is also present.
    if "<tool_call>" in action_payload:
        action_payload = action_payload.split("<tool_call>", 1)[0].strip()
    # In case models surround the block with fences.
    if action_payload.startswith("```"):
        action_payload = re.sub(r"^```(?:json)?\s*", "", action_payload)
        action_payload = re.sub(r"\s*```$", "", action_payload)

    if not action_payload.startswith("{"):
        raise ValueError("Expected an Action JSON object.")
    return _load_json(_extract_json_object(action_payload))


def _extract_json_object(text: str) -> str:
    depth = 0
    in_string = False
    escaped = False
    start = None
    for idx, char in enumerate(text):
        if start is None:
            if char != "{":
                continue
            start = idx
            depth = 1
            continue
        if in_string:
            if char == "\\" and not escaped:
                escaped = True
                continue
            if char == '"' and not escaped:
                in_string = False
            escaped = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
            if depth < 0:
                break
    raise ValueError("Malformed Action JSON object.")


def _extract_tool_call_json(content: str) -> dict[str, Any]:
    match = re.search(r"<tool_call>(.*?)</tool_call>", content, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("Expected a `<tool_call>` block in the response.")
    return _load_json(match.group(1).strip().strip('"'))


def _extract_mai_ui_tool_call(content: str) -> dict[str, Any]:
    normalized = content
    if "</think>" in normalized and "</thinking>" not in normalized:
        normalized = normalized.replace("</think>", "</thinking>")
        if "<thinking>" not in normalized:
            normalized = "<thinking>" + normalized
    match = re.search(r"<tool_call>(.*?)</tool_call>", normalized, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("Expected a `<tool_call>` block in the response.")
    return _load_json(match.group(1).strip().strip('"'))


def _normalize_general_e2e_action(action_json: dict[str, Any]) -> dict[str, Any]:
    raw_type = str(action_json.get("action_type") or action_json.get("action") or "").strip().lower()
    action_type = {
        "tap": "click",
        "press": "click",
        "touch": "click",
        "double_click": "double_tap",
        "type": "input_text",
        "enter_text": "input_text",
        "write": "input_text",
        "enter": "keyboard_enter",
        "fling": "scroll",
        "swipe": "scroll",
    }.get(raw_type, raw_type)

    if action_type in {"click", "double_tap", "long_press"}:
        x, y = _extract_point(action_json.get("coordinate"))
        return {
            "action_type": {
                "click": "tap",
                "double_tap": "double_tap",
                "long_press": "long_press",
            }[action_type],
            "x": x,
            "y": y,
            "relative": True,
        }
    if action_type == "drag":
        start_x, start_y = _extract_point(action_json.get("start_coordinate"))
        end_x, end_y = _extract_point(action_json.get("end_coordinate"))
        return {
            "action_type": "drag",
            "x": start_x,
            "y": start_y,
            "x2": end_x,
            "y2": end_y,
            "relative": True,
        }
    if action_type == "scroll":
        if action_json.get("start_coordinate") is not None and action_json.get("end_coordinate") is not None:
            start_x, start_y = _extract_point(action_json.get("start_coordinate"))
            end_x, end_y = _extract_point(action_json.get("end_coordinate"))
            return {
                "action_type": "swipe",
                "x": start_x,
                "y": start_y,
                "x2": end_x,
                "y2": end_y,
                "relative": True,
            }
        payload: dict[str, Any] = {
            "action_type": "scroll",
            "text": _normalize_direction(action_json.get("direction") or action_json.get("text") or "down"),
            "pixels": int(action_json.get("pixels") or _DEFAULT_SCROLL_PIXELS),
            "relative": True,
        }
        if action_json.get("coordinate") is not None:
            x, y = _extract_point(action_json.get("coordinate"))
            payload["x"] = x
            payload["y"] = y
        return payload
    if action_type == "input_text":
        return {"action_type": "input_text", "text": str(action_json.get("text", ""))}
    if action_type == "open_app":
        return {"action_type": "open_app", "text": str(action_json.get("app_name") or action_json.get("text") or "")}
    if action_type == "navigate_back":
        return {"action_type": "back"}
    if action_type == "navigate_home":
        return {"action_type": "home"}
    if action_type == "keyboard_enter":
        return {"action_type": "hotkey", "key": ["ENTER"]}
    if action_type == "wait":
        payload = {"action_type": "wait"}
        if action_json.get("duration_ms") is not None:
            payload["duration_ms"] = int(action_json["duration_ms"])
        return payload
    if action_type == "ask_user":
        return _request_intervention_payload(str(action_json.get("text", "")).strip() or "Agent requested user input.")
    if action_type in {"status", "answer"}:
        status = action_json.get("goal_status") or action_json.get("status") or action_json.get("text")
        return {"action_type": "done", "status": _normalize_done_status(status)}
    raise ValueError(f"Unsupported general_e2e action type: {action_type!r}")


def _normalize_qwen3vl_action(action_json: dict[str, Any]) -> dict[str, Any]:
    action_type = str(action_json.get("action") or action_json.get("action_type") or "").strip().lower()
    if action_type == "click":
        x, y = _extract_point(action_json.get("coordinate"))
        return {"action_type": "tap", "x": x, "y": y, "relative": True}
    if action_type == "long_press":
        x, y = _extract_point(action_json.get("coordinate"))
        payload = {"action_type": "long_press", "x": x, "y": y, "relative": True}
        duration_ms = _extract_duration_ms(action_json)
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return payload
    if action_type == "type":
        return {"action_type": "input_text", "text": str(action_json.get("text", ""))}
    if action_type == "swipe":
        start_x, start_y = _extract_point(action_json.get("coordinate"))
        end_x, end_y = _extract_point(action_json.get("coordinate2"))
        return {
            "action_type": "swipe",
            "x": start_x,
            "y": start_y,
            "x2": end_x,
            "y2": end_y,
            "relative": True,
        }
    if action_type == "system_button":
        button = str(action_json.get("button", "")).strip().lower()
        if button == "home":
            return {"action_type": "home"}
        if button == "back":
            return {"action_type": "back"}
        if button == "enter":
            return {"action_type": "hotkey", "key": ["ENTER"]}
        raise ValueError(f"Unsupported system button: {button!r}")
    if action_type == "wait":
        payload = {"action_type": "wait"}
        duration_ms = _extract_duration_ms(action_json)
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return payload
    if action_type == "terminate":
        return {"action_type": "done", "status": _normalize_done_status(action_json.get("status"))}
    if action_type == "answer":
        return {"action_type": "done", "status": "success"}
    if action_type == "ask_user":
        return _request_intervention_payload(str(action_json.get("text", "")).strip() or "Agent requested user input.")
    if action_type == "open":
        return {"action_type": "open_app", "text": str(action_json.get("text", ""))}
    raise ValueError(f"Unsupported qwen3vl action type: {action_type!r}")


def _normalize_mai_ui_action(action_json: dict[str, Any]) -> dict[str, Any]:
    raw_type = str(action_json.get("action") or action_json.get("action_type") or "").strip().lower()
    if raw_type == "click":
        x, y = _extract_point(action_json.get("coordinate"))
        return {"action_type": "tap", "x": x, "y": y, "relative": True}
    if raw_type == "long_press":
        x, y = _extract_point(action_json.get("coordinate"))
        return {"action_type": "long_press", "x": x, "y": y, "relative": True}
    if raw_type == "double_click":
        x, y = _extract_point(action_json.get("coordinate"))
        return {"action_type": "double_tap", "x": x, "y": y, "relative": True}
    if raw_type == "type":
        return {"action_type": "input_text", "text": str(action_json.get("text", ""))}
    if raw_type == "drag":
        start_x, start_y = _extract_point(action_json.get("start_coordinate"))
        end_x, end_y = _extract_point(action_json.get("end_coordinate"))
        return {
            "action_type": "drag",
            "x": start_x,
            "y": start_y,
            "x2": end_x,
            "y2": end_y,
            "relative": True,
        }
    if raw_type == "swipe":
        if "direction" in action_json:
            payload = {
                "action_type": "scroll",
                "text": _normalize_direction(action_json.get("direction")),
                "relative": True,
                "pixels": int(action_json.get("pixels") or _DEFAULT_SCROLL_PIXELS),
            }
            if "coordinate" in action_json:
                x, y = _extract_point(action_json.get("coordinate"))
                payload["x"] = x
                payload["y"] = y
            return payload
        if "coordinate2" in action_json and "coordinate" in action_json:
            start_x, start_y = _extract_point(action_json.get("coordinate"))
            end_x, end_y = _extract_point(action_json.get("coordinate2"))
            return {
                "action_type": "swipe",
                "x": start_x,
                "y": start_y,
                "x2": end_x,
                "y2": end_y,
                "relative": True,
            }
    if raw_type == "open":
        return {"action_type": "open_app", "text": str(action_json.get("text", ""))}
    if raw_type == "system_button":
        button = str(action_json.get("button", "")).strip().lower()
        if button == "home":
            return {"action_type": "home"}
        if button == "back":
            return {"action_type": "back"}
        if button == "enter":
            return {"action_type": "hotkey", "key": ["ENTER"]}
        raise ValueError(f"Unsupported MAI-UI system button: {button!r}")
    if raw_type == "wait":
        return {"action_type": "wait"}
    if raw_type == "terminate":
        return {"action_type": "done", "status": _normalize_done_status(action_json.get("status"))}
    if raw_type == "answer":
        return {"action_type": "done", "status": "success"}
    if raw_type == "ask_user":
        return _request_intervention_payload(str(action_json.get("text", "")).strip() or "Agent requested user input.")
    raise ValueError(f"Unsupported MAI-UI action type: {raw_type!r}")


def _extract_duration_ms(value: dict[str, Any]) -> int | None:
    for field in ("duration_ms", "time", "seconds"):
        raw_value = value.get(field)
        if raw_value is None:
            continue
        try:
            seconds = float(raw_value)
        except (TypeError, ValueError):
            continue
        if seconds < 0:
            return None
        if field == "duration_ms":
            return int(round(seconds))
        return int(round(seconds * 1000))
    return None


def _normalize_gelab_action(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        payload = dict(content)
        action_value = payload.get("action") or payload.get("action_type") or ""
        payload["action"] = action_value
        if "point" not in payload and "coordinate" in payload:
            payload["point"] = payload["coordinate"]
        if "point1" not in payload and "start_coordinate" in payload:
            payload["point1"] = payload["start_coordinate"]
        if "point2" not in payload and "end_coordinate" in payload:
            payload["point2"] = payload["end_coordinate"]
    else:
        normalized = re.sub(
            r"<\s*/?(?:THINK|think|TINK|tink)\s*>",
            lambda match: "<THINK>" if "/" not in match.group(0) else "</THINK>",
            content.strip(),
        )
        if "</THINK>" in normalized:
            kv_part = normalized.split("</THINK>", 1)[1].strip()
        else:
            kv_part = normalized
        payload: dict[str, Any] = {}
        for part in kv_part.split("\t"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            payload[key.strip()] = value.strip()
    action_type = payload.get("action", "").upper()
    if action_type == "CLICK":
        x, y = _extract_point(payload.get("point"))
        return {"action_type": "tap", "x": x, "y": y, "relative": True}
    if action_type == "TYPE":
        return {"action_type": "input_text", "text": payload.get("value", "")}
    if action_type == "LONGPRESS":
        x, y = _extract_point(payload.get("point"))
        return {"action_type": "long_press", "x": x, "y": y, "relative": True}
    if action_type == "SLIDE":
        start_x, start_y = _extract_point(payload.get("point1"))
        end_x, end_y = _extract_point(payload.get("point2"))
        return {
            "action_type": "drag",
            "x": start_x,
            "y": start_y,
            "x2": end_x,
            "y2": end_y,
            "relative": True,
        }
    if action_type == "AWAKE":
        return {"action_type": "open_app", "text": payload.get("value", "")}
    if action_type == "WAIT":
        result: dict[str, Any] = {"action_type": "wait"}
        try:
            result["duration_ms"] = int(float(payload.get("value", "1")) * 1000)
        except ValueError:
            pass
        return result
    if action_type == "COMPLETE":
        return {"action_type": "done", "status": "success"}
    if action_type == "INFO":
        return _request_intervention_payload(payload.get("value", "") or "Gelab requested user input.")
    if action_type == "ABORT":
        return {"action_type": "done", "status": "failure"}
    raise ValueError(f"Unsupported Gelab action type: {action_type!r}")


def _normalize_seed_action(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        function_name = str(content.get("function") or "").strip()
        params = content.get("parameters", {})
        if not function_name:
            function_name = str(content.get("action") or "").strip()
            if not params:
                params = dict(content)
        if not isinstance(params, dict):
            params = {}
    else:
        actions = _parse_seed_xml_action(content)
        if not actions:
            raise ValueError("Expected a Seed <tool_call> block with one function.")
        first_action = actions[0]
        function_name = first_action["function"]
        params = first_action["parameters"]

    function_name = function_name.lower()
    if function_name == "click":
        x, y = _extract_point(params.get("point"))
        return {"action_type": "tap", "x": x, "y": y, "relative": True}
    if function_name == "left_double":
        x, y = _extract_point(params.get("point"))
        return {"action_type": "double_tap", "x": x, "y": y, "relative": True}
    if function_name == "drag":
        start_x, start_y = _extract_point(params.get("start_point"))
        end_x, end_y = _extract_point(params.get("end_point"))
        return {
            "action_type": "drag",
            "x": start_x,
            "y": start_y,
            "x2": end_x,
            "y2": end_y,
            "relative": True,
        }
    if function_name == "scroll":
        payload = {
            "action_type": "scroll",
            "text": _normalize_direction(params.get("direction") or "down"),
            "pixels": _DEFAULT_SCROLL_PIXELS,
            "relative": True,
        }
        if params.get("point") is not None:
            x, y = _extract_point(params.get("point"))
            payload["x"] = x
            payload["y"] = y
        return payload
    if function_name == "type":
        return {"action_type": "input_text", "text": params.get("content", "")}
    if function_name == "press_home":
        return {"action_type": "home"}
    if function_name == "press_back":
        return {"action_type": "back"}
    if function_name == "wait":
        return {"action_type": "wait"}
    if function_name == "finished":
        return {"action_type": "done", "status": "success"}
    if function_name == "call_user":
        return _request_intervention_payload(params.get("content", "") or "Seed requested user input.")
    raise ValueError(f"Unsupported Seed function: {function_name!r}")


def _load_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = json_repair.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


def _extract_point(raw: Any) -> tuple[int, int]:
    if raw is None:
        raise ValueError("Missing coordinates.")
    if isinstance(raw, str):
        text = re.sub(r"</?point>", "", raw).strip()
        text = text.strip("()")
        parts = [piece for piece in re.split(r"[\s,]+", text) if piece]
        if len(parts) < 2:
            raise ValueError(f"Invalid coordinate string: {raw!r}")
        return _normalize_relative_number(parts[0]), _normalize_relative_number(parts[1])
    if isinstance(raw, (list, tuple)):
        if len(raw) == 2:
            return _normalize_relative_number(raw[0]), _normalize_relative_number(raw[1])
        if len(raw) == 4:
            x1 = _normalize_relative_number(raw[0])
            y1 = _normalize_relative_number(raw[1])
            x2 = _normalize_relative_number(raw[2])
            y2 = _normalize_relative_number(raw[3])
            return round((x1 + x2) / 2), round((y1 + y2) / 2)
    raise ValueError(f"Unsupported coordinate payload: {raw!r}")


def _normalize_relative_number(value: Any) -> int:
    return max(0, min(int(round(float(value))), 999))


def _normalize_direction(value: Any) -> str:
    text = str(value or "down").strip().lower()
    mapping = {
        "top": "up",
        "bottom": "down",
    }
    return mapping.get(text, text)


def _normalize_done_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(token in text for token in ("fail", "abort", "error")):
        return "failure"
    return "success"


def _request_intervention_payload(reason: str) -> dict[str, Any]:
    return {"action_type": "request_intervention", "text": reason.strip() or "User input required."}


def _parse_seed_xml_action(response_text: str) -> list[dict[str, Any]]:
    parsed_actions: list[dict[str, Any]] = []
    tool_call_matches = re.findall(r"<tool_call[^>]*>(.*?)</tool_call[^>]*>", response_text, re.DOTALL)

    if not tool_call_matches:
        function_matches = re.findall(r"<function=(\w+)>(.*?)</function>", response_text, re.DOTALL)
        for function_name, function_content in function_matches:
            parsed_actions.append(
                {"function": function_name, "parameters": _extract_seed_parameters(function_content)}
            )
        return parsed_actions

    for tool_call_content in tool_call_matches:
        function_matches = re.findall(r"<function=(\w+)>(.*?)</function>", tool_call_content, re.DOTALL)
        for function_name, function_content in function_matches:
            parsed_actions.append(
                {"function": function_name, "parameters": _extract_seed_parameters(function_content)}
            )
    return parsed_actions


def _extract_seed_parameters(function_content: str) -> dict[str, str]:
    params: dict[str, str] = {}
    param_matches = re.findall(
        r"<parameter=(\w+)>(.*?)(?:</parameter>|(?=<parameter=)|$)",
        function_content,
        re.DOTALL,
    )
    for param_name, param_value in param_matches:
        inner = re.search(r"<\w+>(.*?)</\w+>", param_value, re.DOTALL)
        if inner:
            param_value = inner.group(1)
        params[param_name] = param_value.strip()
    return params
