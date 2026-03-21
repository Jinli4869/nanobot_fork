"""Read-only task capability routes for the TUI backend."""

from fastapi import APIRouter, Depends

from nanobot.tui.dependencies import get_task_launch_service
from nanobot.tui.schemas import TaskContractResponse
from nanobot.tui.services import TaskLaunchService

router = APIRouter()


@router.get("/tasks", response_model=TaskContractResponse)
def describe_tasks(
    service: TaskLaunchService = Depends(get_task_launch_service),
) -> TaskContractResponse:
    """Expose future task-launch capability metadata without executing tasks."""

    return service.describe_capability()
