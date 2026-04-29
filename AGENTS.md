# AGENTS.md — nanobot + OpenGUI Codebase Guide

This file gives AI coding agents (Codex, Claude, Gemini, etc.) the essential context to work in this repository without wasted exploration.

---

## Repository Layout

```
nanobot/        Main agent runtime (channels, providers, tools, session, skills, TUI/Gateway)
opengui/        Vision-based GUI automation engine (standalone or embedded in nanobot)
bridge/         Native desktop bridge binaries (macOS/Linux/Windows)
tests/          Test suite (pytest, asyncio_mode=auto)
nanobot_fork/   Project root — pyproject.toml, docker-compose.yml
```

Both `nanobot` and `opengui` are published as a single package (`nanobot-ai`).

---

## Running the Project

```bash
# Install in editable mode (preferred: uv)
uv pip install -e .

# Run tests
uv run pytest

# Start interactive TUI
uv run nanobot

# Start API gateway (port 18790)
uv run nanobot gateway

# Run OpenGUI standalone
uv run opengui "Open browser and go to github.com"
uv run opengui --backend adb "Open Settings and enable Wi-Fi"
uv run opengui --dry-run "Click the save button"
```

---

## Two Entry Points for OpenGUI

### 1. Standalone CLI (`opengui`)

Reads `~/.opengui/config.yaml`. Minimal config:

```yaml
provider:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3.5-plus"
  api_key: "sk-..."
```

Key CLI flags: `--backend {adb,ios,hdc,local,dry-run}`, `--agent-profile`, `--background`

### 2. nanobot `gui` Subagent Tool

When running inside nanobot, OpenGUI is wired as a tool that the main agent can delegate to. Configured under `"gui"` in `~/.nanobot/config.json`:

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

---

## Core Architecture

### Vision-Action Loop (`opengui/agent.py`)

`GuiAgent` runs a loop: screenshot → LLM → parse action → execute → repeat until `done` or `max_steps`.

Key types:
- `StepResult` — one step's output (action, tool result, next observation)
- `HistoryTurn` — compressed step kept in prompt window

### Protocol Boundary (`opengui/interfaces.py`)

OpenGUI is host-agnostic. It depends on two protocols only:

| Protocol | Purpose |
|----------|---------|
| `LLMProvider` | `async chat(messages, tools, ...) -> LLMResponse` |
| `DeviceBackend` | `observe()`, `execute(action)`, `preflight()`, `platform` |

**Never import nanobot from opengui code.** Adapters live in the host (nanobot) side.

### nanobot Adapter (`nanobot/agent/gui_adapter.py`)

```python
NanobotLLMAdapter   # wraps nanobot LLMProvider → opengui LLMProvider
NanobotEmbeddingAdapter  # wraps async embed_fn → opengui EmbeddingProvider
```

### Backends (`opengui/backends/`)

| File | Platform |
|------|----------|
| `adb.py` | Android (ADB) |
| `ios_wda.py` | iOS (WebDriverAgent) |
| `hdc.py` | HarmonyOS (HDC) |
| `desktop.py` | macOS / Linux |
| `windows_isolated.py` | Windows background isolation |
| `dry_run.py` | Testing / CI (no real actions) |

### Agent Profiles (`opengui/agent_profiles.py`)

Profiles handle models that don't support native tool calling:

| Profile | Model family |
|---------|-------------|
| `default` | OpenAI-style tool calls |
| `general_e2e` | MobileWorld planner_executor style |
| `qwen3vl` | Qwen3VL GUI models |
| `mai_ui` | MAI-UI style |
| `gelab` | Gelab tab-separated format |
| `seed` | Seed XML-style |

### Skills System (`opengui/skills/`)

- `library.py` — BM25 + FAISS hybrid retrieval, per-(platform, app) buckets, LLM deduplication
- `executor.py` — step-by-step execution with valid-state verification and subgoal recovery

---

## nanobot Main Agent (`nanobot/agent/`)

| File | Role |
|------|------|
| `loop.py` | Core tool-call iteration loop |
| `planner.py` | Task complexity gate + TaskPlanner decomposition |
| `router.py` | TreeRouter dispatches plan atoms to subagents/tools |
| `subagent.py` | Background task execution (`SubagentManager`) |
| `context.py` | Session context assembly |
| `memory.py` | Persistent agent memory |
| `gui_adapter.py` | LLM + Embedding adapters bridging nanobot → opengui |

---

## Configuration Schema (`nanobot/config/schema.py`)

All keys accept both `camelCase` and `snake_case`. Key config sections:

- `agents.defaults` — model, provider, maxTokens, temperature, maxToolIterations
- `providers.*` — per-provider API keys and base URLs (Anthropic, OpenAI, DashScope, OpenRouter, Ollama, etc.)
- `gui` — backend, model, agentProfile, maxSteps, skills config (`GuiConfig`)
- `tools.mcp_servers` — MCP server wiring (stdio or HTTP)
- `channels` — Telegram, Slack, Discord, Feishu, WeChat, etc.

---

## Action Types (`opengui/action.py`)

Valid actions: `tap`, `long_press`, `double_tap`, `drag`, `swipe`, `scroll`, `input_text`, `hotkey`, `screenshot`, `wait`, `open_app`, `close_app`, `back`, `home`, `enter`, `app_switch`, `done`, `request_intervention`

Coordinates use a 0–999 relative grid by default. `resolve_coordinate` maps to device pixels.

---

## Testing

```bash
uv run pytest                         # full suite
uv run pytest tests/test_opengui.py   # opengui unit tests
uv run pytest -k "not adb"            # skip hardware tests
```

Test files:
- `tests/test_opengui.py` — core opengui unit tests
- `tests/test_opengui_p1_skills.py` — skill system tests
- `tests/test_opengui_p14_windows_desktop.py` — Windows desktop backend tests

**Use `uv run pytest` — never `python -m pytest` directly.**

---

## Key Conventions

- `opengui` must not import from `nanobot`. Dependency direction: `nanobot → opengui`.
- All protocol implementations must be async-safe.
- `Action` and `LLMResponse` are frozen dataclasses — immutable, safe to share.
- Normalize "no tool calls" to `None`, not `[]`, in `LLMResponse.tool_calls`.
- Config validation: `GuiConfig._validate_agent_profile` calls `canonicalize_agent_profile` — always pass canonical profile names.
