"""Route modules for the TUI backend."""

from nanobot.tui.routes.health import router as health_router
from nanobot.tui.routes.runtime import router as runtime_router
from nanobot.tui.routes.sessions import router as sessions_router
from nanobot.tui.routes.tasks import router as tasks_router

__all__ = [
    "health_router",
    "runtime_router",
    "sessions_router",
    "tasks_router",
]
