"""FastAPI application factory.

Wires the :class:`AgentCoreService` into ``app.state`` (pass your own service
to :func:`create_app` to reuse the routers with a different composition),
registers the domain-error handler, and mounts every router under ``/v1``.
Run it with::

    uvicorn agent_core.api.app:app
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_core.api import errors
from agent_core.api.routes import api_router
from agent_core.application.bootstrap import default_service
from agent_core.application.service import AgentCoreService


def create_app(service: AgentCoreService | None = None) -> FastAPI:
    """Build the app around ``service`` (a default one when omitted)."""
    core = service or default_service()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await core.mcp.disconnect_all()

    app = FastAPI(
        title="Agent Core",
        description="Minimal, decoupled, evolvable multi-agent runtime.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.service = core
    errors.register_error_handlers(app)
    app.include_router(api_router, prefix="/v1")

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
