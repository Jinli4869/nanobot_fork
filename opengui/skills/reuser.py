"""
opengui.skills.reuser
~~~~~~~~~~~~~~~~~~~~~
LLM-gated skill reuse: retrieves top-k candidates from SkillLibrary,
then serially judges each (score-descending) until one is approved by the LLM.

Judgment pipeline per candidate:
1. Build a lightweight prompt with the task description, skill name/app/description,
   and a step summary (action_type + target only, no coordinates).
2. Call the LLM and parse the JSON response for ``{"applicable": true/false}``.
3. Return the first approved (skill, score) pair; fall back to None if all fail.

Fail-closed: any LLM call error causes that candidate to be skipped (returns False),
so the GUI agent loop is the safe fallback.
"""

from __future__ import annotations

import json
import logging
import re
import typing
from typing import Any

if typing.TYPE_CHECKING:
    from opengui.interfaces import LLMProvider
    from opengui.trajectory.recorder import TrajectoryRecorder

logger = logging.getLogger(__name__)


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

Reply with JSON only: {{"applicable": true/false, "reason": "one line"}}
"""


class SkillReuser:
    """Retrieve top-k skill candidates and gate execution with an LLM applicability check.

    Parameters
    ----------
    llm:
        The same :class:`~opengui.interfaces.LLMProvider` used by the main agent.
    top_k:
        Number of candidates to fetch from the library before LLM filtering.
    threshold:
        Minimum hybrid retrieval score; candidates below this are skipped before
        any LLM call is made.
    """

    def __init__(
        self,
        llm: LLMProvider,
        top_k: int = 5,
        threshold: float = 0.35,
    ) -> None:
        self._llm = llm
        self._top_k = top_k
        self._threshold = threshold
        self._usage_accum: dict[str, int] = {}

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
        """Return the first LLM-approved ``(skill, score)`` or ``None``.

        Fetches up to *top_k* candidates from *library*, pre-filters by *threshold*,
        then serially calls the LLM (highest score first) until one is approved.
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

        for skill, score in candidates:
            applicable = await self._judge(task, skill)
            _record(trajectory_recorder, "skill_judge",
                    source="reuser",
                    skill_id=skill.skill_id,
                    skill_name=skill.name,
                    score=round(score, 4),
                    applicable=applicable)
            if applicable:
                _record(trajectory_recorder, "skill_search",
                        source="reuser", matched=True,
                        skill_id=skill.skill_id,
                        skill_name=skill.name,
                        score=round(score, 4))
                return skill, score

        _record(trajectory_recorder, "skill_search",
                source="reuser", matched=False, reason="all_rejected",
                candidates_checked=len(candidates))
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _judge(self, task: str, skill: Any) -> bool:
        """Ask the LLM whether *skill* is applicable for *task*.

        Returns ``True`` if the LLM says applicable, ``False`` on any error
        (fail-closed: when uncertain, skip the skill and try the next one).
        """
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
                "SkillReuser: LLM judge call failed for skill %r: %s",
                skill.name, exc,
            )
            return False

        for k, v in (response.usage or {}).items():
            self._usage_accum[k] = self._usage_accum.get(k, 0) + v

        result = _parse_judge_response(response.content)
        logger.debug(
            "SkillReuser: skill=%r applicable=%s (raw=%r)",
            skill.name, result, response.content[:120],
        )
        return result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _format_steps(skill: Any) -> str:
    """Return a compact step summary (action_type + target, no coordinates)."""
    if not skill.steps:
        return "    (no steps recorded)"
    lines = []
    for i, step in enumerate(skill.steps, 1):
        target = step.target or "(no target)"
        lines.append(f"    {i}. {step.action_type} → {target}")
    return "\n".join(lines)


def _parse_judge_response(text: str) -> bool:
    """Parse LLM response into a boolean applicability verdict.

    Tries structured JSON first; falls back to keyword scan.
    """
    text = text.strip()
    match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            val = obj.get("applicable")
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.strip().lower() in ("true", "yes")
        except json.JSONDecodeError:
            pass
    lowered = text.lower()
    return '"applicable": true' in lowered or (
        "applicable" not in lowered and "true" in lowered
    )


def _record(
    recorder: TrajectoryRecorder | None,
    event: str,
    **kwargs: Any,
) -> None:
    """Fire a trajectory event when a recorder is available."""
    if recorder is None:
        return
    recorder.record_event(event, **kwargs)
