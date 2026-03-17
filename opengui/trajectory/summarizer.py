"""
opengui.trajectory.summarizer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
LLM-driven trajectory summarization.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from opengui.interfaces import LLMProvider

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """\
Summarize the following GUI automation trajectory into a concise natural-language \
description. Focus on:
1. What task was attempted
2. Key actions taken (in order)
3. Whether it succeeded or failed, and why

# Trajectory
{trajectory}

Respond with a concise summary (3-5 sentences max).
"""


class TrajectorySummarizer:
    """Summarize trajectory JSONL files into natural language via LLM."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def summarize_file(self, trajectory_path: Path) -> str:
        """Read a trajectory JSONL and return a natural-language summary."""
        if not trajectory_path.exists():
            logger.warning("Trajectory file not found: %s", trajectory_path)
            return ""

        lines = trajectory_path.read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
        return await self.summarize_events(events)

    async def summarize_events(self, events: list[dict]) -> str:
        """Summarize pre-parsed trajectory events."""
        if not events:
            return ""

        # Build a compact representation for the LLM
        compact = self._compact_events(events)
        prompt = _SUMMARY_PROMPT.format(trajectory=compact)

        messages = [{"role": "user", "content": prompt}]
        response = await self._llm.chat(messages)
        return response.content.strip()

    @staticmethod
    def _compact_events(events: list[dict]) -> str:
        """Build a compact text representation of trajectory events."""
        lines: list[str] = []

        for event in events:
            etype = event.get("type", "")
            if etype == "metadata":
                lines.append(f"Task: {event.get('task', 'unknown')}")
                lines.append(f"Platform: {event.get('platform', 'unknown')}")
            elif etype == "step":
                idx = event.get("step_index", "?")
                action = event.get("action", {})
                action_type = action.get("action_type", "unknown")
                text = action.get("text", "")
                model_out = event.get("model_output", "")
                line = f"Step {idx}: {action_type}"
                if text:
                    line += f' text="{text}"'
                if model_out:
                    line += f" | {model_out[:100]}"
                lines.append(line)
            elif etype == "result":
                success = event.get("success", False)
                duration = event.get("duration_s", 0)
                error = event.get("error")
                status = "SUCCESS" if success else "FAILED"
                line = f"Result: {status} ({duration}s)"
                if error:
                    line += f" error={error}"
                lines.append(line)

        return "\n".join(lines)
