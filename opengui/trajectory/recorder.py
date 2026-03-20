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
from typing import Any


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

    _path: Path | None = field(default=None, init=False, repr=False)
    _step_count: int = field(default=0, init=False, repr=False)
    _start_time: float = field(default=0.0, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _current_phase: ExecutionPhase = field(default=ExecutionPhase.AGENT, init=False, repr=False)

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def step_count(self) -> int:
        return self._step_count

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
        self._write_event({
            "type": event_type,
            "timestamp": time.time(),
            "at_step": self._step_count,
            **payload,
        })

    def record_step(
        self,
        *,
        action: dict[str, Any],
        model_output: str = "",
        screenshot_path: str | None = None,
        observation: dict[str, Any] | None = None,
        prompt: dict[str, Any] | None = None,
        model_response: dict[str, Any] | None = None,
        execution: dict[str, Any] | None = None,
        phase: ExecutionPhase | None = None,
        skill_id: str | None = None,
        skill_step_index: int | None = None,
    ) -> None:
        """Record one agent step.

        Parameters
        ----------
        action:
            Action dict (action_type, x, y, text, etc.).
        model_output:
            Raw model assistant text for this step.
        screenshot_path:
            Path to the screenshot taken before this step.
        observation:
            Observation metadata dict.
        prompt:
            Serialized prompt snapshot, including message window and history context.
        model_response:
            Serialized LLM output for this step.
        execution:
            Serialized backend execution result and follow-up observation.
        phase:
            Override current phase for this step.
        skill_id:
            If executing a skill, the skill's ID.
        skill_step_index:
            If executing a skill, the step index within the skill.
        """
        if self._closed:
            raise RuntimeError("Recorder already closed")

        event: dict[str, Any] = {
            "type": "step",
            "step_index": self._step_count,
            "phase": (phase or self._current_phase).value,
            "timestamp": time.time(),
            "action": action,
            "model_output": model_output,
            "screenshot_path": screenshot_path,
            "observation": observation,
        }
        if prompt is not None:
            event["prompt"] = prompt
        if model_response is not None:
            event["model_response"] = model_response
        if execution is not None:
            event["execution"] = execution
        if skill_id is not None:
            event["skill_id"] = skill_id
        if skill_step_index is not None:
            event["skill_step_index"] = skill_step_index

        self._write_event(event)
        self._step_count += 1

    def finish(self, *, success: bool, error: str | None = None) -> Path:
        """Finalize recording. Returns the trajectory file path."""
        if self._closed:
            raise RuntimeError("Recorder already closed")

        duration = time.time() - self._start_time
        self._write_event({
            "type": "result",
            "success": success,
            "total_steps": self._step_count,
            "duration_s": round(duration, 2),
            "final_phase": self._current_phase.value,
            "error": error,
        })
        self._closed = True
        return self._path  # type: ignore[return-value]

    def _write_event(self, event: dict[str, Any]) -> None:
        if self._path is None:
            raise RuntimeError("Recorder not started; call start() first")
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
