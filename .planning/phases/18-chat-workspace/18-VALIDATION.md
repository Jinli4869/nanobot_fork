---
phase: 18
slug: chat-workspace
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-21
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run --extra dev pytest tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_commands.py -q` |
| **Full suite command** | `uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_commands.py -q` |
| **Estimated runtime** | ~20 seconds |

**Fallback command (current local sandbox):** `.venv/bin/python -m pytest tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_commands.py -q`

---

## Sampling Rate

- **After every 18-01 task commit:** Run `uv run --extra dev pytest tests/test_tui_p18_chat.py tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py -q`
- **After every 18-02 task commit:** Run `uv run --extra dev pytest tests/test_tui_p18_streaming.py tests/test_tui_p18_chat.py -q`
- **After every 18-03 task commit:** Run `uv run --extra dev pytest tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_commands.py -q`
- **After every plan wave:** Run the smallest existing slice for that wave, then promote to the full suite after 18-03 Task 2
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | CHAT-01 | unit/api | `uv run --extra dev pytest tests/test_tui_p18_chat.py::test_chat_routes_create_and_reuse_session_backed_conversations tests/test_tui_p18_chat.py::test_chat_history_route_reads_persisted_session_state -q` | ❌ W0 | ⬜ pending |
| 18-01-02 | 01 | 1 | CHAT-01 | unit/api | `uv run --extra dev pytest tests/test_tui_p18_chat.py::test_chat_routes_create_and_reuse_session_backed_conversations tests/test_tui_p18_chat.py::test_chat_history_route_reads_persisted_session_state tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py -q` | ❌ W0 | ⬜ pending |
| 18-02-01 | 02 | 2 | CHAT-02 | unit/api | `uv run --extra dev pytest tests/test_tui_p18_streaming.py::test_sse_stream_emits_progress_and_final_reply_events tests/test_tui_p18_streaming.py::test_stream_transport_preserves_event_order_for_progress_and_final_message -q` | ❌ W0 | ⬜ pending |
| 18-02-02 | 02 | 2 | CHAT-02 | integration/api | `uv run --extra dev pytest tests/test_tui_p18_streaming.py::test_sse_stream_emits_progress_and_final_reply_events tests/test_tui_p18_streaming.py::test_stream_transport_preserves_event_order_for_progress_and_final_message tests/test_tui_p18_chat.py::test_chat_routes_create_and_reuse_session_backed_conversations -q` | ❌ W0 | ⬜ pending |
| 18-03-01 | 03 | 3 | CHAT-03 | integration/recovery | `uv run --extra dev pytest tests/test_tui_p18_chat.py::test_reconnect_recovers_recent_session_history_from_persisted_state tests/test_tui_p18_streaming.py::test_sse_stream_emits_progress_and_final_reply_events -q` | ❌ W0 | ⬜ pending |
| 18-03-02 | 03 | 3 | CHAT-03 | regression | `uv run --extra dev pytest tests/test_tui_p17_runtime.py tests/test_tui_p17_config.py tests/test_tui_p18_chat.py tests/test_tui_p18_streaming.py tests/test_commands.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_tui_p18_chat.py` — stubs for `CHAT-01` and `CHAT-03`
- [ ] `tests/test_tui_p18_streaming.py` — stubs for `CHAT-02`
- [ ] Existing Phase 17 runtime/config test slices stay green as chat routes are added

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Browser refresh after an in-flight streamed reply still shows the persisted final turn after reload | CHAT-03 | Best confirmed against a real browser consumer once the React client exists | Start `python -m nanobot.tui`, send a chat message from the future web client, refresh after completion, verify the session history view reloads the last assistant reply |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
