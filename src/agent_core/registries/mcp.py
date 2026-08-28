"""MCP Registry: known MCP server definitions and their connection status."""

from __future__ import annotations

from agent_core.domain.mcp import MCPServerDefinition, MCPServerStatus
from agent_core.registries.base import BaseRegistry


class MCPRegistry(BaseRegistry[MCPServerDefinition]):
    """Catalog of MCP servers this deployment can connect to."""

    kind = "mcp-server"

    def key_for(self, item: MCPServerDefinition) -> str:
        return item.id

    def set_status(self, server_id: str, status: MCPServerStatus) -> MCPServerDefinition:
        """Record a connection-status change (driven by the MCP client layer)."""
        server = self.get(server_id)
        server.status = status
        return server
