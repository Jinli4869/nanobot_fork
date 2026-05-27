"""LLM extraction of flat Python GUI skills from code-formatted trajectories."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from opengui.interfaces import LLMProvider
from opengui.skills.data import Skill
from opengui.skills.flat import CODE_HEADER, compile_flat_skills
from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.trajectory_codegen import (
    CodeStep,
    CodegenResult,
    apply_contract_constraints_from_codegen,
    apply_focused_contracts_from_codegen,
    codegen_to_extraction_text,
    codegen_trajectory,
)

logger = logging.getLogger(__name__)

_UNKNOWN_APP_IDS = {"", "unknown", "app-package-or-name"}

_EXTRACT_PROMPT = """\
Extract a reusable GUI skill as Python code from this trajectory.

Target format:
{code_header}

@skill(app="{app}", platform="{platform}", name="short_name", description="One sentence summary")
async def skill_name(device, param1, param2):
    await action("open_app", target="...", fixed=True, fixed_values={{"text": "...[app_name_here]..."}},
                 valid_state="No need to verify")
    await action("tap", target="target element", fixed=True,
                 fixed_values={{"x": 540, "y": 960}},
                 valid_state="target is visible and clickable",
                 state_contract=C(app="...[app_package]...", required=[R(resource_id="target_id", visible=True)]))
    await action("input_text", target="{{{{param1}}}}",
                 valid_state="input field is focused")

Rules:
- Extract ONE cohesive skill that covers the core action sequence. Do NOT split into multiple tiny @skill functions.
- fixed=true + fixed_values: static UI (nav bars, toolbar, system actions, open_app). Copy exact x/y/text from the trajectory step params shown after "|".
- fixed=false: dynamic content (search results, variable input). Use {{{{param}}}} placeholders, omit fixed_values.
- Collapse all app-launch steps into ONE open_app as the first step.
- valid_state: specific present-tense, e.g. "search field is visible and enabled".
- state_contract: use C()/R() with resource_id/content_desc/class from the step's "control:" field. Use class_ when writing a class selector in R(). Omit state_contract if step has no control info or selector is dynamic.
- Drop duplicate/redundant clicks, exploratory taps, and pointless scrolls.
- Transient popups (ads, permissions, consent): keep as optional=True step. Executor skips them when absent.
- Omit app-native confirmation buttons (Done/Save/Submit/App Initial) — the agent handles those after the skill.
- description: MUST be generic and reusable. Mention app name, capability, and broad feature-level route only. Use parameter roles like query, media item, contact, or item. NEVER include literal values/entities, exact titles/names, or narrow qualifiers such as specific, official, first result, or top result. Avoid tap-by-tap UI actions.
{failure_note}
## Trajectory
{code_text}

Output ONLY the Python code. No markdown fences, no JSON object, no explanation.
"""

_FAILURE_NOTE = "FAILURE trajectory: only include steps that succeeded before the failure point."


class SkillExtractor:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm
        self._total_usage: dict[str, int] = {}

    @property
    def total_usage(self) -> dict[str, int]:
        return dict(self._total_usage)

    # -- public API --

    async def extract_from_file(self, trajectory_path: Path, *, is_success: bool = True) -> Skill | None:
        skills = await self.extract_from_file_multi(trajectory_path, is_success=is_success)
        return skills[0] if skills else None

    async def extract_from_file_multi(self, trajectory_path: Path, *, is_success: bool = True) -> list[Skill]:
        result = codegen_trajectory(trajectory_path)
        if result is None or not result.steps:
            _write_log(trajectory_path, "no_candidate", {"reason": "empty_codegen"})
            return []
        skills = await self._extract_all(result, is_success)
        if not skills:
            _write_log(trajectory_path, "no_candidate", {"reason": "compile_returned_none"})
            return []
        _write_log(trajectory_path, "compiled", {
            "skill_ids": [s.skill_id for s in skills],
            "names": [s.name for s in skills],
        })
        return skills

    async def extract_from_steps(self, steps: list[dict[str, Any]], *, is_success: bool = True) -> Skill | None:
        skills = await self.extract_from_steps_multi(steps, is_success=is_success)
        return skills[0] if skills else None

    async def extract_from_steps_multi(self, steps: list[dict[str, Any]], *, is_success: bool = True) -> list[Skill]:
        result = _codegen_from_step_dicts(steps)
        if result is None or not result.steps:
            return []
        return await self._extract_all(result, is_success)

    # -- internal --

    async def _extract_all(self, result: CodegenResult, is_success: bool) -> list[Skill]:
        code_text = codegen_to_extraction_text(result)
        prompt = _EXTRACT_PROMPT.format(
            code_header=CODE_HEADER,
            app=result.app,
            platform=result.platform,
            failure_note=_FAILURE_NOTE if not is_success else "",
            code_text=code_text,
        )
        response = await self._llm.chat(_build_messages(prompt, result.screenshots_b64))
        self._accumulate_usage(response.usage)
        skills = self._compile_all(response.content, result)
        return [
            apply_contract_constraints_from_codegen(
                apply_focused_contracts_from_codegen(skill, result),
                result,
            )
            for skill in skills
        ]

    def _compile_all(self, text: str, result: CodegenResult) -> list[Skill]:
        source = _clean_code_block(text)
        compiled = compile_flat_skills(source)
        if compiled.errors:
            logger.warning("Flat skill compile failed: %s", compiled.errors)
            return []
        skills: list[Skill] = []
        for skill in compiled.skills:
            normalized = replace(
                skill,
                app=normalize_app_identifier(skill.platform, skill.app),
                description=_generalize_skill_description(skill.description),
                steps=tuple(replace(step, expected_state=None) for step in skill.steps),
            )
            resolved = _resolve_skill_app(normalized, result)
            if resolved is None:
                logger.warning("Reject extracted skill %s: app is unknown", skill.name)
                continue
            skills.append(resolved)
        return skills

    def _accumulate_usage(self, usage: dict[str, int]) -> None:
        for key, value in usage.items():
            self._total_usage[key] = self._total_usage.get(key, 0) + int(value)


# -- helpers --

def _build_messages(prompt: str, screenshots_b64: list[str]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for b64 in screenshots_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    return [{"role": "user", "content": content}]


def _clean_code_block(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    if not t.startswith("from opengui"):
        t = f"{CODE_HEADER}\n\n{t}"
    return t.rstrip() + "\n"


def _generalize_skill_description(description: str) -> str:
    text = description.strip()
    replacements = (
        (r"\bspecific\s+", ""),
        (r"\bofficial\s+", ""),
        (r"\b(first|top)\s+search\s+result\b", "matching search result"),
        (r"\b(first|top)\s+result\b", "matching result"),
        (r"\ba\s+(music\s+)?video\s+query\b", "a video by query"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip()


def _resolve_skill_app(skill: Skill, result: CodegenResult) -> Skill | None:
    if not _is_unknown_app(skill.app):
        return skill

    open_app = _first_open_app_text(skill)
    normalized_open_app = normalize_app_identifier(skill.platform, open_app) if open_app else "unknown"
    if not _is_unknown_app(normalized_open_app):
        return replace(skill, app=normalized_open_app)

    fallback_app = normalize_app_identifier(skill.platform, result.app)
    if not _is_unknown_app(fallback_app):
        return replace(skill, app=fallback_app)
    return None


def _first_open_app_text(skill: Skill) -> str:
    for step in skill.steps:
        if step.action_type != "open_app":
            continue
        for source in (step.fixed_values, step.parameters):
            value = source.get("text") if isinstance(source, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        if step.target.strip():
            return step.target.strip()
    return ""


def _is_unknown_app(app: str) -> bool:
    return (app or "").strip().lower() in _UNKNOWN_APP_IDS


def _write_log(trace_path: Path, status: str, detail: Any) -> None:
    (trace_path.parent / "extraction_result.json").write_text(
        json.dumps({"status": status, "trace": str(trace_path), "detail": detail},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _codegen_from_step_dicts(steps: list[dict[str, Any]]) -> CodegenResult | None:
    """Build a minimal CodegenResult from pre-parsed step dicts (for test compat)."""
    if not steps:
        return None
    first = steps[0]
    obs = first.get("observation") or {}
    platform = str(obs.get("platform") or "unknown")
    app = str(obs.get("foreground_app") or obs.get("app") or "")
    task = str(first.get("task") or "")

    code_steps: list[CodeStep] = []
    for i, s in enumerate(steps):
        action = s.get("action") or {}
        action_type = str(action.get("action_type") or "")
        if not app:
            app = str((s.get("observation") or {}).get("foreground_app") or "")
        code_steps.append(CodeStep(
            step_index=i,
            intent=str(s.get("action_intent") or s.get("action_summary") or action_type),
            action_type=action_type,
            action_params={k: action[k] for k in ("x", "y", "x2", "y2", "text", "key", "pixels")
                           if k in action and action[k] is not None},
            control_info="",
            contract_json="",
            screenshot_b64="",
        ))

    return CodegenResult(
        task=task, platform=platform, app=app,
        steps=code_steps, screenshots_b64=[],
    )
