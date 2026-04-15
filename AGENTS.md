# AGENTS.md - nanobot + OpenGUI Codebase Guide

This file gives AI coding agents the essential context to work in this repository without wasted exploration.

## Project Overview

nanobot is a lightweight AI agent framework written in Python with a React/TypeScript WebUI. It centers around an async agent loop that receives messages from chat channels, invokes an LLM provider, executes tools, and manages session memory.

The repository also includes OpenGUI, a vision-based GUI automation engine that can run standalone or as a nanobot subagent tool. Both `nanobot` and `opengui` are published as a single package (`nanobot-ai`).

## Repository Layout

```text
nanobot/        Main agent runtime: channels, providers, tools, sessions, skills, TUI/Gateway
opengui/        Vision-based GUI automation engine
bridge/         Native desktop bridge binaries for macOS/Linux/Windows
tests/          Test suite, with pytest asyncio_mode=auto
webui/          React/TypeScript WebUI
```

## Development Commands

```bash
# Install in editable mode
uv pip install -e .

# Python tests
uv run pytest
uv run pytest tests/test_opengui.py
uv run pytest -k "not adb"

# Python lint
uv run ruff check nanobot/

# Gateway and TUI
uv run nanobot
uv run nanobot gateway

# OpenGUI standalone
uv run opengui "Open browser and go to github.com"
uv run opengui --backend adb "Open Settings and enable Wi-Fi"
uv run opengui --dry-run "Click the save button"

# WebUI
cd webui && bun run dev
cd webui && bun run build
cd webui && bun run test
```

**Use `uv run pytest` for tests.**

## High-Level Architecture

### Core Data Flow

Messages flow through an async `MessageBus` (`nanobot/bus/queue.py`) that decouples chat channels from the agent core:

1. Channels (`nanobot/channels/`) receive messages from external platforms and publish `InboundMessage` events to the bus.
2. `AgentLoop` (`nanobot/agent/loop.py`) consumes inbound messages, builds context, and coordinates the turn.
3. `AgentRunner` (`nanobot/agent/runner.py`) handles the LLM conversation loop: send messages to the provider, receive tool calls, execute tools, and stream responses.
4. Responses are published as `OutboundMessage` events back to the appropriate channel.

### Key Subsystems

- **Agent Loop** (`nanobot/agent/loop.py`, `runner.py`): Core processing engine. `AgentLoop` manages session keys, hooks, and context building. `AgentRunner` executes the multi-turn LLM conversation with tool execution.
- **LLM Providers** (`nanobot/providers/`): Provider implementations built on a common base (`base.py`). `factory.py` and `registry.py` handle instantiation and model discovery.
- **Channels** (`nanobot/channels/`): Platform integrations. `manager.py` discovers and coordinates them.
- **Tools** (`nanobot/agent/tools/`): Agent capabilities exposed to the LLM, including filesystem, shell, web, MCP, cron, subagents, long-running goals, image generation, and self-modification.
- **Memory** (`nanobot/agent/memory.py`): Session history persistence and Dream memory consolidation.
- **Session Management** (`nanobot/session/`): Per-session history, context compaction, TTL-based auto-compaction, and sustained goal state tracking.
- **Config** (`nanobot/config/schema.py`, `loader.py`): Pydantic-based configuration loaded from `~/.nanobot/config.json`, with camelCase and snake_case aliases.
- **WebUI** (`webui/`): Vite-based React SPA that talks to the gateway over a WebSocket multiplex protocol.
- **API Server** (`nanobot/api/server.py`): OpenAI-compatible HTTP API.
- **Skills** (`nanobot/skills/`): Built-in skill definitions loaded into agent context.
- **Security** (`nanobot/security/`): PTH file guard and related CLI-entry security measures.

## OpenGUI Architecture

### Entry Points

OpenGUI can run as a standalone CLI:

```bash
uv run opengui --backend adb "Open Settings and enable Wi-Fi"
```

It can also run inside nanobot through the `gui` subagent tool. Configure it under `"gui"` in `~/.nanobot/config.json`:

```json
{
  "gui": {
    "backend": "adb",
    "model": "openrouter/qwen/qwen2.5-vl-72b-instruct",
    "provider": "openrouter",
    "agentProfile": "qwen3vl",
    "maxSteps": 20,
    "enableSkillExecution": true
  }
}
```

### Vision-Action Loop

`GuiAgent` (`opengui/agent.py`) runs: screenshot -> LLM -> parse action -> execute -> repeat until `done` or `max_steps`.

Key types:
- `StepResult`: one step's output, action, tool result, and next observation.
- `HistoryTurn`: compressed step kept in the prompt window.

### Protocol Boundary

OpenGUI is host-agnostic and depends on two protocols from `opengui/interfaces.py`:

| Protocol | Purpose |
| --- | --- |
| `LLMProvider` | `async chat(messages, tools, ...) -> LLMResponse` |
| `DeviceBackend` | `observe()`, `execute(action)`, `preflight()`, `platform` |

Never import `nanobot` from `opengui` code. Adapters live on the host side, such as `nanobot/agent/gui_adapter.py`.

### Backends

| File | Platform |
| --- | --- |
| `opengui/backends/adb.py` | Android ADB |
| `opengui/backends/ios_wda.py` | iOS WebDriverAgent |
| `opengui/backends/hdc.py` | HarmonyOS HDC |
| `opengui/backends/desktop.py` | macOS/Linux desktop |
| `opengui/backends/windows_isolated.py` | Windows background isolation |
| `opengui/backends/dry_run.py` | Testing and CI |

### Agent Profiles

Agent profiles in `opengui/agent_profiles.py` handle models that do not support native tool calling:

| Profile | Model family |
| --- | --- |
| `default` | OpenAI-style tool calls |
| `general_e2e` | MobileWorld planner_executor style |
| `qwen3vl` | Qwen3VL GUI models |
| `mai_ui` | MAI-UI style |
| `gelab` | Gelab tab-separated format |
| `seed` | Seed XML-style |

### Skills System

- `opengui/skills/library.py`: BM25 + FAISS hybrid retrieval, per-platform/app buckets, and LLM deduplication.
- `opengui/skills/executor.py`: Step-by-step execution with valid-state verification and subgoal recovery.

## Configuration Schema

All config keys accept both `camelCase` and `snake_case`. Key sections:

- `agents.defaults`: model, provider, maxTokens, temperature, maxToolIterations.
- `providers.*`: per-provider API keys and base URLs.
- `gui`: backend, model, provider, agentProfile, maxSteps, skills config.
- `tools.mcp_servers`: MCP server wiring.
- `channels`: Telegram, Slack, Discord, Feishu, WeChat, and other channel integrations.

## Action Types

Valid OpenGUI actions are defined in `opengui/action.py`: `tap`, `long_press`, `double_tap`, `drag`, `swipe`, `scroll`, `input_text`, `hotkey`, `screenshot`, `wait`, `open_app`, `close_app`, `back`, `home`, `enter`, `app_switch`, `done`, and `request_intervention`.

Coordinates use a 0-999 relative grid by default. `resolve_coordinate` maps relative coordinates to device pixels.

## Project-Specific Notes

- Architecture constraints: [`.agent/design.md`](.agent/design.md)
- Security boundaries: [`.agent/security.md`](.agent/security.md)
- Common gotchas: [`.agent/gotchas.md`](.agent/gotchas.md)
- Contribution flow: [`CONTRIBUTING.md`](./CONTRIBUTING.md)

## Code Style

- Python 3.11+, asyncio throughout.
- Line length: 100.
- Linting: `ruff` with rules E, F, I, N, W; E501 is ignored.
- pytest uses `asyncio_mode = "auto"`.

## Key Conventions

- `opengui` must not import from `nanobot`. Dependency direction is `nanobot -> opengui`.
- All protocol implementations must be async-safe.
- `Action` and `LLMResponse` are frozen dataclasses.
- Normalize "no tool calls" to `None`, not `[]`, in `LLMResponse.tool_calls`.
- Config validation for GUI agent profiles goes through `GuiConfig._validate_agent_profile` and `canonicalize_agent_profile`.

## Common File Locations

- Config schema: `nanobot/config/schema.py`
- Provider factory and registry: `nanobot/providers/factory.py`, `nanobot/providers/registry.py`
- Channel base: `nanobot/channels/base.py`
- Tool registry: `nanobot/agent/tools/registry.py`
- OpenGUI action model: `opengui/action.py`
- OpenGUI agent loop: `opengui/agent.py`
- OpenGUI nanobot adapter: `nanobot/agent/gui_adapter.py`
- WebUI dev proxy config: `webui/vite.config.ts`
- Tests mirror the `nanobot/` and `opengui/` package structure.
