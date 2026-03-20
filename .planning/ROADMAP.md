# Roadmap: OpenGUI

## Overview

P0 is complete: the core GuiAgent vision-action loop, ADB backend, DryRun backend, prompts, and 8 passing regression tests are all in place. P1 module code for memory, skills, and trajectory exists but lacks test coverage. The remaining work is: test the P1 modules before trusting them, wire them into the agent loop, expose the agent as a nanobot subagent tool, add the desktop backend, and ship a standalone CLI entry point.

## Milestones

- ✅ **v1.0** - Phases 1-8 (shipped 2026-03-19)
- 🚧 **v1.1 Background Execution** - Phases 9-11 (in progress)

## Phases

<details>
<summary>✅ v1.0 (Phases 1-8) - SHIPPED 2026-03-19</summary>

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: P1 Unit Tests** - Verify all memory, skills, and trajectory module code before integrating into the agent loop
- [x] **Phase 2: Agent Loop Integration** - Wire memory retrieval, skill search + execute, and trajectory recording into GuiAgent.run()
- [ ] **Phase 3: Nanobot Subagent** - Expose GuiAgent as a nanobot tool via GuiSubagentTool + NanobotLLMAdapter + backend selection
- [x] **Phase 4: Desktop Backend** - LocalDesktopBackend using pyautogui + pyperclip for macOS/Linux/Windows
- [ ] **Phase 5: CLI & Extensions** - Standalone CLI entry point and claw adapter documentation
- [x] **Phase 6: Fix Integration Wiring** - Wire skill_context, embedding adapter, Pillow dep, CLI entry point (completed 2026-03-19)
- [x] **Phase 7: Phase 2 Retroactive Verification** - Create missing VERIFICATION.md for Phase 2 (completed 2026-03-19)
- [x] **Phase 8: Dead Export Cleanup** - Wire orphaned TaskPlanner, TreeRouter, TrajectorySummarizer into production code (completed 2026-03-19)

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
**Plans**: 5 plans

Plans:
- [x] 02-00-PLAN.md — Wave 0 test stubs for all Phase 2 requirements (Nyquist compliance)
- [x] 02-01-PLAN.md — Data model extensions (SkillStep fixed fields, Skill confidence, SkillLibrary.update()) + MemoryStore markdown migration
- [x] 02-02-PLAN.md — Wire memory, skill, trajectory into GuiAgent.run() + update P0 tests
- [x] 02-03-PLAN.md — TaskPlanner (AND/OR/ATOM tree) + TreeRouter (capability dispatch) at nanobot level
- [x] 02-04-PLAN.md — Integration tests: full agent loop + planner/router dispatch + memory tests

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
**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md — Wave 0 test stubs + GuiConfig schema + NanobotLLMAdapter + NanobotEmbeddingAdapter (NANO-02, NANO-03)
- [ ] 03-02-PLAN.md — GuiSubagentTool + AgentLoop registration + trajectory save + auto skill extraction (NANO-01, NANO-04, NANO-05)

### Phase 4: Desktop Backend
**Goal**: GuiAgent can automate a local desktop (macOS, Linux, or Windows) using the same DeviceBackend protocol as ADB
**Depends on**: Phase 2
**Requirements**: BACK-03
**Success Criteria** (what must be TRUE):
  1. LocalDesktopBackend.observe() captures a screenshot and returns an Observation with the correct platform string
  2. LocalDesktopBackend.execute() dispatches tap, swipe, scroll, and text_input actions via pyautogui with [0,999] relative coordinate resolution
  3. LocalDesktopBackend.execute() handles text_input using pyperclip for clipboard paste, avoiding per-character typing
  4. Running GuiAgent with LocalDesktopBackend and a real task on the local machine completes without crashing
**Plans**: 1 plan

Plans:
- [x] 04-01-PLAN.md — LocalDesktopBackend implementation, unit tests, and nanobot integration wiring (BACK-03)

### Phase 5: CLI & Extensions
**Goal**: Developers can drive opengui from the command line without writing any host-agent code, and other claw adapters can follow a documented integration pattern
**Depends on**: Phase 2
**Requirements**: CLI-01, EXT-01
**Success Criteria** (what must be TRUE):
  1. `python -m opengui.cli --backend adb --task "Open Settings"` runs a full agent loop and prints the result
  2. `python -m opengui.cli --backend local --task "Open Chrome"` runs a full agent loop against the local desktop
  3. A code comment or docstring in the CLI or interfaces module explains the adapter pattern so another developer can write an openclaw/nanoclaw/zeroclaw adapter without reading nanobot internals
**Plans**: 3 plans

Plans:
- [x] 05-01-PLAN.md — Standalone CLI entry point, YAML config loader, OpenAI-compatible provider bridge, and CLI tests (CLI-01)
- [x] 05-02-PLAN.md — Adapter documentation, protocol pointer comment, and docs regression tests (EXT-01)

### Phase 6: Fix Integration Wiring
**Goal:** Close broken cross-phase connections — instantiate NanobotEmbeddingAdapter, declare missing Pillow dependency, and add CLI entry point to pyproject.toml
**Depends on**: Phase 3, Phase 4, Phase 5
**Requirements**: NANO-03, BACK-03, CLI-01
**Gap Closure:** Closes gaps from audit — fixes 3 broken wiring issues
**Success Criteria** (what must be TRUE):
  1. `GuiSubagentTool` instantiates `NanobotEmbeddingAdapter` and passes it to `SkillLibrary` so FAISS skill search works in the nanobot path
  2. `pip install .[desktop]` installs Pillow and `from PIL import Image` succeeds without error
  3. `pyproject.toml` declares `opengui = "opengui.cli:main"` as a console script entry point
**Plans**: 0 plans

### Phase 7: Phase 2 Retroactive Verification
**Goal:** Create the missing VERIFICATION.md for Phase 2 by verifying all 7 requirements (AGENT-04..06, MEM-05, SKILL-08, TRAJ-03, TEST-05) against code and tests
**Depends on**: Phase 6 (embedding adapter wiring must be fixed first)
**Requirements**: AGENT-04, AGENT-05, AGENT-06, MEM-05, SKILL-08, TRAJ-03, TEST-05
**Gap Closure:** Closes 7 verification gaps from audit
**Success Criteria** (what must be TRUE):
  1. `.planning/phases/02-agent-loop-integration/VERIFICATION.md` exists and covers all 7 requirements
  2. Each requirement has a pass/fail verdict with evidence (test output, code reference, or manual check)
**Plans**: 0 plans

### Phase 8: Dead Export Cleanup
**Goal:** Wire orphaned exports (TaskPlanner, TreeRouter, TrajectorySummarizer) into production code paths — completing remaining Phase 3 requirements (NANO-01, NANO-04, NANO-05) in the process
**Depends on**: Phase 7
**Requirements**: None (tech debt)
**Gap Closure:** Closes 3 orphaned export warnings from audit
**Success Criteria** (what must be TRUE):
  1. No production-unreachable exports remain in `__init__.py` or public APIs
  2. All tests still pass after cleanup
  3. TaskPlanner + TreeRouter wired into AgentLoop with complexity gate
  4. TrajectorySummarizer called in GuiSubagentTool post-run pipeline
**Plans**: 3 plans

Plans:
- [ ] 08-01-PLAN.md — Wire TrajectorySummarizer into GuiSubagentTool post-run + export planner/router from nanobot.agent
- [ ] 08-02-PLAN.md — Enhance TreeRouter: parallel AND execution + OR priority sorting (mcp > tool > gui)
- [ ] 08-03-PLAN.md — Wire TaskPlanner complexity gate + TreeRouter dispatch into AgentLoop._process_message

</details>

---

### 🚧 v1.1 Background Execution (In Progress)

**Milestone Goal:** Enable GUI automation to run in the background on a virtual display, freeing the user's screen during desktop automation tasks.

- [x] **Phase 9: Virtual Display Protocol** - Define VirtualDisplayManager protocol, DisplayInfo dataclass, NoOp and Xvfb implementations (completed 2026-03-20)
- [x] **Phase 10: Background Backend Wrapper** - BackgroundDesktopBackend decorator that injects DISPLAY, applies coordinate offsets, and manages display lifecycle (completed 2026-03-20)
- [ ] **Phase 11: Integration & Tests** - Wire --background flag into CLI and nanobot GuiConfig, plus full CI-safe test suite with mocked subprocess

### Phase 9: Virtual Display Protocol
**Goal**: The codebase has a well-defined, testable abstraction for virtual displays — with a no-op implementation for Android/tests and a working Xvfb implementation for Linux CI and production
**Depends on**: Phase 8 (v1.0 complete)
**Requirements**: VDISP-01, VDISP-02, VDISP-03, VDISP-04
**Success Criteria** (what must be TRUE):
  1. `VirtualDisplayManager` protocol is importable from `opengui.interfaces` and accepts async `start()` / `stop()` calls with no concrete dependency on Xvfb
  2. `DisplayInfo` is a frozen dataclass with `display_id`, `width`, `height`, `offset_x`, `offset_y`, `monitor_index` that any implementation returns from `start()`
  3. `NoOpDisplayManager.start()` returns a `DisplayInfo` immediately without spawning any subprocess, usable in tests and ADB sessions
  4. `XvfbDisplayManager.start()` launches Xvfb via `asyncio.subprocess`, waits for the X11 socket to appear, and returns `DisplayInfo` with the correct display number
  5. `XvfbDisplayManager.stop()` terminates the Xvfb process cleanly; calling `stop()` on a never-started manager does not raise
**Plans**: 3 plans

Plans:
- [ ] 09-00-PLAN.md — Wave 0 test stubs for all VDISP requirements (Nyquist compliance)
- [ ] 09-01-PLAN.md — Protocol + DisplayInfo + NoOpDisplayManager + re-exports + tests (VDISP-01, VDISP-02, VDISP-03)
- [ ] 09-02-PLAN.md — XvfbDisplayManager with error handling, auto-increment, crash detection + tests (VDISP-04)

### Phase 10: Background Backend Wrapper
**Goal**: Any DeviceBackend can be wrapped in `BackgroundDesktopBackend` to run GUI actions against a virtual display — setting `DISPLAY` for X11 and translating coordinates for non-zero-offset displays
**Depends on**: Phase 9
**Requirements**: BGND-01, BGND-02, BGND-03, BGND-04
**Success Criteria** (what must be TRUE):
  1. `BackgroundDesktopBackend(backend, display_manager)` wraps any `DeviceBackend` and itself satisfies the `DeviceBackend` protocol
  2. When `observe()` or `execute()` is called, the `DISPLAY` environment variable is set to `:N` matching the `DisplayInfo.display_id` from the virtual display manager
  3. Tap and swipe coordinates are offset by `DisplayInfo.offset_x` / `offset_y` before being forwarded to the inner backend
  4. Calling `shutdown()` on the wrapper calls `stop()` on the virtual display manager exactly once, even if called multiple times
**Plans**: 2 plans

Plans:
- [ ] 10-01-PLAN.md — Test file with all 13 BGND test cases (BGND-01, BGND-02, BGND-03, BGND-04)
- [ ] 10-02-PLAN.md — Refine BackgroundDesktopBackend with lifecycle guards, context manager, idempotent shutdown (BGND-01, BGND-02, BGND-03, BGND-04)

### Phase 11: Integration & Tests
**Goal**: The `--background` flag is a first-class CLI option, nanobot's `GuiConfig` supports background mode, and every new code path is verified by CI-safe unit tests with mocked subprocess
**Depends on**: Phase 10
**Requirements**: INTG-01, INTG-02, INTG-03, INTG-04, TEST-V11-01
**Success Criteria** (what must be TRUE):
  1. `python -m opengui.cli --background --task "Open Settings"` wraps `LocalDesktopBackend` in `BackgroundDesktopBackend` backed by `XvfbDisplayManager` without any additional flags
  2. Nanobot `GuiConfig` accepts `background`, `display_num`, `width`, and `height` fields; `_build_backend` wraps `LocalDesktopBackend` when `background=true`
  3. All new tests pass in CI without a real Xvfb binary — subprocess creation is mocked at the `asyncio.subprocess` boundary
  4. `pytest tests/` still passes in full after the integration (no regressions against v1.0 test suite)
**Plans**: 2 plans

Plans:
- [ ] 11-01-PLAN.md — CLI --background flag, CliConfig fields, run_cli wrapping + CLI tests (INTG-01, INTG-03, TEST-V11-01)
- [ ] 11-02-PLAN.md — GuiConfig background fields, model_validator, execute() wrapping + nanobot tests (INTG-02, INTG-04, TEST-V11-01)

---

## Progress

**Execution Order:**
v1.0: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8
v1.1: 9 → 10 → 11

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. P1 Unit Tests | v1.0 | 3/3 | Complete | 2026-03-17 |
| 2. Agent Loop Integration | v1.0 | 5/5 | Complete | 2026-03-18 |
| 3. Nanobot Subagent | v1.0 | 1/2 | In Progress | - |
| 4. Desktop Backend | v1.0 | 1/1 | Complete | 2026-03-18 |
| 5. CLI & Extensions | v1.0 | 2/2 | In Progress | - |
| 6. Fix Integration Wiring | v1.0 | 1/1 | Complete | 2026-03-19 |
| 7. Phase 2 Retroactive Verification | v1.0 | 1/1 | Complete | 2026-03-19 |
| 8. Dead Export Cleanup | v1.0 | 3/3 | Complete | 2026-03-19 |
| 9. Virtual Display Protocol | v1.1 | 3/3 | Complete | 2026-03-20 |
| 10. Background Backend Wrapper | 2/2 | Complete    | 2026-03-20 | - |
| 11. Integration & Tests | 1/2 | In Progress|  | - |
