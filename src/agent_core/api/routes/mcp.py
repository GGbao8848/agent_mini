"""MCP server registry and connection lifecycle endpoints.

Connection failures surface as 503 (MCPUnavailableError is retryable); the
definition carries only an ``auth_ref`` — credentials are resolved from the
environment at connect time and never cross the API.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import MCPServerCreateRequest, MCPServerOut
from agent_core.domain.mcp import MCPServerDefinition, MCPServerStatus
from agent_core.errors.exceptions import AgentError

router = APIRouter(prefix="/mcp/servers", tags=["mcp"])


@router.get("", response_model=list[MCPServerOut])
def list_servers(service: ServiceDep) -> list[MCPServerOut]:
    return [MCPServerOut.of(definition) for definition in service.list_servers()]


@router.post("", response_model=MCPServerOut, status_code=201)
async def register_server(payload: MCPServerCreateRequest, service: ServiceDep) -> MCPServerOut:
    definition = MCPServerDefinition(**payload.model_dump())
    return MCPServerOut.of(service.register_server(definition))


@router.delete("/{server_id}", response_model=MCPServerOut)
async def remove_server(server_id: str, service: ServiceDep) -> MCPServerOut:
    """Remove a server definition, best-effort disconnecting it first.

    A stale "healthy" status (persisted by a previous process) must not block
    deletion — a live connection is closed, a stale one is simply cleared.
    """
    definition = service.mcp_registry.get(server_id)
    if definition.status.value == "healthy":
        with contextlib.suppress(AgentError):
            await service.disconnect_server(server_id)
    definition = service.mcp_registry.get(server_id)
    definition.status = MCPServerStatus.UNKNOWN
    return MCPServerOut.of(service.mcp_registry.remove(server_id))


@router.get("/{server_id}", response_model=MCPServerOut)
def get_server(server_id: str, service: ServiceDep) -> MCPServerOut:
    return MCPServerOut.of(service.mcp_registry.get(server_id))


@router.post("/{server_id}/connect", response_model=MCPServerOut)
async def connect_server(server_id: str, service: ServiceDep) -> MCPServerOut:
    await service.connect_server(server_id)
    return MCPServerOut.of(service.mcp_registry.get(server_id))


@router.post("/{server_id}/disconnect", response_model=MCPServerOut)
async def disconnect_server(server_id: str, service: ServiceDep) -> MCPServerOut:
    await service.disconnect_server(server_id)
    return MCPServerOut.of(service.mcp_registry.get(server_id))
