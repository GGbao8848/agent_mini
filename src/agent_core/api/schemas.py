"""HTTP request/response DTOs.

Deliberately separate from the domain models: the wire contract evolves
independently of the domain, and fields that must not leak (or need
reshaping) stay behind these adapters. Response models read domain objects
via ``from_attributes``; requests validate before anything reaches the
application layer.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.action import ApprovalRequest
from agent_core.domain.agent import AgentSpec
from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
from agent_core.domain.schedule import Schedule, ScheduleType
from agent_core.domain.skill import SkillManifest
from agent_core.domain.task import Run, Task, Turn
from agent_core.domain.tool import ToolDefinition
from agent_core.domain.trace import TraceEvent
from agent_core.errors.exceptions import SkillError

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


class TaskCreateRequest(BaseModel):
    agent_id: str | None = Field(
        default=None,
        description="Agent to run; defaults to the default (first registered) agent",
    )
    input: str = Field(min_length=1, description="Task input, e.g. the user's question")


class TaskMessageRequest(BaseModel):
    input: str = Field(min_length=1)


class TaskUpdateRequest(BaseModel):
    """Editable task fields (rename, pin); omitted fields keep values."""

    title: str | None = Field(default=None, min_length=1)
    pinned: bool | None = None


class TurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    created_at: Any
    metadata: dict[str, Any]

    @classmethod
    def of(cls, turn: Turn) -> TurnOut:
        return cls.model_validate(turn)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    title: str
    thread_id: str | None
    turns: list[TurnOut]
    status: str
    active_run_id: str | None
    created_at: Any
    pinned: bool = False
    metadata: dict[str, Any]

    @classmethod
    def of(cls, task: Task, *, status: str, active_run_id: str | None) -> TaskOut:
        return cls(
            id=task.id,
            agent_id=task.agent_id,
            title=task.title,
            thread_id=task.thread_id,
            turns=[TurnOut.of(turn) for turn in task.turns],
            status=status,
            active_run_id=active_run_id,
            created_at=task.created_at,
            pinned=task.pinned,
            metadata=task.metadata,
        )


class ScheduleBase(BaseModel):
    name: str = Field(min_length=1)
    task_input: str = Field(min_length=1)
    schedule_type: ScheduleType
    run_at: datetime | None = None
    cron_expr: str | None = None
    interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool = True


class ScheduleCreateRequest(ScheduleBase):
    pass


class ScheduleUpdateRequest(ScheduleBase):
    pass


class ScheduleOut(BaseModel):
    id: str
    name: str
    agent_id: str
    task_input: str
    schedule_type: str
    run_at: Any | None = None
    cron_expr: str | None = None
    interval_minutes: int | None = None
    enabled: bool
    created_at: Any
    last_run_at: Any | None = None
    next_run_at: Any | None = None
    last_task_id: str | None = None
    run_count: int
    trigger_text: str
    metadata: dict[str, Any]

    @classmethod
    def of(cls, schedule: Schedule) -> ScheduleOut:
        return cls(
            id=schedule.id,
            name=schedule.name,
            agent_id=schedule.agent_id,
            task_input=schedule.task_input,
            schedule_type=schedule.schedule_type,
            run_at=schedule.run_at,
            cron_expr=schedule.cron_expr,
            interval_minutes=schedule.interval_minutes,
            enabled=schedule.enabled,
            created_at=schedule.created_at,
            last_run_at=schedule.last_run_at,
            next_run_at=schedule.next_run_at,
            last_task_id=schedule.last_task_id,
            run_count=schedule.run_count,
            trigger_text=schedule.describe_trigger(),
            metadata=schedule.metadata,
        )


class ScheduleRunOut(BaseModel):
    schedule_id: str
    task_id: str


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


class AgentUpdateRequest(BaseModel):
    """Editable agent fields (tool binding); omitted fields keep values.

    Skills are not editable — every registered skill is loaded for every
    agent, so there is no per-agent skill list to set.
    """

    tools: list[str] | None = None


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
    available: bool = True
    availability_reason: str = ""

    @classmethod
    def of(cls, definition: ToolDefinition) -> ToolOut:
        metadata = definition.metadata or {}
        available = metadata.get("available", True)
        return cls(
            name=definition.name,
            description=definition.description,
            input_schema=definition.input_schema,
            risk_level=definition.risk_level.value,
            source=definition.source.value,
            metadata=metadata,
            available=bool(available),
            availability_reason=str(metadata.get("availability_reason", "")),
        )


class SkillCreateRequest(BaseModel):
    """Install a skill from a server-side directory containing SKILL.md."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    path: str = Field(min_length=1, description="Server-side skill directory")

    def validate_directory(self) -> Path:
        directory = Path(self.path).expanduser().resolve()
        if not directory.is_dir():
            raise SkillError(
                f"Skill directory does not exist: {directory}",
                details={"skill": self.id, "path": str(directory)},
            )
        if not (directory / "SKILL.md").is_file():
            raise SkillError(
                f"'{directory}' is not a skill directory (missing SKILL.md)",
                details={"skill": self.id, "path": str(directory)},
            )
        return directory


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
    """Registration payload; secrets are referenced, never sent.

    ``metadata`` carries per-server connection extras: ``headers`` for http
    transports, ``env`` for stdio processes (imported from standard
    mcpServers configs).
    """

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    transport: MCPTransport
    endpoint: str = ""
    auth_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
