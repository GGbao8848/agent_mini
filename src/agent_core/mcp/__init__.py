"""MCP integration: client, connection lifecycle, tool adaptation."""

from agent_core.mcp.client import MCPSession, open_sdk_session, to_tool_definition
from agent_core.mcp.connection import MCPConnection, SessionOpener
from agent_core.mcp.credentials import CredentialResolver, EnvCredentialResolver
from agent_core.mcp.manager import MCPManager

__all__ = [
    "CredentialResolver",
    "EnvCredentialResolver",
    "MCPConnection",
    "MCPManager",
    "MCPSession",
    "SessionOpener",
    "open_sdk_session",
    "to_tool_definition",
]
