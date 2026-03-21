"""Read-only runtime services for the TUI backend."""

from nanobot.tui.contracts import RuntimeInspectionContract
from nanobot.tui.schemas import RuntimeInspectionResponse


class RuntimeService:
    """Adapter-backed runtime inspector for browser-facing routes."""

    def __init__(self, contract: RuntimeInspectionContract):
        self._contract = contract

    def inspect_runtime(self) -> RuntimeInspectionResponse:
        return RuntimeInspectionResponse.model_validate(self._contract.inspect_runtime())
