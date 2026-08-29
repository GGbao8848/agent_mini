"""HTTP request/response DTOs.

Deliberately separate from the domain models: the wire contract evolves
independently of the domain, and fields that must not leak (or need
reshaping) stay behind these adapters. Response models read domain objects
via ``from_attributes``; requests validate before anything reaches the
application layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.action import ApprovalRequest
from agent_core.domain.agent import AgentSpec
from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
from agent_core.domain.skill import SkillManifest
from agent_core.domain.task import Run
from agent_core.domain.tool import ToolDefinition
from agent_core.domain.trace import TraceEvent

# Human decisions accepted by POST /approvals/{id}/resolve.
ApprovalDecision = Literal["approved", "rejected", "edited", "cancelled"]


class RunCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    input: str = Field(min_length=1, description="Task input, e.g. the user's question")
    parent_run_id: str | None = None


class RunUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    input_tokens: int
    output_tokens: int
    total_tokens: int
    model_calls: int
    tool_calls: int
    duration_ms: float | None


class RunMessageRequest(BaseModel):
    input: str = Field(min_length=1)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    agent_id: str
    parent_run_id: str | None
    thread_id: str | None = None
    status: str
    created_at: Any
    finished_at: Any
    error: str | None
    metadata: dict[str, Any]
    usage: RunUsageOut | None
    # Not on the domain model: filled by the routes layer.
    output: Any | None = None
    input: str = ""

    @classmethod
    def of(cls, run: Run, output: Any | None = None, input: str = "") -> RunOut:
        data = run.model_dump()
        data["output"] = output
        data["input"] = input
        return cls.model_validate(data)


class ApprovalResolveRequest(BaseModel):
    decision: ApprovalDecision
    resolved_by: str = Field(default="user", min_length=1)
    edited_arguments: dict[str, Any] | None = None
    # Human's answer for task-help requests; fed back to the agent as guidance.
    note: str | None = None

    @model_validator(mode="after")
    def _edited_requires_arguments(self) -> ApprovalResolveRequest:
        if self.decision == "edited" and self.edited_arguments is None:
            raise ValueError("decision 'edited' requires 'edited_arguments'")
        return self


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    agent_id: str
    kind: str
    action_id: str | None
    tool_name: str | None
    arguments: dict[str, Any]
    risk_level: str
    question: str
    reason: str
    status: str
    created_at: Any
    resolved_at: Any
    resolved_by: str | None
    edited_arguments: dict[str, Any] | None
    resolved_note: str | None

    @classmethod
    def of(cls, request: ApprovalRequest) -> ApprovalOut:
        return cls.model_validate(request)


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    model: str | None
    system_prompt: str
    skills: list[str]
    tools: list[str]
    subagents: list[Any]
    permissions: Any | None
    limits: Any
    metadata: dict[str, Any]

    @classmethod
    def of(cls, spec: AgentSpec) -> AgentOut:
        return cls.model_validate(spec)


class ToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: str
    source: str
    metadata: dict[str, Any]

    @classmethod
    def of(cls, definition: ToolDefinition) -> ToolOut:
        return cls.model_validate(definition)


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str
    description: str
    path: Path | None
    dependencies: list[str]
    allowed_tools: list[str]
    metadata: dict[str, str]

    @classmethod
    def of(cls, manifest: SkillManifest) -> SkillOut:
        return cls.model_validate(manifest)


class MCPServerCreateRequest(BaseModel):
    """Registration payload; secrets are referenced, never sent."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    transport: MCPTransport
    endpoint: str = ""
    auth_ref: str | None = None


class MCPServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str
    description: str
    transport: str
    endpoint: str
    auth_ref: str | None
    status: str
    metadata: dict[str, Any]

    @classmethod
    def of(cls, definition: MCPServerDefinition) -> MCPServerOut:
        return cls.model_validate(definition)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    run_id: str
    parent_run_id: str | None
    task_id: str | None
    agent_id: str | None
    timestamp: Any
    duration_ms: float | None
    input: Any | None
    output: Any | None
    tool: str | None
    status: str | None
    error: str | None
    metadata: dict[str, Any]

    @classmethod
    def of(cls, event: TraceEvent) -> EventOut:
        return cls.model_validate(event)
