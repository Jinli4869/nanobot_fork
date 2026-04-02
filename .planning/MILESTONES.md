# Milestones

## v1.1 Background Execution (Shipped: 2026-03-20)

**Phases completed:** 3 phases, 7 plans, 11 tasks

**Key accomplishments:**

- Added a reusable virtual display abstraction with `VirtualDisplayManager`, `DisplayInfo`, `NoOpDisplayManager`, and a production-ready `XvfbDisplayManager`.
- Implemented `BackgroundDesktopBackend` with lifecycle guards, async context management, DISPLAY save/restore, coordinate offset handling, and idempotent shutdown.
- Added first-class CLI background execution via `--background`, `--display-num`, `--width`, and `--height`.
- Extended nanobot `GuiConfig` and `GuiSubagentTool.execute()` to support background local execution on Linux with non-Linux fallback warnings.

## v1.2 Cross-Platform Background Execution (Shipped: 2026-03-21)

**Phases completed:** 5 phases, 11 plans

**Key accomplishments:**

- Added shared runtime probing, resolved-mode contracts, and process-wide background serialization.
- Extended isolated background execution support across macOS and Windows while preserving CI-safe test seams.
- Added intervention safety, host handoff boundaries, and milestone-level verification coverage.

## v1.3 Nanobot Web Workspace (Shipped: 2026-03-22)

**Phases completed:** 4 phases, 11 plans

**Key accomplishments:**

- Added a local-first FastAPI + React/Vite workspace under `nanobot/tui`.
- Shipped browser chat, operations console, static/dev integration, and packaged startup seams.
- Preserved CLI-first behavior while exposing browser-backed nanobot workflows.

## v1.4 Capability-Aware Planning and Routing (Shipped: 2026-03-28)

**Phases completed:** 3 phases, 5 plans

**Key accomplishments:**

- Added a live capability catalog and routing-relevant planning memory.
- Turned `tool` and `mcp` planner nodes into real executable routes with fallback behavior.
- Improved mixed-capability planning so GUI is no longer the only default path.

## v1.5 New OpenGUI Skills Architecture (Shipped: 2026-04-02)

**Phases completed:** 4 phases, 9 plans

**Key accomplishments:**

- Added `ShortcutSkill` / `TaskSkill` schemas plus `GrounderProtocol` / `LLMGrounder`.
- Shipped `ShortcutExecutor` / `TaskSkillExecutor` with contract-aware runtime behavior.
- Added quality-gated shortcut extraction primitives and separate versioned shortcut/task stores.
- Integrated unified search and task-skill memory injection into `GuiAgent`.

## v1.6 Shortcut Extraction and Stable Execution (Started: 2026-04-02)

**Focus:**

- Promote trustworthy shortcuts from real traces into the new shortcut store
- Use shortcuts only when current-screen applicability checks pass
- Stabilize shortcut execution with live binding, settle/verification, fallback, and telemetry
