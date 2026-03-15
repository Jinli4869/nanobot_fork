from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import typer

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.cli import commands
from nanobot.config.schema import Config, GuiConfig
from nanobot.providers.base import GenerationSettings


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    return provider


def test_make_gui_provider_reuses_main_provider_when_no_overrides() -> None:
    config = Config()
    provider = object()

    gui_provider, gui_model = commands._make_gui_provider(config, provider)

    assert gui_provider is provider
    assert gui_model == config.agents.defaults.model


def test_make_gui_provider_builds_override_provider(monkeypatch) -> None:
    config = Config.model_validate(
        {
            "agents": {"defaults": {"model": "anthropic/claude-opus-4-5", "provider": "openrouter"}},
            "tools": {"gui": {"model": "gpt-4o", "provider": "openai"}},
        }
    )
    expected = object()
    captured: dict[str, str] = {}

    def fake_make_provider(gui_config: Config):
        captured["model"] = gui_config.agents.defaults.model
        captured["provider"] = gui_config.agents.defaults.provider
        return expected

    monkeypatch.setattr("nanobot.cli.commands._make_provider", fake_make_provider)

    gui_provider, gui_model = commands._make_gui_provider(config, object())

    assert gui_provider is expected
    assert gui_model == "gpt-4o"
    assert captured == {"model": "gpt-4o", "provider": "openai"}


def test_make_gui_provider_requires_model_when_provider_only_conflicts() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "model": "anthropic/claude-opus-4-5",
                    "provider": "openrouter",
                }
            },
            "tools": {"gui": {"provider": "openai"}},
        }
    )

    with pytest.raises(typer.Exit):
        commands._make_gui_provider(config, object())


def test_make_gui_provider_requires_model_when_auto_keyword_conflicts() -> None:
    """P4 edge case: provider=auto, model has no `/` prefix but keyword-matches
    a different provider than gui.provider."""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "model": "claude-sonnet-4-20250514",
                    "provider": "auto",
                }
            },
            "tools": {"gui": {"provider": "openai"}},
        }
    )

    with pytest.raises(typer.Exit):
        commands._make_gui_provider(config, object())


def test_agent_loop_registers_gui_tools_and_sets_context(tmp_path: Path) -> None:
    from nanobot.bus.queue import MessageBus

    provider = _make_provider()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        gui_config=GuiConfig(enabled=True, backend="dry-run"),
    )

    assert loop.tools.has("gui_run")
    assert loop.tools.has("desktop_observe")
    assert loop.tools.has("desktop_act")

    progress_calls: list[str] = []

    async def progress(message: str) -> None:
        progress_calls.append(message)

    loop._set_tool_context("cli", "chat-1", "msg-1", progress)

    gui_tool = loop.tools.get("gui_run")
    observe_tool = loop.tools.get("desktop_observe")
    act_tool = loop.tools.get("desktop_act")

    assert getattr(gui_tool, "_channel") == "cli"
    assert getattr(gui_tool, "_progress_callback") is progress
    assert getattr(observe_tool, "_chat_id") == "chat-1"
    assert getattr(act_tool, "_message_id") == "msg-1"


@pytest.mark.asyncio
async def test_process_direct_does_not_enable_bus_gui_progress(tmp_path: Path) -> None:
    from nanobot.bus.queue import MessageBus

    provider = _make_provider()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        gui_config=GuiConfig(enabled=True, backend="dry-run"),
    )

    loop._run_agent_loop = AsyncMock(return_value=("ok", [], []))

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello"),
        session_key="cli:direct",
        use_bus_gui_progress=False,
    )

    gui_tool = loop.tools.get("gui_run")
    assert getattr(gui_tool, "_progress_callback") is None


@pytest.mark.asyncio
async def test_process_direct_reuses_cli_progress_for_gui_updates(tmp_path: Path) -> None:
    from nanobot.bus.queue import MessageBus

    provider = _make_provider()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        gui_config=GuiConfig(enabled=True, backend="dry-run"),
    )

    loop._run_agent_loop = AsyncMock(return_value=("ok", [], []))

    async def progress(message: str) -> None:
        del message

    await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello"),
        session_key="cli:direct",
        on_progress=progress,
        use_bus_gui_progress=False,
    )

    gui_tool = loop.tools.get("gui_run")
    assert getattr(gui_tool, "_progress_callback") is progress
