"""Read-only task capability services for the TUI backend."""

from nanobot.tui.contracts import TaskLaunchContract
from nanobot.tui.schemas import TaskContractResponse


class TaskLaunchService:
    """Adapter-backed task capability reader for browser-facing routes."""

    def __init__(self, contract: TaskLaunchContract):
        self._contract = contract

    def describe_capability(self) -> TaskContractResponse:
        return TaskContractResponse.model_validate(self._contract.describe_capability())
