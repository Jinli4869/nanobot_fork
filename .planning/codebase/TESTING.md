# Testing Patterns

**Analysis Date:** 2026-03-17

## Test Framework

**Runner:**
- pytest 9.0.0+
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`
- asyncio_mode: `auto` (handles async test discovery automatically)
- testpaths: `["tests"]`

**Async Support:**
- pytest-asyncio 1.3.0+ for async test execution
- Configure with `asyncio_mode = "auto"` to auto-detect `async def test_*` functions
- Decorator `@pytest.mark.asyncio` on async test functions

**Assertion Library:**
- Standard `assert` statements (pytest's assertion introspection)
- Pytest's context managers: `pytest.raises(ExceptionType, match="pattern")`

**Run Commands:**
```bash
pytest tests/                    # Run all tests
pytest tests/ -v                 # Verbose output
pytest tests/ -k test_name       # Run specific test
pytest tests/ -x                 # Stop on first failure
pytest tests/test_file.py::TestClass::test_method  # Run specific test
```

## Test File Organization

**Location:**
- Tests co-located in separate `/tests` directory (not alongside source)
- One test file per major source module: `test_base_channel.py` for `nanobot/channels/base.py`
- Integration tests grouped by feature: `test_dingtalk_channel.py`, `test_telegram_channel.py`

**Naming:**
- Test files: `test_*.py`
- Test functions: `def test_*()` or `async def test_*()`
- Test classes: `class Test*:` or `class TestFeatureName:`
- Example: `TestMemoryConsolidationTypeHandling`, `TestHandleStop`, `TestDispatch`

**File count:** 457 tests across 28+ test files
- Largest: `test_matrix_channel.py` (1318 lines)
- Core tests: `test_base_channel.py`, `test_evaluator.py`, `test_opengui.py`, `test_cron_service.py`

## Test Structure

**Suite Organization:**
```python
# From test_task_cancel.py - Class-based organization
class TestHandleStop:
    @pytest.mark.asyncio
    async def test_stop_no_active_task(self):
        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "No active task" in out.content

    @pytest.mark.asyncio
    async def test_stop_cancels_active_task(self):
        # Additional test...
```

**Patterns:**
- **Setup in test methods:** Create fixtures inline (MessageBus, config objects)
- **Teardown:** Use try/finally for cleanup (e.g., `loop.stop()`)
- **Assertion style:** Direct `assert` with pytest introspection
- **Context managers:** `pytest.raises()` for exception testing

## Mocking

**Framework:** `unittest.mock`

**Import patterns:**
```python
from unittest.mock import AsyncMock, MagicMock, patch
```

**Async Mocking:**
- Use `AsyncMock()` for coroutines
- Set return value: `AsyncMock(return_value=LLMResponse(...))`
- Assert calls: `mock.assert_awaited_once_with(...)`

**Patching:**
- Use `patch()` context manager: `with patch("module.path.to.Class") as MockClass:`
- Monkeypatch for attribute replacement: `monkeypatch.setattr(obj, "attr", value)`
- Example from `test_opengui.py`:
  ```python
  async def test_adb_backend_resolves_relative_tap(monkeypatch: pytest.MonkeyPatch) -> None:
      backend = AdbBackend()
      backend._screen_width = 200
      backend._screen_height = 400
      run_mock = AsyncMock(return_value="")
      monkeypatch.setattr(backend, "_run", run_mock)

      action = parse_action({...})
      await backend.execute(action)

      run_mock.assert_awaited_once_with("shell", "input", "tap", str(expected_x), str(expected_y), timeout=5.0)
  ```

**Recording Mocks:**
- Custom mock classes that track calls: `class _RecordingLLM(_ScriptedLLM):`
- Capture message history for assertion: `self.calls: list[list[dict]] = []`
- Example from `test_opengui.py`:
  ```python
  class _RecordingLLM(_ScriptedLLM):
      def __init__(self, responses: list[LLMResponse]) -> None:
          super().__init__(responses)
          self.calls: list[list[dict]] = []

      async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
          self.calls.append(copy.deepcopy(messages))
          return await super().chat(messages, tools=tools, tool_choice=tool_choice)
  ```

**What to Mock:**
- External service APIs (HTTP clients, LLM providers)
- File I/O operations for deterministic testing
- Time-dependent behavior (asyncio.sleep, Clock)
- Channel handlers and platform-specific SDKs

**What NOT to Mock:**
- Core business logic (message routing, memory consolidation)
- Data structures (dataclasses, pydantic models)
- Simple utilities and helpers
- Standard library functions (unless time-dependent)

## Fixtures and Factories

**Test Data:**
```python
# From test_memory_consolidation_types.py
def _make_messages(message_count: int = 30):
    """Create a list of mock messages."""
    return [
        {"role": "user", "content": f"msg{i}", "timestamp": "2026-01-01 00:00"}
        for i in range(message_count)
    ]

def _make_tool_response(history_entry, memory_update):
    """Create an LLMResponse with a save_memory tool call."""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="call_1",
                name="save_memory",
                arguments={
                    "history_entry": history_entry,
                    "memory_update": memory_update,
                },
            )
        ],
    )
```

**Custom Test Helpers:**
- Prefix with underscore: `_make_messages()`, `_make_loop()`, `_FakeResponse`, `_DummyChannel`
- Define at module level above test classes
- Example helper from `test_task_cancel.py`:
  ```python
  def _make_loop():
      """Create a minimal AgentLoop with mocked dependencies."""
      from nanobot.agent.loop import AgentLoop
      from nanobot.bus.queue import MessageBus

      bus = MessageBus()
      provider = MagicMock()
      provider.get_default_model.return_value = "test-model"
      # ... more setup ...
      return loop, bus
  ```

**Pytest Fixtures:**
- Built-in fixtures used: `tmp_path` (temporary directory), `monkeypatch` (attribute patching)
- Example usage from `test_opengui.py`:
  ```python
  @pytest.mark.asyncio
  async def test_agent_failure_keeps_last_trace_path(tmp_path: Path) -> None:
      agent = GuiAgent(
          _ScriptedLLM([...]),
          DryRunBackend(),
          artifacts_root=tmp_path / "runs",
          max_steps=1,
      )
  ```

**Location:**
- Helpers defined at top of test module
- Shared fixtures would go in `conftest.py` (currently minimal/absent)

## Coverage

**Requirements:** None enforced in codebase

**Current state:** No coverage configuration visible in `pyproject.toml`

**Test count:** 457 test cases across 28 test files (significant coverage achieved through examples)

## Test Types

**Unit Tests:**
- Scope: Single function or class in isolation
- Approach: Mock external dependencies, test logic paths
- Examples: `test_is_allowed_requires_exact_match()`, `test_parse_scroll_allows_center_default()`
- Pattern: Inline setup, single assertion focus

**Integration Tests:**
- Scope: Multiple components working together
- Approach: Real MessageBus, actual channel handler behavior
- Examples: `test_group_message_keeps_sender_id_and_routes_chat_id()` (channel + bus)
- Pattern: Create real objects, exercise end-to-end flow

**Regression Tests:**
- Purpose: Prevent reintroduction of bugs
- Example: `test_dict_arguments_serialized_to_json()` - regression for issue #1042
- Pattern: Minimal test case that reproduces the bug

**Async Tests:**
- Mark: `@pytest.mark.asyncio`
- Pattern: Use `await asyncio.wait_for(..., timeout=1.0)` to prevent hanging
- Example from `test_task_cancel.py`:
  ```python
  @pytest.mark.asyncio
  async def test_stop_cancels_active_task(self):
      loop, bus = _make_loop()
      cancelled = asyncio.Event()

      async def slow_task():
          try:
              await asyncio.sleep(60)
          except asyncio.CancelledError:
              cancelled.set()
              raise

      task = asyncio.create_task(slow_task())
      await asyncio.sleep(0)
      loop._active_tasks["test:c1"] = [task]

      msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
      await loop._handle_stop(msg)

      assert cancelled.is_set()
      out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
      assert "stopped" in out.content.lower()
  ```

## Common Patterns

**Async Testing:**
```python
# Waiting for results with timeout to prevent hangs
out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
assert out.content == "expected"

# Managing long-running background tasks
try:
    # test code
finally:
    service.stop()
```

**Error Testing:**
```python
# Using pytest.raises context manager
def test_add_job_rejects_unknown_timezone(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")

    with pytest.raises(ValueError, match="unknown timezone 'America/Vancovuer'"):
        service.add_job(
            name="tz typo",
            schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Vancovuer"),
            message="hello",
        )

    assert service.list_jobs(include_disabled=True) == []
```

**Dummy/Fake Objects:**
```python
# Lightweight test doubles for validation
class _DummyChannel(BaseChannel):
    name = "dummy"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        return None

# Fake HTTP for network testing
class _FakeHttp:
    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses) if responses else []

    async def post(self, url: str, json=None, headers=None, **kwargs):
        self.calls.append({"method": "POST", "url": url, "json": json, "headers": headers})
        return self._next_response()
```

**State Verification:**
```python
# Track order of execution for concurrent code
order = []

async def mock_process(m, **kwargs):
    order.append(f"start-{m.content}")
    await asyncio.sleep(0.05)
    order.append(f"end-{m.content}")
    return OutboundMessage(channel="test", chat_id="c1", content=m.content)

# ... run test ...
assert order == ["start-a", "start-b", "end-a", "end-b"]  # Verification
```

---

*Testing analysis: 2026-03-17*
