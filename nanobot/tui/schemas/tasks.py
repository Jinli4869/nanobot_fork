"""Task capability schemas for the TUI backend."""

from pydantic import BaseModel


class TaskContractResponse(BaseModel):
    """Read-only task capability payload."""

    name: str
    mutable: bool
    phase: int
    status: str
