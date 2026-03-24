---
phase: quick
plan: 260324-wak
subsystem: gui-memory
tags: [gui, memory, wiring, opengui, nanobot]
dependency_graph:
  requires: []
  provides: [nanobot-gui-memory-retriever]
  affects: [nanobot/agent/tools/gui.py, tests/test_opengui_p6_wiring.py]
tech_stack:
  added: []
  patterns: [default-opengui-memory-dir, fail-soft-memory-init]
key_files:
  modified: [nanobot/agent/tools/gui.py, tests/test_opengui_p6_wiring.py]
  created: []
decisions:
  - "Nanobot GUI wiring now reads memory from ~/.opengui/memory to match the user's existing OpenGUI memory store"
  - "Memory retriever initialization is gated by gui.embedding_model via the existing embedding adapter"
  - "Retriever construction failures log warnings and fall back to memoryless execution"
metrics:
  duration: 15 min
  completed: 2026-03-24
---

# Quick Task 260324-wak: Wire Nanobot GUI Tool To OpenGUI Memory

**One-liner:** Nanobot's `gui_task` now builds an OpenGUI `MemoryRetriever` from `~/.opengui/memory` and injects it into `GuiAgent` whenever `gui.embedding_model` is configured.

## What Changed

- `nanobot/agent/tools/gui.py`
  Added `DEFAULT_OPENGUI_MEMORY_DIR` and `_build_memory_retriever()`, then wired the returned retriever into `GuiAgent(memory_retriever=...)`.

- `nanobot/agent/tools/gui.py`
  The retriever is rebuilt per GUI task from the markdown memory store so fresh edits to `os_guide.md` or related files are visible on the next run.

- `tests/test_opengui_p6_wiring.py`
  Added regression tests covering:
  - default OpenGUI memory directory loading
  - pass-through of the built retriever into `GuiAgent`

## Verification

- `uv run pytest tests/test_opengui_p6_wiring.py tests/test_opengui_p8_trajectory.py tests/test_opengui_p3_nanobot.py tests/test_opengui_p11_integration.py`
- Result: `53 passed`

## Follow-up

- Your local `~/.nanobot/config.json` still needs a `gui.embeddingModel` value for this wiring to activate at runtime.
