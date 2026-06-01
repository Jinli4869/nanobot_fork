#!/usr/bin/env python3
"""Smoke-test compact skill choices inside the general_e2e prompt/parser path.

This script tests the design where a GUI agent keeps the original MobileWorld
``general_e2e`` action format but receives a compact skill catalog in the
system prompt.  The added action is intentionally represented as plain JSON:

    {"action_type": "use_skill", "skill_id": "...", "arguments": {...}}

The existing general_e2e parser passes unknown JSON action types through, and
the OpenGUI profile normalizer preserves them as an OpenGUI payload.  Normal
GUI actions such as ``click`` are still parsed by the original coordinate
conversion path.

Default mode is offline: build prompts, estimate text token overhead, and run
parser checks with synthetic model outputs.  Use ``--call-api`` for an actual
OpenAI-compatible model smoke test.

When ``--skill-store-root`` and ``--task`` are supplied, the compact catalog is
built from ``FlatSkillLibrary.search(task, top_k=...)`` instead of taking the
first N functions from a ``skills.py`` file.  This is intended to test whether
validated shortcut skills such as deeplinks/deep intents are retrieved and
selected by the model as a ``use_skill`` action.
"""

from __future__ import annotations

import argparse
import asyncio
import ast
import base64
import json
import os
import sys
import tempfile
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
from opengui.skills.compact_prompt import (  # noqa: E402
    COMPACT_SKILL_INSTRUCTIONS,
    USE_SKILL_ACTION_ROW,
    USE_SKILL_DECISION_RULE,
    SkillInfo,
    build_catalog,
    is_shortcut_skill,
    skill_info_from_flat_skill,
)

DEFAULT_SKILLS_PY = Path("/home/jinli/Project/MobileWorld_fork/gui_skills/skills.py")
DEFAULT_MODEL = "qwen3.5-flash"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_SCREEN_SIZE = (1080, 2400)

SKILL_TASK = "On Mastodon, replace my profile header with the tiger photo from my photo gallery."
GUI_TASK = "Tap the Continue button on the current screen."


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
            out.append(SkillInfo(node.name, " ".join(description.split()), skill_id=node.name))
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


async def retrieve_skill_infos(
    *,
    store_root: Path,
    task: str,
    platform: str | None,
    app: str | None,
    top_k: int,
    shortcut_only: bool,
) -> list[SkillInfo]:
    from opengui.skills.flat import FlatSkillLibrary

    library = FlatSkillLibrary(store_dir=store_root)
    search_k = max(top_k, top_k * 5 if shortcut_only else top_k)
    results = await library.search(task, platform=platform, app=app, top_k=search_k)
    out: list[SkillInfo] = []
    for skill, score in results:
        if shortcut_only and not is_shortcut_skill(skill):
            continue
        out.append(skill_info_from_flat_skill(skill, score=score))
        if len(out) >= top_k:
            break
    return out


def build_system_prompt(*, catalog: str | None, scale_factor: int = 1000) -> str:
    if not catalog:
        return GENERAL_E2E_PROMPT_TEMPLATE.render(tools="", scale_factor=scale_factor)
    return GENERAL_E2E_PROMPT_TEMPLATE.render(
        tools="",
        scale_factor=scale_factor,
        extra_action_rows=USE_SKILL_ACTION_ROW,
        decision_rules=USE_SKILL_DECISION_RULE,
        compact_skill_instructions=COMPACT_SKILL_INSTRUCTIONS.format(catalog=catalog),
    )


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
        'Action: {"action_type":"use_skill","skill_id":"skill:edit_profile_header",'
        '"skill_name":"edit_profile_header",'
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
            and parsed_skill.get("skill_id") == "skill:edit_profile_header"
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
    skill_task: str,
    negative_task: str,
    screenshot_path: Path,
    width: int,
    height: int,
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int,
    expected_skill: str | None = None,
) -> dict[str, Any]:
    baseline = call_model(
        build_messages(negative_task, system_prompt=base_prompt, screenshot_path=screenshot_path),
        base_url=base_url,
        model=model,
        api_key=api_key,
        max_tokens=1,
    )
    skill_case = call_model(
        build_messages(skill_task, system_prompt=skill_prompt, screenshot_path=screenshot_path),
        base_url=base_url,
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
    )
    gui_case = call_model(
        build_messages(negative_task, system_prompt=skill_prompt, screenshot_path=screenshot_path),
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

    parsed_skill = parsed_or_error(skill_case["content"])
    parsed_gui = parsed_or_error(gui_case["content"])
    return {
        "baseline_prompt_tokens": baseline["usage"].get("prompt_tokens"),
        "skill_prompt_tokens": skill_case["usage"].get("prompt_tokens"),
        "prompt_token_delta": (
            skill_case["usage"].get("prompt_tokens", 0)
            - baseline["usage"].get("prompt_tokens", 0)
        ),
        "skill_case": {
            "task": skill_task,
            "raw": skill_case["content"],
            "usage": skill_case["usage"],
            "parsed": parsed_skill,
            "selection": summarize_skill_selection(parsed_skill, expected_skill=expected_skill),
        },
        "gui_case": {
            "task": negative_task,
            "raw": gui_case["content"],
            "usage": gui_case["usage"],
            "parsed": parsed_gui,
            "selection": summarize_skill_selection(parsed_gui, expected_skill=None),
        },
    }


def summarize_skill_selection(
    parsed: dict[str, Any],
    *,
    expected_skill: str | None,
) -> dict[str, Any]:
    used_skill = parsed.get("action_type") == "use_skill"
    selected_skill_id = parsed.get("skill_id")
    selected_skill_name = parsed.get("skill_name")
    selected = selected_skill_id or selected_skill_name
    expected_match = None
    if expected_skill:
        expected_match = expected_skill in {selected_skill_id, selected_skill_name}
    return {
        "used_skill": used_skill,
        "selected_skill_id": selected_skill_id,
        "selected_skill_name": selected_skill_name,
        "selected": selected,
        "expected_skill": expected_skill,
        "expected_match": expected_match,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-py", type=Path, default=DEFAULT_SKILLS_PY)
    parser.add_argument("--skill-limit", type=int, default=0, help="0 means all skills.")
    parser.add_argument(
        "--skill-store-root",
        type=Path,
        help="FlatSkillLibrary store root. When set with --task, build catalog from retrieval top-k.",
    )
    parser.add_argument("--task", help="Task used for retrieval and the skill-selection API case.")
    parser.add_argument(
        "--negative-task",
        default=GUI_TASK,
        help="Unrelated task used to estimate false-positive use_skill behavior.",
    )
    parser.add_argument("--platform", default="android")
    parser.add_argument("--app", help="Optional app/package filter for FlatSkillLibrary.search().")
    parser.add_argument("--retrieval-top-k", type=int, default=5)
    parser.add_argument(
        "--shortcut-only",
        action="store_true",
        help="After retrieval, keep only shortcut/deeplink/intent skills in the prompt catalog.",
    )
    parser.add_argument(
        "--expected-skill",
        help="Expected selected skill_id or skill_name. Reported as expected_match in API smoke.",
    )
    parser.add_argument("--model", default=os.environ.get("MODEL_NAME", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", help="API key value. Overrides --api-key-env when provided.")
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    parser.add_argument("--call-api", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    retrieval_mode = bool(args.skill_store_root and args.task)
    if retrieval_mode and args.retrieval_top_k <= 0:
        print("--retrieval-top-k must be positive", file=sys.stderr)
        return 2
    if retrieval_mode and not args.skill_store_root.exists():
        print(f"skill store root not found: {args.skill_store_root}", file=sys.stderr)
        return 2
    if not retrieval_mode and not args.skills_py.exists():
        print(f"skills.py not found: {args.skills_py}", file=sys.stderr)
        return 2

    width, height = DEFAULT_SCREEN_SIZE
    if retrieval_mode:
        skills = asyncio.run(
            retrieve_skill_infos(
                store_root=args.skill_store_root,
                task=args.task,
                platform=args.platform,
                app=args.app,
                top_k=args.retrieval_top_k,
                shortcut_only=args.shortcut_only,
            )
        )
    else:
        skills = extract_skills(args.skills_py)
    catalog = build_catalog(skills, limit=args.skill_limit or None)
    base_prompt = build_system_prompt(catalog=None)
    skill_prompt = build_system_prompt(catalog=catalog)
    skill_task = args.task or SKILL_TASK

    with tempfile.TemporaryDirectory(prefix="general_e2e_skill_smoke_") as tmp:
        screenshot_path = Path(tmp) / "screen.png"
        make_dummy_screen(screenshot_path, width=width, height=height)
        result: dict[str, Any] = {
            "mode": "retrieval_top_k" if retrieval_mode else "skills_py_catalog",
            "skills_py": None if retrieval_mode else str(args.skills_py),
            "skill_store_root": str(args.skill_store_root) if args.skill_store_root else None,
            "task": skill_task,
            "negative_task": args.negative_task,
            "platform": args.platform if retrieval_mode else None,
            "app": args.app if retrieval_mode else None,
            "retrieval_top_k": args.retrieval_top_k if retrieval_mode else None,
            "shortcut_only": bool(args.shortcut_only) if retrieval_mode else None,
            "expected_skill": args.expected_skill,
            "skill_count_in_prompt": len(skills if not args.skill_limit else skills[: args.skill_limit]),
            "retrieved_skills": [skill_info_to_dict(skill) for skill in skills] if retrieval_mode else None,
            "retrieval_hit": (
                any(
                    args.expected_skill in {skill.skill_id, skill.function_name}
                    for skill in skills
                )
                if retrieval_mode and args.expected_skill
                else None
            ),
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
            api_key = args.api_key or os.environ.get(args.api_key_env)
            if not api_key:
                print(f"{args.api_key_env} is not set", file=sys.stderr)
                return 2
            result["api_smoke"] = api_smoke(
                base_prompt=base_prompt,
                skill_prompt=skill_prompt,
                skill_task=skill_task,
                negative_task=args.negative_task,
                screenshot_path=screenshot_path,
                width=width,
                height=height,
                base_url=args.base_url,
                model=args.model,
                api_key=api_key,
                max_tokens=args.max_tokens,
                expected_skill=args.expected_skill,
            )

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"mode: {result['mode']}")
        if result["skills_py"]:
            print(f"skills_py: {result['skills_py']}")
        if result["skill_store_root"]:
            print(f"skill_store_root: {result['skill_store_root']}")
            print(f"task: {result['task']}")
            print(f"retrieval_hit: {result['retrieval_hit']}")
            print("retrieved_skills:")
            print(json.dumps(result["retrieved_skills"], ensure_ascii=False, indent=2))
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


def skill_info_to_dict(skill: SkillInfo) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "skill_name": skill.function_name,
        "description": skill.description,
        "app": skill.app,
        "platform": skill.platform,
        "tags": list(skill.tags),
        "parameters": list(skill.parameters),
        "score": skill.score,
        "first_action_type": skill.first_action_type,
        "first_action_target": skill.first_action_target,
        "first_action_parameters": skill.first_action_parameters,
        "first_valid_state": skill.first_valid_state,
    }


if __name__ == "__main__":
    raise SystemExit(main())
