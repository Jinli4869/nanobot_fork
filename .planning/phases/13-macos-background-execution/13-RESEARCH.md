# Phase 13: macOS Background Execution - Research

**Researched:** 2026-03-20
**Domain:** macOS isolated background execution via virtual display, permission-aware capability probing, and target-surface routing
**Confidence:** MEDIUM

<user_constraints>
## User Constraints

No `13-CONTEXT.md` exists for this phase. This research therefore treats the following as authoritative constraints:
- `.planning/ROADMAP.md` Phase 13 goal and success criteria
- `.planning/REQUIREMENTS.md` requirements `MAC-01`, `MAC-02`, and `MAC-03`
- `.planning/STATE.md` and `.planning/PROJECT.md` decisions already locked by Phases 9-12
- project-level research already captured in `.planning/research/SUMMARY.md`, `.planning/research/STACK.md`, and `.planning/research/PITFALLS.md`

### Locked Decisions Inherited From Prior Phases
- Keep the shared `background_runtime.py` probe/result/resolution contract introduced in Phase 12; Phase 13 extends it rather than bypassing it.
- Keep `BackgroundDesktopBackend` as the background orchestration wrapper unless Phase 13 uncovers a hard blocker that truly requires a worker boundary now.
- Preserve the existing `VirtualDisplayManager` / `DisplayInfo` abstraction from Phase 9.
- Keep Linux background execution behavior unchanged.
- Do not silently degrade from requested background mode without explicit warning or block behavior.

### Claude's Discretion
- Exact file/module name for the macOS display manager.
- Exact macOS reason-code taxonomy, as long as it stays stable and maps to actionable remediation.
- Whether target-surface routing is configured through a small optional hook on `LocalDesktopBackend` or a dedicated macOS subclass, provided Phase 13 keeps the existing wrapper-based architecture.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MAC-01 | User can run desktop automation on macOS in an isolated background target when the OS version and permissions support it | Add a `CGVirtualDisplay`-backed `VirtualDisplayManager`, wire Phase 12 probe/resolution to report `backend_name="cgvirtualdisplay"`, and keep lifecycle ownership in `BackgroundDesktopBackend` |
| MAC-02 | User receives actionable remediation when macOS background execution cannot start because required permissions or platform capabilities are missing | Expand the shared probe/remediation contract with macOS-specific reason codes for OS version, missing PyObjC/runtime classes, Screen Recording, Accessibility, and event-post permission failures |
| MAC-03 | User actions on macOS isolated runs land on the correct target surface across display offsets and scale factors | Add an explicit target-surface configuration seam so `LocalDesktopBackend.observe()` uses the selected monitor and `BackgroundDesktopBackend.execute()` continues to apply absolute offset translation against the same display metadata |
</phase_requirements>

## Summary

Phase 13 should stay inside the architecture established by Phases 9-12. The strongest planning path is not "build a brand-new macOS backend hierarchy"; it is "add a macOS virtual-display implementation plus one explicit target-surface routing seam." The current code already has the right high-level contracts: `VirtualDisplayManager`, `DisplayInfo`, `BackgroundDesktopBackend`, and Phase 12's shared runtime probe/result vocabulary. The gap is that `LocalDesktopBackend` still assumes the primary monitor (`mss.monitors[1]`) and has no way to be told which target surface it is supposed to observe.

The concrete implementation path for planning is:
1. Add a macOS `CGVirtualDisplay` manager under `opengui/backends/displays/`.
2. Extend `background_runtime.py` so macOS capability probing returns stable reason codes and remediation before any background run starts.
3. Add a small target-surface configuration seam from `BackgroundDesktopBackend` into `LocalDesktopBackend` so observation and input target the same macOS display.
4. Wire CLI and nanobot isolated-mode startup to instantiate the macOS manager when the shared runtime probe resolves to an isolated macOS backend.
5. Cover routing and remediation with CI-safe unit/integration tests, and reserve real display creation/permission flows for macOS-only smoke verification.

The most important planning decision is to avoid a shallow "just add `CGVirtualDisplayManager`" plan. That would satisfy MAC-01 only on paper. MAC-03 requires the planner to include the IO-routing seam explicitly, because the wrapper alone cannot change which monitor `mss` captures.

**Primary recommendation:** Keep `BackgroundDesktopBackend` + `VirtualDisplayManager` as the Phase 13 execution model, add `CGVirtualDisplayManager`, and introduce a narrow `configure_target_display(DisplayInfo)`-style hook on the local desktop path so capture and input remain aligned on the macOS target surface.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Existing Python stdlib (`dataclasses`, `logging`, `platform`, `typing`, `pathlib`) | project target `>=3.11` | Lifecycle, capability mapping, stable contracts | Already used across OpenGUI background/runtime code |
| Existing desktop stack (`mss`, `pyautogui`, `pyperclip`, `Pillow`) | project `desktop` extra | Screenshot/input path reused for macOS after target-surface routing is fixed | Preserves the shipped desktop backend rather than replacing it wholesale |
| `pyobjc-core`, `pyobjc-framework-Quartz`, `pyobjc-framework-ApplicationServices` | `12.1` from project research | Bridge into CoreGraphics / Quartz / Accessibility APIs and runtime lookup of `CGVirtualDisplay*` classes | Best fit for a Python-first implementation; avoids introducing a Swift helper in Phase 13 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.x | Unit and integration coverage for routing, probe, and entry-point wiring | Default for all Phase 13 automation coverage |
| `pytest-asyncio` | 1.3.x | Async lifecycle tests for display-manager and wrapper interaction | Needed for background startup/shutdown tests |
| `unittest.mock.AsyncMock` | stdlib | Mock virtual-display and permission probe boundaries in CI | Keeps tests macOS-safe without requiring a real virtual display |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reusing `BackgroundDesktopBackend` with a target-surface hook | A dedicated macOS worker process right now | More isolation, but unnecessary extra architecture for Phase 13 if monitor routing can be injected cleanly |
| PyObjC runtime lookup of `CGVirtualDisplay*` | A custom Swift helper binary | Stronger native control, but larger build/distribution burden and not necessary for the first macOS slice |
| Extending the shared runtime probe | Ad hoc permission checks inside CLI and nanobot | Reintroduces the drift that Phase 12 just removed |

**Installation:**
```bash
uv pip install -e ".[desktop,dev]"
uv pip install "pyobjc-core==12.1; sys_platform == 'darwin'" \
  "pyobjc-framework-Quartz==12.1; sys_platform == 'darwin'" \
  "pyobjc-framework-ApplicationServices==12.1; sys_platform == 'darwin'"
```

**Packaging recommendation:** add the PyObjC packages behind macOS environment markers in `pyproject.toml` instead of making non-macOS developers install them.

## Architecture Patterns

### Recommended Project Structure
```text
opengui/
├── backends/
│   ├── background.py                   # existing wrapper; inject target display info into inner backend
│   ├── background_runtime.py           # extend macOS capability probing + remediation
│   ├── desktop.py                      # add target-display configuration and monitor selection
│   ├── virtual_display.py              # existing DisplayInfo / VirtualDisplayManager contract
│   └── displays/
│       ├── __init__.py
│       ├── xvfb.py
│       └── cgvirtualdisplay.py         # new: macOS isolated display manager
tests/
├── test_opengui_p13_macos_display.py   # new: manager probe/lifecycle/routing contract tests
├── test_opengui_p4_desktop.py          # extend: non-primary monitor observe path
├── test_opengui_p5_cli.py              # extend: macOS resolved-mode and manager selection
└── test_opengui_p11_integration.py     # extend: nanobot resolved-mode and acknowledgement paths
```

### Pattern 1: Keep the Shared Runtime Contract, Expand the Probe Taxonomy
**What:** Keep `probe_isolated_background_support()` as the single pre-run capability entry point, but add explicit macOS reason codes and remediation.
**When to use:** Every background request on macOS before any display manager or agent startup.
**Concrete recommendation:**
- `macos_version_unsupported`
- `macos_pyobjc_missing`
- `macos_virtual_display_api_missing`
- `macos_screen_recording_denied`
- `macos_accessibility_denied`
- `macos_event_post_denied`
- `macos_virtual_display_available`

For supported macOS runs, return:
```python
IsolationProbeResult(
    supported=True,
    reason_code="macos_virtual_display_available",
    retryable=False,
    host_platform="macos",
    backend_name="cgvirtualdisplay",
    sys_platform="darwin",
)
```

This preserves the Phase 12 contract and lets CLI/nanobot stay policy consumers instead of platform decision-makers.

### Pattern 2: Add a Real macOS `VirtualDisplayManager`
**What:** Implement `CGVirtualDisplayManager` returning `DisplayInfo(display_id=..., width=..., height=..., offset_x=..., offset_y=..., monitor_index=...)`.
**When to use:** Isolated background runs on supported macOS hosts.
**Concrete recommendation:**
- File: `opengui/backends/displays/cgvirtualdisplay.py`
- Expose `CGVirtualDisplayManager`
- Add a narrow helper such as `probe_macos_virtual_display_support()` there if `background_runtime.py` needs one shared probe surface
- Keep lifecycle inside `start()` / `stop()` only; do not let CLI/nanobot manage Quartz display objects directly

The display manager should be the only place that knows how to:
- look up `CGVirtualDisplay*` classes
- create and destroy the virtual display
- determine the macOS display's global origin and `mss` monitor index
- return stable `DisplayInfo` metadata to the wrapper

### Pattern 3: Inject Target-Surface Metadata Into the Inner Desktop Backend
**What:** Add a small opt-in hook so the wrapper can tell the desktop backend which monitor to capture.
**When to use:** Immediately after `display_manager.start()` and before `inner.preflight()` in `BackgroundDesktopBackend.preflight()`.
**Concrete recommendation:**
```python
class LocalDesktopBackend:
    def configure_target_display(self, display_info: DisplayInfo | None) -> None:
        self._target_display = display_info
```

Then in `observe()`:
- use `display_info.monitor_index` instead of hard-coded `mss.monitors[1]`
- continue downscaling physical pixels to logical width/height as today
- persist the selected logical width/height so later coordinate resolution matches the observed surface

And in `BackgroundDesktopBackend.preflight()`:
```python
if hasattr(self._inner, "configure_target_display"):
    self._inner.configure_target_display(self._display_info)
```

This is the smallest change that directly addresses MAC-03 without changing the public `DeviceBackend` protocol.

### Pattern 4: Keep Coordinate Translation Single-Source
**What:** Let `BackgroundDesktopBackend._apply_offset()` remain the only absolute-coordinate translation layer.
**When to use:** Every macOS isolated execute path after target display info has been injected.
**Why:** Phase 10 already owns absolute offset translation. Re-implementing offset math inside `LocalDesktopBackend.execute()` would create double-shift bugs. The desktop backend should select the correct monitor and resolve logical coordinates relative to its own observed dimensions; the wrapper should continue handling global origin translation.

### Pattern 5: Entry Points Choose the Manager by Resolved Backend Name
**What:** After `decision.mode == "isolated"`, CLI and nanobot should switch on `probe.backend_name`.
**When to use:** Shared isolated-mode wiring in `opengui/cli.py` and `nanobot/agent/tools/gui.py`.
**Concrete recommendation:**
- Linux `backend_name="xvfb"` -> instantiate `XvfbDisplayManager`
- macOS `backend_name="cgvirtualdisplay"` -> instantiate `CGVirtualDisplayManager`
- anything else -> fail fast with `RuntimeError(f"Unsupported isolated backend: {probe.backend_name}")`

This avoids reintroducing direct `sys.platform` branching into host entry points.

### Anti-Patterns to Avoid
- **Wrapper-only planning:** Adding `CGVirtualDisplayManager` without fixing `LocalDesktopBackend.observe()` monitor selection is insufficient for MAC-03.
- **Duplicated permission logic:** Do not let CLI and nanobot each invent their own macOS permission checks.
- **Double coordinate conversion:** Do not apply offsets in both the wrapper and the desktop backend.
- **Unconditional PyObjC imports:** Keep macOS-only imports inside macOS-gated code paths so Linux CI remains stable.
- **Claiming support for all macOS versions:** Use a conservative supported floor and explicit `macos_version_unsupported` remediation.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| macOS runtime capability messaging | Per-entry-point platform strings | Shared reason-code/remediation mapping in `background_runtime.py` | Keeps CLI and nanobot aligned |
| Target display routing | Ad hoc global variables or wrapper-side `mss` hacks | A small `configure_target_display(DisplayInfo)` seam in `LocalDesktopBackend` | Keeps the routing responsibility where screen capture already lives |
| macOS dependency packaging | Always-on PyObjC deps for all platforms | macOS environment markers in `pyproject.toml` | Avoids unnecessary install failures off macOS |
| End-to-end proof | Generic CI test pretending to create a real macOS virtual display | Mocked contract tests plus one platform-gated smoke checklist | The API is host-specific and should not be faked as generally available in CI |

## Common Pitfalls

### Pitfall 1: `observe()` still captures the primary monitor
If the plan never changes `mss.monitors[1]`, screenshots will keep coming from the user's main display even while the virtual display exists. This would make Phase 13 look partially complete while violating MAC-03.

### Pitfall 2: permission checks happen too late
If the code waits for `pyautogui.position()` or first screenshot failure, the user sees opaque runtime errors rather than the actionable remediation required by MAC-02.

### Pitfall 3: offset translation is duplicated
Phase 10 already shifts absolute coordinates in `BackgroundDesktopBackend`. Adding a second offset shift in `LocalDesktopBackend.execute()` would push every absolute macOS action to the wrong place.

### Pitfall 4: `backend_name` is ignored after probe resolution
If CLI/nanobot decide the manager from raw `sys.platform` again, Phase 12's shared runtime contract becomes advisory only, and later platform expansion gets harder.

### Pitfall 5: Phase 13 claims full unattended macOS reliability
The research base for `CGVirtualDisplay` is still weaker than the public Linux/Xvfb path. The plan should include smoke/manual verification and compatibility notes instead of presenting the feature as risk-free.

## Code Examples

### Example 1: macOS probe consumption stays in the shared runtime contract
```python
probe = probe_isolated_background_support(sys_platform="darwin")
decision = resolve_run_mode(
    probe,
    require_isolation=require_isolation,
    require_acknowledgement_for_fallback=is_nanobot,
)
```

### Example 2: wrapper injects display info into the inner backend
```python
self._display_info = await self._display_manager.start()
if hasattr(self._inner, "configure_target_display"):
    self._inner.configure_target_display(self._display_info)
await self._inner.preflight()
```

### Example 3: desktop observe path selects the configured monitor
```python
monitor_index = self._target_display.monitor_index if self._target_display else 1
monitor = sct.monitors[monitor_index]
```

## Open Questions

1. **Support floor: macOS 13+ or 14+?**
   - What we know: global project research treats macOS 14+ as the conservative support floor even though some evidence points to earlier availability.
   - Recommendation: plan Phase 13 around an explicit support floor of macOS 14+ unless a real supported-host test demonstrates macOS 13 stability.

2. **Is `monitor_index` alone enough?**
   - What we know: Phase 9 intentionally carried `monitor_index` for future macOS support, and current routing needs mostly point to monitor selection plus existing offset handling.
   - Recommendation: start with `monitor_index` + `offset_x`/`offset_y`; only add new `DisplayInfo` fields if an actual routing test proves those fields insufficient.

3. **Should the target-surface hook be generic or desktop-only?**
   - What we know: only `LocalDesktopBackend` currently needs it.
   - Recommendation: keep it as a narrow opt-in method on the local desktop backend, detected via `hasattr`, rather than widening the `DeviceBackend` protocol in Phase 13.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio 1.3.x |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` |
| Quick run command | `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py -q` |
| Full suite command | `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MAC-01 | macOS probe returns `supported=True`, `backend_name="cgvirtualdisplay"`, and `reason_code="macos_virtual_display_available"` when OS/runtime/permissions are satisfied | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_probe_macos_virtual_display_available -q` | ❌ Wave 0 |
| MAC-01 | `CGVirtualDisplayManager.start()` returns `DisplayInfo` with non-default `monitor_index`/offset metadata and `stop()` tears down cleanly | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_cgvirtualdisplay_manager_returns_display_info -q` | ❌ Wave 0 |
| MAC-02 | unsupported macOS version resolves to blocked/fallback with `macos_version_unsupported` remediation | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_probe_reports_macos_version_unsupported -q` | ❌ Wave 0 |
| MAC-02 | denied Screen Recording / Accessibility / event-post permissions map to stable reason codes and actionable remediation | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_probe_reports_actionable_permission_remediation -q` | ❌ Wave 0 |
| MAC-03 | `LocalDesktopBackend.observe()` uses configured `monitor_index` instead of hard-coded primary monitor | unit | `uv run pytest tests/test_opengui_p4_desktop.py::test_observe_uses_configured_monitor_index -q` | ❌ Wave 0 |
| MAC-03 | wrapper injects `DisplayInfo` into the inner desktop backend before `inner.preflight()` | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_background_wrapper_configures_target_display_before_preflight -q` | ❌ Wave 0 |
| MAC-03 | absolute actions use existing wrapper offset translation while monitor selection stays aligned with the same target display | unit | `uv run pytest tests/test_opengui_p13_macos_display.py::test_macos_target_surface_routing_keeps_observe_and_execute_aligned -q` | ❌ Wave 0 |
| MAC-01, MAC-02 | CLI isolated path picks `CGVirtualDisplayManager` from the resolved backend name and logs mode before agent start | integration | `uv run pytest tests/test_opengui_p5_cli.py::test_run_cli_uses_cgvirtualdisplay_manager_for_macos_isolated_mode -q` | ❌ Wave 0 |
| MAC-01, MAC-02 | nanobot path uses the same shared macOS runtime decision contract | integration | `uv run pytest tests/test_opengui_p11_integration.py::test_gui_tool_uses_cgvirtualdisplay_manager_for_macos_isolated_mode -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py -q`
- **Per wave merge:** `uv run pytest tests/test_opengui_p13_macos_display.py tests/test_opengui_p4_desktop.py tests/test_opengui_p5_cli.py tests/test_opengui_p11_integration.py tests/test_opengui_p12_runtime_contracts.py -q`
- **Phase gate:** the full Phase 13 suite above must be green before verification

### Wave 0 Gaps
- [ ] `tests/test_opengui_p13_macos_display.py` — new contract and lifecycle coverage for manager, probe taxonomy, and wrapper routing
- [ ] `tests/test_opengui_p4_desktop.py` additions — monitor-index selection coverage for observe path
- [ ] `tests/test_opengui_p5_cli.py` additions — macOS isolated manager selection and mode logging order
- [ ] `tests/test_opengui_p11_integration.py` additions — nanobot macOS isolated manager selection and remediation behavior

## Sources

### Primary (HIGH confidence)
- `opengui/backends/background_runtime.py` — current shared probe/result/resolution contract
- `opengui/backends/background.py` — current wrapper lifecycle and offset-translation seam
- `opengui/backends/desktop.py` — current monitor-selection limitation and screenshot/input behavior
- `opengui/backends/virtual_display.py` — `DisplayInfo` and `VirtualDisplayManager` contract
- `.planning/ROADMAP.md` — Phase 13 goal, requirements, and success criteria
- `.planning/REQUIREMENTS.md` — `MAC-01`, `MAC-02`, `MAC-03`
- `.planning/STATE.md` and `.planning/PROJECT.md` — inherited v1.2 decisions and current milestone context
- `pyproject.toml` — existing desktop/dev dependencies and pytest config

### Secondary (MEDIUM confidence)
- `.planning/research/SUMMARY.md` — roadmap-level recommendation to keep the wrapper model but fix target-surface routing
- `.planning/research/STACK.md` — PyObjC recommendation, packaging guidance, and explicit note that `LocalDesktopBackend.observe()` must stop hard-coding monitor 1
- `.planning/research/PITFALLS.md` — detailed failure modes around macOS permissions, topology fragility, and wrong-surface routing
- `tests/test_opengui_p4_desktop.py`, `tests/test_opengui_p10_background.py`, `tests/test_opengui_p12_runtime_contracts.py` — current test style and reusable patterns

### Tertiary (LOW confidence)
- Reverse-engineered / ecosystem knowledge around `CGVirtualDisplay` viability as already summarized in the project research; useful for planning defensively, but not strong enough to over-promise platform certainty.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM — recommended deps are clear, but the macOS virtual-display path is still version-sensitive
- Architecture: HIGH — current contracts line up cleanly with the recommended plan
- Pitfalls: HIGH — rooted directly in current code and already-documented project research
- Verification strategy: MEDIUM — CI-safe unit coverage is clear; live macOS validation still needs platform access

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (revalidate on macOS support-floor or dependency changes)
