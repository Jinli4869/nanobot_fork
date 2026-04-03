"""
opengui.skills.shortcut_router
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Phase 29 applicability routing for shortcut candidates.

Public symbols
--------------
ApplicabilityDecision       — frozen dataclass holding routing outcome for one shortcut
ShortcutApplicabilityRouter — evaluates a shortcut's preconditions against a screenshot
filter_candidates_by_context — post-retrieval platform + app filter for candidate lists

Design notes (Phase 29)
-----------------------
* ``ApplicabilityDecision`` uses ``outcome: Literal["run", "skip", "fallback"]`` so
  callers can match exhaustively without comparing magic strings.
* ``ShortcutApplicabilityRouter`` accepts any ``ConditionEvaluator`` (including the
  phase-25 LLM-backed one) or defaults to ``_AlwaysPassEvaluator`` for dry-run and
  test scenarios where no device or LLM is available.
* ``filter_candidates_by_context`` is a pure function with no side effects — it never
  modifies the input list, preserves original score ordering, and falls back to
  platform-only results when the app filter returns empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.shortcut import ShortcutSkill, StateDescriptor

if TYPE_CHECKING:
    from opengui.skills.shortcut_store import SkillSearchResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ConditionEvaluator — re-export from multi_layer_executor for convenience
# ---------------------------------------------------------------------------
# We import the Protocol lazily to avoid circular imports at module load time.
# Callers that need the Protocol type directly should import from
# opengui.skills.multi_layer_executor.


# ---------------------------------------------------------------------------
# ApplicabilityDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApplicabilityDecision:
    """Routing decision for a single shortcut candidate.

    Attributes
    ----------
    outcome:
        ``"run"`` — all preconditions satisfied, shortcut may be executed.
        ``"skip"`` — at least one precondition failed; shortcut is inapplicable.
        ``"fallback"`` — evaluation raised an unexpected exception; caller should
        treat the shortcut as if it has no preconditions and decide separately.
    shortcut_id:
        The ``skill_id`` of the evaluated :class:`~opengui.skills.shortcut.ShortcutSkill`.
    reason:
        Human-readable description of why this outcome was produced.
    score:
        Optional retrieval score passed through for callers that need it.
    failed_condition:
        The first ``StateDescriptor`` that caused a ``"skip"`` outcome, or ``None``.
    """

    outcome: Literal["run", "skip", "fallback"]
    shortcut_id: str | None = None
    reason: str = ""
    score: float | None = None
    failed_condition: StateDescriptor | None = None


# ---------------------------------------------------------------------------
# _AlwaysPassEvaluator (private default)
# ---------------------------------------------------------------------------


class _AlwaysPassEvaluator:
    """Trivial ``ConditionEvaluator`` that approves every condition.

    Used as the default when no real evaluator is injected — enables dry-run
    and test scenarios where a live device or LLM is unavailable.
    """

    async def evaluate(self, condition: StateDescriptor, screenshot: Path) -> bool:  # noqa: ARG002
        return True


# ---------------------------------------------------------------------------
# ShortcutApplicabilityRouter
# ---------------------------------------------------------------------------


class ShortcutApplicabilityRouter:
    """Evaluate a shortcut candidate's preconditions against the current screen.

    Parameters
    ----------
    condition_evaluator:
        Any object with an ``async def evaluate(condition, screenshot) -> bool``
        method (i.e., conforming to ``ConditionEvaluator`` from
        ``opengui.skills.multi_layer_executor``).  Defaults to
        ``_AlwaysPassEvaluator`` when ``None`` is passed.
    """

    def __init__(self, condition_evaluator: object | None = None) -> None:
        self._evaluator = (
            condition_evaluator if condition_evaluator is not None else _AlwaysPassEvaluator()
        )

    async def evaluate(
        self, candidate: ShortcutSkill, screenshot_path: Path
    ) -> ApplicabilityDecision:
        """Evaluate all preconditions of *candidate* against *screenshot_path*.

        Returns
        -------
        ApplicabilityDecision
            ``outcome="run"`` if every precondition passes.
            ``outcome="skip"`` with ``failed_condition`` set if any fails.
            ``outcome="fallback"`` with the exception class in ``reason`` on error.
        """
        try:
            for condition in candidate.preconditions:
                passed = await self._evaluator.evaluate(condition, screenshot_path)
                if not passed:
                    return ApplicabilityDecision(
                        outcome="skip",
                        shortcut_id=candidate.skill_id,
                        reason=f"precondition_failed:{condition.kind}:{condition.value}",
                        failed_condition=condition,
                    )
        except Exception as exc:  # noqa: BLE001
            return ApplicabilityDecision(
                outcome="fallback",
                shortcut_id=candidate.skill_id,
                reason=f"evaluation_error:{type(exc).__name__}",
            )

        return ApplicabilityDecision(
            outcome="run",
            shortcut_id=candidate.skill_id,
            reason="all_preconditions_satisfied",
        )


# ---------------------------------------------------------------------------
# filter_candidates_by_context
# ---------------------------------------------------------------------------


def filter_candidates_by_context(
    candidates: list[SkillSearchResult],
    *,
    platform: str,
    app_hint: str | None,
) -> list[SkillSearchResult]:
    """Filter a list of search results by platform and optional app context.

    Algorithm
    ---------
    1. Filter by ``result.skill.platform == platform`` always.
    2. If *app_hint* is truthy, normalize it via ``normalize_app_identifier``.
       If the normalized value is not ``"unknown"``, further filter to results
       whose ``result.skill.app == normalized``.  If that produces an empty list,
       fall back to the platform-only filtered list (step 1 result).
    3. Return the filtered list preserving original score ordering.

    Parameters
    ----------
    candidates:
        Search results to filter (already score-ordered).
    platform:
        Target platform string (e.g. ``"android"``, ``"ios"``).
    app_hint:
        Foreground app name or identifier hint, or ``None`` / ``""`` to skip
        app-level filtering.
    """
    # Step 1: always filter by platform
    platform_filtered = [r for r in candidates if r.skill.platform == platform]

    # Step 2: optionally further filter by normalized app
    if not app_hint:
        return platform_filtered

    normalized = normalize_app_identifier(platform, app_hint)
    if normalized == "unknown":
        # Cannot reliably resolve app hint — return platform-only results
        return platform_filtered

    app_filtered = [r for r in platform_filtered if r.skill.app == normalized]

    # Fall back to platform-only if app filter yields nothing
    return app_filtered if app_filtered else platform_filtered
