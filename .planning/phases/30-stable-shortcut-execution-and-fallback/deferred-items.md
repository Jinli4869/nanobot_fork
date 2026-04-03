# Deferred Items

## 2026-04-03

- Full-suite verification hit an unrelated existing failure in `tests/channels/test_matrix_channel.py::test_on_media_message_downloads_attachment_and_sets_metadata`:
  expected one downloaded media path, got `[]`.
  This plan only touched shortcut execution wiring (`opengui/agent.py`, `opengui/skills/multi_layer_executor.py`, `nanobot/agent/tools/gui.py`, `tests/test_opengui_p30_stable_shortcut_execution.py`), so the Matrix channel regression is out of scope for `30-01`.

- Full-suite verification for `30-03` reported 15 unrelated existing failures across CLI defaults, legacy skill-executor wiring tests, router concurrency tests, older nanobot GUI extraction coverage, memory retriever wiring, and one settle-timing expectation outside the Phase 30 fallback file. The new Phase 30 coverage file itself passed cleanly (`uv run python -m pytest tests/test_opengui_p30_stable_shortcut_execution.py -q --tb=short` -> `15 passed in 3.31s`), so these broader suite failures were logged instead of fixed.
