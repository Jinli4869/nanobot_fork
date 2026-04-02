"""
opengui.grounding.llm
~~~~~~~~~~~~~~~~~~~~~
LLM-backed grounding implementation for semantic target resolution.
"""

from __future__ import annotations

import json
import re
from typing import Any

from opengui.interfaces import LLMProvider
from opengui.skills.shortcut import ParameterSlot

from opengui.grounding.protocol import GroundingContext, GroundingResult


class LLMGrounder:
    def __init__(self, llm: LLMProvider, grounder_id: str = "llm:default") -> None:
        self._llm = llm
        self._grounder_id = grounder_id

    async def ground(self, target: str, context: GroundingContext) -> GroundingResult:
        prompt = self._build_prompt(target, context)
        response = await self._llm.chat(
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        )
        payload = self._extract_payload(response.content, response.tool_calls)
        return GroundingResult(
            grounder_id=payload.get("grounder_id", self._grounder_id),
            confidence=float(payload.get("confidence", 1.0)),
            resolved_params=dict(payload.get("resolved_params", {})),
            fallback_metadata=self._normalize_fallback(payload.get("fallback_metadata")),
        )

    def _build_prompt(self, target: str, context: GroundingContext) -> str:
        slots = ", ".join(self._format_slot(slot) for slot in context.parameter_slots) or "none"
        task_hint = context.task_hint or "none"
        return (
            "Resolve semantic UI target into structured parameters.\n"
            f"Target: {target}\n"
            f"Task hint: {task_hint}\n"
            f"Foreground app: {context.observation.foreground_app or 'unknown'}\n"
            f"Platform: {context.observation.platform}\n"
            f"Screen: {context.observation.screen_width}x{context.observation.screen_height}\n"
            f"Parameter slots: {slots}\n"
            "Respond with JSON containing `resolved_params`, and optionally `confidence`, "
            "`fallback_metadata`, and `grounder_id`."
        )

    @staticmethod
    def _format_slot(slot: ParameterSlot) -> str:
        return f"{slot.name}:{slot.type} ({slot.description})"

    @staticmethod
    def _extract_payload(content: str, tool_calls: list[Any] | None) -> dict[str, Any]:
        if tool_calls:
            first = tool_calls[0]
            if isinstance(first.arguments, dict):
                return dict(first.arguments)

        text = content.strip()
        if text:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    if "resolved_params" in parsed:
                        return parsed
                    reserved = {"confidence", "fallback_metadata", "grounder_id"}
                    resolved_params = {k: v for k, v in parsed.items() if k not in reserved}
                    payload: dict[str, Any] = {"resolved_params": resolved_params}
                    for key in reserved:
                        if key in parsed:
                            payload[key] = parsed[key]
                    return payload
        return {"resolved_params": {}}

    @staticmethod
    def _normalize_fallback(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return dict(value)
        return {"value": value}
