"""GuiSubagentTool: exposes opengui's GuiAgent as a nanobot tool."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import litellm
import numpy as np

from nanobot.agent.gui_adapter import NanobotEmbeddingAdapter, NanobotLLMAdapter
from nanobot.agent.tools.base import Tool
from opengui.interfaces import InterventionHandler, InterventionRequest, InterventionResolution
from opengui.skills.normalization import get_gui_skill_store_root

if TYPE_CHECKING:
    from nanobot.config.schema import GuiConfig
    from nanobot.providers.base import LLMProvider


logger = logging.getLogger(__name__)
DEFAULT_OPENGUI_MEMORY_DIR = Path.home() / ".opengui" / "memory"
_SAFE_INTERVENTION_TARGET_KEYS = frozenset(
    {"display_id", "monitor_index", "desktop_name", "width", "height", "platform"}
)
WindowsIsolatedBackend = None
probe_isolated_background_support = None
resolve_run_mode = None
log_mode_resolution = None
WINDOWS_TARGET_APP_CLASSES = ("classic-win32", "uwp", "directx", "gpu-heavy", "electron-gpu")


class GuiSubagentTool(Tool):
    """Run a GUI automation task through opengui."""

    def __init__(
        self,
        *,
        gui_config: "GuiConfig | None",
        provider: "LLMProvider",
        model: str,
        workspace: Path,
    ) -> None:
        if gui_config is None:
            raise ValueError("GuiSubagentTool requires gui_config")

        self._gui_config = gui_config
        self._provider = provider
        self._model = model
        self._workspace = Path(workspace)
        self._llm_adapter = NanobotLLMAdapter(provider, model)
        self._embedding_adapter = self._build_embedding_adapter() if gui_config.embedding_model else None
        self._skill_libraries: dict[str, Any] = {}
        self._background_postprocess_tasks: set[asyncio.Task[None]] = set()

        self._backend = self._build_backend(gui_config.backend)
        self._skill_library = self._get_skill_library(self._backend.platform)

    @property
    def name(self) -> str:
        return "gui_task"

    @property
    def description(self) -> str:
        return (
            "Execute a GUI automation task on a device. The task is performed by "
            "a vision-action agent that observes screenshots and executes actions. "
            "Returns a structured result with success status, summary, and trace path."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The GUI task to perform.",
                },
                "backend": {
                    "type": "string",
                    "enum": ["adb", "local", "dry-run"],
                    "description": "Optional backend override. Defaults to the configured GUI backend.",
                },
                "require_background_isolation": {
                    "type": "boolean",
                    "description": "Block instead of falling back when isolated background execution is unavailable.",
                },
                "acknowledge_background_fallback": {
                    "type": "boolean",
                    "description": "Explicitly acknowledge foreground fallback when isolated background execution is unavailable.",
                },
                "target_app_class": {
                    "type": "string",
                    "enum": list(WINDOWS_TARGET_APP_CLASSES),
                    "description": "Optional Windows app class hint for isolated background probing.",
                },
            },
            "required": ["task"],
        }

    async def execute(
        self,
        task: str,
        backend: str | None = None,
        require_background_isolation: bool = False,
        acknowledge_background_fallback: bool = False,
        target_app_class: str | None = None,
        **kwargs: Any,
    ) -> str:
        active_backend = self._select_backend(backend)

        if self._gui_config.background:
            probe_fn = probe_isolated_background_support
            resolve_fn = resolve_run_mode
            log_fn = log_mode_resolution
            if probe_fn is None:
                from opengui.backends.background_runtime import (
                    probe_isolated_background_support as runtime_probe_isolated_background_support,
                )

                probe_fn = runtime_probe_isolated_background_support
            if resolve_fn is None:
                from opengui.backends.background_runtime import resolve_run_mode as runtime_resolve_run_mode

                resolve_fn = runtime_resolve_run_mode
            if log_fn is None:
                from opengui.backends.background_runtime import (
                    log_mode_resolution as runtime_log_mode_resolution,
                )

                log_fn = runtime_log_mode_resolution

            resolved_target_app_class = self._resolve_probe_target_app_class(
                backend,
                target_app_class,
                sys_platform=sys.platform,
            )
            probe = probe_fn(
                sys_platform=sys.platform,
                target_app_class=resolved_target_app_class,
            )
            decision = resolve_fn(
                probe,
                require_isolation=require_background_isolation,
                require_acknowledgement_for_fallback=True,
            )
            log_fn(logger, decision, owner="nanobot", task=task)

            if decision.mode == "blocked":
                return self._background_json_failure(decision.message)

            if decision.mode == "fallback" and not acknowledge_background_fallback:
                return self._background_json_failure(
                    f"{decision.message} Re-run with acknowledge_background_fallback=true to continue in foreground."
                )

            if decision.mode == "isolated":
                try:
                    mgr = self._build_isolated_display_manager(probe)
                except RuntimeError as exc:
                    return self._background_json_failure(str(exc))
                if probe.backend_name == "windows_isolated_desktop":
                    wrapped_backend = None
                    try:
                        isolated_backend_cls = WindowsIsolatedBackend
                        if isolated_backend_cls is None:
                            from opengui.backends.windows_isolated import (
                                WindowsIsolatedBackend as isolated_backend_cls,  # type: ignore[assignment]
                            )
                        wrapped_backend = isolated_backend_cls(
                            active_backend,
                            mgr,
                            run_metadata={"owner": "nanobot", "task": task, "model": self._model},
                        )
                        return await self._run_task(wrapped_backend, task, **kwargs)
                    except RuntimeError as exc:
                        return self._background_json_failure(str(exc))
                    finally:
                        if wrapped_backend is not None:
                            await wrapped_backend.shutdown()
                else:
                    from opengui.backends.background import BackgroundDesktopBackend

                    wrapped_backend = BackgroundDesktopBackend(
                        active_backend,
                        mgr,
                        run_metadata={"owner": "nanobot", "task": task, "model": self._model},
                    )
                    try:
                        return await self._run_task(wrapped_backend, task, **kwargs)
                    finally:
                        await wrapped_backend.shutdown()

        return await self._run_task(active_backend, task, **kwargs)

    async def _run_task(self, active_backend: Any, task: str, **kwargs: Any) -> str:
        from opengui.agent import GuiAgent
        from opengui.trajectory.recorder import TrajectoryRecorder

        memory_retriever = await self._build_memory_retriever()
        skill_library = self._get_skill_library(active_backend.platform)
        run_dir = self._make_run_dir()
        recorder = TrajectoryRecorder(
            output_dir=run_dir,
            task=task,
            platform=active_backend.platform,
        )
        agent = GuiAgent(
            llm=self._llm_adapter,
            backend=active_backend,
            trajectory_recorder=recorder,
            model=self._model,
            artifacts_root=run_dir,
            max_steps=self._gui_config.max_steps,
            memory_retriever=memory_retriever,
            skill_library=skill_library,
            skill_threshold=self._gui_config.skill_threshold,
            intervention_handler=self._build_intervention_handler(active_backend, task),
        )

        result = await agent.run(task=task)
        summary = result.summary
        error = result.error
        if error and error.startswith("intervention_cancelled:"):
            summary = f"Task cancelled during intervention after {result.steps_taken} step(s)."
            error = "intervention_cancelled"
        trace_path = self._resolve_trace_path(recorder_path=recorder.path, agent_trace_path=result.trace_path)
        self._schedule_trajectory_postprocessing(trace_path, result.success, skill_library)

        return json.dumps(
            {
                "success": result.success,
                "summary": summary,
                "model_summary": result.model_summary,
                "trace_path": str(trace_path) if trace_path is not None else result.trace_path,
                "steps_taken": result.steps_taken,
                "error": error,
            },
            ensure_ascii=False,
        )

    def _schedule_trajectory_postprocessing(
        self,
        trace_path: Path | None,
        is_success: bool,
        skill_library: Any,
    ) -> None:
        if trace_path is None or not trace_path.exists():
            return

        task = asyncio.create_task(
            self._run_trajectory_postprocessing(trace_path, is_success, skill_library),
            name=f"gui-postprocess-{trace_path.stem}",
        )
        self._background_postprocess_tasks.add(task)
        task.add_done_callback(self._handle_background_postprocess_done)

    async def _run_trajectory_postprocessing(
        self,
        trace_path: Path,
        is_success: bool,
        skill_library: Any,
    ) -> None:
        trajectory_summary = await self._summarize_trajectory(trace_path)
        if trajectory_summary:
            logger.info("Trajectory summary: %s", trajectory_summary[:200])
        await self._extract_skill(trace_path, is_success, skill_library)

    async def _wait_for_pending_postprocessing(self) -> None:
        if not self._background_postprocess_tasks:
            return
        await asyncio.gather(*list(self._background_postprocess_tasks), return_exceptions=True)

    def _handle_background_postprocess_done(self, task: asyncio.Task[None]) -> None:
        self._background_postprocess_tasks.discard(task)
        if task.cancelled():
            logger.debug("Background GUI postprocessing task was cancelled")
            return
        try:
            exc = task.exception()
        except Exception:
            logger.warning("Background GUI postprocessing task failed", exc_info=True)
            return
        if exc is not None:
            logger.warning(
                "Background GUI postprocessing task failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    def _select_backend(self, backend: str | None) -> Any:
        if backend is None or backend == self._gui_config.backend:
            return self._backend
        return self._build_backend(backend)

    async def _build_memory_retriever(self) -> Any | None:
        if self._embedding_adapter is None:
            return None

        from opengui.memory.retrieval import MemoryRetriever
        from opengui.memory.store import MemoryStore

        try:
            memory_store = MemoryStore(DEFAULT_OPENGUI_MEMORY_DIR)
            memory_retriever = MemoryRetriever(embedding_provider=self._embedding_adapter, top_k=5)
            await memory_retriever.index(memory_store.list_all())
            return memory_retriever
        except Exception:
            logger.warning(
                "GUI memory retriever initialization failed for %s",
                DEFAULT_OPENGUI_MEMORY_DIR,
                exc_info=True,
            )
            return None

    def _build_embedding_adapter(self) -> NanobotEmbeddingAdapter:
        """Build a NanobotEmbeddingAdapter backed by litellm.aembedding.

        The embed function:
        - resolves the configured model name via the provider when supported
        - passes provider credentials to litellm so the correct API is used
        - normalises the response into an (n, dim) float32 numpy array
        """
        embedding_model = self._gui_config.embedding_model  # guaranteed non-None by caller

        # Resolve the model name through the provider when the method is available.
        resolve = getattr(self._provider, "_resolve_model", None)
        resolved_model: str = resolve(embedding_model) if callable(resolve) else embedding_model

        provider = self._provider

        async def _embed(texts: list[str]) -> np.ndarray:
            if not texts:
                return np.zeros((0, 0), dtype=np.float32)

            # Collect provider credentials — only pass keys that are truthy to avoid
            # sending empty strings that some backends reject.
            kwargs: dict[str, Any] = {"model": resolved_model, "input": texts}
            api_key = getattr(provider, "api_key", None)
            if api_key:
                kwargs["api_key"] = api_key
            api_base = getattr(provider, "api_base", None)
            if api_base:
                kwargs["api_base"] = api_base
            extra_headers = getattr(provider, "extra_headers", None)
            if extra_headers:
                kwargs["extra_headers"] = extra_headers

            response = await litellm.aembedding(**kwargs)
            vectors = [item.embedding for item in response.data]
            return np.array(vectors, dtype=np.float32)

        return NanobotEmbeddingAdapter(_embed)

    def _build_backend(self, backend_name: str) -> Any:
        if backend_name == "adb":
            from opengui.backends.adb import AdbBackend

            return AdbBackend(serial=self._gui_config.adb.serial)

        if backend_name == "dry-run":
            from opengui.backends.dry_run import DryRunBackend

            return DryRunBackend()

        if backend_name == "local":
            from opengui.backends.desktop import LocalDesktopBackend

            return LocalDesktopBackend()

        raise ValueError(f"Unsupported GUI backend: {backend_name}")

    def _build_isolated_display_manager(self, probe: Any) -> Any:
        if probe.backend_name == "xvfb":
            from opengui.backends.displays.xvfb import XvfbDisplayManager

            display_num = self._gui_config.display_num if self._gui_config.display_num is not None else 99
            return XvfbDisplayManager(
                display_num=display_num,
                width=self._gui_config.display_width,
                height=self._gui_config.display_height,
            )

        if probe.backend_name == "cgvirtualdisplay":
            from opengui.backends.displays.cgvirtualdisplay import CGVirtualDisplayManager

            return CGVirtualDisplayManager(
                width=self._gui_config.display_width,
                height=self._gui_config.display_height,
            )

        if probe.backend_name == "windows_isolated_desktop":
            from opengui.backends.displays.win32desktop import Win32DesktopManager

            return Win32DesktopManager(
                width=self._gui_config.display_width,
                height=self._gui_config.display_height,
            )

        raise RuntimeError(f"Unsupported isolated backend: {probe.backend_name}")

    def _resolve_probe_target_app_class(
        self,
        backend: str | None,
        target_app_class: str | None,
        *,
        sys_platform: str | None = None,
    ) -> str | None:
        if not self._gui_config.background:
            return None
        if (sys_platform or sys.platform) != "win32":
            return None
        if (backend or self._gui_config.backend) != "local":
            return None
        return target_app_class or "classic-win32"

    def _get_skill_library(self, platform: str) -> Any:
        if platform not in self._skill_libraries:
            from opengui.skills.library import SkillLibrary

            self._skill_libraries[platform] = SkillLibrary(
                store_dir=get_gui_skill_store_root(self._workspace),
                embedding_provider=self._embedding_adapter,
                merge_llm=self._llm_adapter,
            )
        return self._skill_libraries[platform]

    def _make_run_dir(self) -> Path:
        runs_root = self._workspace / self._gui_config.artifacts_dir
        while True:
            run_dir = runs_root / datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
                return run_dir
            except FileExistsError:
                continue

    async def _extract_skill(self, trace_path: Path | None, is_success: bool, skill_library: Any) -> None:
        if trace_path is None or not trace_path.exists():
            return

        from opengui.skills.extractor import SkillExtractor

        try:
            extractor = SkillExtractor(llm=self._llm_adapter)
            skill = await extractor.extract_from_file(trace_path, is_success=is_success)
            if skill is None:
                logger.debug("No skill extracted from trajectory %s", trace_path)
                return
            decision, skill_id = await skill_library.add_or_merge(skill)
            logger.info(
                "Extracted GUI skill %s from %s with decision=%s",
                skill_id or skill.skill_id,
                trace_path,
                decision,
            )
        except Exception:
            logger.warning("Skill extraction failed for %s", trace_path, exc_info=True)

    async def _summarize_trajectory(self, trace_path: Path | None) -> str:
        """Summarize the trajectory via LLM; return empty string on error or when unavailable."""
        if trace_path is None or not trace_path.exists():
            return ""
        from opengui.trajectory.summarizer import TrajectorySummarizer

        try:
            summarizer = TrajectorySummarizer(llm=self._llm_adapter)
            return await summarizer.summarize_file(trace_path)
        except Exception:
            logger.warning("Trajectory summarization failed for %s", trace_path, exc_info=True)
            return ""

    @staticmethod
    def _resolve_trace_path(recorder_path: Path | None, agent_trace_path: str | None) -> Path | None:
        if recorder_path is not None and recorder_path.exists():
            return recorder_path

        if not agent_trace_path:
            return None

        candidate = Path(agent_trace_path)
        if candidate.is_file():
            return candidate
        if candidate.is_dir():
            matches = sorted(candidate.glob("**/*.jsonl"))
            if matches:
                return matches[0]
        return None

    @staticmethod
    def _background_json_failure(summary: str) -> str:
        return json.dumps(
            {
                "success": False,
                "summary": summary,
                "trace_path": None,
                "steps_taken": 0,
                "error": None,
            },
            ensure_ascii=False,
        )

    def _build_intervention_handler(self, active_backend: Any, task: str) -> InterventionHandler:
        return _GuiToolInterventionHandler(active_backend=active_backend, task=task)


class _GuiToolInterventionHandler:
    def __init__(self, *, active_backend: Any, task: str) -> None:
        self._active_backend = active_backend
        self._task = task

    async def request_intervention(
        self,
        request: InterventionRequest,
    ) -> InterventionResolution:
        payload = {
            "task": self._task,
            "reason": request.reason,
            "target": self._resolve_target(request),
        }
        scrubbed = self._scrub_payload(payload)
        logger.warning(
            "gui intervention requested: task=%s reason=%s target=%s",
            scrubbed["task"],
            scrubbed["reason"],
            json.dumps(scrubbed["target"], ensure_ascii=False, sort_keys=True),
        )
        return InterventionResolution(
            resume_confirmed=False,
            note="resume_not_confirmed",
        )

    def _resolve_target(self, request: InterventionRequest) -> dict[str, Any]:
        target = dict(request.target)
        get_target = getattr(self._active_backend, "get_intervention_target", None)
        if callable(get_target):
            backend_target = get_target() or {}
            if isinstance(backend_target, dict):
                target.update(backend_target)
        return {
            key: value
            for key, value in target.items()
            if key in _SAFE_INTERVENTION_TARGET_KEYS
        }

    @staticmethod
    def _scrub_payload(payload: dict[str, Any]) -> dict[str, Any]:
        from opengui.agent import GuiAgent

        return GuiAgent._scrub_for_log(payload)
