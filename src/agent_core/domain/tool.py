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


# ---------------------------------------------------------------------------
# Schema compaction (R20 §10: keep the fixed per-request tool cost bounded).
#
# Tool schemas enter EVERY model call, so a verbose description is not a
# one-time cost — it is paid on every reasoning step. Real MCP servers ship
# tool descriptions in the thousands of characters and property docs in the
# hundreds (one TinyFish parameter carried a 1080-char description), which is
# pure fixed overhead the model wades through before it starts working.
#
# These helpers trim the *presentation* only. Types, required lists, enums,
# defaults and nested structure are preserved exactly, so how a tool is called
# never changes — only how much prose describes it.
# ---------------------------------------------------------------------------

_DECORATION_KEYS = frozenset({"example", "examples", "$schema", "$id", "title", "$comment"})
"""JSON-schema keys that cost tokens but carry no calling information."""


def _truncate(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars, marking the cut so it is not silent."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def compact_json_schema(schema: Any, *, description_limit: int) -> Any:
    """Recursively drop schema decorations and trim long descriptions.

    Preserves every key that affects how a tool is called (``type``,
    ``properties``, ``required``, ``enum``, ``default``, ``items``, …); only
    removals are ``_DECORATION_KEYS`` and over-long description strings.
    """
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key, value in schema.items():
            if key in _DECORATION_KEYS:
                continue
            if key == "description" and isinstance(value, str):
                out[key] = _truncate(value, description_limit)
            else:
                out[key] = compact_json_schema(value, description_limit=description_limit)
        return out
    if isinstance(schema, list):
        return [compact_json_schema(item, description_limit=description_limit) for item in schema]
    return schema


def compact_definition(
    definition: ToolDefinition,
    *,
    tool_description_limit: int = 0,
    param_description_limit: int = 0,
) -> ToolDefinition:
    """Return ``definition`` with its model-facing prose trimmed.

    A limit of ``0`` leaves that dimension untouched. Name, risk level, source
    and metadata are copied through unchanged — this only bounds the text the
    model reads.
    """
    if tool_description_limit <= 0 and param_description_limit <= 0:
        return definition
    return definition.model_copy(
        update={
            "description": _truncate(definition.description, tool_description_limit),
            "input_schema": compact_json_schema(
                definition.input_schema, description_limit=param_description_limit
            ),
        }
    )

