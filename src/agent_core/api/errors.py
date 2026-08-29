"""Single funnel from domain errors to HTTP error responses.

Routes raise domain errors freely; the registered handler turns any
:class:`AgentError` into ``{"error": {code, message, retryable, details}}``
with a status that reflects the failure class. The ``retryable`` flag reaches
the client so callers can decide between backoff-and-retry and give-up
without parsing messages.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_core.errors.exceptions import (
    AgentError,
    ApprovalError,
    ConfigurationError,
    MCPUnavailableError,
    PermissionDeniedError,
    RegistryError,
    RunTimeoutError,
    SkillError,
    StateError,
    ToolInvalidArgumentsError,
    ToolTimeoutError,
)

_NOT_FOUND = "not found"


def status_for(exc: AgentError) -> int:
    """HTTP status that best matches the domain failure class."""
    if isinstance(exc, (ToolInvalidArgumentsError, SkillError)):
        return 400
    if isinstance(exc, PermissionDeniedError):
        return 403
    if isinstance(exc, RegistryError):
        return 404 if _NOT_FOUND in exc.message else 409
    if isinstance(exc, (ApprovalError, StateError)):
        return 409
    if isinstance(exc, (MCPUnavailableError, ToolTimeoutError, RunTimeoutError)):
        return 503 if isinstance(exc, MCPUnavailableError) else 504
    if isinstance(exc, ConfigurationError):
        return 500
    return 500


def error_payload(exc: AgentError) -> dict[str, Any]:
    return {
        "error": {
            "code": type(exc).__name__,
            "message": exc.message,
            "retryable": exc.retryable,
            "details": exc.details,
        }
    }


async def _handle_agent_error(request: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, AgentError) else AgentError(str(exc))
    return JSONResponse(status_code=status_for(error), content=error_payload(error))


def register_error_handlers(app: FastAPI) -> None:
    """Register the handler; Starlette matches it against the exception MRO."""
    app.add_exception_handler(AgentError, _handle_agent_error)
