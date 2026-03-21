"""FastAPI app factory for the isolated TUI backend."""

from fastapi import FastAPI

from nanobot.config.schema import Config
from nanobot.tui.routes import (
    health_router,
    runtime_router,
    sessions_router,
    tasks_router,
)


def create_app(
    *,
    config: Config | None = None,
    include_runtime_routes: bool = False,
) -> FastAPI:
    """Create the Phase 17 TUI backend app without booting the CLI runtime."""

    app = FastAPI(
        title="nanobot tui",
        version="0.1.0",
    )
    if config is not None:
        app.state.nanobot_config = config
    app.include_router(health_router)
    if include_runtime_routes:
        app.include_router(sessions_router)
        app.include_router(runtime_router)
        app.include_router(tasks_router)
    return app
