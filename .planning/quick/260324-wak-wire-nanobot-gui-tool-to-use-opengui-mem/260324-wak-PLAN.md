---
phase: quick
plan: 260324-wak
type: execute
wave: 1
depends_on: []
files_modified:
  - nanobot/agent/tools/gui.py
  - tests/test_opengui_p6_wiring.py
autonomous: true
must_haves:
  truths:
    - "Nanobot GUI tasks build an OpenGUI MemoryRetriever when gui.embedding_model is configured"
    - "The retriever reads from ~/.opengui/memory so existing user-maintained memory files are reused"
    - "GuiAgent receives memory_retriever through the nanobot gui_task path"
  artifacts:
    - path: "nanobot/agent/tools/gui.py"
      provides: "Nanobot GUI memory wiring"
      contains: "_build_memory_retriever"
    - path: "tests/test_opengui_p6_wiring.py"
      provides: "Regression coverage for default memory dir loading and GuiAgent injection"
      contains: "test_gui_tool_builds_memory_retriever_from_default_opengui_dir"
---

<objective>
Wire Nanobot's gui_task path to use OpenGUI memory retrieval, matching the user's existing
memory location under ~/.opengui/memory whenever gui.embedding_model is configured.

The goal is to close the current integration gap where Nanobot creates a GuiAgent with
skill_library support but never passes a memory_retriever, causing all tasks to run without
memory hits even when valid memory markdown files already exist.
</objective>

<tasks>

<task type="auto">
  <name>Add OpenGUI memory retriever wiring to GuiSubagentTool</name>
  <files>nanobot/agent/tools/gui.py</files>
  <action>
Add a helper that builds MemoryStore + MemoryRetriever from ~/.opengui/memory using the
already-configured Nanobot embedding adapter. Call the helper from _run_task() and pass the
result into GuiAgent as memory_retriever.

Design constraints:
- Keep behavior unchanged when gui.embedding_model is absent
- Rebuild the retriever per GUI task so edits to memory markdown files are picked up on the next run
- Fail soft: if initialization breaks, log a warning and continue without memory instead of blocking GUI tasks
  </action>
  <verify>
    <automated>tests/test_opengui_p6_wiring.py exercises both retriever construction and GuiAgent injection</automated>
  </verify>
</task>

<task type="auto">
  <name>Add regression tests for the new wiring seam</name>
  <files>tests/test_opengui_p6_wiring.py</files>
  <action>
Add one test to verify the default memory directory (~/.opengui/memory) is used to build a
MemoryRetriever, and another test to verify the resulting retriever is passed through to
GuiAgent during _run_task().
  </action>
  <verify>
    <automated>uv run pytest tests/test_opengui_p6_wiring.py tests/test_opengui_p8_trajectory.py tests/test_opengui_p3_nanobot.py tests/test_opengui_p11_integration.py</automated>
  </verify>
</task>

</tasks>
