"""
opengui.prompts.system
~~~~~~~~~~~~~~~~~~~~~~
System prompt templates for the GUI agent.
"""

from __future__ import annotations

import json
from typing import Any


def _default_tool_definition() -> dict[str, Any]:
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
                            "back", "home", "done",
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
                    "status": {
                        "type": "string",
                        "enum": ["success", "failure"],
                    },
                },
                "required": ["action_type"],
            },
        },
    }


def build_system_prompt(
    *,
    platform: str = "unknown",
    coordinate_mode: str = "absolute",
    memory_context: str | None = None,
    skill_context: str | None = None,
    tool_definition: dict[str, Any] | None = None,
    installed_apps: list[str] | None = None,
) -> str:
    """Build a Mobile-Agent-style system prompt while keeping native tool calls."""
    tool_schema = json.dumps(
        tool_definition or _default_tool_definition(),
        ensure_ascii=False,
    )

    if coordinate_mode == "relative_999":
        coordinate_rules = (
            "- The screen uses a 1000x1000 relative coordinate grid.\n"
            "- For coordinate-based actions, use values in [0, 999] and set `relative=true`."
        )
    else:
        coordinate_rules = (
            "- Use absolute pixel coordinates based on the current screenshot and screen metadata.\n"
            "- Only use `relative=true` when the host explicitly requests relative coordinates."
        )

    sections = [
        "# Tools",
        "",
        "You may call one function to assist with the user query.",
        "",
        "You are provided with function signatures within <tools></tools> XML tags:",
        "<tools>",
        tool_schema,
        "</tools>",
        "",
        "# Environment",
        "",
        "- You are operating on a GUI screen and can only act through the `computer_use` tool.",
        "- Some actions may take time to complete, so you may need to wait and observe again.",
        "- Use the latest screenshot as the source of truth.",
        "- Click the center of the intended UI element unless the task clearly requires an edge.",
        coordinate_rules,
    ]

    if platform != "unknown":
        sections.extend(["", f"- Platform: {platform}"])

    if memory_context:
        sections.extend(["", "# Relevant Knowledge", "", memory_context])

    if installed_apps:
        app_list = "\n".join(f"- {app}" for app in installed_apps)
        if platform == "android":
            sections.extend([
                "",
                "# Installed Apps (package names)",
                "",
                "Use these exact package names for `open_app` and `close_app` actions:",
                app_list,
            ])
        else:
            sections.extend([
                "",
                "# Installed Apps",
                "",
                "Use these app names for `open_app` and `close_app` actions:",
                app_list,
            ])

    if skill_context:
        sections.extend(["", "# Available Skills", "", skill_context])

    sections.extend([
        "",
        "# Response format",
        "",
        "Response format for every step:",
        "1) `Action:` followed by one short imperative describing the next UI move.",
        "2) Call the `computer_use` tool exactly once using the provider's native tool-calling mechanism.",
        "",
        "Rules:",
        "- Output exactly one short `Action:` line in assistant text.",
        "- Put structured arguments only in the native tool call, not in assistant text.",
        "- Execute one action per step.",
        "- If the task is complete or unsafe to continue, call `computer_use` with `action_type=\"done\"` and the appropriate status.",
    ])

    return "\n".join(sections)
