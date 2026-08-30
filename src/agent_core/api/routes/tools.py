"""Tool registry endpoints.

``GET /tools`` lists every registered tool with its availability state
(built-ins expose a config-driven ``available`` flag; MCP tools appear here
once connected). ``POST /tools/reload`` re-runs built-in registration so the
availability flags reflect the current configuration.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import ToolOut
from agent_core.builtins import register_builtin_tools
from agent_core.config.settings import get_settings

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolOut])
def list_tools(service: ServiceDep) -> list[ToolOut]:
    return [ToolOut.of(definition) for definition in service.runtime.tools.list()]


@router.post("/reload", response_model=list[ToolOut])
def reload_tools(service: ServiceDep) -> list[ToolOut]:
    """Re-register built-in tools and recompute availability from settings."""
    register_builtin_tools(service.runtime.tools, get_settings())
    return [ToolOut.of(definition) for definition in service.runtime.tools.list()]
