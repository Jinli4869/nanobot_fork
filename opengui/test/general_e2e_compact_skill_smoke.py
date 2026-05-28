#!/usr/bin/env python3
"""Smoke-test compact skill choices inside the general_e2e prompt/parser path.

This script tests the design where a GUI agent keeps the original MobileWorld
``general_e2e`` action format but receives a compact skill catalog in the
system prompt.  The added action is intentionally represented as plain JSON:

    {"action_type": "use_skill", "skill_name": "...", "arguments": {...}}

The existing general_e2e parser passes unknown JSON action types through, and
the OpenGUI profile normalizer preserves them as an OpenGUI payload.  Normal
GUI actions such as ``click`` are still parsed by the original coordinate
conversion path.

Default mode is offline: build prompts, estimate text token overhead, and run
parser checks with synthetic model outputs.  Use ``--call-api`` for an actual
OpenAI-compatible model smoke test.
"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

NANOBOT_ROOT = Path(__file__).resolve().parents[2]
if str(NANOBOT_ROOT) not in sys.path:
    sys.path.insert(0, str(NANOBOT_ROOT))

from opengui.agents.implementations.general_e2e_agent import (  # noqa: E402
    parse_action,
    parse_response_to_action,
)
from opengui.agents.profiles import parse_mobileworld_action  # noqa: E402
from opengui.agents.utils.prompts import GENERAL_E2E_PROMPT_TEMPLATE  # noqa: E402

DEFAULT_SKILLS_PY = Path("/home/jinli/Project/MobileWorld_fork/gui_skills/skills.py")
DEFAULT_MODEL = "qwen3.5-flash"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_SCREEN_SIZE = (1080, 2400)

SKILL_TASK = "On Mastodon, replace my profile header with the tiger photo from my photo gallery."
GUI_TASK = "Tap the Continue button on the current screen."

COMPACT_SKILL_INSTRUCTIONS = """\
# Optional Compact GUI Skills
You may choose one compact GUI skill as a single action when it is clearly useful
for the user's task. This is optional. If no listed skill clearly matches, keep
using the normal GUI actions above.

Skill action format:
`{{"action_type":"use_skill","skill_name":"function_name","arguments":{{"param":"value"}},"reason":"short reason"}}`

Rules:
- First compare the user task with the compact skill list. If a listed skill
  clearly matches the requested app/workflow, prefer `use_skill` over manual
  navigation.
- Use `use_skill` only when the function name and description clearly match the
  user's task and would be a valid next prefix.
- A compact skill may include navigation/opening the target app internally; the
  current screen does not need to already show the target app.
- Fill `arguments` only when the task provides obvious values; otherwise use an
  empty object.
- If a skill is not clearly applicable, output a normal GUI action such as
  `click`, `input_text`, `scroll`, `answer`, or `status`.

Compact skills:
{catalog}
""".strip()

USE_SKILL_ACTION_ROW = (
    "| `use_skill`     | Run a stored compact GUI skill prefix when it clearly matches the task | "
    '`{"action_type":"use_skill","skill_name":"function_name","arguments":{}}` |'
)

USE_SKILL_DECISION_RULE = (
    "0. Before choosing a manual GUI action, compare the user task with the compact "
    "skill list. If one compact skill clearly matches the requested app/workflow, "
    "choose `use_skill` as the next action. A compact skill may open/navigate to "
    "the target app internally, so do not first open the app manually when the "
    "skill itself matches the whole requested workflow."
)


@dataclass(frozen=True)
class SkillInfo:
    function_name: str
    description: str


def extract_skills(skills_py: Path) -> list[SkillInfo]:
    tree = ast.parse(skills_py.read_text(encoding="utf-8"), filename=str(skills_py))
    out: list[SkillInfo] = []
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        description: str | None = None
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not _is_skill_decorator(decorator.func):
                continue
            for keyword in decorator.keywords:
                if keyword.arg == "description":
                    description = _literal_str(keyword.value)
                    break
            if description is not None:
                break
        if description is not None:
            out.append(SkillInfo(node.name, " ".join(description.split())))
    return out


def _is_skill_decorator(func: ast.expr) -> bool:
    return (
        isinstance(func, ast.Name)
        and func.id == "skill"
        or isinstance(func, ast.Attribute)
        and func.attr == "skill"
    )


def _literal_str(node: ast.expr) -> str | None:
    try:
        value = ast.literal_eval(node)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


def build_catalog(skills: list[SkillInfo], *, limit: int | None) -> str:
    selected = skills[:limit] if limit else skills
    return "\n".join(
        f"- {skill.function_name}: {skill.description}" for skill in selected
    )


def build_system_prompt(*, catalog: str | None, scale_factor: int = 1000) -> str:
    base = GENERAL_E2E_PROMPT_TEMPLATE.render(tools="", scale_factor=scale_factor)
    if not catalog:
        return base
    base = _inject_use_skill_action(base)
    return f"{base}\n\n{COMPACT_SKILL_INSTRUCTIONS.format(catalog=catalog)}"


def _inject_use_skill_action(prompt: str) -> str:
    """Add compact-skill selection to the general_e2e contract without changing parser code."""
    marker = "| `keyboard_enter`   | Press enter key"
    if "`use_skill`" not in prompt and marker in prompt:
        prompt = prompt.replace(marker, f"{USE_SKILL_ACTION_ROW}\n{marker}")
    decision_marker = "# Decision Process\n1. Analyze goal, history, and current screen"
    if USE_SKILL_DECISION_RULE not in prompt and decision_marker in prompt:
        prompt = prompt.replace(
            decision_marker,
            f"# Decision Process\n{USE_SKILL_DECISION_RULE}\n1. Analyze goal, history, and current screen",
        )
    return prompt


def build_messages(task: str, *, system_prompt: str, screenshot_path: Path) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": task},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{_image_b64(screenshot_path)}"
                    },
                },
            ],
        },
    ]


def _image_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def make_dummy_screen(path: Path, *, width: int, height: int) -> None:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 420, width - 120, 620), outline="black", width=4)
    draw.text((160, 490), "Continue", fill="black")
    draw.rectangle((120, 760, width - 120, 960), outline="gray", width=4)
    draw.text((160, 830), "Other", fill="gray")
    image.save(path)


def parse_general_e2e_output(text: str, *, width: int, height: int) -> dict[str, Any]:
    _thought, action_str = parse_action(text)
    return parse_response_to_action(action_str, width, height, scale_factor=1000)


def parser_smoke(width: int, height: int) -> dict[str, Any]:
    skill_response = (
        "Thought: The task directly matches a stored profile header replacement skill.\n"
        'Action: {"action_type":"use_skill","skill_name":"edit_profile_header",'
        '"arguments":{"media_item":"tiger photo"},"reason":"matches Mastodon header change"}'
    )
    gui_response = (
        "Thought: I need to tap the Continue button visible near the top.\n"
        'Action: {"action_type":"click","coordinate":[500,217]}'
    )
    parsed_skill = parse_general_e2e_output(skill_response, width=width, height=height)
    parsed_gui = parse_general_e2e_output(gui_response, width=width, height=height)
    profile_skill = parse_mobileworld_action(
        "general_e2e", skill_response, screen_width=width, screen_height=height
    )
    profile_gui = parse_mobileworld_action(
        "general_e2e", gui_response, screen_width=width, screen_height=height
    )
    return {
        "skill_action_parse": parsed_skill,
        "gui_action_parse": parsed_gui,
        "skill_profile_payload": profile_skill,
        "gui_profile_payload": profile_gui,
        "ok": (
            parsed_skill.get("action_type") == "use_skill"
            and parsed_skill.get("skill_name") == "edit_profile_header"
            and parsed_gui.get("action_type") == "click"
            and parsed_gui.get("x") == width // 2
        ),
    }


def estimate_text_tokens(text: str, model: str) -> int:
    import tiktoken

    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        try:
            enc = tiktoken.get_encoding("o200k_base")
        except ValueError:
            enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def call_model(
    messages: list[dict[str, Any]],
    *,
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int,
) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key or "no-key", base_url=base_url, timeout=120.0)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if "dashscope.aliyuncs.com" in base_url:
        kwargs["extra_body"] = {"enable_thinking": False}
    response = client.chat.completions.create(**kwargs)
    usage_obj = getattr(response, "usage", None)
    usage = (
        {
            "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
        }
        if usage_obj is not None
        else {}
    )
    content = response.choices[0].message.content if response.choices else ""
    return {"content": content or "", "usage": usage}


def api_smoke(
    *,
    base_prompt: str,
    skill_prompt: str,
    screenshot_path: Path,
    width: int,
    height: int,
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int,
) -> dict[str, Any]:
    baseline = call_model(
        build_messages(GUI_TASK, system_prompt=base_prompt, screenshot_path=screenshot_path),
        base_url=base_url,
        model=model,
        api_key=api_key,
        max_tokens=1,
    )
    skill_case = call_model(
        build_messages(SKILL_TASK, system_prompt=skill_prompt, screenshot_path=screenshot_path),
        base_url=base_url,
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
    )
    gui_case = call_model(
        build_messages(GUI_TASK, system_prompt=skill_prompt, screenshot_path=screenshot_path),
        base_url=base_url,
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
    )

    def parsed_or_error(content: str) -> dict[str, Any]:
        try:
            return parse_mobileworld_action(
                "general_e2e", content, screen_width=width, screen_height=height
            )
        except Exception as exc:
            return {"parse_error": str(exc), "raw": content}

    return {
        "baseline_prompt_tokens": baseline["usage"].get("prompt_tokens"),
        "skill_prompt_tokens": skill_case["usage"].get("prompt_tokens"),
        "prompt_token_delta": (
            skill_case["usage"].get("prompt_tokens", 0)
            - baseline["usage"].get("prompt_tokens", 0)
        ),
        "skill_case": {
            "raw": skill_case["content"],
            "usage": skill_case["usage"],
            "parsed": parsed_or_error(skill_case["content"]),
        },
        "gui_case": {
            "raw": gui_case["content"],
            "usage": gui_case["usage"],
            "parsed": parsed_or_error(gui_case["content"]),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-py", type=Path, default=DEFAULT_SKILLS_PY)
    parser.add_argument("--skill-limit", type=int, default=0, help="0 means all skills.")
    parser.add_argument("--model", default=os.environ.get("MODEL_NAME", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    parser.add_argument("--call-api", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.skills_py.exists():
        print(f"skills.py not found: {args.skills_py}", file=sys.stderr)
        return 2

    width, height = DEFAULT_SCREEN_SIZE
    skills = extract_skills(args.skills_py)
    catalog = build_catalog(skills, limit=args.skill_limit or None)
    base_prompt = build_system_prompt(catalog=None)
    skill_prompt = build_system_prompt(catalog=catalog)

    with tempfile.TemporaryDirectory(prefix="general_e2e_skill_smoke_") as tmp:
        screenshot_path = Path(tmp) / "screen.png"
        make_dummy_screen(screenshot_path, width=width, height=height)
        result: dict[str, Any] = {
            "skills_py": str(args.skills_py),
            "skill_count_in_prompt": len(skills if not args.skill_limit else skills[: args.skill_limit]),
            "model": args.model,
            "base_url": args.base_url,
            "prompt_text_tokens": {
                "base_system_prompt": estimate_text_tokens(base_prompt, args.model),
                "compact_skill_system_prompt": estimate_text_tokens(skill_prompt, args.model),
                "delta_per_step": estimate_text_tokens(skill_prompt, args.model)
                - estimate_text_tokens(base_prompt, args.model),
            },
            "parser_smoke": parser_smoke(width, height),
        }
        if args.call_api:
            api_key = os.environ.get(args.api_key_env)
            if not api_key:
                print(f"{args.api_key_env} is not set", file=sys.stderr)
                return 2
            result["api_smoke"] = api_smoke(
                base_prompt=base_prompt,
                skill_prompt=skill_prompt,
                screenshot_path=screenshot_path,
                width=width,
                height=height,
                base_url=args.base_url,
                model=args.model,
                api_key=api_key,
                max_tokens=args.max_tokens,
            )

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"skills_py: {result['skills_py']}")
        print(f"skill_count_in_prompt: {result['skill_count_in_prompt']}")
        print("prompt_text_tokens:")
        for key, value in result["prompt_text_tokens"].items():
            print(f"  {key}: {value}")
        print("parser_smoke:")
        print(json.dumps(result["parser_smoke"], ensure_ascii=False, indent=2))
        if "api_smoke" in result:
            print("api_smoke:")
            print(json.dumps(result["api_smoke"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
