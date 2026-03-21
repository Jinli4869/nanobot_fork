"""Phase 18 Plan 01 browser chat workspace tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from nanobot.session.manager import SessionManager
from nanobot.tui.app import create_app


def test_chat_routes_create_and_reuse_session_backed_conversations(tmp_path: Path) -> None:
    app = create_app(include_runtime_routes=True)
    client = TestClient(app)

    create_response = client.post("/chat/sessions")

    assert create_response.status_code == 200
    created = create_response.json()
    session_id = created["session"]["session_id"]
    assert session_id
    assert created["session"]["session_key"] == f"tui:{session_id}"
    assert created["session"]["message_count"] == 0
    assert created["messages"] == []

    send_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"content": "hello from browser"},
    )

    assert send_response.status_code == 200
    sent = send_response.json()
    assert sent["session"]["session_id"] == session_id
    assert sent["session"]["session_key"] == f"tui:{session_id}"
    assert sent["session"]["session_key"] != "cli:direct"
    assert sent["reply"]["role"] == "assistant"


def test_chat_history_route_reads_persisted_session_state(tmp_path: Path) -> None:
    session_id = "existing-chat"
    session_key = f"tui:{session_id}"
    manager = SessionManager(tmp_path)
    session = manager.get_or_create(session_key)
    session.metadata["origin"] = "browser"
    session.add_message("user", "persisted hello")
    session.add_message("assistant", "persisted reply")
    manager.save(session)

    app = create_app(include_runtime_routes=True)
    client = TestClient(app)

    response = client.get(f"/chat/sessions/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["session_id"] == session_id
    assert payload["session"]["session_key"] == session_key
    assert payload["session"]["metadata"]["origin"] == "browser"
    assert [message["content"] for message in payload["messages"]] == [
        "persisted hello",
        "persisted reply",
    ]
