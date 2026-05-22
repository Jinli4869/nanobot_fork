"""
opengui.trajectory.recorder
~~~~~~~~~~~~~~~~~~~~~~~~~~~
JSONL trajectory recording with metadata, step, and result events.

Supports recording execution phase (skill execution vs. free agent exploration)
to distinguish different execution modes in the trajectory log.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class ExecutionPhase(str, Enum):
    """Phase of execution being recorded."""

    AGENT = "agent"        # Free agent vision-action exploration
    SKILL = "skill"        # Executing a known skill step-by-step
    RETRY = "retry"        # Retrying after a failure
    RECOVERY = "recovery"  # Executing a corrective action from failed skill


@dataclass
class TrajectoryRecorder:
    """Record a GUI agent trajectory as a JSONL file.

    Event types:
    - ``metadata``: Written once at start (task, platform, timestamp).
    - ``phase_change``: Logged when execution switches phase (agent → skill, etc.).
    - ``step``: One per action (step_index, action, phase, model_output, screenshot).
    - ``result``: Written once at end (success, total_steps, duration_s, error).

    Parameters
    ----------
    output_dir:
        Directory to store trajectory files.
    task:
        The task description being executed.
    platform:
        Platform identifier (android, macos, etc.).
    """

    output_dir: Path
    task: str
    platform: str = "unknown"
    event_callback: Callable[[dict[str, Any]], None] | None = None

    _path: Path | None = field(default=None, init=False, repr=False)
    _step_count: int = field(default=0, init=False, repr=False)
    _start_time: float = field(default=0.0, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _current_phase: ExecutionPhase = field(default=ExecutionPhase.AGENT, init=False, repr=False)
    _step_metrics: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _metrics_path: Path | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def metrics_path(self) -> Path | None:
        return self._metrics_path

    @property
    def current_phase(self) -> ExecutionPhase:
        return self._current_phase

    def start(self, *, phase: ExecutionPhase = ExecutionPhase.AGENT) -> Path:
        """Start recording. Returns the trajectory file path."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self._path = self.output_dir / f"trace_{timestamp}.jsonl"
        self._start_time = time.time()
        self._step_count = 0
        self._closed = False
        self._current_phase = phase
        self._step_metrics = []
        self._metrics_path = self.output_dir / "gui_metrics.json"

        self._write_event({
            "type": "metadata",
            "task": self.task,
            "platform": self.platform,
            "initial_phase": phase.value,
            "timestamp": self._start_time,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })
        return self._path

    def set_phase(self, phase: ExecutionPhase, *, reason: str = "") -> None:
        """Switch execution phase and log the transition."""
        if self._closed:
            raise RuntimeError("Recorder already closed")
        prev = self._current_phase
        self._current_phase = phase
        self._write_event({
            "type": "phase_change",
            "from_phase": prev.value,
            "to_phase": phase.value,
            "reason": reason,
            "timestamp": time.time(),
            "at_step": self._step_count,
        })

    def record_event(self, event_type: str, **payload: Any) -> None:
        """Record a non-step lifecycle event in the trajectory."""
        if self._closed:
            raise RuntimeError("Recorder already closed")
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "at_step": self._step_count,
            **payload,
        }
        self._write_event(event)
        if event_type == "skill_step":
            self._step_metrics.append(
                _step_metric_from_event(
                    event,
                    phase_value=ExecutionPhase.SKILL.value,
                    metric_index=len(self._step_metrics),
                )
            )
        elif event_type == "subgoal_step":
            self._step_metrics.append(
                _step_metric_from_event(
                    event,
                    phase_value=ExecutionPhase.RECOVERY.value,
                    metric_index=len(self._step_metrics),
                )
            )

    def record_step(
        self,
        *,
        action: dict[str, Any],
        model_output: str = "",
        screenshot_path: str | None = None,
        foreground_app: str | None = None,
        screen_width: int | None = None,
        screen_height: int | None = None,
        platform: str | None = None,
        observation_extra: dict[str, Any] | None = None,
        interaction_target: dict[str, Any] | None = None,
        phase: ExecutionPhase | None = None,
        token_usage: dict[str, int] | None = None,
        duration_s: float | None = None,
        chat_latency_s: float | None = None,
        ttft_s: float | None = None,
    ) -> None:
        """Record one agent step.

        Parameters
        ----------
        action:
            Action dict (action_type, x, y, text, etc.).
        model_output:
            Concise model action summary for this step.
        screenshot_path:
            Path to the screenshot taken before this step.
        foreground_app:
            App identifier visible in the foreground after the step.
        screen_width:
            Screen width in pixels after the step.
        screen_height:
            Screen height in pixels after the step.
        platform:
            Platform identifier (android, macos, etc.).
        observation_extra:
            Compact structured observation metadata such as UI-tree text lists.
        interaction_target:
            Pre-action UI node/contract matched by the action coordinates.
        phase:
            Override current phase for this step.
        token_usage:
            Token counts for this step broken down by type
            (e.g. ``{"prompt_tokens": 1234, "completion_tokens": 56}``).
        duration_s:
            Wall-clock duration of this step in seconds.
        """
        if self._closed:
            raise RuntimeError("Recorder already closed")

        obs: dict[str, Any] | None = None
        if foreground_app or screen_width is not None or observation_extra:
            obs = {}
            if foreground_app:
                obs["app"] = foreground_app
                obs["foreground_app"] = foreground_app
            if screen_width is not None:
                obs["screen_width"] = screen_width
            if screen_height is not None:
                obs["screen_height"] = screen_height
            if platform:
                obs["platform"] = platform
            if screenshot_path:
                obs["screenshot_path"] = screenshot_path
            if observation_extra:
                obs["extra"] = _compact_observation_extra(observation_extra)

        phase_value = (phase or self._current_phase).value
        event: dict[str, Any] = {
            "type": "step",
            "step_index": self._step_count,
            "phase": phase_value,
            "timestamp": time.time(),
            "action": action,
            "model_output": model_output,
            "screenshot_path": screenshot_path,
            "observation": obs,
        }
        if interaction_target:
            event["interaction_target"] = interaction_target
        if token_usage:
            event["token_usage"] = token_usage
        if duration_s is not None:
            event["duration_s"] = round(duration_s, 3)
        if chat_latency_s is not None:
            event["chat_latency_s"] = round(chat_latency_s, 3)
        if ttft_s is not None:
            event["ttft_s"] = round(ttft_s, 3)

        self._write_event(event)
        self._step_metrics.append(
            _step_metric_from_event(
                event,
                phase_value=phase_value,
                metric_index=len(self._step_metrics),
            )
        )
        self._step_count += 1

    def finish(
        self,
        *,
        success: bool,
        error: str | None = None,
        token_usage: dict[str, int] | None = None,
    ) -> Path:
        """Finalize recording. Returns the trajectory file path."""
        if self._closed:
            raise RuntimeError("Recorder already closed")

        duration = time.time() - self._start_time
        event: dict[str, Any] = {
            "type": "result",
            "success": success,
            "total_steps": self._step_count,
            "duration_s": round(duration, 2),
            "final_phase": self._current_phase.value,
            "error": error,
        }
        if token_usage:
            event["token_usage"] = token_usage
        self._write_event(event)
        self._write_metrics(
            success=success,
            duration_s=round(duration, 2),
            error=error,
            token_usage=token_usage,
        )
        self._closed = True
        return self._path  # type: ignore[return-value]

    def _write_event(self, event: dict[str, Any]) -> None:
        if self._path is None:
            raise RuntimeError("Recorder not started; call start() first")
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        if self.event_callback is not None:
            self.event_callback(dict(event))

    def _write_metrics(
        self,
        *,
        success: bool,
        duration_s: float,
        error: str | None,
        token_usage: dict[str, int] | None,
    ) -> None:
        if self._metrics_path is None:
            self._metrics_path = self.output_dir / "gui_metrics.json"
        # Prefer step-level accumulated usage so totals always reflect all recorded
        # steps (including multi-attempt trajectories) even when the final result
        # returns a smaller aggregate from the last attempt.
        step_token_usage = _sum_step_token_usage(self._step_metrics)
        total_token_usage = step_token_usage or token_usage or {}
        payload = {
            "task": self.task,
            "platform": self.platform,
            "success": success,
            "total_steps": self._step_count,
            "total_recorded_steps": len(self._step_metrics),
            "duration_s": duration_s,
            "total_duration_s": duration_s,
            "error": error,
            "token_usage": total_token_usage,
            "total_token_usage": total_token_usage,
            "phase_metrics": _summarize_phase_metrics(self._step_metrics),
            "steps": self._step_metrics,
        }
        self._metrics_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _compact_observation_extra(extra: dict[str, Any]) -> dict[str, Any]:
    """Keep structured observation metadata bounded in trajectory logs."""
    compact: dict[str, Any] = {}
    for key, value in extra.items():
        if isinstance(value, list):
            compact[key] = value[:80]
        else:
            compact[key] = value
    return compact


def _step_metric_from_event(
    event: dict[str, Any],
    *,
    phase_value: str,
    metric_index: int,
) -> dict[str, Any]:
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    metric: dict[str, Any] = {
        "metric_index": metric_index,
        "event_type": event.get("type"),
        "step_index": event.get("step_index"),
        "phase": phase_value,
        "action_type": action.get("action_type"),
    }
    if event.get("type") == "skill_step":
        metric["skill_id"] = event.get("skill_id")
        metric["skill_name"] = event.get("skill_name")
        metric["skill_step_index"] = event.get("step_index")
    elif event.get("type") == "subgoal_step":
        metric["substep_index"] = event.get("substep_index")
    for key in ("token_usage", "duration_s", "chat_latency_s", "ttft_s"):
        if key in event:
            metric[key] = event[key]
    return metric


def _sum_step_token_usage(steps: list[dict[str, Any]]) -> dict[str, int]:
    total: dict[str, int] = {}
    for step in steps:
        usage = step.get("token_usage")
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, int):
                total[key] = total.get(key, 0) + value
    return total


def _summarize_phase_metrics(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_phase: dict[str, dict[str, Any]] = {}
    for step in steps:
        phase = str(step.get("phase") or "unknown")
        bucket = by_phase.setdefault(phase, {
            "step_count": 0,
            "duration_s": 0.0,
            "token_usage": {},
        })
        bucket["step_count"] += 1
        duration = step.get("duration_s")
        if isinstance(duration, (int, float)):
            bucket["duration_s"] = float(bucket["duration_s"]) + float(duration)
        usage = step.get("token_usage")
        if isinstance(usage, dict):
            target = bucket["token_usage"]
            for key, value in usage.items():
                if isinstance(value, int):
                    target[key] = target.get(key, 0) + value
    for bucket in by_phase.values():
        bucket["duration_s"] = round(float(bucket["duration_s"]), 3)
    return by_phase
