"""Trace and log inspection schemas for the TUI backend."""

from typing import Any
from typing import Literal

from pydantic import BaseModel


class TraceEventSummary(BaseModel):
    """Allowlisted event fields safe for browser inspection."""

    event_id: str | None = None
    event_type: Literal[
        "metadata",
        "attempt_start",
        "attempt_result",
        "attempt_exception",
        "retry",
        "step",
        "result",
    ]
    timestamp: str | None = None
    step_index: int | None = None
    status: str | None = None
    summary: str | None = None
    success: bool | None = None
    done: bool | None = None
    retry_count: int | None = None


class TraceLogLine(BaseModel):
    """Allowlisted log fields safe for browser inspection."""

    timestamp: str | None = None
    level: str | None = None
    code: str | None = None
    message: str


class TraceInspectionResponse(BaseModel):
    """Typed trace inspection payload keyed by run id."""

    run_id: str
    status: Literal["ok", "empty", "not_found"]
    events: list[TraceEventSummary]


class LogInspectionResponse(BaseModel):
    """Typed log inspection payload keyed by run id."""

    run_id: str
    status: Literal["ok", "empty", "not_found"]
    lines: list[TraceLogLine]


class TracePlaybackStep(BaseModel):
    """Detailed per-step playback record for internal operations debugging."""

    step_index: int
    timestamp: str | None = None
    action: dict[str, Any] | None = None
    action_summary: str | None = None
    done: bool | None = None
    screenshot_path: str | None = None
    screenshot_url: str | None = None
    prompt: dict[str, Any] | None = None
    model_output: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    stability: dict[str, Any] | None = None


class TracePlaybackResponse(BaseModel):
    """Detailed playback payload keyed by run id."""

    run_id: str
    status: Literal["ok", "empty", "not_found"]
    task: str | None = None
    total_steps: int = 0
    steps: list[TracePlaybackStep]
