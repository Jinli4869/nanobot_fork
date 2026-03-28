"""Adapter bridge from nanobot providers to opengui protocols."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np

from nanobot.providers.base import LLMProvider as NanobotLLMProvider
from opengui.interfaces import LLMResponse as OpenGuiLLMResponse
from opengui.interfaces import ToolCall


class NanobotLLMAdapter:
    """Wrap a nanobot LLM provider with opengui's chat interface."""

    def __init__(self, provider: NanobotLLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> OpenGuiLLMResponse:
        nano_resp = await self._provider.chat_with_retry(
            messages=messages,
            tools=tools,
            model=self._model,
            tool_choice=tool_choice,
        )
        tool_calls = [
            ToolCall(id=call.id, name=call.name, arguments=call.arguments)
            for call in (nano_resp.tool_calls or [])
        ] or None
        return OpenGuiLLMResponse(
            content=nano_resp.content or "",
            tool_calls=tool_calls,
            raw=nano_resp,
            usage=nano_resp.usage or {},
        )


class NanobotEmbeddingAdapter:
    """Wrap an async embedding callable with opengui's embed interface."""

    def __init__(self, embed_fn: Callable[[list[str]], Awaitable[np.ndarray]]) -> None:
        self._embed_fn = embed_fn

    async def embed(self, texts: list[str]) -> np.ndarray:
        return await self._embed_fn(texts)

