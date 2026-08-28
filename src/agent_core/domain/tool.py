"""Tool domain model.

Every capability an agent can invoke — a local Python function or a tool
adapted from an MCP server — is normalized into a :class:`ToolDefinition` and
registered in the Tool Registry (Phase 2). Tools never execute directly on an
agent's request; they pass through Permission and the Action Gate first.
"""

from __future__ import annotations

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
