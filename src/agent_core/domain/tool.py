"""Tool domain model.

Every capability an agent can invoke — a local Python function or a tool
adapted from an MCP server — is normalized into a :class:`ToolDefinition` and
registered in the Tool Registry (Phase 2). Tools never execute directly on an
agent's request; they pass through Permission and the Action Gate first.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.action import RiskLevel


class ToolSource(StrEnum):
    PYTHON = "python"
    MCP = "mcp"
    INTERNAL = "internal"


class ToolDefinition(BaseModel):
    """A registered capability, described for both the LLM and the policy layer."""

    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    source: ToolSource = ToolSource.PYTHON
    metadata: dict[str, Any] = Field(default_factory=dict)


def adapt_handler_arguments(definition: ToolDefinition, handler: Any) -> Any:
    """Optional args the model omitted keep the handler's own Python defaults.

    The generated args schema gives optional fields an explicit ``None``
    default, so a plain-Python handler would otherwise see ``days=None``
    instead of its own ``days=1`` default. Explicit schema defaults are passed
    through unchanged. This is a domain rule about the schema contract, applied
    at the execution chokepoint for BOTH tool factories (direct and gated).
    """
    schema = definition.input_schema
    required = set(schema.get("required") or [])
    droppable = {
        name
        for name, prop in (schema.get("properties") or {}).items()
        if isinstance(prop, dict) and name not in required and "default" not in prop
    }
    if not droppable:
        return handler

    def drop(kwargs: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in kwargs.items() if not (k in droppable and v is None)}

    if asyncio.iscoroutinefunction(handler):

        async def async_wrapper(**kwargs: Any) -> Any:
            return await handler(**drop(kwargs))

        return async_wrapper

    def sync_wrapper(**kwargs: Any) -> Any:
        return handler(**drop(kwargs))

    return sync_wrapper
