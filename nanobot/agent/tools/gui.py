"""GuiSubagentTool: exposes opengui's GuiAgent as a nanobot tool."""

from __future__ import annotations

import inspect
import json
import logging
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import litellm
import numpy as np

from nanobot.agent.gui_adapter import NanobotEmbeddingAdapter, NanobotLLMAdapter
from nanobot.agent.tools.base import Tool
from opengui.agent import GuiAgent
from opengui.interfaces import InterventionHandler, InterventionRequest, InterventionResolution
from opengui.postprocessing import EvaluationConfig, PostRunProcessor
from opengui.skills.normalization import get_gui_skill_store_root, normalize_app_identifier
from opengui.trajectory.recorder import TrajectoryRecorder

if TYPE_CHECKING:
    from nanobot.config.schema import GuiConfig
    from nanobot.providers.base import LLMProvider


logger = logging.getLogger(__name__)
DEFAULT_OPENGUI_MEMORY_DIR = Path.home() / ".opengui" / "memory"
_EMBEDDING_BATCH_SIZE = 10
_SAFE_INTERVENTION_TARGET_KEYS = frozenset(
    {"display_id", "monitor_index", "desktop_name", "width", "height", "platform"}
)
WindowsIsolatedBackend = None
probe_isolated_background_support = None
resolve_run_mode = None
log_mode_resolution = None
WINDOWS_TARGET_APP_CLASSES = ("classic-win32", "uwp", "directx", "gpu-heavy", "electron-gpu")


@dataclass(frozen=True)
class GuiWorkflowSubtask:
    """One app-scoped GUI workflow step."""

    task: str
    app_hint: str | None = None
    inputs: tuple[str, ...] = field(default_factory=tuple)
    outputs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task", str(self.task).strip())
        object.__setattr__(self, "app_hint", self._clean_optional_text(self.app_hint))
        object.__setattr__(self, "inputs", self._clean_keys(self.inputs))
        object.__setattr__(self, "outputs", self._clean_keys(self.outputs))

    @staticmethod
    def _clean_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _clean_keys(values: Any) -> tuple[str, ...]:
        if values is None:
            return ()
        if isinstance(values, str):
            values = [values]
        cleaned: list[str] = []
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            key = re.sub(r"\s+", "_", text)
            key = re.sub(r"[^\w.-]", "", key)
            if key and key not in cleaned:
                cleaned.append(key)
        return tuple(cleaned)


@dataclass(frozen=True)
class GuiWorkflowPlan:
    """Planner output for a single gui_task invocation."""

    mode: str = "single"
    subtasks: tuple[GuiWorkflowSubtask, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        mode = str(self.mode or "single").strip().lower()
        if mode not in {"single", "multi_app"}:
            mode = "single"
        object.__setattr__(self, "mode", mode)
        subtasks: list[GuiWorkflowSubtask] = []
        for subtask in self.subtasks or ():
            if isinstance(subtask, GuiWorkflowSubtask):
                subtasks.append(subtask)
            elif isinstance(subtask, dict):
                subtasks.append(
                    GuiWorkflowSubtask(
                        app_hint=subtask.get("app_hint"),
                        task=str(subtask.get("task") or "").strip(),
                        inputs=subtask.get("inputs"),
                        outputs=subtask.get("outputs"),
                    )
                )
        object.__setattr__(self, "subtasks", tuple(subtasks))


class GuiWorkflowRunner:
    """Lightweight multi-app orchestration inside one gui_task call."""

    _MAX_SUBTASKS = 3

    def __init__(
        self,
        *,
        llm: NanobotLLMAdapter,
        run_task: Callable[..., Awaitable[str]],
        load_latest_step_event: Callable[[Path | None], dict[str, Any]],
    ) -> None:
        self._llm = llm
        self._run_task = run_task
        self._load_latest_step_event = load_latest_step_event

    async def run(self, active_backend: Any, task: str, **kwargs: Any) -> str:
        plan = await self._safe_plan_workflow(task)
        if plan is None:
            return await self._run_task(active_backend, task, **kwargs)
        plan = self._normalize_plan_app_hints(
            plan,
            platform=str(getattr(active_backend, "platform", "") or "unknown"),
        )
        if plan.mode != "multi_app" or len(plan.subtasks) < 2:
            payload = await self._run_task(active_backend, task, **kwargs)
            return self._with_workflow_mode(payload, "single")

        return await self._run_multi_app(active_backend, task, plan, **kwargs)

    async def _safe_plan_workflow(self, task: str) -> GuiWorkflowPlan | None:
        try:
            return await self._plan_workflow(task)
        except Exception:
            logger.warning("GUI workflow planning failed; falling back to single task.", exc_info=True)
            return None

    async def _plan_workflow(self, task: str) -> GuiWorkflowPlan:
        response = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a narrow GUI task router for one gui_task tool call. "
                        "Return only JSON. Decide whether the original instruction is a single-app task "
                        "or a cross-app workflow.\n\n"
                        "Rules:\n"
                        "1. Use single when the instruction has one core goal, even if that goal needs "
                        "many UI steps inside one app.\n"
                        "2. Use multi_app only when the instruction crosses different apps or transfers "
                        "information from one app into another.\n"
                        "3. For multi_app, split into the fewest ordered app-scoped subtasks. "
                        "All operations within the same app must be merged into one subtask.\n"
                        "4. Return at most 3 subtasks. Each subtask must have: "
                        "app_hint (string or null), task (string), inputs (array of blackboard keys), "
                        "outputs (array of string keys to extract after the subtask). "
                        "Use inputs only for values produced by earlier subtasks. "
                        "Only string values can be transferred.\n\n"
                        "Examples:\n"
                        "Input: Open Settings and turn on mobile network\n"
                        "Output: {\"mode\":\"single\",\"subtasks\":[]}\n"
                        "Input: Open WeChat to message Zhang San, then open Maps and navigate home\n"
                        "Output: {\"mode\":\"multi_app\",\"subtasks\":["
                        "{\"app_hint\":\"WeChat\",\"task\":\"In WeChat, message Zhang San that you arrived.\","
                        "\"inputs\":[],\"outputs\":[]},"
                        "{\"app_hint\":\"Maps\",\"task\":\"In Maps, start navigation home.\","
                        "\"inputs\":[],\"outputs\":[]}]}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Original GUI task:\n{task}",
                },
            ],
            tools=None,
            max_tokens=900,
        )
        payload = self._extract_json_object(response.content)
        if not isinstance(payload, dict):
            return GuiWorkflowPlan(mode="single")

        mode = str(payload.get("mode") or "single").strip().lower()
        raw_subtasks = payload.get("subtasks")
        subtasks: list[GuiWorkflowSubtask] = []
        if isinstance(raw_subtasks, list):
            for raw in raw_subtasks[: self._MAX_SUBTASKS]:
                if not isinstance(raw, dict):
                    continue
                subtask = GuiWorkflowSubtask(
                    app_hint=raw.get("app_hint"),
                    task=str(raw.get("task") or "").strip(),
                    inputs=raw.get("inputs"),
                    outputs=raw.get("outputs"),
                )
                if subtask.task:
                    subtasks.append(subtask)
        if mode != "multi_app" or len(subtasks) < 2:
            return GuiWorkflowPlan(mode="single")
        return GuiWorkflowPlan(mode="multi_app", subtasks=tuple(subtasks))

    @staticmethod
    def _normalize_plan_app_hints(plan: GuiWorkflowPlan, *, platform: str) -> GuiWorkflowPlan:
        if not plan.subtasks:
            return plan
        normalized_subtasks: list[GuiWorkflowSubtask] = []
        for subtask in plan.subtasks:
            app_hint = subtask.app_hint
            if app_hint is not None:
                normalized = normalize_app_identifier(platform, app_hint)
                app_hint = normalized if normalized and normalized != "unknown" else None
            normalized_subtasks.append(
                GuiWorkflowSubtask(
                    task=subtask.task,
                    app_hint=app_hint,
                    inputs=subtask.inputs,
                    outputs=subtask.outputs,
                )
            )
        return GuiWorkflowPlan(mode=plan.mode, subtasks=tuple(normalized_subtasks))

    async def _run_multi_app(
        self,
        active_backend: Any,
        original_task: str,
        plan: GuiWorkflowPlan,
        **kwargs: Any,
    ) -> str:
        blackboard: dict[str, str] = {}
        subtask_records: list[dict[str, Any]] = []
        payloads: list[dict[str, Any]] = []
        total_steps = 0

        for index, subtask in enumerate(plan.subtasks, start=1):
            missing_inputs = [key for key in subtask.inputs if key not in blackboard]
            if missing_inputs:
                return self._workflow_failure_payload(
                    summary=(
                        "GUI workflow stopped because required input(s) were not available: "
                        f"{', '.join(missing_inputs)}."
                    ),
                    error="missing_workflow_input",
                    subtask_records=subtask_records,
                    blackboard=blackboard,
                    missing_outputs=[],
                    payloads=payloads,
                    steps_taken=total_steps,
                )

            task_prompt = self._append_known_values(subtask.task, blackboard, subtask.inputs)
            run_kwargs = dict(kwargs)
            if subtask.app_hint is not None:
                run_kwargs["app_hint"] = subtask.app_hint

            raw_payload = await self._run_task(active_backend, task_prompt, **run_kwargs)
            payload = self._load_result_payload(raw_payload)
            if payload is None:
                return self._workflow_failure_payload(
                    summary=f"GUI workflow stopped at subtask {index}: subtask returned invalid JSON.",
                    error="invalid_subtask_result",
                    subtask_records=subtask_records,
                    blackboard=blackboard,
                    missing_outputs=[],
                    payloads=payloads,
                    steps_taken=total_steps,
                )

            payloads.append(payload)
            total_steps += self._int_or_zero(payload.get("steps_taken"))
            subtask_records.append(self._subtask_record(subtask, payload))

            if not bool(payload.get("success")):
                return self._workflow_failure_payload(
                    summary=f"GUI workflow stopped at subtask {index}: {payload.get('summary') or 'failed'}",
                    error=self._string_or_default(payload.get("error"), "subtask_failed"),
                    subtask_records=subtask_records,
                    blackboard=blackboard,
                    missing_outputs=[],
                    payloads=payloads,
                    steps_taken=total_steps,
                )

            if subtask.outputs:
                trace_path = self._path_or_none(payload.get("trace_path"))
                latest_step = self._load_latest_step_event(trace_path)
                extracted = await self._extract_outputs(
                    original_task=original_task,
                    subtask=subtask,
                    declared_outputs=subtask.outputs,
                    summary=self._string_or_default(payload.get("summary"), ""),
                    model_summary=self._string_or_default(payload.get("model_summary"), ""),
                    latest_step=latest_step,
                )
                for key, value in extracted.items():
                    if key in subtask.outputs and isinstance(value, str) and value.strip():
                        blackboard[key] = value.strip()

                missing_outputs = [key for key in subtask.outputs if key not in blackboard]
                if missing_outputs:
                    return self._workflow_failure_payload(
                        summary=(
                            "GUI workflow stopped because required output(s) were not found: "
                            f"{', '.join(missing_outputs)}."
                        ),
                        error="missing_workflow_output",
                        subtask_records=subtask_records,
                        blackboard=blackboard,
                        missing_outputs=missing_outputs,
                        payloads=payloads,
                        steps_taken=total_steps,
                    )

        last_payload = payloads[-1] if payloads else {}
        result = self._base_workflow_payload(
            success=True,
            summary=self._string_or_default(last_payload.get("summary"), "GUI workflow completed."),
            error=None,
            subtask_records=subtask_records,
            blackboard=blackboard,
            payloads=payloads,
            steps_taken=total_steps,
        )
        return json.dumps(result, ensure_ascii=False)

    async def _extract_outputs(
        self,
        *,
        original_task: str,
        subtask: GuiWorkflowSubtask,
        declared_outputs: tuple[str, ...],
        summary: str,
        model_summary: str,
        latest_step: dict[str, Any],
    ) -> dict[str, str]:
        latest_step_text = self._compact_json(latest_step, max_chars=4000)
        response = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract structured string values from a completed GUI subtask. "
                        "Return only a JSON object. Keys must be selected from the declared output keys. "
                        "If a value is not explicitly present, omit the key. Do not guess."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original task:\n{original_task}\n\n"
                        f"Subtask:\n{subtask.task}\n\n"
                        f"Declared output keys: {json.dumps(list(declared_outputs), ensure_ascii=False)}\n\n"
                        f"Summary:\n{summary}\n\n"
                        f"Model summary:\n{model_summary}\n\n"
                        f"Latest trace step:\n{latest_step_text}"
                    ),
                },
            ],
            tools=None,
            max_tokens=500,
        )
        payload = self._extract_json_object(response.content)
        if not isinstance(payload, dict):
            return {}
        allowed = set(declared_outputs)
        extracted: dict[str, str] = {}
        for key, value in payload.items():
            if key not in allowed or value is None:
                continue
            text = str(value).strip()
            if text:
                extracted[key] = text
        return extracted

    @staticmethod
    def _append_known_values(task: str, blackboard: dict[str, str], inputs: tuple[str, ...]) -> str:
        if not blackboard:
            return task
        keys = [key for key in inputs if key in blackboard] if inputs else list(blackboard)
        if not keys:
            return task
        pairs = []
        for key in keys:
            value = re.sub(r"\s+", " ", blackboard[key]).strip()
            pairs.append(f"{key}={value}")
        return f"{task}\n\nYou must use these known values if relevant: {', '.join(pairs)}"

    @staticmethod
    def _subtask_record(subtask: GuiWorkflowSubtask, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "app_hint": subtask.app_hint,
            "task": subtask.task,
            "success": bool(payload.get("success")),
            "summary": payload.get("summary"),
            "trace_path": payload.get("trace_path"),
        }

    def _workflow_failure_payload(
        self,
        *,
        summary: str,
        error: str,
        subtask_records: list[dict[str, Any]],
        blackboard: dict[str, str],
        missing_outputs: list[str],
        payloads: list[dict[str, Any]],
        steps_taken: int,
    ) -> str:
        payload = self._base_workflow_payload(
            success=False,
            summary=summary,
            error=error,
            subtask_records=subtask_records,
            blackboard=blackboard,
            payloads=payloads,
            steps_taken=steps_taken,
        )
        if missing_outputs:
            payload["missing_outputs"] = missing_outputs
        return json.dumps(payload, ensure_ascii=False)

    def _base_workflow_payload(
        self,
        *,
        success: bool,
        summary: str,
        error: str | None,
        subtask_records: list[dict[str, Any]],
        blackboard: dict[str, str],
        payloads: list[dict[str, Any]],
        steps_taken: int,
    ) -> dict[str, Any]:
        last_payload = payloads[-1] if payloads else {}
        duration_s = self._sum_numeric(payloads, "duration_s")
        token_usage = self._sum_token_usage(payloads, "token_usage")
        return {
            "success": success,
            "summary": summary,
            "model_summary": last_payload.get("model_summary"),
            "trace_path": last_payload.get("trace_path"),
            "steps_taken": steps_taken,
            "error": error,
            "post_run_state": last_payload.get("post_run_state"),
            "metrics_path": last_payload.get("metrics_path"),
            "duration_s": duration_s,
            "token_usage": token_usage,
            "total_duration_s": duration_s,
            "total_token_usage": token_usage,
            "workflow_mode": "multi_app",
            "subtasks": subtask_records,
            "blackboard": dict(blackboard),
        }

    @staticmethod
    def _with_workflow_mode(payload: str, mode: str) -> str:
        data = GuiWorkflowRunner._load_result_payload(payload)
        if data is None:
            return payload
        data["workflow_mode"] = mode
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _load_result_payload(payload: str) -> dict[str, Any] | None:
        try:
            data = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                payload = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _compact_json(value: Any, *, max_chars: int) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = str(value)
        if len(text) > max_chars:
            return f"{text[:max_chars]}..."
        return text

    @staticmethod
    def _path_or_none(value: Any) -> Path | None:
        if not value:
            return None
        path = Path(str(value))
        return path if path.exists() else None

    @staticmethod
    def _int_or_zero(value: Any) -> int:
        return value if isinstance(value, int) else 0

    @staticmethod
    def _string_or_default(value: Any, default: str) -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    @staticmethod
    def _sum_numeric(payloads: list[dict[str, Any]], key: str) -> float | None:
        values = [payload.get(key) for payload in payloads]
        numeric = [value for value in values if isinstance(value, int | float)]
        if not numeric:
            return None
        return float(sum(numeric))

    @staticmethod
    def _sum_token_usage(payloads: list[dict[str, Any]], key: str) -> dict[str, int]:
        totals: dict[str, int] = {}
        for payload in payloads:
            usage = payload.get(key)
            if not isinstance(usage, dict):
                continue
            for usage_key, value in usage.items():
                if isinstance(value, int):
                    totals[usage_key] = totals.get(usage_key, 0) + value
        return totals


class GuiSubagentTool(Tool):
    """Run a GUI automation task through opengui."""

    def __init__(
        self,
        *,
        gui_config: "GuiConfig | None",
        provider: "LLMProvider",
        model: str,
        workspace: Path,
        gui_event_callback: Any | None = None,
        gui_frame_callback: Any | None = None,
    ) -> None:
        if gui_config is None:
            raise ValueError("GuiSubagentTool requires gui_config")

        self._gui_config = gui_config
        self._provider = provider
        self._model = model
        self._workspace = Path(workspace)
        self._gui_event_callback = gui_event_callback
        self._gui_frame_callback = gui_frame_callback
        self._llm_adapter = NanobotLLMAdapter(
            provider, model, capture_ttft=gui_config.capture_ttft,
        )
        self._embedding_signature: str | None = self._resolve_embedding_signature()
        self._embedding_adapter = self._build_embedding_adapter() if gui_config.embedding_model else None
        self._skill_libraries: dict[str, Any] = {}

        self._backend = self._build_backend(gui_config.backend)
        self._skill_library = (
            self._get_skill_library(self._backend.platform, embedding_signature=self._embedding_signature)
            if gui_config.enable_skill_execution
            else None
        )
        self._postprocessor = PostRunProcessor(
            llm=self._llm_adapter,
            merge_llm=self._llm_adapter,
            embedding_provider=self._embedding_adapter,
            embedding_signature=self._embedding_signature,
            skill_store_root=get_gui_skill_store_root(self._workspace),
            enable_skill_extraction=gui_config.enable_skill_extraction,
            evaluation=EvaluationConfig(
                enabled=gui_config.evaluation.enabled,
                judge_model=gui_config.evaluation.judge_model,
                api_key=gui_config.evaluation.api_key,
                api_base=gui_config.evaluation.api_base,
            ),
        )

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
                    "enum": ["adb", "ios", "hdc", "local", "dry-run"],
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
        try:
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
                    from opengui.backends.background_runtime import (
                        resolve_run_mode as runtime_resolve_run_mode,
                    )

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
                            backend_cls = WindowsIsolatedBackend
                            if backend_cls is None:
                                from opengui.backends.windows_isolated import (
                                    WindowsIsolatedBackend as ImportedWindowsIsolatedBackend,
                                )

                                backend_cls = ImportedWindowsIsolatedBackend
                            wrapped_backend = backend_cls(
                                active_backend,
                                mgr,
                                run_metadata={"owner": "nanobot", "task": task, "model": self._model},
                            )
                            return await self._run_workflow_or_task(wrapped_backend, task, **kwargs)
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
                            return await self._run_workflow_or_task(wrapped_backend, task, **kwargs)
                        finally:
                            await wrapped_backend.shutdown()

            return await self._run_workflow_or_task(active_backend, task, **kwargs)
        finally:
            await self._shutdown_android_backend(active_backend)

    async def _run_workflow_or_task(self, active_backend: Any, task: str, **kwargs: Any) -> str:
        runner = GuiWorkflowRunner(
            llm=self._llm_adapter,
            run_task=self._run_task,
            load_latest_step_event=self._load_latest_step_event,
        )
        return await runner.run(active_backend, task, **kwargs)

    async def _run_task(
        self,
        active_backend: Any,
        task: str,
        *,
        app_hint: str | None = None,
        **kwargs: Any,
    ) -> str:
        del kwargs
        policy_context, memory_store = self._load_policy_context_and_memory_store()
        skill_library = None
        if self._gui_config.enable_skill_execution:
            self._refresh_cached_skill_stores()
            skill_library = self._get_skill_library(
                active_backend.platform,
                embedding_signature=self._embedding_signature,
            )
        run_dir = self._make_run_dir()
        recorder = TrajectoryRecorder(
            output_dir=run_dir,
            task=task,
            platform=active_backend.platform,
            event_callback=self._gui_event_callback,
        )

        skill_executor = None
        if self._gui_config.enable_skill_execution:
            from opengui.agent import (
                _AgentActionGrounder,
                _AgentScreenshotProvider,
                _AgentSubgoalRunner,
            )
            from opengui.skills.executor import LLMStateValidator, SkillExecutor

            validator_llm = (
                NanobotLLMAdapter(self._provider, self._gui_config.validator_model)
                if self._gui_config.validator_model
                else self._llm_adapter
            )
            grounder_llm = (
                NanobotLLMAdapter(self._provider, self._gui_config.grounder_model)
                if self._gui_config.grounder_model
                else self._llm_adapter
            )
            grounder_model = self._gui_config.grounder_model or self._model

            state_validator = LLMStateValidator(
                validator_llm,
                image_scale_ratio=self._gui_config.image_scale_ratio,
            )
            skill_executor = SkillExecutor(
                backend=active_backend,
                state_validator=state_validator,
                action_grounder=_AgentActionGrounder(
                    llm=grounder_llm,
                    model=grounder_model,
                    agent_profile=self._gui_config.agent_profile,
                    image_scale_ratio=self._gui_config.image_scale_ratio,
                ),
                subgoal_runner=_AgentSubgoalRunner(
                    llm=self._llm_adapter,
                    backend=active_backend,
                    state_validator=state_validator,
                    model=self._model,
                    artifacts_root=run_dir,
                    trajectory_recorder=recorder,
                    agent_profile=self._gui_config.agent_profile,
                    step_timeout=30.0,
                    image_scale_ratio=self._gui_config.image_scale_ratio,
                ),
                screenshot_provider=_AgentScreenshotProvider(
                    backend=active_backend,
                    artifacts_root=run_dir,
                ),
                trajectory_recorder=recorder,
                stop_on_failure=True,
                max_recovery_steps=3,
            )

        skill_reuser = None
        if skill_library is not None and self._gui_config.reuser_model:
            from opengui.skills.reuser import SkillReuser

            reuser_llm = NanobotLLMAdapter(self._provider, self._gui_config.reuser_model)
            skill_reuser = SkillReuser(reuser_llm, threshold=self._gui_config.skill_threshold)

        sc_dir = Path(self._workspace) / "shortcut_cache"
        sc_dir.mkdir(parents=True, exist_ok=True)

        agent = GuiAgent(
            llm=self._llm_adapter,
            backend=active_backend,
            trajectory_recorder=recorder,
            model=self._model,
            artifacts_root=run_dir,
            max_steps=self._gui_config.max_steps,
            policy_context=policy_context,
            skill_library=skill_library,
            skill_threshold=self._gui_config.skill_threshold,
            skill_executor=skill_executor,
            skill_reuser=skill_reuser,
            intervention_handler=self._build_intervention_handler(active_backend, task),
            memory_store=memory_store,
            agent_profile=self._gui_config.agent_profile,
            image_scale_ratio=self._gui_config.image_scale_ratio,
            stagnation_limit=self._gui_config.stagnation_limit,
            shortcuts={},
            shortcut_backend=active_backend,
            shortcut_cache_dir=str(sc_dir),
        )

        if app_hint is not None:
            result = await agent.run(task=task, app_hint=app_hint)
        else:
            result = await agent.run(task=task)
        summary = result.summary
        error = result.error
        if error and error.startswith("intervention_cancelled:"):
            error = "intervention_cancelled"
        trace_path = self._resolve_trace_path(recorder_path=recorder.path, agent_trace_path=result.trace_path)
        post_run_state = self._build_post_run_state(
            trace_path=trace_path,
            success=result.success,
            summary=summary,
            error=error,
        )
        metrics_path = recorder.metrics_path
        metrics = self._load_gui_metrics(metrics_path)
        total_duration_s = metrics.get("total_duration_s") or metrics.get("duration_s")
        total_token_usage = (
            metrics.get("total_token_usage")
            or metrics.get("token_usage")
            or result.token_usage
            or {}
        )
        self._postprocessor.schedule(trace_path, is_success=result.success, platform=active_backend.platform, task=task)

        return json.dumps(
            {
                "success": result.success,
                "summary": summary,
                "model_summary": result.model_summary,
                "trace_path": str(trace_path) if trace_path is not None else result.trace_path,
                "steps_taken": result.steps_taken,
                "error": error,
                "post_run_state": post_run_state,
                "metrics_path": str(metrics_path) if metrics_path is not None and metrics_path.exists() else None,
                "duration_s": total_duration_s,
                "token_usage": total_token_usage,
                "total_duration_s": total_duration_s,
                "total_token_usage": total_token_usage,
            },
            ensure_ascii=False,
        )

    def _build_post_run_state(
        self,
        *,
        trace_path: Path | None,
        success: bool,
        summary: str,
        error: str | None,
    ) -> dict[str, Any]:
        step_event = self._load_latest_step_event(trace_path)
        observation = self._extract_latest_observation(step_event)
        last_action = step_event.get("action") if isinstance(step_event, dict) else None
        last_action_summary = None
        latest_screenshot_path = None
        if isinstance(step_event, dict):
            last_action_summary = self._string_or_none(step_event.get("model_output"))
            latest_screenshot_path = self._string_or_none(step_event.get("screenshot_path"))
        if latest_screenshot_path is None and observation:
            latest_screenshot_path = self._string_or_none(observation.get("screenshot_path"))

        foreground_app = self._string_or_none(observation.get("foreground_app")) if observation else None
        platform = self._string_or_none(observation.get("platform")) if observation else None
        resolution = self._format_resolution(observation)
        current_state = self._describe_current_state(
            success=success,
            summary=summary,
            error=error,
            foreground_app=foreground_app,
            resolution=resolution,
        )

        return {
            "trace_read": trace_path is not None and trace_path.exists(),
            "latest_screenshot_path": latest_screenshot_path,
            "last_action": last_action,
            "last_action_summary": last_action_summary,
            "last_foreground_app": foreground_app,
            "platform": platform,
            "screen_resolution": resolution,
            "current_state": current_state,
            "completion_assessment": "completed" if success else "not_completed",
        }

    async def _wait_for_pending_postprocessing(self) -> None:
        """Drain all pending post-processing background tasks."""
        await self._postprocessor.drain()

    @staticmethod
    def _load_latest_step_event(trace_path: Path | None) -> dict[str, Any]:
        if trace_path is None or not trace_path.exists():
            return {}

        latest_step: dict[str, Any] = {}
        try:
            with open(trace_path, encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict) and event.get("type") == "step":
                        latest_step = event
        except OSError:
            logger.warning("Could not read GUI trace for post-run state: %s", trace_path, exc_info=True)
        return latest_step

    @staticmethod
    def _extract_latest_observation(step_event: dict[str, Any]) -> dict[str, Any]:
        execution = step_event.get("execution") if isinstance(step_event, dict) else None
        if isinstance(execution, dict):
            next_observation = execution.get("next_observation")
            if isinstance(next_observation, dict):
                return next_observation

        observation = step_event.get("observation") if isinstance(step_event, dict) else None
        if isinstance(observation, dict):
            return observation

        prompt = step_event.get("prompt") if isinstance(step_event, dict) else None
        if isinstance(prompt, dict):
            current_observation = prompt.get("current_observation")
            if isinstance(current_observation, dict):
                return current_observation

        return {}

    @staticmethod
    def _format_resolution(observation: dict[str, Any]) -> str | None:
        width = observation.get("screen_width")
        height = observation.get("screen_height")
        if isinstance(width, int) and isinstance(height, int):
            return f"{width}x{height}"
        return None

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return str(value)

    @staticmethod
    def _describe_current_state(
        *,
        success: bool,
        summary: str,
        error: str | None,
        foreground_app: str | None,
        resolution: str | None,
    ) -> str:
        note = summary.strip()
        if note:
            return note

        parts = ["GUI task completed successfully." if success else "GUI task did not complete successfully."]
        if error:
            parts.append(f"Error: {error}.")
        if foreground_app:
            parts.append(f"Latest visible app: {foreground_app}.")
        if resolution:
            parts.append(f"Screen resolution: {resolution}.")
        return " ".join(parts)

    def _select_backend(self, backend: str | None) -> Any:
        if backend is None or backend == self._gui_config.backend:
            return self._backend
        return self._build_backend(backend)

    async def _build_memory_retriever(self) -> Any | None:
        """Build a memory retriever indexed with POLICY entries only.

        Guide entries (os_guide, app_guide, icon_guide) are not surfaced here;
        nanobot no longer has a planner layer that consumes them.
        """
        if self._embedding_adapter is None:
            return None

        from opengui.memory.retrieval import MemoryRetriever
        from opengui.memory.store import MemoryStore
        from opengui.memory.types import MemoryType

        try:
            memory_store = MemoryStore(DEFAULT_OPENGUI_MEMORY_DIR)
            policy_entries = memory_store.list_all(memory_type=MemoryType.POLICY)
            if not policy_entries:
                return None
            memory_retriever = MemoryRetriever(embedding_provider=self._embedding_adapter, top_k=5)
            await memory_retriever.index(policy_entries)
            return memory_retriever
        except Exception:
            logger.warning(
                "GUI memory retriever initialization failed for %s",
                DEFAULT_OPENGUI_MEMORY_DIR,
                exc_info=True,
            )
            return None

    def _load_policy_context(self) -> str | None:
        policy_context, _ = GuiSubagentTool._load_policy_context_and_memory_store(self)
        return policy_context

    def _load_policy_context_and_memory_store(self) -> tuple[str | None, Any | None]:
        """Load all POLICY entries as raw text for direct injection into the GUI agent system prompt.

        Policies must always be present regardless of task relevance, so they are loaded
        in full without embedding-based search filtering.
        """
        from opengui.memory.store import MemoryStore
        from opengui.memory.types import MemoryType

        try:
            memory_store = MemoryStore(DEFAULT_OPENGUI_MEMORY_DIR)
            policy_entries = memory_store.list_all(memory_type=MemoryType.POLICY)
            if not policy_entries:
                return None, memory_store
            lines = [f"- {entry.content}" for entry in policy_entries]
            return "\n".join(lines), memory_store
        except Exception:
            logger.warning("Failed to load GUI policy memory", exc_info=True)
            return None, None

    def _build_embedding_adapter(self) -> NanobotEmbeddingAdapter:
        """Build a NanobotEmbeddingAdapter backed by litellm.aembedding.

        The embed function:
        - resolves the configured model name via the provider when supported
        - passes provider credentials to litellm so the correct API is used
        - normalises the response into an (n, dim) float32 numpy array
        """
        resolved_model = self._resolve_embedding_model()

        embedding_model = resolved_model

        direct_client = getattr(self._provider, "_client", None)
        if direct_client is not None and hasattr(direct_client, "embeddings"):
            direct_model = self._normalize_direct_embedding_model(embedding_model)

            async def _embed_direct(texts: list[str]) -> np.ndarray:
                async def _request_batch(batch: list[str]) -> list[list[float]]:
                    response = await direct_client.embeddings.create(
                        model=direct_model,
                        input=batch,
                    )
                    return [item.embedding for item in response.data]

                return await self._embed_texts_in_batches(texts, _request_batch)

            return NanobotEmbeddingAdapter(_embed_direct)

        provider = self._provider

        async def _embed(texts: list[str]) -> np.ndarray:
            async def _request_batch(batch: list[str]) -> list[list[float]]:
                # Collect provider credentials — only pass keys that are truthy to avoid
                # sending empty strings that some backends reject.
                kwargs: dict[str, Any] = {"model": resolved_model, "input": batch}
                # OpenAI-compatible embedding endpoints (including DashScope compatible-mode)
                # expect an explicit encoding_format. LiteLLM may default to an unsupported
                # format for some providers if omitted.
                kwargs["encoding_format"] = "float"
                api_key = getattr(provider, "api_key", None)
                if api_key:
                    kwargs["api_key"] = api_key
                api_base = getattr(provider, "api_base", None)
                if not api_base:
                    api_base = self._default_embedding_api_base(resolved_model)
                if api_base:
                    kwargs["api_base"] = api_base
                extra_headers = getattr(provider, "extra_headers", None)
                if extra_headers:
                    kwargs["extra_headers"] = extra_headers

                response = await litellm.aembedding(**kwargs)
                vectors: list[list[float]] = []
                for item in response.data:
                    if isinstance(item, dict):
                        embedding = item.get("embedding")
                    else:
                        embedding = getattr(item, "embedding", None)
                    if embedding is None:
                        raise ValueError("Embedding response item missing 'embedding' field")
                    vectors.append(embedding)
                return vectors

            return await self._embed_texts_in_batches(texts, _request_batch)

        return NanobotEmbeddingAdapter(_embed)

    def _resolve_embedding_model(self) -> str:
        embedding_model = self._gui_config.embedding_model
        if not embedding_model:
            raise ValueError("embedding model is required to build embedding adapter")

        resolve = getattr(self._provider, "_resolve_model", None)
        resolved = resolve(embedding_model) if callable(resolve) else embedding_model

        # DashScope's compatible-mode endpoint is OpenAI-style under LiteLLM.
        # When users configure bare model names like "text-embedding-v4", normalize
        # to "openai/<model>" so provider routing is deterministic.
        if (
            isinstance(resolved, str)
            and "/" not in resolved
            and (self._gui_config.provider or "").strip().lower() == "dashscope"
        ):
            return f"openai/{resolved}"
        return resolved

    def _resolve_embedding_signature(self) -> str | None:
        embedding_model = self._gui_config.embedding_model
        if not embedding_model:
            return None

        resolved_model = self._resolve_embedding_model()
        direct_client = getattr(self._provider, "_client", None)
        if direct_client is not None and hasattr(direct_client, "embeddings"):
            resolved_model = self._normalize_direct_embedding_model(resolved_model)

        gateway = getattr(self._provider, "_gateway", None)
        provider_name = (
            getattr(gateway, "name", None)
            or getattr(gateway, "litellm_prefix", None)
            or self._provider.__class__.__name__
        )
        api_base = getattr(self._provider, "api_base", None)
        if not api_base:
            api_base = getattr(self._provider, "_api_base", None)
        if not api_base:
            api_base = self._default_embedding_api_base(resolved_model)

        parts = [str(provider_name)]
        if api_base:
            parts.append(str(api_base))
        parts.append(resolved_model)
        return "|".join(parts)

    def _default_embedding_api_base(self, resolved_model: str) -> str | None:
        """Return provider-specific fallback API base for embedding requests."""
        provider_name = (self._gui_config.provider or "").strip().lower()
        if provider_name == "dashscope" and resolved_model.startswith("openai/"):
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return None

    async def _embed_texts_in_batches(
        self,
        texts: list[str],
        request_batch: Callable[[list[str]], Awaitable[list[list[float]]]],
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + _EMBEDDING_BATCH_SIZE]
            vectors.extend(await request_batch(batch))
        return np.array(vectors, dtype=np.float32)

    @staticmethod
    def _normalize_direct_embedding_model(model: str) -> str:
        """Strip LiteLLM-style provider prefixes for direct OpenAI-compatible clients."""
        if "/" not in model:
            return model
        return model.split("/", 1)[1]

    def _build_backend(self, backend_name: str) -> Any:
        if backend_name == "adb":
            from opengui.backends.adb import AdbBackend

            return AdbBackend(
                serial=self._gui_config.adb.serial,
                scrcpy_max_fps=self._gui_config.scrcpy.max_fps,
                scrcpy_jpeg_quality=self._gui_config.scrcpy.jpeg_quality,
                scrcpy_frame_timeout_ms=self._gui_config.scrcpy.frame_timeout_ms,
                scrcpy_max_frame_age_ms=self._gui_config.scrcpy.max_frame_age_ms,
                on_jpeg_frame=self._gui_frame_callback,
                collect_ui_tree=True,
                collect_ui_tree_nodes=True,
            )

        if backend_name == "ios":
            from opengui.backends.ios_wda import WdaBackend

            return WdaBackend(wda_url=self._gui_config.ios.wda_url)

        if backend_name == "hdc":
            from opengui.backends.hdc import HdcBackend

            return HdcBackend(serial=self._gui_config.hdc.serial)

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

    def _get_skill_library(
        self,
        platform: str,
        *,
        embedding_signature: str | None = None,
    ) -> Any:
        if platform not in self._skill_libraries:
            from opengui.skills.flat import FlatSkillLibrary

            self._skill_libraries[platform] = FlatSkillLibrary(
                store_dir=get_gui_skill_store_root(self._workspace),
                embedding_provider=self._embedding_adapter,
                merge_llm=self._llm_adapter,
                embedding_signature=embedding_signature,
            )
        return self._skill_libraries[platform]

    def _refresh_cached_skill_stores(self) -> None:
        for cached in getattr(self, "_skill_libraries", {}).values():
            refresh_if_stale = getattr(cached, "refresh_if_stale", None)
            if callable(refresh_if_stale):
                refresh_if_stale()

    def _make_run_dir(self) -> Path:
        runs_root = self._workspace / self._gui_config.artifacts_dir
        while True:
            run_dir = runs_root / datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
                return run_dir
            except FileExistsError:
                continue

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
    def _load_gui_metrics(metrics_path: Path | None) -> dict[str, Any]:
        if metrics_path is None or not metrics_path.exists():
            return {}
        try:
            payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _background_json_failure(summary: str) -> str:
        return json.dumps(
            {
                "success": False,
                "summary": summary,
                "trace_path": None,
                "steps_taken": 0,
                "error": None,
                "metrics_path": None,
                "duration_s": None,
                "token_usage": {},
                "total_duration_s": None,
                "total_token_usage": {},
            },
            ensure_ascii=False,
        )

    def _build_intervention_handler(self, active_backend: Any, task: str) -> InterventionHandler:
        return _GuiToolInterventionHandler(active_backend=active_backend, task=task)

    async def shutdown(self) -> None:
        await self._wait_for_pending_postprocessing()
        shutdown = getattr(self._backend, "shutdown", None)
        if callable(shutdown):
            await shutdown()

    async def _shutdown_android_backend(self, backend: Any) -> None:
        if getattr(backend, "platform", None) != "android":
            return
        shutdown = getattr(backend, "shutdown", None)
        if not callable(shutdown):
            return
        result = shutdown()
        if inspect.isawaitable(result):
            await result


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
        return GuiAgent._scrub_for_log(payload)
