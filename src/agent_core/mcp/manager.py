"""MCPManager: connect/disconnect registered servers and adapt their tools.

Tools discovered from a server are registered in the flat Tool Registry under
``{server_id}_{tool}`` names, with an executable handler that calls the live
session — so they pass through the same Action Gate as every other tool.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.mcp import MCPServerStatus
from agent_core.domain.tool import ToolDefinition
from agent_core.errors.exceptions import MCPUnavailableError, RegistryError
from agent_core.mcp.client import open_sdk_session
from agent_core.mcp.connection import MCPConnection, SessionOpener
from agent_core.mcp.credentials import CredentialResolver
from agent_core.registries import MCPRegistry, ToolHandler, ToolRegistry


class MCPManager:
    """Owns the live-connection lifecycle for the MCP Registry."""

    def __init__(
        self,
        registry: MCPRegistry,
        tools: ToolRegistry,
        *,
        credentials: CredentialResolver | None = None,
        opener: SessionOpener = open_sdk_session,
    ) -> None:
        self._registry = registry
        self._tools = tools
        self._credentials = credentials
        self._opener = opener
        self._connections: dict[str, MCPConnection] = {}
        self._registered: dict[str, list[str]] = {}

    def connection(self, server_id: str) -> MCPConnection:
        """Return the live connection for ``server_id``."""
        try:
            return self._connections[server_id]
        except KeyError:
            raise RegistryError(
                kind="mcp-connection", key=server_id, detail="not connected"
            ) from None

    def is_connected(self, server_id: str) -> bool:
        return server_id in self._connections

    async def connect(self, server_id: str) -> list[str]:
        """Connect ``server_id`` and register its tools; returns the tool names."""
        definition = self._registry.get(server_id)
        if server_id in self._connections:
            raise RegistryError(
                kind="mcp-connection", key=server_id, detail="already connected"
            )
        credential = (
            self._credentials.resolve(definition.auth_ref)
            if self._credentials is not None and definition.auth_ref is not None
            else None
        )
        connection = MCPConnection(definition, credential=credential, opener=self._opener)
        try:
            session = await connection.start()
            discovered = await session.list_tools()
        except Exception as exc:
            await connection.close()
            self._registry.set_status(server_id, MCPServerStatus.UNREACHABLE)
            raise MCPUnavailableError(server_id, str(exc)) from exc

        self._connections[server_id] = connection
        self._registry.set_status(server_id, MCPServerStatus.HEALTHY)
        names: list[str] = []
        for tool_definition in discovered:
            self._tools.register(
                tool_definition, handler=self._make_handler(server_id, tool_definition)
            )
            names.append(tool_definition.name)
        self._registered[server_id] = names
        return names

    async def disconnect(self, server_id: str) -> None:
        """Close the connection and unregister the server's tools."""
        connection = self._connections.pop(server_id, None)
        if connection is None:
            raise RegistryError(
                kind="mcp-connection", key=server_id, detail="not connected"
            )
        for name in self._registered.pop(server_id, []):
            self._tools.remove(name)
        await connection.close()
        self._registry.set_status(server_id, MCPServerStatus.UNKNOWN)

    async def disconnect_all(self) -> None:
        """Disconnect every live server (process shutdown)."""
        for server_id in list(self._connections):
            await self.disconnect(server_id)

    def _make_handler(self, server_id: str, tool_definition: ToolDefinition) -> ToolHandler:
        mcp_tool = tool_definition.metadata["mcp_tool"]

        async def handler(**kwargs: Any) -> str:
            connection = self._connections.get(server_id)
            if connection is None or connection.session is None:
                raise MCPUnavailableError(server_id, "not connected")
            return await connection.session.call_tool(mcp_tool, kwargs)

        return handler
