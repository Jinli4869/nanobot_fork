"""Runtime inspection schemas for the TUI backend."""

from pydantic import BaseModel


class RuntimeInspectionResponse(BaseModel):
    """Read-only runtime state returned to the browser."""

    status: str
    channel_runtime_booted: bool
    agent_loop_booted: bool
    task_launch_available: bool
