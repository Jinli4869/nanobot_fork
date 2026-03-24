---
phase: quick
plan: 260324-mzh
type: execute
wave: 1
depends_on: []
files_modified:
  - nanobot/agent/loop.py
  - tests/test_dispatch_typing_stop.py
autonomous: true
must_haves:
  truths:
    - "Telegram typing indicator stops after GUI task completes even when _process_message returns None"
    - "All non-CLI channels receive an empty OutboundMessage when response is None, triggering channel-specific cleanup"
    - "Existing CLI empty-response behavior is preserved"
  artifacts:
    - path: "nanobot/agent/loop.py"
      provides: "Fixed _dispatch method"
      contains: "else:"
    - path: "tests/test_dispatch_typing_stop.py"
      provides: "Regression test for typing stop"
  key_links:
    - from: "nanobot/agent/loop.py (_dispatch)"
      to: "nanobot/channels/telegram.py (send)"
      via: "bus.publish_outbound(OutboundMessage) triggers channel.send() which calls _stop_typing"
      pattern: "publish_outbound.*OutboundMessage"
---

<objective>
Fix Telegram bot not replying after GUI task completion. When `_process_message` returns
None (because MessageTool already sent in-turn), the `_dispatch` method only publishes an
empty OutboundMessage for the CLI channel. Non-CLI channels (Telegram, Discord, Matrix)
get nothing, so their typing indicators persist indefinitely.

Purpose: Ensure all channels receive cleanup signals after processing completes.
Output: One-line fix in loop.py + regression test.
</objective>

<execution_context>
@/Users/jinli/.claude/get-shit-done/workflows/execute-plan.md
@/Users/jinli/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@nanobot/agent/loop.py (lines 567-587: _dispatch method)
@nanobot/agent/loop.py (lines 732-733: _process_message returning None)
@nanobot/channels/telegram.py (lines 342-350: send() calls _stop_typing)
@tests/test_opengui_agent_loop.py (existing test patterns: _make_loop, _inbound helpers)
</context>

<interfaces>
<!-- From nanobot/bus/events.py -->
OutboundMessage(channel: str, chat_id: str, content: str, metadata: dict)

<!-- From nanobot/agent/loop.py _dispatch (lines 567-587) -->
# Current broken code:
elif msg.channel == "cli":
    await self.bus.publish_outbound(OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id,
        content="", metadata=msg.metadata or {},
    ))

<!-- From nanobot/channels/telegram.py send() (lines 342-350) -->
# _stop_typing is called inside send() for non-progress messages:
if not msg.metadata.get("_progress", False):
    self._stop_typing(msg.chat_id)
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Fix _dispatch to publish empty OutboundMessage for all channels when response is None</name>
  <files>nanobot/agent/loop.py</files>
  <action>
In `_dispatch` method (line 574), change `elif msg.channel == "cli":` to `else:`.

This is a single-word change. The logic becomes:
```python
if response is not None:
    await self.bus.publish_outbound(response)
else:
    await self.bus.publish_outbound(OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id,
        content="", metadata=msg.metadata or {},
    ))
```

Why this works: When `_process_message` returns None (line 732-733, because MessageTool
already sent during the turn), `_dispatch` now publishes an empty OutboundMessage for
every channel. Each channel's `send()` method handles this appropriately:
- Telegram: `send()` calls `_stop_typing(chat_id)` at line 350 before checking content
- Discord: `send()` calls `_stop_typing(channel_id)` similarly
- Matrix: `send()` calls `_stop_typing_keepalive()` similarly
- CLI: Behavior unchanged (was already in the `elif` path)

Empty content is harmless: Telegram's `send()` returns early after `_stop_typing` when
there is no text/media to deliver (the content check happens after typing cleanup).
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -c "
import ast, sys
tree = ast.parse(open('nanobot/agent/loop.py').read())
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef) and node.name == '_dispatch':
        src = open('nanobot/agent/loop.py').read().split('\n')
        body = '\n'.join(src[node.lineno-1:node.end_lineno])
        assert 'elif msg.channel ==' not in body, 'Still has elif msg.channel check'
        assert 'else:' in body, 'Missing else clause'
        print('PASS: _dispatch uses else: instead of elif msg.channel == cli')
        sys.exit(0)
print('FAIL: _dispatch not found'); sys.exit(1)
"</automated>
  </verify>
  <done>Line 574 reads `else:` instead of `elif msg.channel == "cli":`. All channels now receive empty OutboundMessage when _process_message returns None.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add regression test for typing-stop on non-CLI channels</name>
  <files>tests/test_dispatch_typing_stop.py</files>
  <behavior>
    - Test 1: _dispatch publishes empty OutboundMessage for telegram channel when _process_message returns None
    - Test 2: _dispatch publishes empty OutboundMessage for cli channel when _process_message returns None (existing behavior preserved)
    - Test 3: _dispatch publishes the actual response when _process_message returns a non-None OutboundMessage
  </behavior>
  <action>
Create `tests/test_dispatch_typing_stop.py` following the pattern from
`tests/test_opengui_agent_loop.py` (_make_loop helper with mocked bus, provider,
patched _register_default_tools).

Three test cases:
1. `test_dispatch_publishes_empty_outbound_for_telegram_when_response_none`:
   - Build AgentLoop via _make_loop
   - Patch `_process_message` to return None (AsyncMock(return_value=None))
   - Call `await loop._dispatch(InboundMessage(channel="telegram", ...))`
   - Assert `bus.publish_outbound` was called once with OutboundMessage(channel="telegram", content="")

2. `test_dispatch_publishes_empty_outbound_for_cli_when_response_none`:
   - Same setup but channel="cli"
   - Assert `bus.publish_outbound` called with OutboundMessage(channel="cli", content="")

3. `test_dispatch_publishes_actual_response_when_not_none`:
   - Patch `_process_message` to return OutboundMessage(content="hello")
   - Assert `bus.publish_outbound` called with that exact OutboundMessage

Use `@pytest.mark.asyncio` decorator. Import from existing patterns in test_opengui_agent_loop.py.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork && python -m pytest tests/test_dispatch_typing_stop.py -x -v 2>&1 | tail -20</automated>
  </verify>
  <done>All 3 tests pass. Regression coverage confirms empty OutboundMessage is published for non-CLI channels when _process_message returns None.</done>
</task>

</tasks>

<verification>
1. `python -m pytest tests/test_dispatch_typing_stop.py -x -v` -- all 3 tests pass
2. `python -m pytest tests/test_opengui_agent_loop.py -x -v` -- existing tests still pass
3. Manual grep confirms no `elif msg.channel == "cli"` remains in _dispatch
</verification>

<success_criteria>
- The `elif msg.channel == "cli"` guard in _dispatch is replaced with `else:`
- 3 regression tests pass covering telegram, cli, and normal response paths
- Existing agent loop tests remain green
</success_criteria>

<output>
After completion, create `.planning/quick/260324-mzh-fix-telegram-bot-not-replying-after-gui-/260324-mzh-SUMMARY.md`
</output>
