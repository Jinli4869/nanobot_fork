# Technology Stack

**Analysis Date:** 2026-03-17

## Languages

**Primary:**
- Python 3.11+ (>=3.11, tested on 3.11-3.12) - Core agent framework, CLI, channels, and tools

**Secondary:**
- TypeScript 5.4.0 - Node.js WhatsApp bridge (`bridge/` directory)
- JavaScript (Node.js 20+) - Build and runtime for WhatsApp bridge

## Runtime

**Environment:**
- Python 3.12 (primary runtime in Docker)
- Node.js 20.x (for WhatsApp bridge only)

**Package Manager:**
- `uv` (Astral's unified Python package manager) - Primary package management
- `npm` (Node Package Manager) - WhatsApp bridge only
- Lockfiles: `uv.lock` (main), `bridge/package-lock.json` (implicit)

## Frameworks

**Core:**
- Typer 0.20+ - CLI framework for command-line interface (`nanobot` CLI command)
- Pydantic 2.12+ - Data validation and configuration management
- Pydantic Settings 2.12+ - Configuration from environment variables and config files

**LLM & AI:**
- LiteLLM 1.82+ - Unified LLM provider interface (30+ providers supported)
- OpenAI 2.8+ - Direct OpenAI API client library
- Tiktoken 0.12+ - Token counting for OpenAI models

**Async & Network:**
- Websockets 16.0+ - WebSocket server for client connections
- Websocket-client 1.9+ - WebSocket client for remote connections
- HTTPX 0.28+ - Async HTTP client for API calls
- Python-SocketIO 5.16+ - Socket.IO protocol implementation

**Channels & Integrations:**
- DingTalk Stream SDK 0.24+ - DingTalk messaging integration
- Python-Telegram-Bot 22.6+ - Telegram bot support
- Slack SDK 3.39+ - Slack workspace integration
- QQ BotPy 1.2+ - QQ bot support
- Lark-OAPI 1.5+ - Feishu (Lark) API client
- Matrix-NIO 0.25+ (optional) - Matrix protocol support
- Slackify-Markdown 0.2+ - Markdown to Slack formatting
- WeCom SDK (optional) - WeCom AI Bot support

**Node.js Bridge (WhatsApp):**
- @whiskeysockets/baileys 7.0.0-rc.9 - WhatsApp Web protocol
- WS 8.17.1 - WebSocket library for Node.js
- Pino 9.0+ - Structured logging for Node.js

**Utilities:**
- Loguru 0.7+ - Structured logging framework
- Rich 14.0+ - Terminal output formatting and progress bars
- Readability-lxml 0.8+ - Web content extraction
- DDGS 9.5+ - DuckDuckGo search integration
- JSON-Repair 0.57+ - Robust JSON parsing and repair
- Chardet 3.0-6.0 - Character encoding detection
- Croniter 6.0+ - Cron expression parser
- OAuth-CLI-Kit 0.1+ - OAuth token management
- Python-SOCKS 2.8+ - SOCKS proxy support
- Socksio 1.0+ - SOCKS5 client implementation
- Prompt-Toolkit 3.0+ - Interactive CLI prompt support
- MCP 1.26+ - Model Context Protocol (Claude integration)

**TypeScript/Node.js Bridge:**
- TypeScript 5.4.0 - Type safety in bridge
- @types/node 20.14+ - Node.js type definitions
- @types/ws 8.5+ - WebSocket type definitions
- QRCode-Terminal 0.12+ - QR code display in terminal

## Key Dependencies

**Critical:**
- `litellm` - Enables support for 30+ LLM providers (Anthropic, OpenAI, DeepSeek, Groq, Ollama, etc.)
- `pydantic` - Runtime type validation and configuration schema
- `websockets` - Real-time bidirectional communication with agents and channels

**Infrastructure:**
- `loguru` - Centralized, structured logging across all modules
- `httpx` - Async-capable HTTP client for external API calls
- `asyncio` (stdlib) - Async/await runtime for concurrent operations

## Configuration

**Environment:**
- Configured via `~/.nanobot/config.json` (YAML/JSON formats)
- Environment variables override config file (prefix: `NANOBOT_`)
- Nested config via double-underscore delimiters (e.g., `NANOBOT_AGENTS__DEFAULTS__MODEL`)

**Build:**
- Python project: `pyproject.toml` - Single source of truth for dependencies, build, metadata
- Node.js bridge: `bridge/tsconfig.json` - TypeScript compilation settings
- Docker: `Dockerfile` - Multi-stage build (Python + Node.js), builds bridge and installs packages
- Docker Compose: `docker-compose.yml` - Gateway service with resource limits

## Optional Dependencies

**Matrix Protocol:**
- `matrix-nio[e2e]` 0.25+ - End-to-end encrypted Matrix chat support
- `mistune` 3.0+ - Markdown parsing for Matrix messages
- `nh3` 0.2+ - HTML sanitization for Matrix

**LangSmith Integration:**
- `langsmith` 0.1+ - LLM tracing and monitoring (optional observability)

**Development:**
- `pytest` 9.0+ - Test runner
- `pytest-asyncio` 1.3+ - Async test support
- `ruff` 0.1+ - Fast Python linter (E, F, I, N, W rules)

## Platform Requirements

**Development:**
- Python 3.11+ (supported versions: 3.11, 3.12)
- `uv` package manager
- Git for version control

**Production:**
- Docker with Docker Compose (recommended)
- Alternatively: Python 3.12 + Node.js 20
- Persistent storage: `~/.nanobot/` directory for config, sessions, and state
- Network: TCP port 18790 (gateway) exposed for client connections

**Deployment Target:**
- Linux (recommended, especially in Docker)
- macOS (development/testing)
- Docker containers (ghcr.io/astral-sh/uv:python3.12-bookworm-slim base)

---

*Stack analysis: 2026-03-17*
