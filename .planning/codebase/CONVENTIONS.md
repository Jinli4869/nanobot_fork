# Coding Conventions

**Analysis Date:** 2026-03-17

## Naming Patterns

**Files:**
- Lowercase with underscores: `base_channel.py`, `message_bus.py`, `dingtalk.py`
- Test files prefixed with `test_`: `test_opengui.py`, `test_base_channel.py`
- Internal/private helpers prefixed with underscore: `_DummyChannel`, `_FakeResponse`, `_make_messages()`

**Functions:**
- snake_case: `publish_inbound()`, `consume_inbound()`, `transcribe_audio()`
- Leading underscore for private/internal: `_safe_chat()`, `_sanitize_empty_content()`, `_handle_message()`
- Test functions use descriptive pattern: `test_add_job_rejects_unknown_timezone()`, `test_group_message_keeps_sender_id_and_routes_chat_id()`

**Variables:**
- snake_case: `sender_id`, `chat_id`, `allow_list`, `max_tokens`
- Constants in UPPERCASE: `_CHAT_RETRY_DELAYS`, `_TRANSIENT_ERROR_MARKERS`, `_IMAGE_UNSUPPORTED_MARKERS`

**Types:**
- PascalCase for classes: `BaseChannel`, `MessageBus`, `LLMResponse`, `ToolCallRequest`
- Type aliases use PascalCase: `OutboundMessage`, `InboundMessage`, `GenerationSettings`
- Dataclass fields use lowercase with type hints

## Code Style

**Formatting:**
- Tool: `ruff`
- Line length: 100 characters (configured in `pyproject.toml`)
- Target version: Python 3.11+

**Linting:**
- Tool: `ruff`
- Selected rules: `E`, `F`, `I`, `N`, `W` (Error, Pyflakes, isort, pep8-naming, Warnings)
- Ignored: `E501` (line length enforced via ruff's formatter, not as a lint error)

**Future Annotations:**
- Standard practice: `from __future__ import annotations` at top of every module
- Found in: `nanobot/channels/base.py`, `nanobot/config/paths.py`, all test files
- Enables forward references and cleaner type hints

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first)
2. Standard library imports (abc, asyncio, json, pathlib, typing, etc.)
3. Third-party imports (pydantic, loguru, httpx, etc.)
4. Local nanobot imports (nanobot.*)

**Path Aliases:**
- No aliases configured in codebase
- Imports use absolute paths: `from nanobot.bus.queue import MessageBus`
- Conditional imports under `if TYPE_CHECKING:` for avoiding circular dependencies

**Example from `nanobot/channels/base.py`:**
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
```

## Error Handling

**Patterns:**
- Broad exception catching with logging fallback: `except Exception as e: logger.warning(...); return fallback_value`
- Example from `nanobot/channels/base.py` - `transcribe_audio()`:
  - Tries operation
  - Catches any exception with `logger.warning()`
  - Returns safe default (empty string)
- asyncio.CancelledError always re-raised: `except asyncio.CancelledError: raise`
- Transient error detection via marker strings (404, rate limit, timeout, etc.)

**Error Response Pattern:**
- LLMProvider returns `LLMResponse` with `finish_reason="error"` rather than raising
- Content field holds error message: `LLMResponse(content=f"Error calling LLM: {exc}", finish_reason="error")`

## Logging

**Framework:** `loguru`

**Import pattern:**
```python
from loguru import logger
```

**Usage patterns:**
- `logger.warning()`: Recoverable errors, fallbacks available
- `logger.info()`: Important state changes, decisions
- `logger.debug()`: Implementation details
- `logger.exception()`: Critical failures before fallback
- Format string style: `logger.warning("text: {}", variable)` with positional placeholders

**Examples from codebase:**
```python
logger.warning("{}: audio transcription failed: {}", self.name, e)
logger.warning("{}: allow_from is empty — all access denied", self.name)
logger.info("evaluate_response: should_notify={}, reason={}", should_notify, reason)
```

## Comments

**When to Comment:**
- Explain the "why" not the "what" — code structure shows what it does
- Document non-obvious design decisions (retry logic, fallback behavior)
- Mark intentional deviations from conventions

**Docstrings:**
- Module level: Single-line summary of purpose
- Class level: Multi-line explaining responsibility and interface
- Method level: Brief description, Args, Returns, Raises (if applicable)
- Example from `nanobot/providers/base.py`:
  ```python
  """Base LLM provider interface."""
  ```

**Docstring Style (Google/Numpy hybrid):**
```python
def method(self, param1: str) -> bool:
    """Brief description.

    Longer explanation if needed.

    Args:
        param1: Parameter description.

    Returns:
        Boolean indicating success.
    """
```

## Function Design

**Size:** Keep functions focused and under 50 lines where possible; complex retry/sanitization logic acceptable in utilities

**Parameters:**
- Use type hints throughout: `def method(self, sender_id: str) -> bool:`
- Union types with pipe syntax: `str | None`, `list[dict[str, Any]] | None`
- Default to None for optional parameters
- Avoid positional-only; use named parameters for clarity

**Return Values:**
- Explicit return types: `-> bool`, `-> str`, `-> LLMResponse`
- Return default/safe values on error rather than None when possible
  - `return ""` instead of `None` for strings
  - `return False` instead of `None` for booleans
- Return compound objects (dataclasses) for multiple related values

**Example from `nanobot/bus/queue.py`:**
```python
async def consume_inbound(self) -> InboundMessage:
    """Consume the next inbound message (blocks until available)."""
    return await self.inbound.get()
```

## Module Design

**Exports:**
- Use `__all__` lists explicitly in modules that define public APIs
- Classes are public by default; prefix with underscore if private
- Test helpers prefixed with underscore: `_make_messages()`, `_make_tool_response()`

**Dataclasses:**
- Use `@dataclass` for data structures: `ToolCallRequest`, `LLMResponse`, `GenerationSettings`
- Include field docstrings for clarity
- Use `field(default_factory=...)` for mutable defaults
- Frozen dataclasses for immutable configuration: `@dataclass(frozen=True)` for `GenerationSettings`

**Abstract Base Classes:**
- Define interfaces with ABC and `@abstractmethod`
- Example: `nanobot/channels/base.py` defines `BaseChannel` with abstract `start()`, `stop()`, `send()`
- Concrete implementations in separate modules: `dingtalk.py`, `telegram.py`, etc.

**Type Hints:**
- Use `from typing import TYPE_CHECKING` for conditional imports
- Leverage `|` syntax for unions (Python 3.10+)
- Use `Any` sparingly, with comments explaining why

**Example from `nanobot/providers/base.py`:**
```python
if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig

class LLMProvider(ABC):
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base
        self.generation: GenerationSettings = GenerationSettings()
```

---

*Convention analysis: 2026-03-17*
