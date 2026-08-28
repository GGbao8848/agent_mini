"""Tool adapters: registry entries -> LangChain tools.

A tool's JSON-schema ``input_schema`` is converted to a pydantic model so the
LLM sees typed parameters, and the handler is invoked with keyword arguments
matching that schema. v1 ships the *direct* factory (handler invoked as-is);
Phase 4 adds the gated factory that routes every invocation through
Permission + Action Gate instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from agent_core.domain.tool import ToolDefinition
from agent_core.errors.exceptions import ConfigurationError
from agent_core.registries import ToolHandler

_JSON_TYPES: dict[str, type[Any]] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}

ToolFactory = Callable[[ToolDefinition, ToolHandler | None], BaseTool]
"""Builds the executable LangChain tool for a registry entry."""


def schema_to_pydantic(tool_name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Build a pydantic args model from a tool's JSON-schema ``input_schema``."""
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}
    for prop_name, raw_prop in properties.items():
        prop = raw_prop if isinstance(raw_prop, dict) else {}
        py_type = _JSON_TYPES.get(prop.get("type", "string"), str)
        description = prop.get("description")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(description=description))
        else:
            fields[prop_name] = (
                py_type | None,
                Field(default=prop.get("default"), description=description),
            )
    return create_model(f"{tool_name}_args", **fields)


def _omit_unset_optionals(definition: ToolDefinition, handler: ToolHandler) -> ToolHandler:
    """Optional args the model omitted keep the handler's own Python defaults.

    The generated args schema gives optional fields an explicit ``None``
    default, so a plain-Python handler would otherwise see ``days=None``
    instead of its own ``days=1`` default. Explicit schema defaults are passed
    through unchanged.
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


def make_direct_tool(definition: ToolDefinition, handler: ToolHandler | None) -> BaseTool:
    """Build a LangChain tool that invokes the handler directly (no policy).

    This is the Phase 3 default; production runs must use the Action Gate
    factory instead (Phase 4) so invocations cannot bypass the policy layer.
    """
    if handler is None:
        raise ConfigurationError(
            f"Tool '{definition.name}' has no executable handler",
            details={"tool": definition.name},
        )
    handler = _omit_unset_optionals(definition, handler)
    args_model = schema_to_pydantic(definition.name, definition.input_schema)
    if asyncio.iscoroutinefunction(handler):
        return StructuredTool(
            name=definition.name,
            description=definition.description or definition.name,
            args_schema=args_model,
            coroutine=handler,
        )
    return StructuredTool(
        name=definition.name,
        description=definition.description or definition.name,
        args_schema=args_model,
        func=handler,
    )
