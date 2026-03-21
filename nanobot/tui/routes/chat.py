"""Browser chat routes for the TUI backend."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nanobot.tui.dependencies import get_chat_workspace_service
from nanobot.tui.schemas import (
    ChatCreateSessionResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionResponse,
)
from nanobot.tui.services import ChatWorkspaceService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatCreateSessionResponse)
async def create_session(
    service: ChatWorkspaceService = Depends(get_chat_workspace_service),
) -> ChatCreateSessionResponse:
    """Create a browser chat session persisted under the `tui:` namespace."""

    return service.create_session()


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: str,
    service: ChatWorkspaceService = Depends(get_chat_workspace_service),
) -> ChatSessionResponse:
    """Return the persisted transcript for a browser chat session."""

    try:
        return service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="chat session not found") from exc


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
async def send_message(
    session_id: str,
    payload: ChatMessageRequest,
    service: ChatWorkspaceService = Depends(get_chat_workspace_service),
) -> ChatMessageResponse:
    """Send a follow-up message through the direct chat runtime path."""

    try:
        return await service.send_message(session_id, payload.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="chat session not found") from exc
