# Phase 5: CLI & Extensions - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Standalone CLI entry point (`python -m opengui.cli`) that drives a full GuiAgent loop without any host agent code, plus a documented adapter pattern (ADAPTERS.md) so other claw integrations can implement their own LLMProvider/DeviceBackend bridges. This phase does NOT add new agent capabilities, modify the agent loop, or change any existing backends.

</domain>

<decisions>
## Implementation Decisions

### CLI invocation & flags
- Entry point: `python -m opengui.cli` via `opengui/cli.py` + `opengui/__main__.py`
- Task specified as positional arg OR `--task` flag: `python -m opengui.cli "Open Settings"` or `--task "Open Settings"`
- Backend selection: `--backend adb|local|dry-run` (default: `local`)
- `--dry-run` shortcut flag as alias for `--backend dry-run`
- Minimal flags only: `--backend`, `--task`, `--dry-run`, `--json`, `--config`. No agent tuning knobs (max-steps etc.) — sensible defaults
- LLM configuration via config file (not CLI flags) — see LLM provider section

### CLI output & feedback
- Step-by-step log printed during runs: `Step 1: tap (500, 300) — Tapped Settings icon`
- Final result in human-readable text by default
- `--json` flag outputs AgentResult as JSON for scripting/CI use
- Artifacts (screenshots + trace.jsonl) auto-saved to `./opengui_runs/{timestamp}/` by default

### LLM provider setup
- CLI ships its own **OpenAI-compatible LLMProvider** implementation — works with OpenAI, Azure, local servers (Ollama, vLLM), any OpenAI-compatible endpoint
- Config file at `~/.opengui/config.yaml` with provider settings (base_url, model, api_key)
- Environment variable fallback: `OPENAI_API_KEY` used if api_key not in config — standard convention, good for CI
- Config file overridable via `--config path/to/config.yaml`
- **Memory/skills are optional**: if embedding config is present in config.yaml (embedding_api_key, embedding_model), memory retrieval and skill library are enabled. If absent, agent runs without them — keeps one-off CLI use simple

### Adapter documentation (EXT-01)
- Separate `ADAPTERS.md` file in repo root (not inline docstrings)
- Scope: protocol summary + code example — list the two protocols (LLMProvider, DeviceBackend), explain the wiring pattern
- Includes a **skeleton example adapter** (~30 lines) showing how to wrap a hypothetical host's LLM into opengui's LLMProvider — copy-paste starting point
- References NanobotLLMAdapter as the real-world production example

### Claude's Discretion
- argparse vs click for CLI parsing (argparse preferred for zero-dependency)
- Config file YAML schema details
- Default max_steps value
- OpenAI-compatible provider implementation details (httpx vs openai SDK)
- Exact step log formatting
- ADAPTERS.md section organization and skeleton adapter naming

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core Protocols
- `opengui/interfaces.py` — LLMProvider, DeviceBackend, EmbeddingProvider protocols that adapters must conform to
- `opengui/agent.py` — GuiAgent constructor params (llm, backend, trajectory_recorder, memory_retriever, skill_library) and AgentResult dataclass

### Existing Backend Implementations
- `opengui/backends/adb.py` — AdbBackend reference implementation
- `opengui/backends/desktop.py` — LocalDesktopBackend for `--backend local`
- `opengui/backends/dry_run.py` — DryRunBackend for `--dry-run`

### Adapter Reference Implementation
- `nanobot/agent/gui_adapter.py` — NanobotLLMAdapter + NanobotEmbeddingAdapter (real-world adapter bridge pattern to document)

### Agent Components (optional CLI features)
- `opengui/memory/retriever.py` — MemoryRetriever for optional memory support
- `opengui/skills/library.py` — SkillLibrary for optional skill support
- `opengui/trajectory/recorder.py` — TrajectoryRecorder for run artifacts

### Prior Phase Decisions
- `.planning/phases/03-nanobot-subagent/03-CONTEXT.md` — Backend selection pattern, adapter bridge design
- `.planning/phases/04-desktop-backend/04-CONTEXT.md` — LocalDesktopBackend behavior and platform detection

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `GuiAgent`: Full constructor with all optional components — CLI just needs to wire up the right provider and backend
- `AgentResult`: Frozen dataclass with success, summary, trace_path, steps_taken, error — maps directly to CLI output
- `TrajectoryRecorder`: JSONL recording with artifacts_root — CLI sets artifacts_root to `./opengui_runs/{timestamp}/`
- `AdbBackend`, `LocalDesktopBackend`, `DryRunBackend`: All three backends ready to use
- `MemoryRetriever`, `SkillLibrary`, `SkillExecutor`: Optional components CLI can wire if embedding config present

### Established Patterns
- Protocol-based interfaces — CLI's OpenAI-compatible LLMProvider must satisfy `LLMProvider` structurally
- Async-first design — CLI will need `asyncio.run()` as the entry point
- Frozen dataclasses for data containers
- `ProgressCallback` type in interfaces.py — CLI can use this for step-by-step logging

### Integration Points
- `opengui/__main__.py`: New file — `from opengui.cli import main; main()`
- `opengui/cli.py`: New file — argparse setup, config loading, provider construction, agent wiring
- `ADAPTERS.md`: New file in repo root — adapter pattern documentation

</code_context>

<specifics>
## Specific Ideas

- Config file approach for LLM settings keeps the CLI invocation clean — no long flag chains for API keys and model names
- Env var fallback for API keys follows standard conventions (OPENAI_API_KEY) — familiar to developers, works in CI
- Memory/skills as opt-in via config keeps the entry barrier low for quick one-off runs while allowing power users to build up a skill library over time
- ADAPTERS.md with a skeleton adapter gives other claw developers a copy-paste starting point rather than forcing them to reverse-engineer NanobotLLMAdapter

</specifics>

<deferred>
## Deferred Ideas

- Interactive mode (step-by-step with user confirmation) — explicitly out of scope per PROJECT.md
- Plugin system for custom backends — overkill for v1, DeviceBackend protocol is sufficient
- Web UI for watching agent runs — separate project entirely
- Config file validation/init command (`opengui init`) — nice-to-have for v2
- Multi-provider support (Anthropic, Google natively) — OpenAI-compatible covers most cases via proxy

</deferred>

---

*Phase: 05-cli-extensions*
*Context gathered: 2026-03-18*
