"""GuiSubagentTool: exposes opengui's GuiAgent as a nanobot tool."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import litellm
import numpy as np

from nanobot.agent.gui_adapter import NanobotEmbeddingAdapter, NanobotLLMAdapter
from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.config.schema import GuiConfig
    from nanobot.providers.base import LLMProvider


logger = logging.getLogger(__name__)


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
            },
            "required": ["task"],
        }

    async def execute(self, task: str, backend: str | None = None, **kwargs: Any) -> str:
        from opengui.agent import GuiAgent
        from opengui.trajectory.recorder import TrajectoryRecorder

        active_backend = self._select_backend(backend)
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
            skill_library=skill_library,
            skill_threshold=self._gui_config.skill_threshold,
        )

        result = await agent.run(task=task)
        trace_path = self._resolve_trace_path(recorder_path=recorder.path, agent_trace_path=result.trace_path)
        summary = await self._summarize_trajectory(trace_path)
        if summary:
            logger.info("Trajectory summary: %s", summary[:200])
        await self._extract_skill(trace_path, result.success, skill_library)

        return json.dumps(
            {
                "success": result.success,
                "summary": result.summary,
                "trace_path": str(trace_path) if trace_path is not None else result.trace_path,
                "steps_taken": result.steps_taken,
                "error": result.error,
            },
            ensure_ascii=False,
        )

    def _select_backend(self, backend: str | None) -> Any:
        if backend is None or backend == self._gui_config.backend:
            return self._backend
        return self._build_backend(backend)

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

    def _get_skill_library(self, platform: str) -> Any:
        if platform not in self._skill_libraries:
            from opengui.skills.library import SkillLibrary

            self._skill_libraries[platform] = SkillLibrary(
                store_dir=self._workspace / "gui_skills" / platform,
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
