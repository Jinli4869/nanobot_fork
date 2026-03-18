# Phase 5: CLI & Extensions - Research

**Researched:** 2026-03-18
**Domain:** Standalone `opengui` CLI wiring, OpenAI-compatible provider bridge, adapter documentation
**Confidence:** HIGH (phase boundary and integration seams verified against current codebase; only new dependency need is YAML parsing)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- Entry point is `python -m opengui.cli` via `opengui/cli.py` plus `opengui/__main__.py`
- Task can be passed positionally or with `--task`
- Backend flags are minimal: `--backend adb|local|dry-run`, `--dry-run`, `--json`, `--config`
- Default backend is `local`
- LLM settings live in `~/.opengui/config.yaml`, overridable with `--config`
- `OPENAI_API_KEY` is the fallback if the config omits `api_key`
- CLI uses its own OpenAI-compatible `LLMProvider` implementation
- Memory and skills are optional and only enabled when embedding config is present
- Run artifacts are written under `./opengui_runs/{timestamp}/`
- Adapter documentation lives in a separate repo-root `ADAPTERS.md`
- Documentation must explain `LLMProvider` / `DeviceBackend` and reference `NanobotLLMAdapter`

### Claude's Discretion

- YAML schema details for CLI config
- Exact default `max_steps`
- Whether the OpenAI-compatible provider helper lives in `opengui/cli.py` or a small adjacent helper module
- Exact progress log format
- Whether to add one short adapter-oriented comment/docstring in code in addition to `ADAPTERS.md`

### Deferred / Out of Scope

- Interactive CLI mode
- Plugin system for custom backends
- New GUI agent capabilities or agent-loop redesign
- Native multi-provider abstractions beyond an OpenAI-compatible endpoint
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CLI-01 | `python -m opengui.cli` standalone entry point | `GuiAgent`, backends, trajectory recorder, and prompt loop are already production code; only CLI/config/provider wiring is missing |
| EXT-01 | Document adapter pattern for other claw hosts | `opengui.interfaces` defines the two protocols cleanly and `nanobot/agent/gui_adapter.py` is an existing real adapter reference |
</phase_requirements>

---

## Summary

Phase 5 is mostly orchestration, not new core logic. The key finding is that the `opengui` runtime pieces already exist and are stable:

- `GuiAgent` already exposes the full constructor seam the CLI needs: `llm`, `backend`, `trajectory_recorder`, optional `memory_retriever`, optional `skill_library`, optional `skill_executor`, and `progress_callback`
- `AdbBackend`, `LocalDesktopBackend`, and `DryRunBackend` are already available and selected entirely in Python
- `TrajectoryRecorder` already writes a JSONL artifact for every run and `GuiAgent` already writes screenshots and trace files under `artifacts_root`
- `nanobot/agent/gui_adapter.py` is the clearest real-world example of the adapter pattern Phase 5 needs to document

The missing pieces are:

1. A standalone CLI surface in `opengui`
2. A config loader independent from nanobot
3. An OpenAI-compatible `LLMProvider` implementation in `opengui`
4. Optional embedding-backed memory/skill wiring
5. Adapter documentation that satisfies both the roadmap requirement and the context decision

Two implementation constraints matter for planning:

- `GuiAgent` requires a `TrajectoryRecorder`; the CLI cannot just instantiate the agent with `llm` and `backend`
- If the CLI enables `skill_library`, it should also enable `skill_executor`; otherwise `GuiAgent` may still match skills and run post-run confidence maintenance even though no skill was actually executed

The cleanest plan split is:

- Plan 05-01: CLI entry point, config loading, provider adapter, backend factory, result/progress output, and automated dry-run tests
- Plan 05-02: adapter documentation plus the small code comment/docstring needed to satisfy the success criterion precisely

---

## Standard Stack

### Core

| Tool / Module | Use | Why |
|---------------|-----|-----|
| `argparse` (stdlib) | CLI parsing | Zero new runtime dependency; matches locked decision for a minimal CLI |
| `asyncio` (stdlib) | `asyncio.run()` entrypoint | `GuiAgent`, backends, and provider interfaces are async-first |
| `openai.AsyncOpenAI` | OpenAI-compatible chat + embeddings client | Already a project dependency and already used in `nanobot/providers/custom_provider.py` |
| `PyYAML` | `config.yaml` parsing | Required by the locked YAML config decision; not currently in project dependencies |
| `json_repair` | Tool-call argument parsing | Already a dependency and already used in `nanobot/providers/custom_provider.py` for malformed tool JSON |
| `pathlib` / `dataclasses` / `json` | Config paths and JSON output | Standard library; enough for the CLI data flow |

### Reuse From Current Codebase

| File | Why it matters |
|------|----------------|
| `opengui/agent.py` | Exact constructor and progress-callback contract the CLI must honor |
| `opengui/interfaces.py` | Source of truth for `LLMProvider`, `DeviceBackend`, `ToolCall`, and `LLMResponse` |
| `opengui/backends/adb.py` | Factory target for `--backend adb` |
| `opengui/backends/desktop.py` | Factory target for `--backend local` |
| `opengui/backends/dry_run.py` | Fast automated CLI integration path |
| `opengui/trajectory/recorder.py` | Artifact and JSONL recording behavior |
| `nanobot/providers/custom_provider.py` | Best local reference for an OpenAI-compatible provider bridge |
| `nanobot/agent/gui_adapter.py` | Best local reference for adapter documentation |

### Do Not Reuse Directly

| Existing code | Why not |
|---------------|---------|
| `nanobot.config.*` | Pulls `opengui` back into nanobot conventions; Phase 5 should keep `opengui` usable without nanobot |
| `nanobot.providers.*` | Same dependency-direction problem; use as reference, not as runtime dependency |
| `typer`-based nanobot CLI patterns | Overkill for the locked minimal CLI surface |

---

## Architecture Patterns

### Pattern 1: Keep `opengui` Independent

The CLI must not import nanobot config or provider classes at runtime. The only acceptable dependency direction is:

```text
opengui -> opengui
nanobot -> opengui
```

`nanobot/agent/gui_adapter.py` is documentation input, not an implementation dependency.

### Pattern 2: Thin CLI Wrapper Around `GuiAgent`

The CLI should assemble components, then hand execution to `GuiAgent.run()`:

```python
backend = build_backend(args, config)
run_root = Path("opengui_runs") / timestamp
recorder = TrajectoryRecorder(output_dir=run_root, task=task, platform=backend.platform)
agent = GuiAgent(
    llm=provider,
    backend=backend,
    trajectory_recorder=recorder,
    artifacts_root=run_root,
    progress_callback=progress_cb,
    memory_retriever=memory_retriever,
    skill_library=skill_library,
    skill_executor=skill_executor,
)
result = await agent.run(task)
```

This is the correct abstraction boundary: the CLI owns configuration and presentation, while `GuiAgent` owns the step loop.

### Pattern 3: Provider Bridge Mirrors `nanobot/providers/custom_provider.py`

`opengui.interfaces.LLMProvider` is smaller than nanobot's provider interface:

- `chat(messages, tools=None, tool_choice=None) -> LLMResponse`

The Phase 5 provider should:

- use `AsyncOpenAI(base_url=..., api_key=...)`
- pass through tools and `tool_choice`
- parse provider tool calls into `opengui.interfaces.ToolCall`
- use `json_repair.loads()` for tool arguments
- return `opengui.interfaces.LLMResponse`

This is a direct parallel to `NanobotLLMAdapter`, except the provider talks to an OpenAI-compatible HTTP endpoint instead of adapting nanobot's provider ABC.

### Pattern 4: Embeddings Must Be Gated as a Bundle

The context decision is "if embedding config is present, enable memory retrieval and skill library." In practice, the safe bundle is:

- embedding provider
- `MemoryStore` + `MemoryRetriever`
- `SkillLibrary`
- `SkillExecutor`

Do not enable `SkillLibrary` without `SkillExecutor`. `GuiAgent` will still search skills and later run `_skill_maintenance()` on the matched skill, which is misleading if the skill never executed.

Also, `SkillLibrary` already persists by `{platform}/{app}` internally, so the standalone CLI should not add a second outer platform directory layer around its chosen skill store root.

### Pattern 5: Progress Output Should Wrap `progress_callback`

`GuiAgent` already emits progress through an async callback with lines like:

```text
GUI step 1/15: tap (500, 300)
```

The CLI does not need a new progress protocol. It only needs an async printer that converts those messages into the desired terminal format.

### Pattern 6: Documentation Must Satisfy Two Targets

There is a small requirement/context mismatch:

- roadmap success criterion: a code comment or docstring in the CLI or interfaces module explains the adapter pattern
- context decision: put the real documentation in `ADAPTERS.md`

The safe implementation is:

1. `ADAPTERS.md` contains the real explanation and skeleton example
2. `opengui/interfaces.py` or `opengui/cli.py` gets a short pointer comment/docstring that references `ADAPTERS.md`

That satisfies both without bloating code comments.

---

## Recommended Project Structure

```text
opengui/
├── __main__.py              # delegates to cli.main()
├── cli.py                   # argparse + config + provider/backend assembly
├── interfaces.py            # small adapter-pattern note or docstring pointer
└── ...existing modules...
ADAPTERS.md                  # new adapter documentation
tests/
└── test_opengui_p5_cli.py   # new Phase 5 tests
```

Possible helper split if `cli.py` gets too large:

```text
opengui/
├── cli.py
├── cli_provider.py          # OpenAI-compatible provider + embedding adapter
└── cli_config.py            # YAML loader/dataclasses
```

This is acceptable if the planner decides the single-file CLI would become too dense.

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| CLI framework | Typer/Rich command tree | `argparse` | Phase scope is small and flags are fixed |
| Chat client | Manual `httpx` request payloads | `openai.AsyncOpenAI` | Already in dependencies; handles OpenAI-compatible APIs cleanly |
| Tool-call JSON recovery | ad hoc regex parsing | `json_repair.loads()` | Already used in nanobot provider code |
| YAML parsing | hand-written parser | `PyYAML.safe_load()` | The config format is explicitly YAML |
| Adapter docs | reverse-engineering prose from nanobot internals | `ADAPTERS.md` + direct reference to `nanobot/agent/gui_adapter.py` | Faster and clearer for downstream integrators |

---

## Common Pitfalls

### Pitfall 1: Pulling Nanobot Runtime Code Into `opengui`

This would violate the core architectural boundary that `opengui` is host-agent-independent. Use nanobot files as reference material only.

### Pitfall 2: Forgetting the YAML Dependency

The repo currently has no runtime YAML parser in `pyproject.toml`. If Phase 5 chooses `config.yaml`, it must add `PyYAML` (or equivalent) explicitly.

### Pitfall 3: Enabling Skill Search Without Skill Execution

`GuiAgent.run()` always performs `_search_skill()` when `skill_library` exists. If `skill_executor` is omitted, the skill is not executed but `_skill_maintenance()` can still update confidence counters for the matched skill after the run. The plan should wire both together or disable both together.

### Pitfall 4: Misunderstanding `artifacts_root`

`GuiAgent` creates a per-task-attempt subdirectory under `artifacts_root`; it does not write directly into `artifacts_root`. If the CLI prints artifact paths, it should rely on `AgentResult.trace_path` / recorder path instead of assuming a fixed leaf path.

### Pitfall 5: Treating `progress_callback` as Sync

`ProgressCallback` is `Callable[[str], Awaitable[None]]`. A synchronous `print` callback will not satisfy the protocol.

### Pitfall 6: `ADAPTERS.md` May Not Ship in the Current sdist

Current build config includes only selected root files. If packaged source distribution visibility matters, Phase 5 may need to add `ADAPTERS.md` to the sdist include list.

### Pitfall 7: Missing the Success-Criterion Comment / Docstring

`ADAPTERS.md` alone may satisfy the context decision but not the literal roadmap text. Add one short in-code pointer.

---

## Code Examples

### `GuiAgent` seam the CLI should target

```python
# Source: opengui/agent.py
agent = GuiAgent(
    llm=provider,
    backend=backend,
    trajectory_recorder=recorder,
    model=config.model,
    artifacts_root=run_root,
    progress_callback=progress_cb,
    memory_retriever=memory_retriever,
    skill_library=skill_library,
    skill_executor=skill_executor,
)
result = await agent.run(task=task)
```

### OpenAI-compatible provider parsing pattern

```python
# Source pattern: nanobot/providers/custom_provider.py
response = await client.chat.completions.create(
    model=model,
    messages=messages,
    tools=tools,
    tool_choice=tool_choice or "auto",
)
tool_calls = [
    ToolCall(
        id=tc.id,
        name=tc.function.name,
        arguments=json_repair.loads(tc.function.arguments),
    )
    for tc in (response.choices[0].message.tool_calls or [])
]
return LLMResponse(content=response.choices[0].message.content or "", tool_calls=tool_calls or None)
```

### `__main__` delegation pattern

```python
from opengui.cli import main

if __name__ == "__main__":
    main()
```

### Adapter doc pointer in code

```python
"""For host-agent adapter examples, see repo-root ADAPTERS.md and nanobot/agent/gui_adapter.py."""
```

---

## State of the Art

| Old state | Current state | Impact on Phase 5 |
|-----------|---------------|-------------------|
| No `opengui` CLI entry point | Only nanobot has a first-class CLI | Phase 5 is the first direct user-facing surface for `opengui` |
| Host integration via nanobot only | Protocol-first architecture already exists in `opengui.interfaces` | Other claw hosts can be documented without changing core protocols |
| Config conventions live in nanobot JSON | Phase 5 intentionally chooses `~/.opengui/config.yaml` | `opengui` gets an independent user-facing configuration story |

---

## Open Questions

1. **Where should optional memory and skill stores live by default?**
   - The context locks artifact output but does not lock memory/skill directories.
   - Recommendation: either add explicit config keys for those paths or default to `~/.opengui/memory/` and `~/.opengui/skills/`.

2. **Should `ADAPTERS.md` be shipped in sdists?**
   - If the docs are only for repo contributors, root file is enough.
   - If packaged consumers are in scope, update the hatch sdist include list.

3. **Should Phase 5 add a console script too?**
   - Not required. `python -m opengui.cli` is sufficient for the roadmap.
   - `python -m opengui` via `__main__.py` is still worthwhile because the context asked for it and it is nearly free.

4. **How much config schema should be exposed now?**
   - Locked flags are minimal, but the YAML can still include optional fields for embeddings, memory path, skills path, and model name.
   - Recommendation: keep the file small and focused on provider + optional embeddings.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_opengui_p5_cli.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CLI-01 | CLI parses `--backend`, `--dry-run`, positional task, and `--task` correctly | unit | `pytest tests/test_opengui_p5_cli.py::test_cli_parses_task_and_backend_flags -x` | ❌ Wave 0 |
| CLI-01 | config loader reads YAML and falls back to `OPENAI_API_KEY` when `api_key` is omitted | unit | `pytest tests/test_opengui_p5_cli.py::test_load_config_env_fallback -x` | ❌ Wave 0 |
| CLI-01 | backend factory returns `AdbBackend`, `LocalDesktopBackend`, and `DryRunBackend` for the three modes | unit | `pytest tests/test_opengui_p5_cli.py::test_build_backend_variants -x` | ❌ Wave 0 |
| CLI-01 | CLI runner instantiates `GuiAgent` and prints human-readable output for a successful dry-run | integration | `pytest tests/test_opengui_p5_cli.py::test_cli_runs_dry_run_agent_loop -x` | ❌ Wave 0 |
| CLI-01 | `--json` prints machine-readable `AgentResult` fields | integration | `pytest tests/test_opengui_p5_cli.py::test_cli_json_output -x` | ❌ Wave 0 |
| CLI-01 | `opengui/__main__.py` delegates to CLI main | unit | `pytest tests/test_opengui_p5_cli.py::test_package_main_delegates_to_cli -x` | ❌ Wave 0 |
| EXT-01 | `ADAPTERS.md` names `LLMProvider`, `DeviceBackend`, includes a skeleton adapter, and references `NanobotLLMAdapter` | docs | `pytest tests/test_opengui_p5_cli.py::test_adapters_doc_contains_required_sections -x` | ❌ Wave 0 |
| EXT-01 | code comment or docstring points developers from code to the adapter docs | docs | `pytest tests/test_opengui_p5_cli.py::test_adapter_pointer_exists_in_code -x` | ❌ Wave 0 |

### Manual-Only Verifications

| Behavior | Requirement | Why manual | Test instructions |
|----------|-------------|------------|-------------------|
| `python -m opengui.cli --backend adb --task "Open Settings"` runs a real agent loop | CLI-01 SC1 | Needs an actual Android device / emulator and configured model endpoint | Configure `~/.opengui/config.yaml`, connect ADB device, run the command, verify non-error result and generated trace directory |
| `python -m opengui.cli --backend local --task "Open Chrome"` runs on the local desktop | CLI-01 SC2 | Needs a real desktop session and Accessibility permissions | Configure local backend run, execute the command on macOS/Linux/Windows, verify the agent loop completes and artifacts are written |

### Sampling Rate

- After every task commit: `pytest tests/test_opengui_p5_cli.py -x -q`
- After every plan wave: `pytest tests/ -x -q`
- Before verification: full suite must be green

### Wave 0 Gaps

- [ ] `tests/test_opengui_p5_cli.py` with parsing, config, backend-factory, dry-run integration, JSON output, and docs assertions
- [ ] Runtime YAML dependency added to `pyproject.toml`
- [ ] Clear fake provider / monkeypatch strategy for CLI integration tests

---

## Sources

Local codebase sources inspected:

- `opengui/interfaces.py`
- `opengui/agent.py`
- `opengui/prompts/system.py`
- `opengui/backends/adb.py`
- `opengui/backends/desktop.py`
- `opengui/backends/dry_run.py`
- `opengui/memory/store.py`
- `opengui/memory/retrieval.py`
- `opengui/skills/library.py`
- `opengui/skills/executor.py`
- `opengui/trajectory/recorder.py`
- `opengui/__init__.py`
- `nanobot/agent/gui_adapter.py`
- `nanobot/agent/tools/gui.py`
- `nanobot/providers/custom_provider.py`
- `nanobot/config/loader.py`
- `nanobot/config/schema.py`
- `pyproject.toml`
- `tests/test_opengui.py`
- `tests/test_opengui_p2_memory.py`
- `tests/test_opengui_p3_nanobot.py`
- `tests/test_opengui_p4_desktop.py`

---

## Metadata

- Research mode: local codebase analysis
- External browsing: not required for planning-quality answers in this phase
- Trigger for re-research later: if the Phase 5 context changes the config format, dependency policy, or documentation target
