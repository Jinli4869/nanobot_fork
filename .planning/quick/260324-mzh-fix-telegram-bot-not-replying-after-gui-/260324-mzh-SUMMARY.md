---
phase: quick
plan: 260324-mzh
subsystem: agent-loop
tags: [bug-fix, telegram, dispatch, typing-indicator]
dependency_graph:
  requires: []
  provides: [typing-stop-on-all-channels]
  affects: [nanobot/agent/loop.py, nanobot/channels/telegram.py]
tech_stack:
  added: []
  patterns: [publish-empty-outbound-for-cleanup]
key_files:
  modified: [nanobot/agent/loop.py]
  created: [tests/test_dispatch_typing_stop.py]
decisions:
  - "Replace elif msg.channel == 'cli': with else: in _dispatch so all channels receive empty OutboundMessage cleanup signal when _process_message returns None"
metrics:
  duration: 5 min
  completed: 2026-03-24
---

# Quick Task 260324-mzh: Fix Telegram Bot Not Replying After GUI Task Completion

**One-liner:** Replace `elif msg.channel == "cli":` with `else:` in `_dispatch` so every channel (Telegram, Discord, Matrix, CLI) receives an empty `OutboundMessage` when `_process_message` returns `None`, triggering `_stop_typing` cleanup on non-CLI channels.

## What Was Done

### Task 1: Fix `_dispatch` in `nanobot/agent/loop.py`

Changed line 574 from:
```python
elif msg.channel == "cli":
```
to:
```python
else:
```

When `_process_message` returns `None` (because `MessageTool` already sent the response during the turn), `_dispatch` now publishes an empty `OutboundMessage` for **every** channel. Each channel's `send()` calls `_stop_typing` before checking content, so typing indicators are cleared on Telegram/Discord/Matrix. CLI behaviour is unchanged.

Commit: `5d76244`

### Task 2: Regression test in `tests/test_dispatch_typing_stop.py`

Three `@pytest.mark.asyncio` tests using the `_make_loop` helper pattern from `test_opengui_agent_loop.py`:

1. `test_dispatch_publishes_empty_outbound_for_telegram_when_response_none` — non-CLI channel receives empty OutboundMessage
2. `test_dispatch_publishes_empty_outbound_for_cli_when_response_none` — CLI channel still receives empty OutboundMessage (preserved)
3. `test_dispatch_publishes_actual_response_when_not_none` — real response is forwarded as-is

All 3 pass. Existing 11 `test_opengui_agent_loop.py` tests remain green.

Commit: `5124b0d`

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `nanobot/agent/loop.py` modified: FOUND
- `tests/test_dispatch_typing_stop.py` created: FOUND
- Commit `5d76244` (fix): FOUND
- Commit `5124b0d` (test): FOUND
- All 3 regression tests: PASS
- All 11 existing loop tests: PASS
