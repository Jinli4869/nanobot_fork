"""Browser chat workspace services for the TUI backend."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import uuid4

from nanobot.session.manager import Session, SessionManager
from nanobot.tui.schemas import (
    ChatCreateSessionResponse,
    ChatMessage,
    ChatMessageResponse,
    ChatSessionResponse,
    ChatSessionSummary,
)


class DirectChatRuntime(Protocol):
    """Minimal runtime surface needed for browser chat."""

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        ...

    async def close_mcp(self) -> None:
        ...


class ChatWorkspaceService:
    """Thin adapter over SessionManager and AgentLoop.process_direct()."""

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        runtime_factory: Callable[[], DirectChatRuntime],
    ) -> None:
        self._session_manager = session_manager
        self._runtime_factory = runtime_factory

    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"tui:{session_id}"

    def _session_exists(self, session_key: str) -> bool:
        return any(item.get("key") == session_key for item in self._session_manager.list_sessions())

    def _summary_from_session(self, session_id: str, session: Session) -> ChatSessionSummary:
        return ChatSessionSummary(
            session_id=session_id,
            session_key=session.key,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
            metadata=dict(session.metadata),
            message_count=len(session.messages),
        )

    @staticmethod
    def _messages_from_session(session: Session) -> list[ChatMessage]:
        return [ChatMessage.model_validate(message) for message in session.messages]

    def create_session(self) -> ChatCreateSessionResponse:
        session_id = uuid4().hex
        session = self._session_manager.get_or_create(self._session_key(session_id))
        session.metadata.setdefault("origin", "browser")
        session.metadata.setdefault("channel", "tui")
        self._session_manager.save(session)
        return ChatCreateSessionResponse(
            session=self._summary_from_session(session_id, session),
            messages=self._messages_from_session(session),
        )

    def get_session(self, session_id: str) -> ChatSessionResponse:
        session_key = self._session_key(session_id)
        if not self._session_exists(session_key):
            raise KeyError(session_id)
        session = self._session_manager.get_or_create(session_key)
        return ChatSessionResponse(
            session=self._summary_from_session(session_id, session),
            messages=self._messages_from_session(session),
        )

    async def send_message(self, session_id: str, content: str) -> ChatMessageResponse:
        session_key = self._session_key(session_id)
        if not self._session_exists(session_key):
            raise KeyError(session_id)

        runtime = self._runtime_factory()
        try:
            reply = await runtime.process_direct(
                content,
                session_key=session_key,
                channel="tui",
                chat_id=session_id,
                on_progress=self._silent_progress,
            )
        finally:
            await runtime.close_mcp()

        session = self._session_manager.get_or_create(session_key)
        return ChatMessageResponse(
            session=self._summary_from_session(session_id, session),
            reply=ChatMessage(role="assistant", content=reply),
        )

    @staticmethod
    async def _silent_progress(_content: str) -> None:
        return None
