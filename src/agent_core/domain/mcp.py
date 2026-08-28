"""MCP server domain model.

Agent Core does not redefine the MCP protocol. It keeps a local/enterprise
registry of MCP server definitions (connection metadata, status, ownership)
and adapts their tools into the unified Tool Registry. Secrets are never
stored here — ``auth_ref`` points at a credential managed by the credential
layer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MCPTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class MCPServerStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"


class MCPServerDefinition(BaseModel):
    """Connection and metadata for one MCP server."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    transport: MCPTransport
    endpoint: str = Field(
        default="",
        description="URL for streamable_http transport; command line for stdio transport",
    )
    auth_ref: str | None = Field(
        default=None,
        description="Reference to credentials in the credential layer; never a secret itself",
    )
    status: MCPServerStatus = MCPServerStatus.UNKNOWN
    metadata: dict[str, Any] = Field(default_factory=dict)
