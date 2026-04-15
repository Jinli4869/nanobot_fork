"""
opengui.skills.extractor
~~~~~~~~~~~~~~~~~~~~~~~~
LLM-driven skill extraction from recorded trajectories.

Handles both successful and failed trajectories:
- **Success**: Full trace → generalized reusable skill with parameterized steps.
- **Failure**: Reliable prefix up to the failure point + one corrective action.

Each extracted step includes a ``valid_state`` description used by the executor
to verify screen state before execution.

Screenshots attached to trajectory steps are forwarded to the LLM as vision
content blocks, giving the model direct visual context for deduplication and
action correction.  Token usage is accumulated across calls and exposed via
:attr:`SkillExtractor.total_usage`.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from opengui.interfaces import LLMProvider
from opengui.skills.data import Skill, SkillStep
from opengui.skills.normalization import normalize_app_identifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction prompts
# ---------------------------------------------------------------------------

_SUCCESS_PROMPT = """\
You are a GUI automation expert. Given the following trajectory of a \
**successful** GUI task, extract a reusable skill.

# Trajectory Format
The trajectory below may contain two phases:
- **skill_phase**: A previously-learned skill that was executed. Each step shows the \
skill's intended action and whether it succeeded. If a step has \
``subgoal_recovery_attempts``, those are the visual-verification sub-steps the executor \
tried before concluding the ``valid_state`` was not reached.
- **agent_phase**: Free agent steps taken after the skill completed or partially succeeded.

Synthesize the BEST reusable action sequence from the combined context of both phases. \
Understand what the skill intended, how/why it failed, and how the agent corrected it.

# Trajectory
{trajectory}

# Core principle: NAVIGATIONAL PREFIX
Extract the **shortest, most generic** action sequence — a "navigational \
prefix" that reaches the target screen and fills in core inputs, then STOPS.

- The skill is a REUSABLE PREFIX, not a complete task. An autonomous agent \
will take over after the skill finishes and handle any remaining steps \
(saving, adjusting options, confirming dialogs) based on the specific task.
- STOP after the last core input action (e.g. after typing text into a field). \
Do NOT include:
  - Confirmation/save buttons (Done, Save, OK, Submit) — the agent decides \
when and whether to confirm.
  - Fine-grained widget manipulation (date/time pickers, spinners, sliders, \
dropdown selections) — these vary by task and device.
  - Post-input navigation or cleanup steps.
- Prefer ONE parameterized step over multiple mechanical sub-steps.
- When in doubt, **leave it out**. Fewer steps = more reusable.

# App-opening collapse rule
If the trajectory begins with steps that navigate to and open an app \
(e.g. scrolling the home screen, tapping an app icon, waiting for launch), \
collapse ALL of those steps into a single step:
  {{"action_type": "open_app", "target": "Launch <app>", \
"parameters": {{"text": "<app_package_or_name>"}}, \
"valid_state": "No need to verify", \
"expected_state": "<app> is open and in the foreground"}}
Use the app name from ``observation.foreground_app`` or ``observation.app`` \
in the trajectory data — do NOT guess a display name. \
If the trajectory already starts with the target app open (no launch steps), \
omit the open_app step entirely.

# Instructions
1. Identify the high-level goal and break it into atomic steps.
2. For each step, provide:
   - ``action_type``: the action (tap, input_text, swipe, scroll, etc.)
   - ``target``: UI element description (use ``{{{{param}}}}`` for user-variable values)
   - ``parameters``: dict of action parameters (x, y, text, etc.)
   - ``expected_state``: what the screen should look like AFTER this step succeeds
   - ``valid_state``: what MUST be true on screen BEFORE executing this step
3. Identify user-provided values → ``{{{{param_name}}}}`` placeholders.
4. List preconditions (e.g. "app must be on home screen").
5. If screenshots are provided, use them to:
   - Remove duplicate or redundant steps that interact with the same UI state.
   - Fix target descriptions and coordinates to match visible UI elements.
   - Write accurate ``valid_state`` descriptions based on what is actually on screen.
6. If trajectory steps include ``observation.foreground_app`` or ``observation.app``,
   treat that observed foreground app as the strongest app identity signal.
   Prefer the observed package/app over guessed display names when filling ``app``.
7. Return ONLY a JSON object (no markdown fences):

{{
  "name": "short_snake_case_name",
  "description": "One-line human description",
  "app": "app_package_or_name",
  "platform": "android|macos|linux|windows",
  "parameters": ["param1", "param2"],
  "preconditions": ["precondition1"],
  "steps": [
    {{
      "action_type": "tap|input_text|swipe|...",
      "target": "description, may contain {{{{param}}}}",
      "parameters": {{}},
      "expected_state": "state after step",
      "valid_state": "required state before step",
      "fixed": true
    }}
  ]
}}

## fixed field guidelines
- ``open_app`` MUST always have ``"fixed": true``.
- Set ``"fixed": true`` for: navigation taps on static/structural UI elements \
(menu items, nav bars, fixed toolbar buttons), system actions (back, home, enter), \
any step whose target UI position is stable across repeated runs.
- Set ``"fixed": false`` for: taps on search results or dynamic list items \
(position varies by content), ``input_text`` with user-variable content, \
scrolls/swipes whose extent depends on current screen state, any step where \
the target element location may differ on re-execution.
- When ``"fixed": true`` AND the action requires coordinates \
(tap, long_press, double_tap, drag, swipe): copy the exact ``x``, ``y`` \
(and ``x2``, ``y2`` for drag/swipe) values from the corresponding trajectory \
action into ``parameters``. If the trajectory action shows ``"relative": true``, \
include ``"relative": true`` in ``parameters`` as well.
- When ``"fixed": true`` for ``input_text``: include the concrete ``text`` value \
in ``parameters``.
- When ``"fixed": false``: omit ``x``/``y`` from ``parameters``; use \
``{{{{param}}}}`` placeholders for user-variable text values.

## valid_state guidelines
- For app launch / wait actions: "No need to verify"
- For tap actions: "the target button/element is visible and clickable"
- For input_text: "text input field is visible and focused"
- For scroll/swipe: "content area is scrollable and visible"
- Be specific about which UI element should be visible.

## Quality checks
- The ``description`` field MUST accurately reflect what the steps actually do. \
Do NOT describe steps that are not present (e.g., do not say "from the hot feed" \
if no step navigates to a hot/trending tab).
- Do NOT include error-recovery language (correction, fix, retry, loop) in the \
description for successful trajectories.
- If the trajectory shows the agent undoing a previous action (e.g., pressing Back), \
exclude both the undone action AND the Back action from the skill.
"""

_FAILURE_PROMPT = """\
You are a GUI automation expert. Given the following trajectory of a \
**failed** GUI task, extract a partial skill from the reliable prefix \
(actions before the failure) plus one corrective action.

# Trajectory Format
The trajectory below may contain two phases:
- **skill_phase**: A previously-learned skill that was executed. Each step shows the \
skill's intended action and whether it succeeded. If a step has \
``subgoal_recovery_attempts``, those are the visual-verification sub-steps the executor \
tried before concluding the ``valid_state`` was not reached.
- **agent_phase**: Free agent steps taken after the skill completed or partially succeeded.

Synthesize the BEST reusable action sequence from the combined context of both phases. \
Understand what the skill intended, how/why it failed, and how the agent corrected it.

# Trajectory
{trajectory}

# Core principle: NAVIGATIONAL PREFIX
Even for failed trajectories, extract only the **shortest, most generic** \
reliable prefix — the minimal navigation + input steps that succeeded.

- The skill is a REUSABLE PREFIX. An autonomous agent will take over after \
the skill finishes to handle remaining steps and avoid the original failure.
- Keep only essential navigation and core input steps from the reliable prefix. \
Do NOT include:
  - Confirmation/save buttons (Done, Save, OK, Submit).
  - Fine-grained widget manipulation (date/time pickers, spinners, sliders).
  - Post-input navigation or cleanup steps.
- Prefer ONE parameterized step over multiple mechanical sub-steps.
- The corrective action should describe WHAT went wrong, not replay the \
failed mechanical steps.
- When in doubt, **leave it out**. Fewer steps = more reusable.

# App-opening collapse rule
If the trajectory begins with steps that navigate to and open an app \
(e.g. scrolling the home screen, tapping an app icon, waiting for launch), \
collapse ALL of those steps into a single step:
  {{"action_type": "open_app", "target": "Launch <app>", \
"parameters": {{"text": "<app_package_or_name>"}}, \
"valid_state": "No need to verify", \
"expected_state": "<app> is open and in the foreground"}}
Use the app name from ``observation.foreground_app`` or ``observation.app`` \
in the trajectory data — do NOT guess a display name. \
If the trajectory already starts with the target app open (no launch steps), \
omit the open_app step entirely.

# Failure handling rules
- Keep ONLY the reliable actions that executed successfully before the failure.
- Append exactly ONE corrective action at the end describing what should be \
done differently to avoid the failure.
- The corrective action's ``target`` must describe the correction.
- Mark the corrective action with ``"is_corrective": true`` in parameters.

# Instructions
Same as success extraction, but:
1. Only include steps up to (not including) the failure point.
2. Add one corrective step at the end.
3. Set description to explain what went wrong and the correction.
4. Each step MUST have ``valid_state`` (pre-execution state requirement).
5. If screenshots are provided, use them to:
   - Identify the exact point of failure from visual evidence.
   - Write an accurate corrective action based on what the screen showed.
6. If trajectory steps include ``observation.foreground_app`` or ``observation.app``,
   treat that observed foreground app as the strongest app identity signal.
   Prefer the observed package/app over guessed display names when filling ``app``.

Return ONLY a JSON object (no markdown fences):

{{
  "name": "short_snake_case_name",
  "description": "What went wrong + correction",
  "app": "app_package_or_name",
  "platform": "android|macos|linux|windows",
  "parameters": ["param1"],
  "preconditions": ["precondition1"],
  "steps": [
    {{
      "action_type": "tap|input_text|...",
      "target": "description",
      "parameters": {{}},
      "expected_state": "state after step",
      "valid_state": "required state before step",
      "fixed": true
    }}
  ]
}}

## fixed field guidelines
Same rules as above: ``open_app`` is always ``fixed: true``; \
static navigation taps include concrete ``x``/``y`` from the trajectory; \
dynamic or user-variable steps use ``fixed: false`` with ``{{{{param}}}}`` \
placeholders and no coordinates.
"""

# Max screenshots forwarded to the LLM per extraction call.
_DEFAULT_MAX_SCREENSHOTS = 10


class SkillExtractor:
    """Extract reusable skills from trajectory JSONL files via LLM.

    Supports both successful and failed trajectories.

    Parameters
    ----------
    llm:
        An :class:`~opengui.interfaces.LLMProvider` implementation.
    include_screenshots:
        When ``True`` (default), screenshot files referenced in trajectory
        steps are encoded and forwarded to the LLM as vision content blocks.
        Falls back to text-only if no screenshots are found or if the provider
        does not support vision (the retry logic in the provider handles that).
    max_screenshots:
        Maximum number of screenshots to include in a single extraction call.
        Defaults to ``10``.  Steps are sampled uniformly when the trajectory
        is longer than this limit.
    """

    def __init__(
        self,
        llm: LLMProvider,
        *,
        include_screenshots: bool = True,
        max_screenshots: int = _DEFAULT_MAX_SCREENSHOTS,
    ) -> None:
        self._llm = llm
        self._include_screenshots = include_screenshots
        self._max_screenshots = max_screenshots
        self._total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    # ------------------------------------------------------------------
    # Public token-usage API
    # ------------------------------------------------------------------

    @property
    def total_usage(self) -> dict[str, int]:
        """Accumulated token usage across all extraction calls (read-only copy)."""
        return dict(self._total_usage)

    def reset_usage(self) -> None:
        """Reset the accumulated token counters to zero."""
        self._total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # ------------------------------------------------------------------
    # Public extraction API
    # ------------------------------------------------------------------

    async def extract_from_file(
        self,
        trajectory_path: Path,
        *,
        is_success: bool = True,
    ) -> Skill | None:
        """Read a trajectory JSONL and extract a skill.

        Parameters
        ----------
        trajectory_path:
            Path to a ``.jsonl`` trajectory file.
        is_success:
            Whether the trajectory represents a successful or failed task.
        """
        if not trajectory_path.exists():
            logger.warning("Trajectory file not found: %s", trajectory_path)
            return None

        lines = trajectory_path.read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(line) for line in lines if line.strip()]

        # Check outcome from result event if available
        result_events = [e for e in events if e.get("type") == "result"]
        if result_events:
            outcome = result_events[-1].get("success", is_success)
            is_success = bool(outcome)

        # Build rich trajectory including skill, subgoal, and agent phases
        trajectory, screenshot_events = _build_full_trajectory(events)

        agent_steps = [e for e in events if e.get("type") == "step"]
        skill_steps = [e for e in events if e.get("type") == "skill_step"]
        if len(agent_steps) + len(skill_steps) < 1:
            logger.info(
                "Trajectory too short (%d agent steps, %d skill steps)",
                len(agent_steps), len(skill_steps),
            )
            return None

        return await self._extract(trajectory, screenshot_events, is_success=is_success)

    async def extract_from_steps(
        self,
        steps: list[dict[str, Any]],
        *,
        is_success: bool = True,
    ) -> Skill | None:
        """Extract a skill from pre-parsed agent step dicts (backward-compatible)."""
        if len(steps) < 2:
            return None
        trajectory: dict[str, Any] = {"agent_phase": steps}
        screenshot_events = [s for s in steps if s.get("screenshot_path")]
        return await self._extract(trajectory, screenshot_events, is_success=is_success)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _extract(
        self,
        trajectory: dict[str, Any],
        screenshot_events: list[dict[str, Any]],
        *,
        is_success: bool,
    ) -> Skill | None:
        trajectory_text = json.dumps(trajectory, ensure_ascii=False, indent=2)
        prompt_template = _SUCCESS_PROMPT if is_success else _FAILURE_PROMPT
        prompt = prompt_template.format(trajectory=trajectory_text)

        messages = self._build_messages(prompt, screenshot_events)
        response = await self._llm.chat(messages)

        self._accumulate_usage(response.usage)
        skill = self._parse_response(response.content)
        if skill is not None and not _passes_quality_check(skill, is_success):
            return None
        return skill

    def _build_messages(
        self,
        prompt: str,
        screenshot_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the LLM messages list, attaching screenshots when available.

        ``screenshot_events`` is a flat chronological list of trace events
        (``subgoal_step`` and/or ``step``) that carry a ``screenshot_path``.
        Each screenshot is labelled by its event type so the LLM can map it
        to the correct phase in the trajectory.
        """
        if not self._include_screenshots:
            return [{"role": "user", "content": prompt}]

        # Collect (index, path, label) for events with readable screenshots.
        candidates: list[tuple[int, str, str]] = []
        for i, event in enumerate(screenshot_events):
            path = event.get("screenshot_path")
            if not path or not Path(path).is_file():
                continue
            action_type = (event.get("action") or {}).get("action_type", "?")
            if event.get("type") == "subgoal_step":
                goal_snippet = (event.get("goal") or "")[:70]
                label = (
                    f"Subgoal substep {event.get('substep_index', i)} ({action_type})"
                    f" — goal: {goal_snippet}"
                )
            else:
                label = f"Agent step {event.get('step_index', i)} — {action_type}"
            candidates.append((i, path, label))

        if not candidates:
            return [{"role": "user", "content": prompt}]

        # Uniform sampling when there are more screenshots than the cap.
        selected = _uniform_sample(candidates, self._max_screenshots)

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.append({
            "type": "text",
            "text": (
                f"\n\nThe following {len(selected)} screenshot(s) show the screen state "
                "during execution (subgoal recovery attempts and agent steps). "
                "Use them to verify element descriptions, remove redundant actions, "
                "and write accurate valid_state fields."
            ),
        })

        for _, path, label in selected:
            content.append({"type": "text", "text": f"\n{label}:"})
            b64 = _encode_image_b64(path)
            if b64 is not None:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })

        return [{"role": "user", "content": content}]

    def _accumulate_usage(self, usage: dict[str, int]) -> None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self._total_usage[key] = self._total_usage.get(key, 0) + usage.get(key, 0)

    def _parse_response(self, text: str) -> Skill | None:
        """Parse LLM response JSON into a Skill."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            last_fence = cleaned.rfind("```")
            cleaned = cleaned[first_newline + 1:last_fence].strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse skill extraction response as JSON")
            return None

        try:
            steps = []
            for s in data.get("steps", []):
                action_type = s["action_type"]
                parameters = s.get("parameters", {})
                # open_app is always fixed; otherwise honour the model's choice
                fixed = action_type == "open_app" or bool(s.get("fixed", False))
                # For fixed steps, concrete values live in fixed_values so the
                # executor can bypass grounding; parameters are kept as-is for
                # documentation and template-fallback purposes.
                fixed_values = dict(parameters) if fixed else {}
                steps.append(SkillStep(
                    action_type=action_type,
                    target=s.get("target", ""),
                    parameters=parameters,
                    expected_state=s.get("expected_state"),
                    valid_state=s.get("valid_state"),
                    fixed=fixed,
                    fixed_values=fixed_values,
                ))

            return Skill(
                skill_id=str(uuid.uuid4()),
                name=data["name"],
                description=data.get("description", ""),
                app=normalize_app_identifier(
                    data.get("platform", "unknown"),
                    data.get("app", ""),
                ),
                platform=data.get("platform", "unknown"),
                steps=tuple(steps),
                parameters=tuple(data.get("parameters", ())),
                preconditions=tuple(data.get("preconditions", ())),
            )
        except (KeyError, TypeError) as exc:
            logger.error("Invalid skill data structure: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _build_full_trajectory(
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Convert raw trace events into a structured trajectory dict.

    Returns
    -------
    trajectory:
        A dict with up to two keys:

        * ``skill_phase`` — present when a matched skill was executed.
          Each step embeds any ``subgoal_recovery_attempts`` that were run
          to verify the step's ``valid_state``.
        * ``agent_phase`` — free agent steps taken after the skill finished
          (or directly, when no skill was matched).

    screenshot_events:
        Flat chronological list of events that carry a ``screenshot_path``
        (``subgoal_step`` and ``step`` events only), ready to pass to
        :meth:`SkillExtractor._build_messages`.
    """
    screenshot_events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Skill phase
    # ------------------------------------------------------------------
    skill_exec_start = next(
        (e for e in events if e.get("type") == "skill_execution_start"), None
    )
    skill_phase: dict[str, Any] | None = None

    if skill_exec_start:
        skill_search = next(
            (e for e in events if e.get("type") == "skill_search" and e.get("matched")),
            None,
        )
        skill_exec_result = next(
            (e for e in events if e.get("type") == "skill_execution_result"), None
        )

        # Group subgoal events by goal text so they can be attached to the
        # skill step that triggered them (matched by valid_state == goal).
        subgoal_steps_by_goal: dict[str, list[dict[str, Any]]] = {}
        subgoal_result_by_goal: dict[str, dict[str, Any]] = {}
        for e in events:
            goal = e.get("goal", "")
            if e.get("type") == "subgoal_step":
                subgoal_steps_by_goal.setdefault(goal, []).append(e)
                if e.get("screenshot_path"):
                    screenshot_events.append(e)
            elif e.get("type") == "subgoal_result":
                subgoal_result_by_goal[goal] = e

        enriched_steps: list[dict[str, Any]] = []
        for e in events:
            if e.get("type") != "skill_step":
                continue
            step_info: dict[str, Any] = {
                "step_index": e.get("step_index"),
                "target": e.get("target"),
                "action": e.get("action"),
                "action_summary": e.get("action_summary"),
                "valid_state": e.get("valid_state"),
                "succeeded": bool(e.get("valid_state_check", True)) and not e.get("error"),
                "error": e.get("error"),
            }
            # Attach subgoal recovery attempts for this step if any.
            valid_state = e.get("valid_state") or ""
            if valid_state in subgoal_steps_by_goal:
                step_info["subgoal_recovery_attempts"] = [
                    {
                        "substep_index": s.get("substep_index"),
                        "action": s.get("action"),
                        "action_summary": s.get("action_summary"),
                        "goal_reached": s.get("goal_reached"),
                    }
                    for s in subgoal_steps_by_goal[valid_state]
                ]
                result = subgoal_result_by_goal.get(valid_state)
                if result:
                    if result.get("success"):
                        step_info["subgoal_recovery_outcome"] = "succeeded"
                    else:
                        step_info["subgoal_recovery_outcome"] = (
                            f"failed after {result.get('steps_taken', 0)} attempts"
                            + (f": {result['error']}" if result.get("error") else "")
                        )
            enriched_steps.append(step_info)

        skill_phase = {
            "matched_skill": skill_exec_start.get("skill_name"),
            "match_score": skill_search.get("score") if skill_search else None,
            "steps": enriched_steps,
            "outcome": skill_exec_result.get("execution_summary") if skill_exec_result else None,
        }

    # ------------------------------------------------------------------
    # Agent phase
    # ------------------------------------------------------------------
    agent_steps_raw = [e for e in events if e.get("type") == "step"]
    for e in agent_steps_raw:
        if e.get("screenshot_path"):
            screenshot_events.append(e)

    agent_phase = [
        {
            "step_index": e.get("step_index"),
            "action": e.get("action"),
            "model_output": e.get("model_output"),
            "foreground_app": (e.get("observation") or {}).get("foreground_app"),
        }
        for e in agent_steps_raw
    ]

    # ------------------------------------------------------------------
    # Assemble trajectory
    # ------------------------------------------------------------------
    trajectory: dict[str, Any] = {}
    if skill_phase:
        trajectory["skill_phase"] = skill_phase
    if agent_phase:
        trajectory["agent_phase"] = agent_phase

    return trajectory, screenshot_events


_CORRECTIVE_KEYWORDS = frozenset({
    "correction", "corrective", "fix", "fixed", "loop", "retry",
    "repetitive", "broke", "wrong", "undo",
})


def _passes_quality_check(skill: "Skill", is_success: bool) -> bool:
    """Return ``False`` when the extracted skill is likely low-quality.

    Filters:
    1. Successful trajectories should not produce skills whose description
       contains error-recovery language — that signals the LLM misread the
       trajectory.
    2. Skills with zero non-open_app steps are too trivial to keep.
    """
    desc_lower = skill.description.lower()

    # Filter 1: corrective language in a success-extracted skill
    if is_success:
        for kw in _CORRECTIVE_KEYWORDS:
            if kw in desc_lower:
                logger.info(
                    "Quality filter: rejecting skill %r — corrective keyword %r "
                    "in description of a successful trajectory",
                    skill.name, kw,
                )
                return False

    # Filter 2: trivial skill (only open_app / wait steps)
    substantive = [s for s in skill.steps if s.action_type not in ("open_app", "wait")]
    if not substantive:
        logger.info(
            "Quality filter: rejecting skill %r — no substantive steps",
            skill.name,
        )
        return False

    return True


def _encode_image_b64(path: str) -> str | None:
    """Return base64-encoded PNG of *path* scaled to 1/4 width and height, or ``None`` on error."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
            scaled = img.resize((w // 4, h // 4), Image.LANCZOS)
            buf = io.BytesIO()
            scaled.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        logger.debug("Could not encode screenshot %s: %s", path, exc)
        return None


def _uniform_sample(items: list[Any], n: int) -> list[Any]:
    """Return up to *n* items sampled uniformly from *items*."""
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]
