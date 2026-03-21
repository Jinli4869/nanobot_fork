"""Read-only runtime routes for the TUI backend."""

from fastapi import APIRouter, Depends

from nanobot.tui.dependencies import get_runtime_service
from nanobot.tui.schemas import RuntimeInspectionResponse
from nanobot.tui.services import RuntimeService

router = APIRouter()


@router.get("/runtime", response_model=RuntimeInspectionResponse)
def inspect_runtime(
    service: RuntimeService = Depends(get_runtime_service),
) -> RuntimeInspectionResponse:
    """Expose lightweight runtime state without booting agent orchestration."""

    return service.inspect_runtime()
