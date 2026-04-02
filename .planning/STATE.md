---
gsd_state_version: 1.0
milestone: v1.5
milestone_name: New OpenGUI Skills Architecture
current_phase: 27
current_phase_name: storage-search-agent-integration
current_plan: Not started
status: completed
stopped_at: Completed 27-02-PLAN.md
last_updated: "2026-04-02T12:58:09.855Z"
last_activity: 2026-04-02
progress:
  total_phases: 11
  completed_phases: 10
  total_plans: 24
  completed_plans: 24
  percent: 96
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-02)

**Core value:** Any host agent can spawn a GUI subagent to complete device tasks autonomously.
**Current focus:** Phase 27 — storage-search-agent-integration

## Current Position

**Current Phase:** 27
**Current Phase Name:** storage-search-agent-integration
**Total Phases:** 11
**Current Plan:** Not started
**Total Plans in Phase:** 2
**Status:** Milestone complete

## Performance Metrics

**Progress:** [██████████] 96%

| Execution | Duration | Tasks | Files |
|-----------|----------|-------|-------|
| 17-01 | 99 min | 2 | 19 |
| 17-02 | 38 min | 2 | 5 |
| 18-01 | 5 min | 2 | 10 |
| 18-02 | 10 min | 2 | 10 |
| 18-03 | 6 min | 2 | 5 |
| 19-01 | 8 min | 2 | 9 |
| 19-02 | 11 min | 2 | 7 |
| 19-03 | 9 min | 2 | 10 |
| 20-01 | 22 min | 2 | 12 |
| 20-02 | 18 min | 2 | 12 |
| 20-03 | 6 min | 2 | 10 |
| 21-02 | 7 min | 2 | 6 |

**Velocity:**

- Total plans completed (tracked): 12
- Average duration: 20 min
- Total execution time: 239 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 17 | 2 | 137 min | 69 min |
| 18 | 3 | 21 min | 7 min |
| 19 | 3 | 28 min | 9 min |
| 20 | 3 | 46 min | 15 min |
| 21 | 2 | 31 min | 16 min |

*Updated after each plan completion*
| Phase 22 P01 | 4 | 2 tasks | 2 files |
| Phase 22 P02 | 7 | 2 tasks | 4 files |
| Phase 24 P01 | 2 min | 2 tasks | 4 files |
| Phase 24 P02 | 4min | 2 tasks | 3 files |
| Phase 24 P03 | 1min | 2 tasks | 4 files |
| Phase 25 P01 | 4 | 2 tasks | 4 files |
| Phase 25 P02 | 4 min | 2 tasks | 3 files |
| Phase 27 P01 | 6 min | 1 tasks | 3 files |
| Phase 27-storage-search-agent-integration P02 | 5 min | 2 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.

- [v1.0]: All 8 phases completed — core protocols, tests, agent loop, subagent, desktop backend, CLI, wiring, cleanup
- [v1.1]: Decorator pattern for BackgroundDesktopBackend (thin wrapper + DISPLAY env var; zero coordinate offset for Xvfb)
- [v1.1]: Xvfb subprocess management via asyncio.subprocess — no Python deps, no real Xvfb needed in CI (mock at boundary)
- [v1.1]: macOS CGVirtualDisplay and Windows CreateDesktop deferred to v1.2
- [Phase 09-virtual-display-protocol]: Wave-0 xfail stub pattern: create test files before production code to satisfy Nyquist sampling; guarded imports with _IMPORTS_OK + pytestmark skipif for test files whose imports depend on not-yet-implemented code
- [Phase 09]: virtual_display.py draft fully matched all locked decisions — committed to git without modification
- [Phase 09]: ROADMAP.md Phase 9 SC-2 already had correct offset_x/offset_y names — no update needed
- [Phase 09-virtual-display-protocol]: XvfbCrashedError propagates directly (not caught in retry loop); only lock-file presence triggers auto-increment retry
- [Phase 09-virtual-display-protocol]: TimeoutError from _try_start() propagates directly to caller — timeout is not a collision signal, no retry attempted
- [Phase 09-virtual-display-protocol]: _poll_socket() as separate coroutine enables asyncio.wait_for() clean cancellation on timeout
- [Phase 10-background-backend-wrapper]: 14 tests written (plan frontmatter said 13 — acceptance criteria list had 14 named functions; all implemented)
- [Phase 10-background-backend-wrapper]: DISPLAY env tests use try/finally with original-value save instead of monkeypatch, consistent with Phase 9 async test style
- [Phase 10-background-backend-wrapper]: _SENTINEL: object = object() with explicit type annotation used for DISPLAY env save/restore state tracking
- [Phase 10-background-backend-wrapper]: DeviceBackend imported under TYPE_CHECKING only — eliminates type:ignore[union-attr] without circular import risk
- [Phase 10-background-backend-wrapper]: shutdown() catches Exception broadly for best-effort cleanup — unknown Xvfb crash exceptions suppressed, _stopped=True always set
- [Phase 11-integration-tests P02]: GuiConfig.background=True raises ValidationError for non-local backends at config load time via model_validator
- [Phase 11-integration-tests P02]: execute() extracts _run_task() helper to avoid duplicating 20+ lines across wrapped and unwrapped paths
- [Phase 11-integration-tests P02]: BackgroundDesktopBackend and XvfbDisplayManager imported lazily inside execute() — avoids import-time cost on non-Linux
- [Phase 11-integration-tests P02]: Non-Linux fallback runs task in foreground with WARNING log containing 'Linux-only' — no exception raised
- [Phase 11-integration-tests P01]: Two separate parser.error() calls needed — args.backend check catches --backend adb/dry-run; args.dry_run check catches --dry-run flag which leaves args.backend at default 'local'
- [Phase 11-integration-tests P01]: XvfbDisplayManager patched at module attribute level for correct resolution of run_cli's local from-import
- [Phase 11-integration-tests P01]: _execute_agent() extracted as standalone async function to avoid duplicating 40+ lines across background and non-background paths
- [Phase 12-background-runtime-contracts]: Shared `background_runtime.py` now owns capability probing, resolved-mode logging, and remediation text for background runs
- [Phase 12-background-runtime-contracts]: `BackgroundRuntimeCoordinator` serializes overlapping background runs and surfaces busy metadata through the wrapper lease
- [Phase 13]: Implemented CGVirtualDisplayManager with lazy macOS imports and patchable helper boundaries — Preserves Linux CI stability while adding a real macOS isolated-display seam
- [Phase 13]: Added configure_target_display() to LocalDesktopBackend so observe() can follow DisplayInfo.monitor_index without touching action math — Separates surface selection from coordinate translation and keeps the existing desktop execution path stable
- [Phase 13]: BackgroundDesktopBackend now injects and clears DisplayInfo metadata around inner lifecycle calls — Ensures macOS background monitor routing stays aligned across observe() and execute() and does not leak into later foreground runs
- [Phase 13]: CLI isolated execution now selects Xvfb vs CGVirtualDisplay from probe.backend_name — Keeps macOS enablement on the shared runtime contract and avoids reintroducing host-specific drift in run_cli()
- [Phase 13]: Nanobot GUI execution now uses the same backend_name dispatch and structured remediation semantics as the CLI path — Preserves one cross-host background contract while keeping nanobot's JSON failure behavior stable
- [Phase 13]: Phase 13 closeout reruns the full macOS regression slice and fixes stale Linux/darwin expectations in the same wave — Keeps the milestone honest by treating verification regressions as implementation work instead of deferring them
- [Phase 14]: Windows isolated support resolves through backend_name="windows_isolated_desktop" in the shared runtime contract
- [Phase 14]: Win32DesktopManager owns desktop naming and idempotent teardown while publishing DisplayInfo for later worker launch wiring
- [Phase 14]: Windows isolated runs use a dedicated backend instead of BackgroundDesktopBackend so worker launch, routing, and cleanup stay desktop-aware.
- [Phase 14]: The worker launch seam is import-safe on non-Windows hosts but still encodes STARTUPINFO.lpDesktop for Windows process creation.
- [Phase 14]: Both host entry points dispatch isolated execution from probe.backend_name instead of raw platform branching.
- [Phase 14]: Nanobot preserves cleanup_reason= and display_id= tokens by returning RuntimeError text through the existing background JSON failure payload.
- [Phase 14]: Windows isolated runs use WindowsIsolatedBackend directly while Linux and macOS continue through BackgroundDesktopBackend.
- [Phase 14]: Phase 14 closeout keeps a fully green regression slice unchanged and records the verification as its own atomic task commit.
- [Phase 14]: Real-host Windows validation remains phase-local in 14-MANUAL-SMOKE.md and reuses the same runtime and cleanup tokens asserted by automated tests.
- [Phase 14]: Windows isolated desktop IO now belongs exclusively to the child worker, so the parent backend no longer observes or executes against the user desktop.
- [Phase 14]: Win32 support probing now validates session, input-desktop, and create-desktop prerequisites through patchable Win32 wrappers instead of hard-coded availability booleans.
- [Phase 14]: CLI and nanobot now default omitted Windows app-class hints to classic-win32 only for background local runs on win32 hosts.
- [Phase 14]: Unsupported Windows app classes stay on the shared remediation path: CLI warns before agent start, while nanobot returns its existing JSON failure shape before any task execution.
- [Phase 14]: The Phase 14 regression fix stayed in test code because the failing Windows metadata check was a stale worker fixture, not a runtime defect.
- [Phase 15]: Intervention is a first-class action_type instead of overloading done or assistant free text.
- [Phase 15]: GuiAgent owns the intervention pause boundary so request_intervention stops both execute() and observe() before backend IO.
- [Phase 15]: Resume always reacquires a fresh observation at the next step screenshot path before the model continues.
- [Phase 15]: Trace and trajectory artifacts scrub input_text, intervention reasons, and credential-like keys before write.
- [Phase 15]: CLI intervention now requires an exact `resume` acknowledgement before automation continues.
- [Phase 15]: Host-visible handoff data is filtered to safe target-surface keys instead of raw observation extras.
- [Phase 15]: Cancelled intervention runs are terminal and do not re-enter the standard retry loop.
- [Phase 15]: Real-host intervention, explicit resume, and artifact-scrubbing validation stay phase-local in 15-MANUAL-SMOKE.md.
- [Phase 15]: Phase 15 closeout records a clean regression rerun as its own atomic test commit instead of touching already-green coverage.
- [Phase 17]: `nanobot.tui.create_app()` stays health-only by default; the runnable module entry opts into read-only browser routes explicitly.
- [Phase 17]: Browser-facing routes depend on typed contract-backed services so the web layer can reuse `SessionManager` metadata without booting `AgentLoop`, channels, or GUI startup.
- [Phase 17]: The new web runtime uses a dedicated `tui` config section with `127.0.0.1` defaults instead of reusing `gateway.host` or `gateway.port`.
- [Phase 18]: Browser chat streaming stays inside `nanobot/tui` via a transient in-process broker, while `SessionManager` remains the durable transcript source.
- [Phase 18]: Chat mutations stay POST-driven and browser updates arrive over `GET /chat/sessions/{session_id}/events` SSE instead of WebSockets or POST-streaming.
- [Phase 18-chat-workspace]: Browser reconnect recovery remains split by concern: SessionManager supplies transcript state, while the SSE broker only replays transient transport events after Last-Event-ID.
- [Phase 18-chat-workspace]: CLI safety stayed test-driven; tests now assert the unchanged cli:direct process_direct call shape instead of broadening nanobot/cli/commands.py.
- [Phase 19]: RuntimeService normalizes legacy Phase 17 RuntimeInspectionContract payloads to the Phase 19 aggregate DTO shape.
- [Phase 19]: Phase 19 keeps get_task_launch_contract() read-only while the mutable typed launch contract is injected only through get_task_launch_service().
- [Phase 19]: Typed nanobot browser launches translate to private GuiSubagentTool task text inside nanobot/tui so no free-form task or prompt API is exposed publicly.
- [Phase 19]: OpenGUI browser launches run through tui-local local/dry-run backend adapters instead of shelling out through opengui.cli.
- [Phase 19]: Public diagnostics stay run_id-addressed only; TraceInspectionService resolves artifact directories internally from the shared registry or artifacts root.
- [Phase 19]: Trace and log payloads are allowlist-based and sanitize prompt/path leakage by dropping unsafe fields and redacting prompt/path text in summaries or messages.
- [Phase 20]: The browser workspace lives in a dedicated `nanobot/tui/web` React/Vite app, while session and run identity stay encoded in the URL for cross-view continuity.
- [Phase 20]: Built frontend serving remains opt-in behind `serve_frontend=True`, and both fetch and SSE clients share one explicit API base-resolution contract.
- [Phase 20]: `python -m nanobot.tui` remains the canonical packaged seam, with `nanobot-tui` added as an alias while the existing `nanobot` CLI stays unchanged.
- [Phase 20]: Packaged frontend assets resolve through `nanobot.tui.web` package resources instead of cwd-relative paths.
- [Phase 21]: PlanningContext now wraps planner-only inputs so future memory hints can extend planning without another planner API break.
- [Phase 21]: Capability catalogs are built from an allowlisted live route inventory instead of dumping raw tool schemas into the planner prompt.
- [Phase 21]: Route metadata stays optional on PlanNode and is exposed in logs only; router dispatch behavior remains unchanged until Phase 22.
- [Phase 21]: Routing memory stays planner-only and read-only by extracting compact DTOs from MemoryStore instead of reusing ContextBuilder or get_memory_context().
- [Phase 21]: Planner prompts render routing memory in a separate capped section with explicit omission text once hint count or budget limits are hit.
- [Phase 21]: AgentLoop builds routing hints immediately before planning so the live catalog and memory evidence stay aligned without changing router dispatch behavior.
- [Phase 22]: Route resolution uses _ROUTE_ID_TO_TOOL_NAME + _INSTRUCTION_PARAM tables; multi-param tools return None param_key from _resolve_route() to prevent instruction-only dispatch
- [Phase 22]: MCP dispatch routes through context.tool_registry (not mcp_client) since MCPToolWrapper pre-registers mcp_{server}_{tool} keys; mcp_client retained for backward compatibility
- [Phase 22]: _run_tool and _run_mcp accept full PlanNode (not instruction string) so route_id and fallback_route_ids are available at dispatch time
- [Phase 22]: _dispatch_with_fallback is shared between _run_tool and _run_mcp: capability boundary advisory when fallbacks declared
- [Phase 22]: gui.desktop is a sentinel route_id that delegates to _run_gui, skipped with diagnostic when gui_agent is None
- [Phase 22]: _run_tool/_run_mcp delegate to _dispatch_with_fallback only when fallback_route_ids is non-empty to preserve simple direct-dispatch path
- [260325-l2b]: PlanningContext.active_gui_route carries session GUI route_id; empty string = planner self-judgment (no regression)
- [260325-l2b]: CapabilityCatalogBuilder.build() gui_backend="adb" overrides route_id/kind/summary inline; _ROUTE_SPECS class constant unchanged
- [260325-l2b]: active_gui_route derivation: adb->gui.adb, local/dry-run->gui.desktop (local does NOT produce gui.local)
- [260325-l2b]: Router _dispatch_with_fallback handles gui.adb sentinel same as gui.desktop via set membership check
- [Phase quick]: [260326-e16]: _JIEBA_AVAILABLE module-level flag dispatches _tokenize() to jieba or char-level fallback; SkillLibrary inherits improvement via shared _BM25Index with no changes
- [Phase quick-260330-l0g]: HdcBackend platform=harmonyos for AppCache keying; JPEG->PNG via PIL in asyncio.to_thread; static bundle list for list_apps(); open_app uses bundle/ability slash convention with MainAbility default; gui.hdc sentinel added to router/loop/capabilities like gui.adb and gui.ios
- [v1.5-roadmap]: Phase 24 groups SCHEMA-01..06 and GRND-01..03 together because grounding protocol is a typed contract required by both schemas and executors; they form a single foundation layer
- [v1.5-roadmap]: Phase 25 (execution) and Phase 26 (extraction) both depend on Phase 24 schemas but are independent of each other; execution needs the runtime contracts, extraction only needs schema shapes to produce skill candidates
- [v1.5-roadmap]: Phase 27 is the capstone: persists what extraction produces, enables search across both layers, and wires GuiAgent to consume both layers with memory context injection
- [v1.5-roadmap]: Fresh start on skill data — old skills.json kept as reference, new stores start empty; quality-gated re-extraction produces better seeds than migrating brittle pixel-coordinate skills
- [Phase 24]: ShortcutSkill reuses the legacy SkillStep contract so Phase 24 adds schema without changing the existing executor path.
- [Phase 24]: StateDescriptor omits negated from serialized output when false so shortcut schema payloads stay compact while preserving round-trip fidelity.
- [Phase 24]: TaskSkill persists mixed task nodes with explicit `kind` tags (`shortcut_ref`, `atom_step`, `branch`) instead of field-shape inference.
- [Phase 24]: TaskSkill keeps memory_context_id as an opaque string pointer — Preserves a stable schema contract in Phase 24 without pulling memory lookup behavior into the model layer before Phase 27.
- [Phase 24]: Grounding returns structured parameter metadata instead of executable Action objects — Keeps Phase 24 contract-only and lets Phase 25 executors own action construction and runtime execution semantics.
- [Phase 24]: LLMGrounder accepts the existing `LLMProvider` protocol and parses JSON or tool-call argument payloads into `resolved_params`.
- [Phase 25]: ShortcutExecutor in multi_layer_executor.py is separate from legacy executor.py — incompatible fail-open and template-fallback semantics
- [Phase 25]: ConditionEvaluator optional injection defaults to always-pass _AlwaysPassEvaluator for dry-run and test scenarios without LLM/device
- [Phase 25]: All step actions normalize through parse_action() regardless of grounding mode — fixed steps feed fixed_values, grounded steps feed resolved_params
- [Phase 25 P02]: TaskSkillExecutor delegates inline SkillStep execution to ShortcutExecutor._execute_step — ensures EXEC-03 grounding seam is truly shared, not duplicated
- [Phase 25 P02]: Fallback block measured before shortcut resolution attempt — avoids partial execution ambiguity on resolution edge cases
- [Phase 25 P02]: BranchNode subtrees recursively processed via _walk_nodes — enables nested branches without special-casing
- [Phase 26]: ExtractionPipeline rejects trajectories with fewer than two steps before invoking any critic, then short-circuits from step critic to trajectory critic to producer in strict order
- [Phase 26]: Phase 26 public extraction types are exported from opengui.skills so callers can adopt the pipeline without deep module imports
- [Phase 27]: Run BM25 plus optional FAISS search inside each store, then merge via UnifiedSkillSearch with layer weights.

### Pending Todos

1. Discuss Phase 27 — storage, search, and agent integration (STOR-01, STOR-02, INTEG-01, INTEG-02)
2. Plan Phase 27 — versioned stores, unified search, and GuiAgent wiring

### Blockers/Concerns

- v1.2 closeout artifacts still exist in `.planning/phases/16-host-integration-and-verification/` and should not be overwritten during v1.3 work.
- The web milestone must avoid broad runtime refactors that would entangle `nanobot`, `opengui`, and the new frontend.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260322-kjf | Implement planner fallback so forced create_plan tool_choice automatically retries with auto on unsupported thinking-mode tool_choice errors, preserving diagnostics and tests | 2026-03-22 | 4da2b40 | [260322-kjf-implement-planner-fallback-so-forced-cre](./quick/260322-kjf-implement-planner-fallback-so-forced-cre/) |
| 260322-krq | Fix planner decomposition logging to print the real tree.to_dict() output instead of the literal %s placeholder | 2026-03-22 | 82386a7 | [260322-krq-fix-planner-decomposition-logging-to-pri](./quick/260322-krq-fix-planner-decomposition-logging-to-pri/) |
| 260322-kvk | Add a human-friendly indented tree representation for planner decomposition logs while preserving structured plan visibility | 2026-03-22 | eef711b | [260322-kvk-add-a-human-friendly-indented-tree-repre](./quick/260322-kvk-add-a-human-friendly-indented-tree-repre/) |
| 260322-l7j | Design capability-aware planning and routing so planner can see live routes, use memory-derived routing hints, and drive real tool/MCP router dispatch; update roadmap and design docs for v1.4 | 2026-03-22 | cd1f90c | [260322-l7j-design-capability-aware-planning-and-rou](./quick/260322-l7j-design-capability-aware-planning-and-rou/) |
| 260322-otm | Add PlanNode.params field and update router dispatch to prefer structured params over instruction fallback; enables multi-param tools (write_file, edit_file) to be dispatched by the planner | 2026-03-22 | 76e6b2b | [260322-otm-planner](./quick/260322-otm-planner/) |
| 260322-ptr | Replace debug-card ChatWorkspaceRoute with full chat UI: Tailwind v4 earth-tone styling, SSE streaming, session sidebar with localStorage persistence, message bubbles and input | 2026-03-22 | a6a56da | [260322-ptr-web-chat-ui-mvp](./quick/260322-ptr-web-chat-ui-mvp/) |
| 260322-uqf | Fix CJK IME composing Enter bug in MessageInput and clean up shell header/operations debug UI; all 5 frontend tests pass | 2026-03-22 | a61f88b | [260322-uqf-composing-enter-bug](./quick/260322-uqf-composing-enter-bug/) |
| 260323-p01 | 修复 GUI action 容错与 GUI 成功后 Telegram 完成消息延迟 | 2026-03-23 | b828c5b | [260323-p01-gui-action-gui-telegram](./quick/260323-p01-gui-action-gui-telegram/) |
| 260323-q1s | 设计 desktop 真实 GUI memory 命中端到端测试并标明应查看的 run trace | 2026-03-23 | 8048c6b | [260323-q1s-desktop-gui-memory-run-trace](./quick/260323-q1s-desktop-gui-memory-run-trace/) |
| 260323-q5j | 执行 desktop/local 真实 GUI memory 命中测试并分析实际 run trace；确认 memory 命中但执行结果仅 partial | 2026-03-23 | 464fbbc | [260323-q5j-desktop-local-gui-memory-run-trace](./quick/260323-q5j-desktop-local-gui-memory-run-trace/) |
| 260323-qdw | 审查并提交必要的 memory 可观测性改动，然后修复 `~/.opengui/config.yaml` 的 embedding 兼容问题 | 2026-03-23 | uncommitted | [260323-qdw-memory-opengui-config-yaml-embedding](./quick/260323-qdw-memory-opengui-config-yaml-embedding/) |
| 260323-qm7 | 构建 Android 手机 memory 文件：创建 icon_guide.md 和 policy.md，将 tmp_ 文件转换为可解析格式，并为 os_guide.md 和 app_guide.md 添加 17 条 Android OS 操作和 35 条主流中国 App 使用指南 | 2026-03-23 | 3608ed9 | [260323-qm7-build-android-phone-memory-files-for-ope](./quick/260323-qm7-build-android-phone-memory-files-for-ope/) |
| 260323-tm8 | 修复 planner 返回大写 `AND/ATOM` 时 router 报 `Unknown node type` 的问题，并补解析与执行层回归测试 | 2026-03-23 | uncommitted | [260323-tm8-planner-and-atom-router-unknown-node-typ](./quick/260323-tm8-planner-and-atom-router-unknown-node-typ/) |
| 260323-ud4 | 在 planning 分支执行前向当前 channel 发送 plan 预览消息，并补发送行为测试 | 2026-03-23 | uncommitted | [260323-ud4-plan-channel-plan](./quick/260323-ud4-plan-channel-plan/) |
| 260324-k9r | 修复技能提取：统一 gui_skills 存储根目录并规范化提取出的 app 标识，恢复 SkillLibrary 的合并与管理能力 | 2026-03-24 | 0e5ef97 | [260324-k9r-gui-skills-app-skilllibrary](./quick/260324-k9r-gui-skills-app-skilllibrary/) |
| 260324-ltk | Add OPPO/ColorOS app mappings, filter annotate_android_apps to mapped-only, show display names without package identifiers in system prompt | 2026-03-24 | b392c90 | [260324-ltk-filter-system-prompt-to-mapped-only-apps](./quick/260324-ltk-filter-system-prompt-to-mapped-only-apps/) |
| 260324-mzh | Fix Telegram bot not replying after GUI task: replace elif msg.channel == "cli": with else: in _dispatch so all channels receive empty OutboundMessage cleanup signal | 2026-03-24 | 5124b0d | [260324-mzh-fix-telegram-bot-not-replying-after-gui-](./quick/260324-mzh-fix-telegram-bot-not-replying-after-gui-/) |
| 260324-oks | 简化 gui_skills 目录结构为每个平台单一 skills.json 聚合文件 | 2026-03-24 | uncommitted | [260324-oks-gui-skills-skills-json](./quick/260324-oks-gui-skills-skills-json/) |
| 260324-p41 | Make GUI trajectory summarization and skill extraction run in background after GUI agent returns | 2026-03-24 | uncommitted | [260324-p41-make-gui-trajectory-summarization-and-sk](./quick/260324-p41-make-gui-trajectory-summarization-and-sk/) |
| 260402-q5f | 现在执行gui任务，我希望动作执行完成之后再进行截图，而不是动作还没执行结束就截图;另外，eval.py上，/Users/jinli/.nanobot/workspace/gui_runs/2026-04-02_184228_600485/trace_20260402_184228.jsonl和/Users/jinli/.nanobot/workspace/gui_runs/2026-04-02_184228_600485/evaluation.json，应该只读type为step的步骤计入步数 | 2026-04-02 | 1ac5e43 | [260402-q5f-gui-eval-py-users-jinli-nanobot-workspac](./quick/260402-q5f-gui-eval-py-users-jinli-nanobot-workspac/) |
| 260324-wak | Wire Nanobot GUI tool to use OpenGUI memory retrieval with configured embedding model | 2026-03-24 | uncommitted | [260324-wak-wire-nanobot-gui-tool-to-use-opengui-mem](./quick/260324-wak-wire-nanobot-gui-tool-to-use-opengui-mem/) |
| 260325-06v | Switch nanobot GUI memory embedding to the same direct OpenAI-compatible path used by OpenGUI CLI and document required config changes | 2026-03-25 | uncommitted | [260325-06v-switch-nanobot-gui-memory-embedding-to-t](./quick/260325-06v-switch-nanobot-gui-memory-embedding-to-t/) |
| 260325-kgy | Split GUI memory by type: os/app/icon guide entries to planner via PlanningContext.gui_memory_context, policy entries directly to GUI agent system prompt | 2026-03-25 | c008d1e | [260325-kgy-gui-memory-os-app-icon-guide-planner-pla](./quick/260325-kgy-gui-memory-os-app-icon-guide-planner-pla/) |
| 260325-l2b | Fix planner route selection so GUI subtasks use gui.adb vs gui.desktop based on active backend; PlanningContext.active_gui_route, backend-aware catalog, planner directive, router gui.adb sentinel | 2026-03-25 | b2b7daf | [260325-l2b-planner-planningcontext-active-backend-p](./quick/260325-l2b-planner-planningcontext-active-backend-p/) |
| 260325-sku | Fix ExecTool exit code error detection, AND sequential execution, and GUI-only complexity gate in router.py and loop.py | 2026-03-25 | 56e685b | [260325-sku-and-complexity-tool-gui-plan](./quick/260325-sku-and-complexity-tool-gui-plan/) |
| 260325-ts0 | Wire SkillExecutor into nanobot GuiSubagentTool via enable_skill_execution config flag; add enable_skill_execution field to GuiConfig | 2026-03-25 | 5f81c1b | [260325-ts0-nanobot](./quick/260325-ts0-nanobot/) |
| 260326-e16 | 引入jieba进行分词,为稳定的中文检索进行支持,并确认skills的检索也支持中文稳定检索 | 2026-03-26 | 34b41ed | [260326-e16-jieba-skills](./quick/260326-e16-jieba-skills/) |
| 260330-khq | Add iOS/iPhone WDA backend to OpenGUI: WdaBackend, bundle ID normalization, CLI --backend ios, nanobot gui.ios routing | 2026-03-30 | 34adab0 | [260330-khq-opengui-iphone-os](./quick/260330-khq-opengui-iphone-os/) |
| 260330-l0g | Add HarmonyOS HDC backend to OpenGUI: HdcBackend with JPEG screenshot, uitest uiInput actions, aa dump foreground detection, CLI --backend hdc, nanobot gui.hdc routing | 2026-03-30 | 767e290 | [260330-l0g-opengui-hdc-harmony-os](./quick/260330-l0g-opengui-hdc-harmony-os/) |
| 260402-pb1 | Decouple main-agent vs GUI-agent model/provider selection and add optional GUI post-run evaluation hook wired to shared eval logic | 2026-04-02 | uncommitted | [260402-pb1-nanobot-opengui-agent-gui-agent-nanobot-](./quick/260402-pb1-nanobot-opengui-agent-gui-agent-nanobot-/) |

## Session Continuity

Last activity: 2026-04-02

Last session: 2026-04-02T12:48:21.616Z
Stopped at: Completed 27-02-PLAN.md
Resume file: None
