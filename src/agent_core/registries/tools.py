"""Tool Registry.

A tool has two halves: the :class:`ToolDefinition` metadata the LLM and policy
layer see, and an executable :data:`ToolHandler`. A definition may be
registered before its handler exists (e.g. MCP tools discovered ahead of the
server connection); invoking a handler-less tool raises.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_core.domain.tool import ToolDefinition
from agent_core.errors.exceptions import RegistryError
from agent_core.persistence.store import SqliteStore
from agent_core.registries.base import BaseRegistry

ToolHandler = Callable[..., Any]
"""Executable behind a tool; invoked with keyword arguments from the call site."""


class ToolRegistry(BaseRegistry[ToolDefinition]):
    """Tool metadata + handler store, keyed by tool name.

    Only the definition is persistable; handlers are process-local callables
    and must be re-registered by code (hydrating a registry restores tool
    metadata but leaves invocation to fail until a handler is attached — the
    same contract as MCP tools discovered ahead of their connection).
    """

    kind = "tool"
    model_cls = ToolDefinition

    def __init__(self, store: SqliteStore | None = None) -> None:
        super().__init__(store)
        self._handlers: dict[str, ToolHandler] = {}

    def key_for(self, item: ToolDefinition) -> str:
        return item.name

    def register(self, item: ToolDefinition, handler: ToolHandler | None = None) -> None:
        """Register a tool definition, optionally together with its executable."""
        super().register(item)
        if handler is not None:
            self._handlers[item.name] = handler

    def set_handler(self, tool_name: str, handler: ToolHandler) -> None:
        """Attach (or replace) the executable for an already-registered tool."""
        self.get(tool_name)
        self._handlers[tool_name] = handler

    def handler_for(self, tool_name: str) -> ToolHandler:
        """Return the executable for ``tool_name``."""
        self.get(tool_name)
        try:
            return self._handlers[tool_name]
        except KeyError:
            raise RegistryError(
                kind=self.kind, key=tool_name, detail="no executable handler registered"
            ) from None
