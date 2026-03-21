"""Transient SSE event broker for browser chat runs."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import uuid4

from nanobot.tui.schemas import ChatEvent


class EventStreamBroker:
    """In-process event fanout with a small per-session replay buffer."""

    def __init__(self) -> None:
        self._events: dict[str, list[ChatEvent]] = defaultdict(list)
        self._subscribers: dict[str, set[asyncio.Queue[ChatEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(
        self,
        *,
        event_type: str,
        session_id: str,
        run_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> ChatEvent:
        event = ChatEvent(
            id=uuid4().hex,
            type=event_type,
            session_id=session_id,
            run_id=run_id,
            payload=dict(payload or {}),
        )
        async with self._lock:
            self._events[session_id].append(event)
            subscribers = list(self._subscribers[session_id])
        for queue in subscribers:
            await queue.put(event)
        return event

    async def subscribe(self, session_id: str) -> AsyncIterator[ChatEvent]:
        queue: asyncio.Queue[ChatEvent] = asyncio.Queue()
        async with self._lock:
            backlog = list(self._events.get(session_id, ()))
            self._subscribers[session_id].add(queue)
        try:
            for event in backlog:
                yield event
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(session_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(session_id, None)
