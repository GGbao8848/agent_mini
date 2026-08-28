"""Request-scoped access to the application service."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from agent_core.application.service import AgentCoreService


def get_service(request: Request) -> AgentCoreService:
    """Return the service wired into ``app.state`` by :func:`create_app`."""
    service: AgentCoreService = request.app.state.service
    return service


ServiceDep = Annotated[AgentCoreService, Depends(get_service)]
