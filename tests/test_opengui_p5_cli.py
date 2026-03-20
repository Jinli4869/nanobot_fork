"""Phase 5 CLI regression tests.

Task 1 seeds the CLI contract as xfailed tests. Task 2 removes the xfail mark
and promotes this file to passing coverage.
"""

from __future__ import annotations

import asyncio
import json
import runpy
import sys
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest


def _write_config(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return path


class _FakeBackend:
    def __init__(self, platform: str = "dry-run") -> None:
        self._platform = platform
        self.preflight_calls = 0

    @property
    def platform(self) -> str:
        return self._platform

    async def preflight(self) -> None:
        self.preflight_calls += 1


def test_cli_parses_task_and_backend_flags() -> None:
    import opengui.cli as cli

    positional = cli.parse_args(["Open Settings"])
    assert cli.resolve_task(positional) == "Open Settings"
    assert cli.resolve_backend_name(positional) == "local"

    flagged = cli.parse_args(["--task", "Open Settings", "--backend", "adb"])
    assert cli.resolve_task(flagged) == "Open Settings"
    assert cli.resolve_backend_name(flagged) == "adb"

    dry_run = cli.parse_args(["--task", "Open Settings", "--backend", "adb", "--dry-run"])
    assert cli.resolve_backend_name(dry_run) == "dry-run"

    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_load_config_env_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import opengui.cli as cli

    default_config = _write_config(
        tmp_path / ".opengui" / "config.yaml",
        """
        provider:
          base_url: http://localhost:1234/v1
          model: qwen-gui
        """,
    )
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", default_config)
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    cfg = cli.load_config()
    assert cfg.provider.base_url == "http://localhost:1234/v1"
    assert cfg.provider.model == "qwen-gui"
    assert cfg.provider.api_key == "env-key"

    custom_config = _write_config(
        tmp_path / "custom.yaml",
        """
        provider:
          base_url: http://localhost:9999/v1
          model: qwen-custom
          api_key: inline-key
        adb:
          serial: emulator-5554
          adb_path: /tmp/adb
        """,
    )
    override = cli.load_config(custom_config)
    assert override.provider.base_url == "http://localhost:9999/v1"
    assert override.provider.model == "qwen-custom"
    assert override.provider.api_key == "inline-key"
    assert override.adb.serial == "emulator-5554"
    assert override.adb.adb_path == "/tmp/adb"


def test_build_backend_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    import opengui.cli as cli

    calls: dict[str, list[dict[str, Any]]] = {"adb": [], "local": [], "dry-run": []}

    class FakeAdbBackend:
        def __init__(self, serial: str | None = None, adb_path: str = "adb") -> None:
            calls["adb"].append({"serial": serial, "adb_path": adb_path})

    class FakeLocalDesktopBackend:
        def __init__(self) -> None:
            calls["local"].append({})

    class FakeDryRunBackend:
        def __init__(self) -> None:
            calls["dry-run"].append({})

    monkeypatch.setattr(cli, "AdbBackend", FakeAdbBackend)
    monkeypatch.setattr(cli, "LocalDesktopBackend", FakeLocalDesktopBackend)
    monkeypatch.setattr(cli, "DryRunBackend", FakeDryRunBackend)

    config = cli.CliConfig(
        provider=cli.ProviderConfig(
            base_url="http://localhost:1234/v1",
            model="qwen-gui",
            api_key="test-key",
        ),
        adb=cli.AdbConfig(serial="emulator-5554", adb_path="/tmp/adb"),
    )

    assert isinstance(cli.build_backend("adb", config), FakeAdbBackend)
    assert isinstance(cli.build_backend("local", config), FakeLocalDesktopBackend)
    assert isinstance(cli.build_backend("dry-run", config), FakeDryRunBackend)
    assert calls["adb"] == [{"serial": "emulator-5554", "adb_path": "/tmp/adb"}]


def test_cli_runs_dry_run_agent_loop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from opengui.agent import AgentResult
    import opengui.cli as cli

    config = cli.CliConfig(
        provider=cli.ProviderConfig(
            base_url="http://localhost:1234/v1",
            model="qwen-gui",
            api_key="test-key",
        )
    )
    backend = _FakeBackend()
    recorder_state: dict[str, Any] = {}
    agent_state: dict[str, Any] = {}

    class FakeProvider:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    class FakeRecorder:
        def __init__(self, output_dir: Path, task: str, platform: str = "unknown") -> None:
            self.output_dir = output_dir
            self.task = task
            self.platform = platform
            recorder_state["output_dir"] = output_dir
            recorder_state["task"] = task
            recorder_state["platform"] = platform

    class FakeGuiAgent:
        def __init__(self, **kwargs: Any) -> None:
            agent_state.update(kwargs)
            self._progress_callback = kwargs["progress_callback"]

        async def run(self, task: str, **_: Any) -> AgentResult:
            await self._progress_callback("GUI step 1/15: inspect screen")
            return AgentResult(
                success=True,
                summary=f"Completed {task}",
                model_summary="Opened app and confirmed final state.",
                trace_path="trace.jsonl",
                steps_taken=2,
                error=None,
            )

    async def fake_build_optional_components(*_: Any, **__: Any) -> tuple[Any, Any, Any]:
        return None, None, None

    monkeypatch.setattr(cli, "load_config", lambda path=None: config)
    monkeypatch.setattr(cli, "OpenAICompatibleLLMProvider", FakeProvider)
    monkeypatch.setattr(cli, "build_backend", lambda backend_name, cfg: backend)
    monkeypatch.setattr(cli, "TrajectoryRecorder", FakeRecorder)
    monkeypatch.setattr(cli, "GuiAgent", FakeGuiAgent)
    monkeypatch.setattr(cli, "build_optional_components", fake_build_optional_components)

    exit_code = cli.main(["--dry-run", "--task", "Open Settings"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "GUI step 1/15: inspect screen" in captured.out
    assert "status: success" in captured.out
    assert "success: true" in captured.out
    assert "summary: Completed Open Settings" in captured.out
    assert "model_summary: Opened app and confirmed final state." in captured.out
    assert "trace_path: trace.jsonl" in captured.out
    assert "steps_taken: 2" in captured.out
    assert recorder_state["task"] == "Open Settings"
    assert recorder_state["platform"] == "dry-run"
    assert recorder_state["output_dir"].parent == cli.DEFAULT_RUNS_DIR
    assert agent_state["backend"] is backend
    assert agent_state["model"] == "qwen-gui"
    assert agent_state["artifacts_root"] == recorder_state["output_dir"]


def test_cli_json_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from opengui.agent import AgentResult
    import opengui.cli as cli

    config = cli.CliConfig(
        provider=cli.ProviderConfig(
            base_url="http://localhost:1234/v1",
            model="qwen-gui",
            api_key="test-key",
        )
    )
    backend = _FakeBackend()

    class FakeProvider:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    class FakeRecorder:
        def __init__(self, output_dir: Path, task: str, platform: str = "unknown") -> None:
            self.output_dir = output_dir
            self.task = task
            self.platform = platform

    class FakeGuiAgent:
        def __init__(self, **kwargs: Any) -> None:
            self._progress_callback = kwargs["progress_callback"]

        async def run(self, task: str, **_: Any) -> AgentResult:
            await self._progress_callback("GUI step 1/15: inspect screen")
            return AgentResult(
                success=True,
                summary=f"Completed {task}",
                model_summary="Opened app and confirmed final state.",
                trace_path="trace.jsonl",
                steps_taken=3,
                error=None,
            )

    async def fake_build_optional_components(*_: Any, **__: Any) -> tuple[Any, Any, Any]:
        return None, None, None

    monkeypatch.setattr(cli, "load_config", lambda path=None: config)
    monkeypatch.setattr(cli, "OpenAICompatibleLLMProvider", FakeProvider)
    monkeypatch.setattr(cli, "build_backend", lambda backend_name, cfg: backend)
    monkeypatch.setattr(cli, "TrajectoryRecorder", FakeRecorder)
    monkeypatch.setattr(cli, "GuiAgent", FakeGuiAgent)
    monkeypatch.setattr(cli, "build_optional_components", fake_build_optional_components)

    exit_code = cli.main(["--json", "--dry-run", "--task", "Open Settings"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload == {
        "success": True,
        "summary": "Completed Open Settings",
        "model_summary": "Opened app and confirmed final state.",
        "trace_path": "trace.jsonl",
        "steps_taken": 3,
        "error": None,
    }
    assert "GUI step 1/15: inspect screen" not in captured.out


def test_cli_main_catches_runtime_exception_and_prints_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import opengui.cli as cli

    monkeypatch.setattr(cli, "run_cli", lambda args: (_ for _ in ()).throw(RuntimeError("boom")))

    exit_code = cli.main(["--dry-run", "--task", "Open Settings"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "status: failure" in captured.out
    assert "success: false" in captured.out
    assert "summary: CLI execution failed." in captured.out
    assert "error: RuntimeError: boom" in captured.out


def test_package_main_delegates_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    fake_cli = types.ModuleType("opengui.cli")

    def fake_main() -> int:
        called.append("main")
        return 0

    fake_cli.main = fake_main
    monkeypatch.setitem(sys.modules, "opengui.cli", fake_cli)
    sys.modules.pop("opengui.__main__", None)

    runpy.run_module("opengui.__main__", run_name="__main__")

    assert called == ["main"]


def test_cli_enables_memory_and_skill_bundle_when_embedding_config_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opengui.cli as cli

    calls: dict[str, list[Any]] = {
        "embedding": [],
        "memory_store": [],
        "retriever": [],
        "indexed_entries": [],
        "skill_library": [],
        "validator": [],
        "skill_executor": [],
    }

    class FakeEmbeddingProvider:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls["embedding"].append(kwargs)

    class FakeMemoryStore:
        def __init__(self, store_dir: Path) -> None:
            calls["memory_store"].append(store_dir)

        def list_all(self, **_: Any) -> list[str]:
            return ["entry-1", "entry-2"]

    class FakeMemoryRetriever:
        def __init__(self, embedding_provider: Any, top_k: int = 5) -> None:
            self.embedding_provider = embedding_provider
            self.top_k = top_k
            calls["retriever"].append({"embedding_provider": embedding_provider, "top_k": top_k})

        async def index(self, entries: list[str]) -> None:
            calls["indexed_entries"].append(entries)

    class FakeSkillLibrary:
        def __init__(self, store_dir: Path, embedding_provider: Any = None, merge_llm: Any = None) -> None:
            calls["skill_library"].append(
                {
                    "store_dir": store_dir,
                    "embedding_provider": embedding_provider,
                    "merge_llm": merge_llm,
                }
            )

    class FakeValidator:
        def __init__(self, provider: Any) -> None:
            calls["validator"].append(provider)

    class FakeSkillExecutor:
        def __init__(self, backend: Any, state_validator: Any = None) -> None:
            calls["skill_executor"].append({"backend": backend, "state_validator": state_validator})

    monkeypatch.setattr(cli, "OpenAICompatibleEmbeddingProvider", FakeEmbeddingProvider)
    monkeypatch.setattr(cli, "MemoryStore", FakeMemoryStore)
    monkeypatch.setattr(cli, "MemoryRetriever", FakeMemoryRetriever)
    monkeypatch.setattr(cli, "SkillLibrary", FakeSkillLibrary)
    monkeypatch.setattr(cli, "LLMStateValidator", FakeValidator)
    monkeypatch.setattr(cli, "SkillExecutor", FakeSkillExecutor)

    provider = object()
    backend = _FakeBackend(platform="macos")
    with_embedding = cli.CliConfig(
        provider=cli.ProviderConfig(
            base_url="http://localhost:1234/v1",
            model="qwen-gui",
            api_key="test-key",
        ),
        embedding=cli.EmbeddingConfig(
            base_url="http://localhost:5678/v1",
            model="embed-model",
            api_key="embed-key",
        ),
    )

    memory_retriever, skill_library, skill_executor = asyncio.run(
        cli.build_optional_components(with_embedding, provider=provider, backend=backend)
    )

    assert memory_retriever is not None
    assert skill_library is not None
    assert skill_executor is not None
    assert calls["memory_store"] == [cli.DEFAULT_MEMORY_DIR]
    assert calls["indexed_entries"] == [["entry-1", "entry-2"]]
    assert calls["retriever"][0]["top_k"] == 5
    assert calls["skill_library"][0]["store_dir"] == cli.DEFAULT_SKILLS_DIR
    assert calls["skill_library"][0]["merge_llm"] is provider
    assert calls["validator"] == [provider]
    assert calls["skill_executor"][0]["backend"] is backend

    before = {key: len(value) for key, value in calls.items()}
    no_embedding = cli.CliConfig(
        provider=cli.ProviderConfig(
            base_url="http://localhost:1234/v1",
            model="qwen-gui",
            api_key="test-key",
        )
    )

    disabled = asyncio.run(cli.build_optional_components(no_embedding, provider=provider, backend=backend))

    assert disabled == (None, None, None)
    assert {key: len(value) for key, value in calls.items()} == before


# ---------------------------------------------------------------------------
# Phase 11 Plan 01 — --background CLI flag tests
# ---------------------------------------------------------------------------


def test_cli_parses_background_flags() -> None:
    """parse_args accepts --background and optional display geometry flags."""
    import opengui.cli as cli

    # Basic --background flag
    args = cli.parse_args(["--background", "--task", "t"])
    assert args.background is True
    assert args.display_num is None
    assert args.width is None
    assert args.height is None

    # With all display geometry flags
    args2 = cli.parse_args(
        ["--background", "--display-num", "42", "--width", "1920", "--height", "1080", "--task", "t"]
    )
    assert args2.background is True
    assert args2.display_num == 42
    assert args2.width == 1920
    assert args2.height == 1080


def test_cli_background_rejects_adb() -> None:
    """--background combined with --backend adb exits with an error."""
    import opengui.cli as cli

    with pytest.raises(SystemExit):
        cli.parse_args(["--background", "--backend", "adb", "--task", "t"])


def test_cli_background_rejects_dry_run() -> None:
    """--background combined with --dry-run exits with an error."""
    import opengui.cli as cli

    with pytest.raises(SystemExit):
        cli.parse_args(["--background", "--dry-run", "--task", "t"])


def test_cli_background_implies_local() -> None:
    """--background without --backend should resolve to 'local'."""
    import opengui.cli as cli

    args = cli.parse_args(["--background", "--task", "t"])
    assert cli.resolve_backend_name(args) == "local"


def test_run_cli_background_wraps_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux, run_cli wraps the inner backend in BackgroundDesktopBackend."""
    from opengui.agent import AgentResult
    import opengui.cli as cli

    config = cli.CliConfig(
        provider=cli.ProviderConfig(
            base_url="http://localhost:1234/v1",
            model="qwen-gui",
            api_key="test-key",
        )
    )
    inner_backend = _FakeBackend(platform="linux")
    wrapped_backend_ref: list[Any] = []
    agent_backend_ref: list[Any] = []

    class FakeXvfbDisplayManager:
        def __init__(self, display_num: int = 99, width: int = 1280, height: int = 720) -> None:
            self.display_num = display_num
            self.width = width
            self.height = height

        async def start(self) -> Any:
            from opengui.backends.virtual_display import DisplayInfo
            return DisplayInfo(display_id=":99", width=self.width, height=self.height)

        async def stop(self) -> None:
            pass

    class FakeBackgroundBackend:
        def __init__(self, inner: Any, manager: Any) -> None:
            self._inner = inner
            self._manager = manager
            wrapped_backend_ref.append(self)

        async def __aenter__(self) -> "FakeBackgroundBackend":
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        @property
        def platform(self) -> str:
            return self._inner.platform

    class FakeProvider:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class FakeRecorder:
        def __init__(self, output_dir: Path, task: str, platform: str = "unknown") -> None:
            self.output_dir = output_dir
            self.task = task
            self.platform = platform

    class FakeGuiAgent:
        def __init__(self, **kwargs: Any) -> None:
            agent_backend_ref.append(kwargs["backend"])

        async def run(self, task: str, **_: Any) -> AgentResult:
            return AgentResult(
                success=True,
                summary="done",
                model_summary=None,
                trace_path=None,
                steps_taken=1,
                error=None,
            )

    async def fake_build_optional_components(*_: Any, **__: Any) -> tuple[Any, Any, Any]:
        return None, None, None

    monkeypatch.setattr(cli, "load_config", lambda path=None: config)
    monkeypatch.setattr(cli, "OpenAICompatibleLLMProvider", FakeProvider)
    monkeypatch.setattr(cli, "build_backend", lambda name, cfg: inner_backend)
    monkeypatch.setattr(cli, "TrajectoryRecorder", FakeRecorder)
    monkeypatch.setattr(cli, "GuiAgent", FakeGuiAgent)
    monkeypatch.setattr(cli, "build_optional_components", fake_build_optional_components)
    monkeypatch.setattr(cli, "BackgroundDesktopBackend", FakeBackgroundBackend)
    monkeypatch.setattr(sys, "platform", "linux")

    import opengui.backends.displays.xvfb as xvfb_mod
    monkeypatch.setattr(xvfb_mod, "XvfbDisplayManager", FakeXvfbDisplayManager)

    # Also patch the xvfb import inside run_cli's local scope by patching the module reference
    import importlib
    import opengui.backends.displays.xvfb as _xvfb
    monkeypatch.setattr(_xvfb, "XvfbDisplayManager", FakeXvfbDisplayManager)

    args = cli.parse_args(["--background", "--task", "open settings"])
    asyncio.run(cli.run_cli(args))

    # FakeBackgroundBackend was constructed and the agent received the wrapped backend
    assert len(wrapped_backend_ref) == 1
    assert wrapped_backend_ref[0]._inner is inner_backend
    assert len(agent_backend_ref) == 1
    assert agent_backend_ref[0] is wrapped_backend_ref[0]


def test_run_cli_background_nonlinux_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On non-Linux platforms, --background logs a warning and uses raw backend."""
    import logging
    from opengui.agent import AgentResult
    import opengui.cli as cli

    config = cli.CliConfig(
        provider=cli.ProviderConfig(
            base_url="http://localhost:1234/v1",
            model="qwen-gui",
            api_key="test-key",
        )
    )
    inner_backend = _FakeBackend(platform="macos")
    agent_backend_ref: list[Any] = []
    bg_created: list[Any] = []

    class FakeBackgroundBackend:
        def __init__(self, inner: Any, manager: Any) -> None:
            bg_created.append(self)

        async def __aenter__(self) -> "FakeBackgroundBackend":
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        @property
        def platform(self) -> str:
            return "linux"

    class FakeProvider:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class FakeRecorder:
        def __init__(self, output_dir: Path, task: str, platform: str = "unknown") -> None:
            self.output_dir = output_dir
            self.task = task
            self.platform = platform

    class FakeGuiAgent:
        def __init__(self, **kwargs: Any) -> None:
            agent_backend_ref.append(kwargs["backend"])

        async def run(self, task: str, **_: Any) -> AgentResult:
            return AgentResult(
                success=True,
                summary="done",
                model_summary=None,
                trace_path=None,
                steps_taken=1,
                error=None,
            )

    async def fake_build_optional_components(*_: Any, **__: Any) -> tuple[Any, Any, Any]:
        return None, None, None

    monkeypatch.setattr(cli, "load_config", lambda path=None: config)
    monkeypatch.setattr(cli, "OpenAICompatibleLLMProvider", FakeProvider)
    monkeypatch.setattr(cli, "build_backend", lambda name, cfg: inner_backend)
    monkeypatch.setattr(cli, "TrajectoryRecorder", FakeRecorder)
    monkeypatch.setattr(cli, "GuiAgent", FakeGuiAgent)
    monkeypatch.setattr(cli, "build_optional_components", fake_build_optional_components)
    monkeypatch.setattr(cli, "BackgroundDesktopBackend", FakeBackgroundBackend)
    # Leave sys.platform as "darwin" (do not patch)

    args = cli.parse_args(["--background", "--task", "open settings"])
    with caplog.at_level(logging.WARNING, logger="opengui.cli"):
        asyncio.run(cli.run_cli(args))

    # BackgroundDesktopBackend was NOT constructed
    assert len(bg_created) == 0
    # Agent received raw backend
    assert len(agent_backend_ref) == 1
    assert agent_backend_ref[0] is inner_backend
    # Warning was logged mentioning Linux-only
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Linux-only" in msg for msg in warning_messages), (
        f"Expected 'Linux-only' in warning logs, got: {warning_messages}"
    )


def test_run_cli_background_uses_cli_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """XvfbDisplayManager is constructed with --display-num, --width, --height values."""
    from opengui.agent import AgentResult
    import opengui.cli as cli

    config = cli.CliConfig(
        provider=cli.ProviderConfig(
            base_url="http://localhost:1234/v1",
            model="qwen-gui",
            api_key="test-key",
        )
    )
    inner_backend = _FakeBackend(platform="linux")
    xvfb_init_kwargs: list[dict[str, Any]] = []

    class FakeXvfbDisplayManager:
        def __init__(self, display_num: int = 99, width: int = 1280, height: int = 720) -> None:
            xvfb_init_kwargs.append({"display_num": display_num, "width": width, "height": height})

        async def start(self) -> Any:
            from opengui.backends.virtual_display import DisplayInfo
            return DisplayInfo(display_id=":42", width=1920, height=1080)

        async def stop(self) -> None:
            pass

    class FakeBackgroundBackend:
        def __init__(self, inner: Any, manager: Any) -> None:
            self._inner = inner
            self._manager = manager

        async def __aenter__(self) -> "FakeBackgroundBackend":
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        @property
        def platform(self) -> str:
            return self._inner.platform

    class FakeProvider:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class FakeRecorder:
        def __init__(self, output_dir: Path, task: str, platform: str = "unknown") -> None:
            self.output_dir = output_dir

    class FakeGuiAgent:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, task: str, **_: Any) -> AgentResult:
            return AgentResult(
                success=True,
                summary="done",
                model_summary=None,
                trace_path=None,
                steps_taken=1,
                error=None,
            )

    async def fake_build_optional_components(*_: Any, **__: Any) -> tuple[Any, Any, Any]:
        return None, None, None

    monkeypatch.setattr(cli, "load_config", lambda path=None: config)
    monkeypatch.setattr(cli, "OpenAICompatibleLLMProvider", FakeProvider)
    monkeypatch.setattr(cli, "build_backend", lambda name, cfg: inner_backend)
    monkeypatch.setattr(cli, "TrajectoryRecorder", FakeRecorder)
    monkeypatch.setattr(cli, "GuiAgent", FakeGuiAgent)
    monkeypatch.setattr(cli, "build_optional_components", fake_build_optional_components)
    monkeypatch.setattr(cli, "BackgroundDesktopBackend", FakeBackgroundBackend)
    monkeypatch.setattr(sys, "platform", "linux")

    import opengui.backends.displays.xvfb as _xvfb
    monkeypatch.setattr(_xvfb, "XvfbDisplayManager", FakeXvfbDisplayManager)

    args = cli.parse_args(
        ["--background", "--display-num", "42", "--width", "1920", "--height", "1080", "--task", "t"]
    )
    asyncio.run(cli.run_cli(args))

    assert len(xvfb_init_kwargs) == 1
    assert xvfb_init_kwargs[0] == {"display_num": 42, "width": 1920, "height": 1080}
