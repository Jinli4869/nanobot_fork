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

# Trajectory
{trajectory}

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
6. Return ONLY a JSON object (no markdown fences):

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
      "valid_state": "required state before step"
    }}
  ]
}}

## valid_state guidelines
- For app launch / wait actions: "No need to verify"
- For tap actions: "the target button/element is visible and clickable"
- For input_text: "text input field is visible and focused"
- For scroll/swipe: "content area is scrollable and visible"
- Be specific about which UI element should be visible.
"""

_FAILURE_PROMPT = """\
You are a GUI automation expert. Given the following trajectory of a \
**failed** GUI task, extract a partial skill from the reliable prefix \
(actions before the failure) plus one corrective action.

# Trajectory
{trajectory}

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
      "valid_state": "required state before step"
    }}
  ]
}}
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

        # Filter to step events
        steps = [e for e in events if e.get("type") == "step"]
        if len(steps) < 2:
            logger.info("Trajectory too short (%d steps)", len(steps))
            return None

        # Check outcome from result event if available
        result_events = [e for e in events if e.get("type") == "result"]
        if result_events:
            outcome = result_events[-1].get("success", is_success)
            is_success = bool(outcome)

        return await self._extract(steps, is_success=is_success)

    async def extract_from_steps(
        self,
        steps: list[dict[str, Any]],
        *,
        is_success: bool = True,
    ) -> Skill | None:
        """Extract a skill from pre-parsed step dicts."""
        if len(steps) < 2:
            return None
        return await self._extract(steps, is_success=is_success)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _extract(
        self,
        steps: list[dict[str, Any]],
        *,
        is_success: bool,
    ) -> Skill | None:
        trajectory_text = json.dumps(steps, ensure_ascii=False, indent=2)
        prompt_template = _SUCCESS_PROMPT if is_success else _FAILURE_PROMPT
        prompt = prompt_template.format(trajectory=trajectory_text)

        messages = self._build_messages(prompt, steps)
        response = await self._llm.chat(messages)

        self._accumulate_usage(response.usage)
        return self._parse_response(response.content)

    def _build_messages(
        self,
        prompt: str,
        steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the LLM messages list, attaching screenshots when available."""
        if not self._include_screenshots:
            return [{"role": "user", "content": prompt}]

        # Collect (step_index, path) pairs for steps that have readable screenshots.
        candidates: list[tuple[int, str]] = []
        for i, step in enumerate(steps):
            path = step.get("screenshot_path")
            if path and Path(path).is_file():
                candidates.append((i, path))

        if not candidates:
            return [{"role": "user", "content": prompt}]

        # Uniform sampling when there are more screenshots than the cap.
        selected = _uniform_sample(candidates, self._max_screenshots)

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        content.append({
            "type": "text",
            "text": (
                f"\n\nThe following {len(selected)} screenshot(s) show the screen state "
                "before the labelled step. Use them to verify element descriptions, "
                "remove redundant actions, and write accurate valid_state fields."
            ),
        })

        for step_idx, path in selected:
            action_type = steps[step_idx].get("action", {}).get("action_type", "?")
            content.append({
                "type": "text",
                "text": f"\nStep {step_idx} — {action_type}:",
            })
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
                steps.append(SkillStep(
                    action_type=s["action_type"],
                    target=s.get("target", ""),
                    parameters=s.get("parameters", {}),
                    expected_state=s.get("expected_state"),
                    valid_state=s.get("valid_state"),
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
