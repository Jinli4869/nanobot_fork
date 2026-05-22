"""
opengui.skills.reuser
~~~~~~~~~~~~~~~~~~~~~
LLM-gated skill reuse: retrieves top-k candidates from FlatSkillLibrary,
then asks the LLM to choose the best reusable prefix, including optional
truncation.

Selection pipeline:
1. Build a lightweight prompt with the task description and top-k skill summaries.
2. Call the LLM once and parse ``selected_skill_id`` plus optional ``end_step``.
3. Return the selected skill prefix; fall back to None if no candidate is suitable.

Fail-closed: any LLM call or parse error returns None, so the GUI agent loop is
the safe fallback.
"""

from __future__ import annotations

import json
import logging
import re
import time
import typing
from dataclasses import replace
from typing import Any

if typing.TYPE_CHECKING:
    from opengui.interfaces import LLMProvider
    from opengui.trajectory.recorder import TrajectoryRecorder

logger = logging.getLogger(__name__)


_SELECTION_PROMPT = """\
You choose whether one stored GUI skill can serve as a useful action prefix for a new task.

Task: {task}

Candidates:
{candidates}

Rules:
- Return null when no candidate is clearly useful for this task.
- Prefer the shortest prefix that moves toward the task without doing irrelevant later actions.
- end_step is 1-based and inclusive. Use the full step count only when every step is relevant.
- If the task has no app-specific requirement, return null to avoid false positives.
- Do not choose a candidate only because it shares generic words such as open, search, tap, or settings.

Reply with JSON only:
{{"selected_skill_id": "skill-id-or-null", "end_step": 1, "reason": "short reason"}}
"""

_JUDGE_PROMPT = """\
You are deciding whether a stored GUI skill can serve as a **complete or preceding** \
action sequence for a new task.

Task: {task}

Skill:
  Name: {name}
  App:  {app}
  Description: {description}
  Steps:
{steps}

Can this skill fully complete, or be a valid preceding sub-sequence for, the task above?
If the task doesn't contain any app-specific requirement, return false to avoid false positives.

Reply with JSON only: {{"applicable": true/false}}
"""


class SkillReuser:
    """Retrieve top-k skill candidates and gate execution with an LLM applicability check.

    Parameters
    ----------
    llm:
        The same :class:`~opengui.interfaces.LLMProvider` used by the main agent.
    top_k:
        Number of candidates to fetch from the library before LLM filtering.
    auto_accept_threshold:
        Deprecated compatibility argument. Candidate selection always goes
        through one LLM top-k selection call.
    threshold:
        Minimum hybrid retrieval score; candidates below this are skipped before
        any LLM call is made.
    """

    def __init__(
        self,
        llm: LLMProvider,
        top_k: int = 5,
        threshold: float = 0.35,
        auto_accept_threshold: float = 0.98,
    ) -> None:
        self._llm = llm
        self._top_k = top_k
        self._threshold = threshold
        self._auto_accept_threshold = auto_accept_threshold
        self._usage_accum: dict[str, int] = {}
        self._last_selection_timing: dict[str, float] = {}

    def drain_usage(self) -> dict[str, int]:
        """Return accumulated token usage since the last drain and reset the counter."""
        usage = dict(self._usage_accum)
        self._usage_accum.clear()
        return usage

    async def find(
        self,
        task: str,
        library: Any,
        platform: str | None = None,
        *,
        trajectory_recorder: TrajectoryRecorder | None = None,
    ) -> tuple[Any, float] | None:
        """Return an LLM-selected ``(skill_prefix, score)`` or ``None``.

        Fetches up to *top_k* candidates from *library*, pre-filters by *threshold*,
        then asks the LLM to pick one candidate and optional prefix length.
        """
        results: list[tuple[Any, float]] = await library.search(
            task, platform=platform, top_k=self._top_k
        )
        candidates = [(skill, score) for skill, score in results if score >= self._threshold]

        if not candidates:
            _record(trajectory_recorder, "skill_search",
                    source="reuser", matched=False, reason="no_candidates",
                    threshold=self._threshold)
            return None

        auto_selected = _auto_accept_candidate(
            task,
            candidates,
            threshold=self._auto_accept_threshold,
        )
        if auto_selected is not None:
            skill, score = auto_selected
            _record(trajectory_recorder, "skill_search",
                    source="reuser", matched=True,
                    skill_id=skill.skill_id,
                    skill_name=skill.name,
                    score=round(score, 4),
                    reason="auto_accept")
            return skill, score

        selection = await self._select(task, candidates)
        selection_timing = dict(self._last_selection_timing)
        if selection is None:
            _record(trajectory_recorder, "skill_search",
                    source="reuser", matched=False, reason="all_rejected",
                    selection_duration_s=selection_timing.get("selection_duration_s"),
                    llm_latency_s=selection_timing.get("llm_latency_s"),
                    candidates_checked=len(candidates))
            return None

        selected_skill_id, end_step, reason = selection
        candidate_by_id = {skill.skill_id: (skill, score) for skill, score in candidates}
        selected = candidate_by_id.get(selected_skill_id)
        if selected is None:
            _record(trajectory_recorder, "skill_search",
                    source="reuser", matched=False, reason="invalid_selection",
                    selected_skill_id=selected_skill_id,
                    candidates_checked=len(candidates))
            return None

        skill, score = selected
        step_count = len(getattr(skill, "steps", ()) or ())
        if step_count > 0:
            end_step = max(1, min(end_step or step_count, step_count))
        else:
            end_step = 0
        selected_skill = skill
        if 0 < end_step < step_count:
            selected_skill = replace(skill, steps=skill.steps[:end_step])

        _record(trajectory_recorder, "skill_selection",
                source="reuser",
                candidate_count=len(candidates),
                selected_skill_id=skill.skill_id,
                selected_skill_name=skill.name,
                score=round(score, 4),
                end_step=end_step,
                total_steps=step_count,
                truncated=end_step < step_count,
                selection_duration_s=selection_timing.get("selection_duration_s"),
                llm_latency_s=selection_timing.get("llm_latency_s"),
                reason=reason)
        _record(trajectory_recorder, "skill_search",
                source="reuser", matched=True,
                skill_id=skill.skill_id,
                skill_name=skill.name,
                score=round(score, 4),
                end_step=end_step,
                total_steps=step_count,
                selection_duration_s=selection_timing.get("selection_duration_s"),
                llm_latency_s=selection_timing.get("llm_latency_s"))
        return selected_skill, score

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _select(
        self,
        task: str,
        candidates: list[tuple[Any, float]],
    ) -> tuple[str, int | None, str] | None:
        """Ask the LLM to choose one candidate prefix.

        Returns ``(skill_id, end_step, reason)`` or ``None`` on rejection/error.
        """
        prompt = _SELECTION_PROMPT.format(
            task=task,
            candidates=_format_candidates(candidates),
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        self._last_selection_timing = {}
        t0 = time.monotonic()
        try:
            response = await self._llm.chat(messages)
        except Exception as exc:
            self._last_selection_timing = {
                "selection_duration_s": round(time.monotonic() - t0, 3),
            }
            logger.warning(
                "SkillReuser: LLM selection call failed: %s",
                exc,
            )
            return None
        selection_duration = time.monotonic() - t0
        self._last_selection_timing = {
            "selection_duration_s": round(selection_duration, 3),
        }
        latency_s = getattr(response, "latency_s", None)
        if latency_s is not None:
            self._last_selection_timing["llm_latency_s"] = round(float(latency_s), 3)

        for k, v in (response.usage or {}).items():
            self._usage_accum[k] = self._usage_accum.get(k, 0) + v

        result = _parse_selection_response(response.content)
        if result is None:
            legacy_judgment = _parse_legacy_applicable_response(response.content)
            if legacy_judgment is not None:
                return await self._legacy_selection_from_applicable_response(
                    task,
                    candidates,
                    first_candidate_applicable=legacy_judgment,
                )
        logger.debug(
            "SkillReuser: selection=%s (raw=%r)",
            result, response.content[:120],
        )
        return result

    async def _legacy_selection_from_applicable_response(
        self,
        task: str,
        candidates: list[tuple[Any, float]],
        *,
        first_candidate_applicable: bool,
    ) -> tuple[str, int | None, str] | None:
        """Compatibility path for older judge prompts returning applicable."""
        if not candidates:
            return None
        first_skill, _ = candidates[0]
        if first_candidate_applicable:
            return first_skill.skill_id, None, "legacy_applicable"
        for skill, _score in candidates[1:]:
            if await self._judge(task, skill):
                return skill.skill_id, None, "legacy_applicable"
        return None

    async def _judge(self, task: str, skill: Any) -> bool:
        prompt = _JUDGE_PROMPT.format(
            task=task,
            name=skill.name,
            app=skill.app,
            description=skill.description,
            steps=_format_steps(skill),
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        try:
            response = await self._llm.chat(messages)
        except Exception as exc:
            logger.warning(
                "SkillReuser: legacy LLM judge call failed for skill %r: %s",
                skill.name,
                exc,
            )
            return False
        for k, v in (response.usage or {}).items():
            self._usage_accum[k] = self._usage_accum.get(k, 0) + v
        return bool(_parse_legacy_applicable_response(response.content))


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _format_candidates(
    candidates: list[tuple[Any, float]],
) -> str:
    lines: list[str] = []
    for index, (skill, score) in enumerate(candidates, 1):
        parameters = tuple(getattr(skill, "parameters", ()) or ())
        parameter_text = ", ".join(parameters) if parameters else "(none)"
        skill_id = getattr(skill, "skill_id", "")
        lines.extend([
            f"Candidate {index}:",
            f"  skill_id: {skill_id}",
            f"  score: {score:.4f}",
            f"  name: {getattr(skill, 'name', '')}",
            f"  app: {getattr(skill, 'app', '')}",
            f"  description: {getattr(skill, 'description', '')}",
            f"  parameters: {parameter_text}",
            "  steps:",
            _format_steps(skill),
        ])
    return "\n".join(lines)


def _auto_accept_candidate(
    task: str,
    candidates: list[tuple[Any, float]],
    *,
    threshold: float,
) -> tuple[Any, float] | None:
    del task
    for skill, score in candidates:
        if score < threshold:
            continue
        return skill, score
    return None


def _format_steps(skill: Any) -> str:
    """Return a compact step summary (action_type + target, no coordinates)."""
    if not skill.steps:
        return "    (no steps recorded)"
    lines = []
    for i, step in enumerate(skill.steps, 1):
        target = step.target or "(no target)"
        lines.append(f"    {i}. {step.action_type} → {target}")
    return "\n".join(lines)


def _parse_selection_response(text: str) -> tuple[str, int | None, str] | None:
    """Parse LLM response into a selected skill id and optional prefix length.

    Tries structured JSON only. Unclear answers fail closed.
    """
    text = text.strip()
    match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
    if match is None:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    raw_id = obj.get("selected_skill_id")
    if raw_id is None:
        return None
    skill_id = str(raw_id).strip()
    if not skill_id or skill_id.lower() in {"none", "null", "false"}:
        return None
    raw_end_step = obj.get("end_step")
    end_step: int | None = None
    if raw_end_step is not None:
        try:
            end_step = int(raw_end_step)
        except (TypeError, ValueError):
            end_step = None
    reason = str(obj.get("reason") or "").strip()
    return skill_id, end_step, reason


def _parse_legacy_applicable_response(text: str) -> bool | None:
    text = text.strip()
    match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            obj = {}
        if "applicable" in obj:
            val = obj.get("applicable")
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.strip().lower() in ("true", "yes")
    lowered = text.lower()
    if '"applicable": true' in lowered:
        return True
    if '"applicable": false' in lowered:
        return False
    return None


def _record(
    recorder: TrajectoryRecorder | None,
    event: str,
    **kwargs: Any,
) -> None:
    """Fire a trajectory event when a recorder is available."""
    if recorder is None:
        return
    recorder.record_event(event, **kwargs)
