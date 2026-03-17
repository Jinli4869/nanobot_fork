# Architecture

**Analysis Date:** 2026-03-17

## Pattern Overview

**Overall:** Layered Agent-Bus-Channel Pattern

**Key Characteristics:**
- Decoupled message bus separates chat channels from the agent core
- Pluggable channel system enabling multi-platform support (Telegram, Discord, Slack, etc.)
- Tool-based agent execution with LLM provider abstraction
- Session and memory persistence for context continuity
- Async-first design using asyncio for concurrent operations

## Layers

**Channels Layer:**
- Purpose: Handle incoming/outgoing messages from chat platforms
- Location: `nanobot/channels/`
- Contains: Platform-specific implementations (Telegram, Discord, Slack, Matrix, Feishu, DingTalk, etc.)
- Depends on: MessageBus for publishing/consuming messages
- Used by: ChannelManager

**Bus Layer:**
- Purpose: Async message queue decoupling channels from agent
- Location: `nanobot/bus/`
- Contains: MessageBus (inbound/outbound async queues), InboundMessage, OutboundMessage data classes
- Depends on: Nothing (pure async queue implementation)
- Used by: Channels, ChannelManager, AgentLoop

**Agent Layer:**
- Purpose: Core agent logic and decision-making
- Location: `nanobot/agent/`
- Contains: AgentLoop (main iteration), ContextBuilder (prompt assembly), MemoryConsolidator (persistence), ToolRegistry, SubagentManager
- Depends on: Bus, Providers, Session, Config
- Used by: CLI

**Providers Layer:**
- Purpose: LLM abstraction supporting multiple vendors
- Location: `nanobot/providers/`
- Contains: Base provider interface, implementations for OpenAI, Azure OpenAI, Anthropic, DeepSeek, Groq, Ollama, etc.
- Depends on: litellm for unified API
- Used by: AgentLoop, HeartbeatService, MemoryConsolidator

**Session & Memory Layer:**
- Purpose: Conversation history and agent memory persistence
- Location: `nanobot/session/`, `nanobot/agent/memory.py`
- Contains: SessionManager (manages Session objects), MemoryConsolidator (summarizes and saves to MEMORY.md/HISTORY.md)
- Depends on: FileSystem
- Used by: AgentLoop

**Skills & Tools Layer:**
- Purpose: Extensible capabilities for agent
- Location: `nanobot/agent/tools/`, `nanobot/skills/`
- Contains: Tool registry and implementations (filesystem, web, shell, message, spawn, MCP, cron)
- Depends on: Base Tool interface
- Used by: AgentLoop during iteration

**Config Layer:**
- Purpose: Configuration management
- Location: `nanobot/config/`
- Contains: Schema definition (Pydantic models), loader, paths management
- Depends on: Pydantic
- Used by: CLI, all main services

**CLI Layer:**
- Purpose: User interface and command entry point
- Location: `nanobot/cli/`
- Contains: Typer-based commands, interactive/batch mode runners, prompt_toolkit integration
- Depends on: All layers
- Used by: End user

## Data Flow

**Message Processing Flow:**

1. **Inbound:** User sends message to platform (Telegram/Discord/etc)
2. **Channel Receives:** Platform channel implementation captures message, creates InboundMessage
3. **Bus Publish:** Channel publishes to bus.inbound queue
4. **Agent Consumes:** AgentLoop.run() consumes from bus.inbound
5. **Context Build:** ContextBuilder assembles system prompt + message history + memory + skills
6. **LLM Call:** AgentLoop calls provider.chat_with_retry(messages, tools)
7. **Tool Loop:** If LLM returns tool_calls, execute each via ToolRegistry, add results to messages
8. **Final Response:** Once LLM returns text (no tool calls), add to session and create OutboundMessage
9. **Bus Publish:** AgentLoop publishes OutboundMessage to bus.outbound
10. **Dispatch:** ChannelManager._dispatch_outbound() routes to appropriate channel.send()
11. **Platform Send:** Channel sends response back to user

**State Management:**
- **Session State:** Conversation messages stored in `workspace/sessions/` as JSONL files
- **Memory State:** Persistent facts in `workspace/MEMORY.md`, daily summaries in `workspace/HISTORY.md`
- **Config State:** Global config in `~/.nanobot/config.json`, workspace-specific in `workspace/`
- **Append-Only Messages:** Session messages are append-only to enable LLM prompt caching

## Key Abstractions

**MessageBus:**
- Purpose: Decouple channels from agent processing
- Examples: `nanobot/bus/queue.py`, `nanobot/bus/events.py`
- Pattern: Simple async queue with inbound (channel→agent) and outbound (agent→channel) queues

**BaseChannel:**
- Purpose: Abstract interface for chat platforms
- Examples: `nanobot/channels/telegram.py`, `nanobot/channels/slack.py`, `nanobot/channels/matrix.py`
- Pattern: Each platform implements async start(), stop(), send(msg), and handles platform-specific authentication

**LLMProvider:**
- Purpose: Abstract interface for language models
- Examples: `nanobot/providers/anthropic.py`, `nanobot/providers/openai_codex_provider.py`
- Pattern: Unified chat_with_retry() interface, supports tool calling and streaming

**Tool:**
- Purpose: Executable capabilities for agent
- Examples: `nanobot/agent/tools/filesystem.py`, `nanobot/agent/tools/web.py`, `nanobot/agent/tools/shell.py`
- Pattern: Abstract base with name, description, parameters, and async execute()

**SkillsLoader:**
- Purpose: Load and manage optional skill documentation
- Examples: `nanobot/skills/github/`, `nanobot/skills/memory/`, `nanobot/skills/summarize/`
- Pattern: SKILL.md files in skill directories teach agent how to use advanced features

## Entry Points

**CLI:**
- Location: `nanobot/cli/commands.py`
- Triggers: `nanobot` or `nanobot run` command
- Responsibilities: Parse config, initialize channels, start agent loop, handle interactive/batch modes

**Agent Loop:**
- Location: `nanobot/agent/loop.py` — AgentLoop.run()
- Triggers: Called by CLI after channels initialized
- Responsibilities: Consume inbound messages, build context, call LLM, execute tools, publish outbound

**Channel Start:**
- Location: `nanobot/channels/*/` — Each channel's async start() method
- Triggers: ChannelManager.start_all()
- Responsibilities: Connect to platform, listen for incoming messages, publish to bus.inbound

**Heartbeat Service:**
- Location: `nanobot/heartbeat/service.py`
- Triggers: Optional periodic timer (default 30min)
- Responsibilities: Check HEARTBEAT.md for background tasks, wake agent to process them

**Cron Service:**
- Location: `nanobot/cron/service.py`
- Triggers: Scheduled by workspace cron jobs
- Responsibilities: Evaluate and execute scheduled tasks defined in workspace

## Error Handling

**Strategy:** Log and continue on channel/tool errors; fail fast on config/auth errors

**Patterns:**
- Channel errors logged but don't crash other channels (ChannelManager._start_channel)
- Tool errors caught and returned as string result (ToolRegistry.execute)
- LLM errors trigger response.finish_reason="error" (AgentLoop logs and breaks iteration)
- Provider connection retries via chat_with_retry (configurable backoff in base provider)

## Cross-Cutting Concerns

**Logging:** Loguru configured globally; all modules use logger = logger from loguru

**Validation:** Pydantic models validate config at load time (Config, ChannelsConfig, AgentDefaults)

**Authentication:** Provider API keys from config; channel auth handled per-platform via BaseChannel subclasses

**Media Handling:** Channels convert platform-specific media to URLs; MediaDownloadTool handles downloads to workspace/media/

**Session Isolation:** Each (channel:chat_id) pair has isolated session and MessageBus context via session_key
