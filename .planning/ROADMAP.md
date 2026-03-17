# Roadmap: OpenGUI

## Overview

P0 is complete: the core GuiAgent vision-action loop, ADB backend, DryRun backend, prompts, and 8 passing regression tests are all in place. P1 module code for memory, skills, and trajectory exists but lacks test coverage. The remaining work is: test the P1 modules before trusting them, wire them into the agent loop, expose the agent as a nanobot subagent tool, add the desktop backend, and ship a standalone CLI entry point.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: P1 Unit Tests** - Verify all memory, skills, and trajectory module code before integrating into the agent loop
- [ ] **Phase 2: Agent Loop Integration** - Wire memory retrieval, skill search + execute, and trajectory recording into GuiAgent.run()
- [ ] **Phase 3: Nanobot Subagent** - Expose GuiAgent as a nanobot tool via GuiSubagentTool + NanobotLLMAdapter + backend selection
- [ ] **Phase 4: Desktop Backend** - LocalDesktopBackend using pyautogui + pyperclip for macOS/Linux/Windows
- [ ] **Phase 5: CLI & Extensions** - Standalone CLI entry point and claw adapter documentation

## Phase Details

### Phase 1: P1 Unit Tests
**Goal**: All memory, skills, and trajectory modules are covered by fast, isolated unit tests that catch regressions before integration begins
**Depends on**: Nothing (P1 code already exists)
**Requirements**: TEST-02, TEST-03, TEST-04
**Success Criteria** (what must be TRUE):
  1. `pytest tests/` passes with tests covering MemoryStore JSON persistence and MemoryRetriever BM25+FAISS hybrid search
  2. SkillLibrary CRUD, hybrid search, deduplication, SkillExecutor per-step valid_state, and SkillExtractor parsing are each exercised by at least one test
  3. TrajectoryRecorder event sequencing and TrajectorySummarizer output format are verified by at least one test each
  4. No test requires a live device, real LLM call, or network access (all external I/O is mocked)
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Add faiss-cpu/numpy deps + memory module tests (TEST-02)
- [x] 01-02-PLAN.md — Skills module tests: library CRUD, search, dedup, executor, extractor (TEST-03)
- [x] 01-03-PLAN.md — Trajectory module tests: recorder events, summarizer output (TEST-04)

### Phase 2: Agent Loop Integration
**Goal**: GuiAgent.run() is a fully wired agent loop — it retrieves memory context, searches for matching skills, executes or explores, and records the trajectory end-to-end. The main agent (nanobot) gains a TaskPlanner that decomposes tasks into AND/OR/ATOM trees and routes each ATOM to the appropriate executor (GUI subagent, tool, or MCP).
**Depends on**: Phase 1
**Requirements**: AGENT-04, AGENT-05, AGENT-06, MEM-05, SKILL-08, TRAJ-03, TEST-05
**Success Criteria** (what must be TRUE):
  1. When GuiAgent.run() is called with an instruction, memory entries matching the instruction appear in the system prompt
  2. When a matching skill exists in the library, GuiAgent uses SkillExecutor to attempt execution before falling back to free exploration
  3. Every agent run produces a JSONL trajectory file with one entry per step (screenshot path + action + model output)
  4. The main-agent TaskPlanner decomposes a task into an AND/OR/ATOM tree with capability-typed ATOMs (gui/tool/mcp)
  5. The integration test with DryRunBackend + mock LLM + pre-seeded memory and skill library runs to completion without errors
**Plans**: TBD

Plans:
- [ ] TBD

### Phase 3: Nanobot Subagent
**Goal**: The main nanobot agent can spawn a GUI subagent to complete device tasks, receive a structured result, and optionally extract new skills from the recorded trajectory
**Depends on**: Phase 2
**Requirements**: NANO-01, NANO-02, NANO-03, NANO-04, NANO-05
**Success Criteria** (what must be TRUE):
  1. GuiSubagentTool is registered in the nanobot tool registry and callable from the main agent loop
  2. NanobotLLMAdapter bridges nanobot's LLM provider to the opengui LLMProvider protocol without any opengui code importing nanobot
  3. Backend is selected from nanobot config (adb / local / dry-run) and the agent starts without additional configuration
  4. After a run, the trajectory JSONL file is saved to the nanobot workspace and the main agent receives a structured result dict
  5. The main agent has a trajectory_summary skill that summarizes a trajectory and extracts new skills into the SkillLibrary
**Plans**: TBD

Plans:
- [ ] 03-01: GuiSubagentTool + NanobotLLMAdapter + backend selection from config
- [ ] 03-02: Trajectory workspace save + NANO-04 result handoff
- [ ] 03-03: trajectory_summary skill for post-run skill extraction (NANO-05)

### Phase 4: Desktop Backend
**Goal**: GuiAgent can automate a local desktop (macOS, Linux, or Windows) using the same DeviceBackend protocol as ADB
**Depends on**: Phase 2
**Requirements**: BACK-03
**Success Criteria** (what must be TRUE):
  1. LocalDesktopBackend.observe() captures a screenshot and returns an Observation with the correct platform string
  2. LocalDesktopBackend.execute() dispatches tap, swipe, scroll, and text_input actions via pyautogui with [0,999] relative coordinate resolution
  3. LocalDesktopBackend.execute() handles text_input using pyperclip for clipboard paste, avoiding per-character typing
  4. Running GuiAgent with LocalDesktopBackend and a real task on the local machine completes without crashing
**Plans**: TBD

Plans:
- [ ] 04-01: LocalDesktopBackend implementation and unit tests (mocked pyautogui)

### Phase 5: CLI & Extensions
**Goal**: Developers can drive opengui from the command line without writing any host-agent code, and other claw adapters can follow a documented integration pattern
**Depends on**: Phase 2
**Requirements**: CLI-01, EXT-01
**Success Criteria** (what must be TRUE):
  1. `python -m opengui.cli --backend adb --task "Open Settings"` runs a full agent loop and prints the result
  2. `python -m opengui.cli --backend local --task "Open Chrome"` runs a full agent loop against the local desktop
  3. A code comment or docstring in the CLI or interfaces module explains the adapter pattern so another developer can write an openclaw/nanoclaw/zeroclaw adapter without reading nanobot internals
**Plans**: TBD

Plans:
- [ ] 05-01: CLI entry point (`opengui/cli.py` with `__main__` support)
- [ ] 05-02: Claw adapter documentation (EXT-01)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5
Phase 4 depends only on Phase 2 and can run in parallel with Phase 3 if desired.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. P1 Unit Tests | 3/3 | Complete   | 2026-03-17 |
| 2. Agent Loop Integration | 0/4 | Not started | - |
| 3. Nanobot Subagent | 0/3 | Not started | - |
| 4. Desktop Backend | 0/1 | Not started | - |
| 5. CLI & Extensions | 0/2 | Not started | - |
