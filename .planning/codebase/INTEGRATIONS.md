# External Integrations

**Analysis Date:** 2026-03-17

## APIs & External Services

**LLM Providers:**
- Anthropic Claude - LiteLLM support via `ANTHROPIC_API_KEY`
- OpenAI (GPT series) - Native support via `OPENAI_API_KEY`
- Azure OpenAI - Direct integration via `azure_openai` provider
- DeepSeek - Supported via `DEEPSEEK_API_KEY`
- Google Gemini - Via `GEMINI_API_KEY`
- OpenRouter (gateway) - Supports 200+ models via `OPENROUTER_API_KEY` (prefix: `sk-or-`)
- Groq - Voice transcription and LLM via `GROQ_API_KEY`
- DashScope (Qwen) - Alibaba Qwen models via `DASHSCOPE_API_KEY`
- Zhipu AI (GLM) - Via `ZAI_API_KEY` / `ZHIPUAI_API_KEY`
- Moonshot (Kimi) - Via `MOONSHOT_API_KEY` + `MOONSHOT_API_BASE`
- MiniMax - Via `MINIMAX_API_KEY`
- AiHubMix - OpenAI-compatible gateway via custom `OPENAI_API_KEY` + `api_base`
- SiliconFlow (硅基流动) - Via `OPENAI_API_KEY` + `api_base`
- VolcEngine (火山引擎) - Via `OPENAI_API_KEY` + `api_base`
- BytePlus - VolcEngine international via `OPENAI_API_KEY` + `api_base`
- Local: Ollama, vLLM - OpenAI-compatible, `api_base` configured locally
- OAuth: OpenAI Codex, GitHub Copilot - OAuth-based (no API key)

**Messaging & Communication:**
- Slack - App token (`SLACK_APP_TOKEN`) + Bot token (`SLACK_BOT_TOKEN`)
  - SDK: `slack-sdk`
  - Auth: Socket Mode protocol with workspace tokens
  - File: `nanobot/channels/slack.py`

- Telegram - Bot token (`TELEGRAM_BOT_TOKEN`)
  - SDK: `python-telegram-bot[socks]`
  - Auth: Token-based bot authentication
  - File: `nanobot/channels/telegram.py`
  - Features: Proxy support (SOCKS5), file/media handling

- DingTalk (钉钉) - App ID + Secret
  - SDK: `dingtalk-stream`
  - Auth: Token-based streaming connection
  - File: `nanobot/channels/dingtalk.py`
  - Features: File/image/richText message support, media download to `~/.nanobot/media/`

- Feishu (Lark) - App ID + Secret
  - SDK: `lark-oapi`
  - Auth: OAuth2 token exchange
  - File: `nanobot/channels/feishu.py`
  - Features: Full message formatting, markdown support

- WeCom (企业微信) - Bot ID + Secret (optional, requires `wecom-aibot-sdk-python`)
  - SDK: `wecom-aibot-sdk-python` (optional)
  - Auth: WebSocket with credentials
  - File: `nanobot/channels/wecom.py`
  - Features: Media download/decrypt, message formatting

- Matrix - Homeserver URL + Access Token
  - SDK: `matrix-nio[e2e]` (optional)
  - Auth: Token-based connection
  - File: `nanobot/channels/matrix.py`
  - Features: End-to-end encryption, markdown support

- WhatsApp - Node.js bridge via WebSocket
  - SDK: `@whiskeysockets/baileys` (Node.js)
  - Auth: QR code scan, session tokens stored locally
  - File: `bridge/src/` (TypeScript), `nanobot/channels/whatsapp.py`
  - Connection: WebSocket to Node.js bridge (default: `ws://localhost:3001`)

- QQ (QQ Bot) - Bot ID + Secret
  - SDK: `qq-botpy`
  - Auth: Token-based
  - File: `nanobot/channels/qq.py`

- Discord - Bot token + Intents
  - File: `nanobot/channels/discord.py`

- MoChat - Custom OAuth integration
  - File: `nanobot/channels/mochat.py`
  - Features: Skill registry integration, public skill search/install

- Email - SMTP configuration
  - File: `nanobot/channels/email.py`
  - Auth: SMTP server, username, password

## Data Storage

**Databases:**
- Not applicable - No database integration in core
- File-based storage only

**File Storage:**
- Local filesystem only
  - Session history: `~/.nanobot/sessions/`
  - Media files: `~/.nanobot/media/`
  - Configuration: `~/.nanobot/config.json`
  - Workspace: `~/.nanobot/workspace/` (default, configurable)

**Memory & State:**
- JSON file-based persistent store (`opengui/memory/store.py`)
  - Path: `{store_dir}/memory.json`
  - Format: Single JSON file with atomic writes via tempfile
  - Features: Append-only message logging, LLM cache optimization

- Session history (`nanobot/session/manager.py`)
  - JSONL format for message history
  - Path: `~/.nanobot/sessions/{key}.jsonl`
  - Features: Conversation consolidation, summary extraction to MEMORY.md/HISTORY.md

**Caching:**
- None detected - No built-in caching layer
- LiteLLM handles provider-side caching (e.g., Anthropic prompt caching if supported)

## Authentication & Identity

**Auth Provider:**
- Custom token-based authentication per channel
- OAuth 2.0 support for specific providers (OpenAI Codex, GitHub Copilot, Feishu)
- Environment variable-based API key management

**Implementation:**
- Per-channel auth credentials stored in `~/.nanobot/config.json`
- Config schema: `nanobot/config/schema.py` with `ProviderConfig` fields (`api_key`, `api_base`, `extra_headers`)
- OAuth flow: `oauth-cli-kit` package for OAuth token lifecycle

## Monitoring & Observability

**Error Tracking:**
- None built-in - Relies on logging only

**Logs:**
- Loguru-based structured logging to stderr/files
- Log levels: DEBUG, INFO, WARNING, ERROR
- Integration with external tools via loguru hooks (if configured)

**LLM Observability (Optional):**
- LangSmith integration available via optional `langsmith` dependency
  - Enabled via `LANGSMITH_API_KEY` environment variable
  - Tracing: `litellm_provider.py` detects and respects LangSmith config

## CI/CD & Deployment

**Hosting:**
- Self-hosted (Docker containers recommended)
- Docker image: Based on `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
- Docker Compose: `docker-compose.yml` with `nanobot-gateway` service
- Resource limits: CPU 1 core, memory 1GB (default; configurable)

**CI Pipeline:**
- Not detected in codebase
- GitHub-based (implied from README and HKUDS/nanobot repository)

## Environment Configuration

**Required env vars (for LLM providers):**
- `ANTHROPIC_API_KEY` - Anthropic Claude access
- `OPENAI_API_KEY` - OpenAI or OpenAI-compatible gateways (AiHubMix, SiliconFlow, etc.)
- `OPENROUTER_API_KEY` - OpenRouter gateway
- Provider-specific keys: `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, etc.

**Optional observability:**
- `LANGSMITH_API_KEY` - LangSmith tracing (if installed)

**Secrets location:**
- Environment variables (recommended for Docker)
- Config file: `~/.nanobot/config.json` (local development, user-owned)
- Both support nested structure via `NANOBOT_PROVIDERS__<PROVIDER>__API_KEY`

## Webhooks & Callbacks

**Incoming:**
- Gateway port 18790: Accepts client WebSocket connections
- Channel-specific WebSocket servers: DingTalk, WhatsApp, Telegram, etc.
- HTTP-based webhooks: Some channels support webhook ingestion (Discord, Slack via Socket Mode)

**Outgoing:**
- Channel message delivery: All channels send responses back to source platform
- Tool execution: External API calls via HTTPX for web search, content fetch, etc.
- MCP (Model Context Protocol): Bidirectional tool invocation with Claude via stdio/SSE/HTTP
  - Config: `tools.mcp_servers` in `nanobot/config/schema.py`

## External Tools & Skills

**Web Search:**
- Provider options: `brave`, `tavily`, `duckduckgo`, `searxng`, `jina`
- Config: `tools.web.search` with `api_key` and `base_url`
- Client: `ddgs` (DuckDuckGo Search) or provider-specific SDK

**Web Content Retrieval:**
- Readability: `readability-lxml` for article extraction

**Proxy Support:**
- HTTP/SOCKS5 proxy via `python-socks[asyncio]` and `socksio`
- Config: `tools.web.proxy` (e.g., `"http://127.0.0.1:7890"` or `"socks5://127.0.0.1:1080"`)

---

*Integration audit: 2026-03-17*
