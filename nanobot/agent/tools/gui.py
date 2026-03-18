"""GuiSubagentTool: exposes opengui's GuiAgent as a nanobot tool."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.gui_adapter import NanobotLLMAdapter
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
        self._embedding_adapter = None
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

    def _build_backend(self, backend_name: str) -> Any:
        if backend_name == "adb":
            from opengui.backends.adb import AdbBackend

            return AdbBackend(serial=self._gui_config.adb.serial)

        if backend_name == "dry-run":
            from opengui.backends.dry_run import DryRunBackend

            return DryRunBackend()

        if backend_name == "local":
            raise NotImplementedError("LocalDesktopBackend is planned for Phase 4 and is not available yet.")

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
