"""MCP SDK client: opens real sessions over stdio or streamable HTTP.

The rest of Agent Core depends only on the narrow :class:`MCPSession`
protocol, so tests substitute fakes and future transports can be added
without touching the manager.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from agent_core.domain.action import RiskLevel
from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import ToolError


class MCPSession(Protocol):
    """Narrow view of a live MCP connection, normalized for Agent Core."""

    async def list_tools(self) -> list[ToolDefinition]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...


def tool_name_for_server(server_id: str, tool_name: str) -> str:
    """Namespace an MCP tool into the flat Tool Registry."""
    return f"{server_id}_{tool_name}"


def to_tool_definition(server_id: str, tool: Any) -> ToolDefinition:
    """Normalize an MCP tool descriptor into a registry :class:`ToolDefinition`."""
    return ToolDefinition(
        name=tool_name_for_server(server_id, tool.name),
        description=tool.description or "",
        input_schema=tool.input_schema or {},
        source=ToolSource.MCP,
        # MCP tools are remote code: label them MEDIUM so operators consciously
        # lower the risk via agent permission rules rather than by default.
        risk_level=RiskLevel.MEDIUM,
        metadata={"mcp_server": server_id, "mcp_tool": tool.name},
    )


@asynccontextmanager
async def open_sdk_session(
    definition: MCPServerDefinition, credential: str | None
) -> AsyncIterator[MCPSession]:
    """Open a real MCP session for ``definition``.

    stdio: the credential (if any) is injected as the environment variable
    named by ``auth_ref`` for the server process. streamable_http: it is sent
    as an ``Authorization: Bearer`` header.
    """
    if definition.transport is MCPTransport.STDIO:
        command = shlex.split(definition.endpoint)
        env = _stdio_env(definition, credential)
        async with stdio_client(
            StdioServerParameters(command=command[0], args=command[1:], env=env)
        ) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            yield _SdkSession(definition.id, session)
    else:
        # mcp 2.x takes a pre-configured http client for auth headers; we own
        # and close it, so it wraps outermost in the context stack.
        http_client = create_mcp_http_client(headers=_http_headers(definition, credential))
        async with http_client, streamable_http_client(
            definition.endpoint, http_client=http_client
        ) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            yield _SdkSession(definition.id, session)


def _bearer_headers(credential: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {credential}"} if credential else {}


def _http_headers(definition: MCPServerDefinition, credential: str | None) -> dict[str, str]:
    """Authorization for http transports: imported headers + optional credential."""
    headers = dict(definition.metadata.get("headers") or {})
    if credential and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {credential}"
    return headers


def _stdio_env(definition: MCPServerDefinition, credential: str | None) -> dict[str, str]:
    """Process environment for stdio servers: host env + auth_ref + imported env."""
    env = dict(os.environ)
    if credential and definition.auth_ref:
        env[definition.auth_ref] = credential
    env.update(definition.metadata.get("env") or {})
    return env


class _SdkSession:
    """Adapter from the raw SDK session to the :class:`MCPSession` protocol."""

    def __init__(self, server_id: str, session: ClientSession) -> None:
        self._server_id = server_id
        self._session = session

    async def list_tools(self) -> list[ToolDefinition]:
        result = await self._session.list_tools()
        return [to_tool_definition(self._server_id, tool) for tool in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._session.call_tool(name, arguments)
        if result.is_error:
            raise ToolError(
                f"MCP tool '{name}' returned an error: {_result_text(result)}",
                details={"tool": name},
            )
        return _result_text(result)


def _result_text(result: Any) -> str:
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)
