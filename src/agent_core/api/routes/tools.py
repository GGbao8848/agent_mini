"""Tool registry endpoints (read-only; MCP tools appear here once connected)."""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import ToolOut

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolOut])
def list_tools(service: ServiceDep) -> list[ToolOut]:
    return [ToolOut.of(definition) for definition in service.runtime.tools.list()]
