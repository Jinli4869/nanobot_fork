"""Trace and log inspection routes for the TUI backend."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from nanobot.tui.dependencies import get_trace_inspection_service
from nanobot.tui.schemas import (
    LogInspectionResponse,
    TraceInspectionResponse,
    TracePlaybackResponse,
)
from nanobot.tui.services import TraceInspectionService

router = APIRouter()


@router.get("/runtime/runs/{run_id}/trace", response_model=TraceInspectionResponse)
def inspect_trace(
    run_id: str,
    service: TraceInspectionService = Depends(get_trace_inspection_service),
) -> TraceInspectionResponse:
    """Expose filtered trace events for one run id."""

    return service.inspect_trace(run_id)


@router.get("/runtime/runs/{run_id}/logs", response_model=LogInspectionResponse)
def inspect_logs(
    run_id: str,
    service: TraceInspectionService = Depends(get_trace_inspection_service),
) -> LogInspectionResponse:
    """Expose filtered log lines for one run id."""

    return service.inspect_logs(run_id)


@router.get("/runtime/runs/{run_id}/trace-playback", response_model=TracePlaybackResponse)
def inspect_trace_playback(
    run_id: str,
    service: TraceInspectionService = Depends(get_trace_inspection_service),
) -> TracePlaybackResponse:
    """Expose detailed step playback data for one run id."""

    return service.inspect_playback(run_id)


@router.get("/runtime/runs/{run_id}/screenshots/{filename}")
def get_run_screenshot(
    run_id: str,
    filename: str,
    service: TraceInspectionService = Depends(get_trace_inspection_service),
) -> FileResponse:
    """Serve a step screenshot for operations playback."""

    screenshot_path = service.resolve_screenshot_path(run_id, filename)
    if screenshot_path is None:
        raise HTTPException(status_code=404, detail="screenshot_not_found")
    return FileResponse(screenshot_path)
