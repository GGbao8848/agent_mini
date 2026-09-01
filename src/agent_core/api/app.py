"""FastAPI application factory.

Wires the :class:`AgentCoreService` into ``app.state`` (pass your own service
to :func:`create_app` to reuse the routers with a different composition),
registers the domain-error handler, and mounts every router under ``/v1``.
Run it with::

    uvicorn agent_core.api.app:app
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agent_core.api import errors
from agent_core.api.routes import api_router
from agent_core.application.bootstrap import default_service
from agent_core.application.service import AgentCoreService
from agent_core.config.settings import get_settings

_CONSOLE_DIR = Path(__file__).parent / "console"


def create_app(service: AgentCoreService | None = None) -> FastAPI:
    """Build the app around ``service`` (a default one when omitted)."""
    core = service or default_service()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if core.schedules is not None:
            core.schedules.start()
        # Restored MCP servers have no live connection (connections are
        # process-local). Reconnect them best-effort so tools are ready for
        # the first run instead of the console requiring a manual click.
        # A server that fails to connect stays UNREACHABLE and can be retried
        # from the console; the API must come up regardless.
        with contextlib.suppress(Exception):
            await core.mcp.auto_connect_all()
        try:
            yield
        finally:
            if core.schedules is not None:
                core.schedules.stop()
            await core.mcp.disconnect_all()
            if core.store is not None:
                core.store.close()

    app = FastAPI(
        title="Agent Core",
        description="Minimal, decoupled, evolvable multi-agent runtime.",
        version="0.1.0",
        lifespan=lifespan,
    )

    token = get_settings().console_token
    if token:

        @app.middleware("http")
        async def console_token_guard(request: Any, call_next: Any) -> Any:
            # Only the API is gated: the console page itself carries no
            # secrets, and it must load so the browser can collect the token.
            if request.url.path.startswith("/v1"):
                provided = request.headers.get("X-Console-Token") or request.query_params.get(
                    "token"
                )
                if provided != token:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": {
                                "code": "unauthorized",
                                "message": "missing or invalid console token",
                                "retryable": False,
                            }
                        },
                    )
            return await call_next(request)

    app.mount("/console", StaticFiles(directory=_CONSOLE_DIR, html=True), name="console")
    app.state.service = core
    errors.register_error_handlers(app)
    app.include_router(api_router, prefix="/v1")

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
