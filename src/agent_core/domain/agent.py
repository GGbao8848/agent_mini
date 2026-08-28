"""Agent domain model.

An :class:`AgentSpec` is pure data describing *what* an agent is (model,
prompt, capabilities, limits). It is never a live runtime object — business
code resolves agents through the Agent Registry (Phase 2), never by importing
an instance.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.permission import PermissionSpec


class SubAgentRef(BaseModel):
    """Declarative reference to a sub-agent, resolved via the Agent Registry."""

    agent_id: str = Field(min_length=1)
    description: str = ""
    max_depth: int = Field(default=1, ge=1, description="Delegation depth below this sub-agent")
    timeout_seconds: float | None = Field(default=None, gt=0)


class AgentLimits(BaseModel):
    """Guardrails preventing unbounded agent recursion and runaway runs."""

    max_depth: int = Field(default=2, ge=1, description="Maximum sub-agent delegation depth")
    max_subagents: int = Field(default=8, ge=1)
    timeout_seconds: float = Field(default=600.0, gt=0)
    token_budget: int | None = Field(default=None, gt=0)


class AgentSpec(BaseModel):
    """Complete declarative definition of one agent."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    model: str | None = None
    system_prompt: str = ""
    skills: list[str] = Field(default_factory=list, description="Skill ids to load")
    tools: list[str] = Field(default_factory=list, description="Tool ids/names to expose")
    subagents: list[SubAgentRef] = Field(default_factory=list)
    permissions: PermissionSpec | None = None
    limits: AgentLimits = Field(default_factory=AgentLimits)
    metadata: dict[str, Any] = Field(default_factory=dict)
