---
phase: quick
plan: 260325-kgy
subsystem: gui-memory
tags: [gui, memory, planner, policy, split]
dependency_graph:
  requires: []
  provides: [gui-memory-split]
  affects: [nanobot/agent/loop.py, nanobot/agent/planner.py, nanobot/agent/capabilities.py, nanobot/agent/tools/gui.py, opengui/agent.py]
tech_stack:
  added: []
  patterns: [direct policy injection, guide-to-planner routing, split memory paths]
key_files:
  created:
    - tests/test_gui_memory_split.py
  modified:
    - nanobot/agent/capabilities.py
    - nanobot/agent/planner.py
    - nanobot/agent/loop.py
    - nanobot/agent/tools/gui.py
    - opengui/agent.py
decisions:
  - GUI guide entries (os/app/icon) now flow to the planner via PlanningContext.gui_memory_context; the GUI agent never sees them
  - Policy entries are injected directly into the GUI agent system prompt as raw text (no embedding search)
  - opengui CLI backward compat preserved via the existing memory_retriever fallback path in GuiAgent._retrieve_memory
metrics:
  duration: 6 min
  completed: 2026-03-25
  tasks_completed: 2
  files_modified: 5
  files_created: 1
---

# Quick Task 260325-kgy: GUI Memory Split — OS/App/Icon Guides to Planner, Policy Direct to GUI Agent

Split GUI memory usage by type: os_guide / app_guide / icon_guide entries go to the planner for task-aware decomposition, while policy entries are injected fully and directly into the GUI agent system prompt without search filtering.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Extend PlanningContext and planner; split memory in GUI tool and agent | a4ce495 | capabilities.py, planner.py, loop.py, gui.py, agent.py |
| 2 | Add regression tests for the memory split | c008d1e | tests/test_gui_memory_split.py |

## Changes Made

### nanobot/agent/capabilities.py

Added `gui_memory_context: str = ""` field to `PlanningContext`. This carries os/app/icon guide content to the planner without changing the entrypoint shape.

### nanobot/agent/planner.py

In `_build_system_prompt()`, injected `gui_memory_context` under a "Device and app knowledge" header immediately before the closing call-to-action lines. The header is only emitted when the field is non-empty.

### nanobot/agent/loop.py

Added `_load_gui_memory_for_planner()` static method that loads os_guide, app_guide, and icon_guide entries from the opengui MemoryStore. The method is guarded with a directory-existence check and a broad try/except so systems without opengui memory continue to work. The entries are formatted as `- [TAG] (app) content` lines consistent with `MemoryRetriever.format_context()`. The result is passed as `gui_memory_context` to `PlanningContext`.

### nanobot/agent/tools/gui.py

- `_build_memory_retriever()`: now indexes only POLICY entries (guide entries go to the planner instead). Returns `None` early when no policy entries exist.
- `_load_policy_context()`: new synchronous method that loads all POLICY entries as raw text (no embedding overhead). Returns `None` when no entries exist.
- `_run_task()`: replaced `memory_retriever=memory_retriever` with `policy_context=policy_context` in the GuiAgent constructor call. The `_build_memory_retriever()` method is retained but no longer called from `_run_task`.

### opengui/agent.py

- Added `policy_context: str | None = None` parameter to `GuiAgent.__init__()`, stored as `self._policy_context`.
- `_retrieve_memory()`: returns `self._policy_context` directly when it is not None, logging the injection via `_log_policy_injection()`. Falls through to the existing retriever-based search path when `_policy_context` is None, preserving full backward compatibility for the opengui CLI.
- Added `_log_policy_injection()` helper that records a `memory_retrieval` trajectory event for observability.

## Decisions Made

1. **Guide to planner, policy to GUI agent:** The planner needs device/app navigation knowledge to decompose GUI tasks intelligently. The GUI agent needs all safety rules always present regardless of query relevance. The split cleanly separates these two concerns.

2. **Policy as full direct injection (no search):** Policy rules are safety boundaries — they must be present 100% of the time. Search-based retrieval can silently drop entries with low relevance scores, which is unacceptable for safety constraints.

3. **opengui CLI backward compat preserved:** The `memory_retriever` path in `GuiAgent._retrieve_memory` is unchanged. Callers constructing `GuiAgent` directly with a retriever (e.g., the opengui CLI) continue to work without modification.

4. **Synchronous policy loading (no embedding):** Loading policy entries is a simple file read + list operation, no async overhead needed.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

All verification criteria passed:

1. `python3 -c "from nanobot.agent.capabilities import PlanningContext, CapabilityCatalog; pc = PlanningContext(catalog=CapabilityCatalog(), gui_memory_context='x'); assert pc.gui_memory_context == 'x'"` — PASSED
2. `python -m pytest tests/test_gui_memory_split.py -x -v` — 6/6 PASSED
3. `python -m pytest tests/test_opengui_p21_planner_context.py -x -v` — 7/7 PASSED
4. `python -m pytest tests/test_opengui_p2_memory.py -x -v` — 3/3 PASSED

## Self-Check: PASSED

All files exist and all commits verified.
