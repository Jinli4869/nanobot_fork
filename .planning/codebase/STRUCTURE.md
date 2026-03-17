# Codebase Structure

**Analysis Date:** 2026-03-17

## Directory Layout

```
nanobot_fork/
├── nanobot/                    # Main package
│   ├── agent/                  # Agent core and tools
│   ├── bus/                    # Message bus (channels ↔ agent)
│   ├── channels/               # Chat platform implementations
│   ├── cli/                    # CLI entry point and commands
│   ├── config/                 # Configuration and schema
│   ├── cron/                   # Scheduled task service
│   ├── gui/                    # Desktop GUI automation (experimental)
│   ├── heartbeat/              # Periodic wake-up service
│   ├── providers/              # LLM provider implementations
│   ├── security/               # Network security utilities
│   ├── session/                # Session management
│   ├── skills/                 # Built-in skill definitions
│   ├── templates/              # Default workspace templates
│   └── utils/                  # Helper utilities
│
├── opengui/                    # GUI automation module (separate package)
│   ├── agents/                 # GUI agent implementations
│   ├── backends/               # Platform-specific UI backends
│   ├── memory/                 # GUI state memory
│   ├── prompts/                # GUI reasoning prompts
│   ├── skills/                 # GUI-related skills
│   └── trajectory/             # Action/observation trajectory tracking
│
├── bridge/                     # Native bindings bridge (C extensions)
├── case/                       # Test case files
├── docs/                       # Documentation and planning
├── tests/                      # Unit and integration tests
├── .planning/                  # GSD planning artifacts
└── pyproject.toml              # Python package definition
```

## Directory Purposes

**`nanobot/agent/`:**
- Purpose: Core agent loop, context, memory, and tool management
- Contains: AgentLoop (main iteration engine), ContextBuilder, MemoryConsolidator, Skills loader, Tool registry
- Key files: `loop.py`, `context.py`, `memory.py`, `skills.py`, `subagent.py`

**`nanobot/bus/`:**
- Purpose: Async message queue decoupling channels from agent
- Contains: MessageBus, InboundMessage, OutboundMessage classes
- Key files: `queue.py`, `events.py`

**`nanobot/channels/`:**
- Purpose: Platform-specific chat channel implementations
- Contains: BaseChannel interface + implementations for Telegram, Discord, Slack, Matrix, Feishu, DingTalk, Email, WhatsApp, Wecom, QQ, Mochat, etc.
- Key files: `base.py`, `manager.py`, `registry.py`, `{platform}.py` (one per platform)

**`nanobot/cli/`:**
- Purpose: Command-line interface and entry point
- Contains: Typer CLI app, interactive/batch mode runners, prompt_toolkit REPL
- Key files: `commands.py` (800+ lines, main CLI dispatcher)

**`nanobot/config/`:**
- Purpose: Configuration management and schema
- Contains: Pydantic schema (Config, ChannelsConfig, AgentDefaults, ProvidersConfig), loader, paths
- Key files: `schema.py`, `loader.py`, `paths.py`

**`nanobot/cron/`:**
- Purpose: Scheduled task service
- Contains: Cron job definitions and execution, croniter integration
- Key files: `service.py`

**`nanobot/gui/`:**
- Purpose: Desktop GUI automation (experimental, underdeveloped)
- Contains: Placeholder/stub implementations for GUI interaction
- Key files: `__init__.py`, (minimal content)

**`nanobot/heartbeat/`:**
- Purpose: Periodic wake-up service for background tasks
- Contains: HeartbeatService that checks HEARTBEAT.md and triggers agent
- Key files: `service.py`

**`nanobot/providers/`:**
- Purpose: LLM provider abstraction and implementations
- Contains: Base provider interface, implementations (OpenAI, Azure OpenAI, Anthropic, DeepSeek, Groq, Ollama, etc.)
- Key files: `base.py` (interface), `openai_codex_provider.py`, `azure_openai_provider.py`, `litellm_provider.py`

**`nanobot/security/`:**
- Purpose: Network and execution security
- Contains: Network access control, path validation
- Key files: `network.py`

**`nanobot/session/`:**
- Purpose: Conversation session management
- Contains: Session class (append-only message store), SessionManager (JSONL file persistence)
- Key files: `manager.py`

**`nanobot/skills/`:**
- Purpose: Built-in skill definitions
- Contains: Directories per skill, each with SKILL.md and optional scripts
- Key files: `skill-creator/`, `memory/`, `github/`, `weather/`, `tmux/`, `clawhub/`, `cron/`, `summarize/`

**`nanobot/templates/`:**
- Purpose: Default workspace templates synced on startup
- Contains: Bootstrap files (AGENTS.md, SOUL.md, USER.md, TOOLS.md), memory templates
- Key files: `memory/` (template directory)

**`nanobot/utils/`:**
- Purpose: Shared utilities and helpers
- Contains: Token estimation, time formatting, file helpers
- Key files: `helpers.py`, `evaluator.py`

**`opengui/`:**
- Purpose: Desktop GUI automation (separate module, experimental)
- Contains: Agent for GUI interaction, action/observation tracking, backend abstractions
- Key files: `agent.py`, `action.py`, `observation.py`, `interfaces.py`

## Key File Locations

**Entry Points:**
- `nanobot/cli/commands.py`: CLI entry point (`nanobot` command via `pyproject.toml` scripts)
- `nanobot/__main__.py`: Package main module
- `nanobot/__init__.py`: Version and logo definition

**Configuration:**
- `nanobot/config/schema.py`: Pydantic models for all config
- `nanobot/config/loader.py`: Config loading from `~/.nanobot/config.json`
- `nanobot/config/paths.py`: Workspace and data directory resolution

**Core Logic:**
- `nanobot/agent/loop.py`: AgentLoop (main iteration, tool execution)
- `nanobot/agent/context.py`: ContextBuilder (prompt assembly)
- `nanobot/agent/memory.py`: MemoryConsolidator (session summarization)
- `nanobot/bus/queue.py`: MessageBus implementation
- `nanobot/channels/manager.py`: ChannelManager (channel coordination)
- `nanobot/providers/base.py`: LLMProvider base class

**Testing:**
- `tests/`: All test files (pytest)
- Files: `test_*.py` (one per component)

## Naming Conventions

**Files:**
- `{feature}.py`: Single feature modules (e.g., `logger.py`, `parser.py`)
- `{service_name}_provider.py`: Provider implementations (e.g., `openai_codex_provider.py`)
- `{platform}.py`: Channel implementations (e.g., `telegram.py`, `slack.py`)
- `test_{component}.py`: Test files (e.g., `test_exec_security.py`)
- `SKILL.md`: Skill definition files (always named SKILL.md in each skill dir)

**Directories:**
- `{component}/`: Feature modules (e.g., `agent/`, `channels/`)
- `skills/{skill_name}/`: Skill definitions (e.g., `skills/github/`, `skills/memory/`)
- `templates/{template_type}/`: Template directories (e.g., `templates/memory/`)

## Where to Add New Code

**New Feature:**
- Primary code: `nanobot/{feature_name}/` (create new module)
- Tests: `tests/test_{feature_name}.py`
- Add to imports: `nanobot/cli/commands.py` if CLI-exposed

**New Channel/Platform:**
- Implementation: `nanobot/channels/{platform}.py`
- Base class: Extend `nanobot/channels/base.py` (BaseChannel)
- Registration: Implement via entry_points in `pyproject.toml` or pkgutil discovery
- Config schema: Add to `nanobot/config/schema.py` (ChannelsConfig)

**New Tool:**
- Implementation: `nanobot/agent/tools/{tool_name}.py`
- Base class: Extend `nanobot/agent/tools/base.py` (Tool)
- Registration: Register in `AgentLoop._register_default_tools()` or ToolRegistry
- Schema: Define `name`, `description`, `parameters` properties

**New Skill:**
- Directory: `nanobot/skills/{skill_name}/`
- Definition: `nanobot/skills/{skill_name}/SKILL.md` (teaches agent how to use)
- Scripts: Optional `scripts/` subdirectory for supporting code
- Registration: Automatic via SkillsLoader (scans builtin and workspace skills)

**New Provider:**
- Implementation: `nanobot/providers/{provider_name}_provider.py`
- Base class: Extend `nanobot/providers/base.py` (LLMProvider)
- Registration: Add class method to provider registry or via entry_points
- Config: Add to `ProvidersConfig` in `nanobot/config/schema.py`

**Utilities:**
- Shared helpers: `nanobot/utils/helpers.py`
- Specialized utils: `nanobot/utils/{module}.py`

## Special Directories

**`workspace/` (default: `~/.nanobot/workspace/`):**
- Purpose: User data directory per agent instance
- Generated: Yes (created on first run)
- Committed: No (data directory, user-local)
- Contains: `config.json` (optional, overrides global), `sessions/`, `MEMORY.md`, `HISTORY.md`, `HEARTBEAT.md`, `media/`, `skills/`

**`.planning/codebase/`:**
- Purpose: GSD codebase analysis artifacts
- Generated: Yes (by /gsd:map-codebase command)
- Committed: Yes
- Contains: `ARCHITECTURE.md`, `STRUCTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `STACK.md`, `INTEGRATIONS.md`, `CONCERNS.md`

**`nanobot/skills/`:**
- Purpose: Built-in skills
- Generated: No (checked into repo)
- Committed: Yes
- Each skill is a directory with `SKILL.md` describing its capabilities

**`.pytest_cache/`:**
- Purpose: Pytest cache
- Generated: Yes (by pytest)
- Committed: No

**`bridge/`:**
- Purpose: Native C/C++ bindings (if needed for performance)
- Generated: No
- Committed: Yes (source only, binaries generated at build time)

## Code Organization Patterns

**Module Initialization:**
- Each module has `__init__.py` for public exports
- Top-level imports typically empty or minimal

**Async-First Design:**
- All I/O operations are async (asyncio)
- Sync wrappers in CLI only

**Provider Abstraction:**
- All LLM calls go through `LLMProvider.chat_with_retry()`
- Actual provider selected at runtime via config

**Tool Registry Pattern:**
- Tools registered dynamically via `ToolRegistry.register()`
- Tool definitions fetched for LLM via `ToolRegistry.get_definitions()`
- Tool execution routed via `ToolRegistry.execute()`

**Session Isolation:**
- Each conversation thread isolated by session_key
- Messages stored in JSONL for durability and append-only semantics
