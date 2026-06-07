"""#1 — embedding retrieval for GUI-memory items in GuiRouterMemoryRetriever.

The induced memory items are deliberately abstract / keyword-sparse, which the
keyword scorer under-retrieves.  ``retrieve_async`` ranks them with the framework's
hybrid BM25+FAISS MemoryRetriever; without an embedding provider, or if embedding
fails, it degrades to the keyword path so nothing is silently dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

import nanobot.agent.tools.gui as gui_tools
from nanobot.agent.tools.gui import GuiRouterMemoryRetriever
from scripts.induce_gui_memory import GuiMemoryItem, append_to_memory_bank


class _TopicEmbedder:
    """Maps topic-synonyms to a shared slot so semantically-related (but not
    lexically overlapping) texts embed close together."""

    DIM = 6
    _SLOTS = {
        # slot 0 — composing / messaging
        "compose": 0, "composing": 0, "draft": 0, "new": 0, "message": 0,
        "write": 0, "email": 0, "mail": 0, "editor": 0, "pencil": 0, "recipient": 0,
        # slot 1 — scrolling / feeds
        "scroll": 1, "feed": 1, "list": 1, "older": 1, "entries": 1, "swipe": 1,
    }

    async def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            hit = False
            for token in re.findall(r"[a-z]+", text.lower()):
                slot = self._SLOTS.get(token)
                if slot is not None:
                    vecs[i, slot] += 1.0
                    hit = True
            if not hit:  # keep non-topic texts off the topic axes deterministically
                vecs[i, abs(hash(text)) % self.DIM] = 1.0
        return vecs


class _BoomEmbedder:
    async def embed(self, texts: list[str]) -> np.ndarray:
        raise RuntimeError("embedding endpoint down")


_COMPOSE = GuiMemoryItem(
    title="Open the compose editor",
    description="Use when starting a new message draft.",
    content="Tap the pencil to open a new message editor and begin composing a draft to the recipient.",
    status="success",
    app="com.gmailclone",
)
_SCROLL = GuiMemoryItem(
    title="Reveal older entries",
    description="Use when the target sits far down a feed.",
    content="Scroll the feed list repeatedly to reach older entries.",
    status="success",
    app="org.joinmastodon.android.mastodon",
)
_INVITE = GuiMemoryItem(
    title="Generate invite links",
    description="Use when generating an expiring invite link.",
    content="Open mastodon server invite controls to generate an invite link with expiry.",
    status="success",
    app="org.joinmastodon.android.mastodon",
)


def _make_bank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: list[GuiMemoryItem]) -> None:
    bank_dir = tmp_path / "opengui_memory"
    bank_dir.mkdir()
    append_to_memory_bank(items, bank_dir / "gui_memory_bank.jsonl")
    monkeypatch.setattr(gui_tools, "DEFAULT_OPENGUI_MEMORY_DIR", bank_dir)


async def test_embedding_ranks_semantic_match_over_lexical_void(tmp_path, monkeypatch):
    """A query that shares no keywords with the relevant item still ranks it first."""
    _make_bank(tmp_path, monkeypatch, [_COMPOSE, _SCROLL])
    retriever = GuiRouterMemoryRetriever(tmp_path / "ws", embedding_provider=_TopicEmbedder())

    # "write an email" shares the *topic* of the compose item but none of its words.
    context = await retriever.retrieve_async("write an email to a teammate", platform="android")

    assert context.evidence, "expected GUI-memory evidence"
    top = context.evidence[0]
    assert "pencil" in top.text or "composing" in top.text  # the compose item, ranked first
    assert top.source.startswith("opengui/gui_memory:com.gmailclone")


async def test_no_provider_delegates_to_keyword(tmp_path, monkeypatch):
    """Without an embedding provider, retrieve_async == sync keyword retrieve."""
    _make_bank(tmp_path, monkeypatch, [_INVITE])
    retriever = GuiRouterMemoryRetriever(tmp_path / "ws")  # provider=None
    task = "Generate a one-person invite link that expires in one day."

    async_ctx = await retriever.retrieve_async(task, platform="android")
    sync_ctx = retriever.retrieve(task, platform="android")

    assert async_ctx == sync_ctx
    assert any("invite" in item.text.casefold() for item in async_ctx.evidence)


async def test_embedding_failure_falls_back_to_keyword(tmp_path, monkeypatch):
    """If the embedding call errors, GUI memory still surfaces via the keyword path."""
    _make_bank(tmp_path, monkeypatch, [_INVITE])
    retriever = GuiRouterMemoryRetriever(tmp_path / "ws", embedding_provider=_BoomEmbedder())

    context = await retriever.retrieve_async(
        "Generate a one-person invite link that expires in one day.", platform="android"
    )

    assert any("invite" in item.text.casefold() for item in context.evidence)
    assert any(
        item.source.startswith("opengui/gui_memory:org.joinmastodon.android.mastodon")
        for item in context.evidence
    )


async def test_empty_bank_yields_no_evidence(tmp_path, monkeypatch):
    _make_bank(tmp_path, monkeypatch, [])
    retriever = GuiRouterMemoryRetriever(tmp_path / "ws", embedding_provider=_TopicEmbedder())
    context = await retriever.retrieve_async("write an email", platform="android")
    assert context.evidence == ()
