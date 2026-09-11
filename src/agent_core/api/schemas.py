"""HTTP request/response DTOs.

Deliberately separate from the domain models: the wire contract evolves
independently of the domain, and fields that must not leak (or need
reshaping) stay behind these adapters. Response models read domain objects
via ``from_attributes``; requests validate before anything reaches the
application layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.capabilities.model import EffectiveCapabilitySet
from agent_core.domain.action import ApprovalRequest
from agent_core.domain.agent import AgentSpec
from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
from agent_core.domain.memory import Memory
from agent_core.domain.metrics import RunUsage
from agent_core.domain.permission_mode import PermissionMode
from agent_core.domain.project import Project
from agent_core.domain.schedule import Schedule, ScheduleType
from agent_core.domain.skill import SkillManifest
from agent_core.domain.task import Run, Task, Turn
from agent_core.domain.tool import ToolDefinition
from agent_core.domain.trace import TraceEvent
from agent_core.errors.exceptions import SkillError
from agent_core.execution.policy import ExecutionPolicy
from agent_core.task_state.domain import TaskState

if TYPE_CHECKING:
    from agent_core.config.model_config import CustomModel as CustomModelSpec

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
    last_input_tokens: int = 0
    """Input tokens of the most recent model call ≈ current context size."""
    estimated_system_tokens: int = 0
    """Heuristic: system-message tokens of the last call (context panel)."""
    estimated_messages_tokens: int = 0
    """Heuristic: history-message tokens of the last call (context panel)."""


class RunMessageRequest(BaseModel):
    input: str = Field(min_length=1)


class TaskCreateRequest(BaseModel):
    agent_id: str | None = Field(
        default=None,
        description="Agent to run; defaults to the default (first registered) agent",
    )
    input: str = Field(min_length=1, description="Task input, e.g. the user's question")
    model: str | None = Field(
        default=None,
        description="Model spec ('provider:model') for this conversation's turns",
    )
    attachments: list[str] = Field(
        default_factory=list,
        description=(
            "Optional workspace-relative paths of files uploaded with this message; "
            "the agent can read them with its file tools."
        ),
    )
    project_id: str | None = Field(
        default=None,
        description=(
            "Bind the conversation to a registered project: the agent then "
            "works directly inside the project's directory."
        ),
    )
    permission_mode: PermissionMode | None = Field(
        default=None,
        description=(
            "Autonomy dial for this conversation: confirm / auto / plan / full. "
            "Omitted means the server default (confirm)."
        ),
    )


class TaskMessageRequest(BaseModel):
    input: str = Field(min_length=1)
    model: str | None = Field(
        default=None,
        description="Model spec ('provider:model') for this turn",
    )
    attachments: list[str] = Field(
        default_factory=list,
        description=(
            "Optional workspace-relative paths of files uploaded with this message; "
            "the agent can read them with its file tools."
        ),
    )
    permission_mode: PermissionMode | None = Field(
        default=None,
        description="Change the conversation's autonomy dial for this turn onward.",
    )


class TaskUpdateRequest(BaseModel):
    """Editable task fields (rename, pin, rebind); omitted fields keep values."""

    title: str | None = Field(default=None, min_length=1)
    pinned: bool | None = None
    project_id: str | None = Field(
        default=None,
        description="Rebind to a project ('' clears the binding; None keeps it)",
    )


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
    project_id: str | None = None
    turns: list[TurnOut]
    status: str
    active_run_id: str | None
    created_at: Any
    pinned: bool = False
    has_unread: bool = False
    """A newer assistant reply exists past the human's read marker (sidebar dot)."""
    permission_mode: PermissionMode
    metadata: dict[str, Any]

    @classmethod
    def of(cls, task: Task, *, status: str, active_run_id: str | None) -> TaskOut:
        return cls(
            id=task.id,
            agent_id=task.agent_id,
            title=task.title,
            thread_id=task.thread_id,
            project_id=task.project_id,
            turns=[TurnOut.of(turn) for turn in task.turns],
            status=status,
            active_run_id=active_run_id,
            created_at=task.created_at,
            pinned=task.pinned,
            has_unread=task.has_unread,
            permission_mode=task.permission_mode,
            metadata=task.metadata,
        )


class ExecutionPolicyOut(BaseModel):
    """The code-execution envelope (R24), shown to operators."""

    mode: str
    sandbox_image: str | None = None
    filesystem_isolated: bool
    filesystem: dict[str, Any]
    network_mode: str
    network_allow: list[str]
    network_enforced: bool
    network_note: str
    env_forwarded: list[str]
    env_host_secrets_visible: bool
    memory_mb: int
    cpus: float
    pids_limit: int
    timeout_seconds: float
    timeout_max_seconds: float
    summary: dict[str, str]

    @classmethod
    def of(cls, policy: ExecutionPolicy) -> ExecutionPolicyOut:
        return cls(
            mode=policy.mode.value,
            sandbox_image=policy.sandbox_image,
            filesystem_isolated=policy.filesystem.isolated,
            filesystem=policy.filesystem.model_dump(),
            network_mode=policy.network.mode.value,
            network_allow=list(policy.network.allow),
            network_enforced=policy.network.enforced,
            network_note=policy.network.note,
            env_forwarded=list(policy.env.forwarded),
            env_host_secrets_visible=policy.env.host_secrets_visible,
            memory_mb=policy.resources.memory_mb,
            cpus=policy.resources.cpus,
            pids_limit=policy.resources.pids_limit,
            timeout_seconds=policy.resources.timeout_seconds,
            timeout_max_seconds=policy.resources.timeout_max_seconds,
            summary=policy.summary(),
        )


class CapabilityEntryOut(BaseModel):
    """One tool's effective state for an agent (R22)."""

    name: str
    description: str = ""
    source: str = "python"
    risk_level: str
    exposed: bool
    decision: str
    state: str
    reason: str = ""


class AgentCapabilitiesOut(BaseModel):
    """An agent's computed capabilities — the same set the runtime enforces."""

    agent_id: str
    notes: list[str] = Field(default_factory=list)
    entries: list[CapabilityEntryOut]
    exposed: list[str]
    """Names that become model-visible tools."""

    @classmethod
    def of(cls, capabilities: EffectiveCapabilitySet) -> AgentCapabilitiesOut:
        return cls(
            agent_id=capabilities.agent_id,
            notes=list(capabilities.notes),
            entries=[
                CapabilityEntryOut(
                    name=e.name,
                    description=e.description,
                    source=e.source,
                    risk_level=e.risk_level.value,
                    exposed=e.exposed,
                    decision=e.decision.value,
                    state=e.state.value,
                    reason=e.reason,
                )
                for e in capabilities.entries
            ],
            exposed=capabilities.exposed_names(),
        )


class TaskStepOut(BaseModel):
    id: str
    description: str
    status: str
    tool: str | None = None
    detail: str = ""


class ActivityOut(BaseModel):
    tool: str
    count: int
    failed: bool
    detail: str = ""


class ArtifactRefOut(BaseModel):
    path: str
    name: str = ""
    run_id: str | None = None


class TaskStateOut(BaseModel):
    """Recorded progress of a conversation (R21), for the console / API."""

    task_id: str
    goal: str
    status: str
    steps: list[TaskStepOut]
    decisions: list[str]
    artifacts: list[ArtifactRefOut]
    failures: list[str]
    activity: list[ActivityOut]
    current_step_id: str | None
    next_action: str | None
    run_count: int
    plan_revision: int
    updated_at: datetime
    exists: bool = True
    """False when nothing has been recorded yet (empty default shape)."""

    @classmethod
    def of(cls, state: TaskState | None, *, task_id: str) -> TaskStateOut:
        if state is None:
            return cls(
                task_id=task_id,
                goal="",
                status="created",
                steps=[],
                decisions=[],
                artifacts=[],
                failures=[],
                activity=[],
                current_step_id=None,
                next_action=None,
                run_count=0,
                plan_revision=0,
                updated_at=datetime.now(UTC),
                exists=False,
            )
        return cls(
            task_id=state.task_id,
            goal=state.goal,
            status=state.status,
            steps=[
                TaskStepOut(
                    id=s.id,
                    description=s.description,
                    status=s.status.value,
                    tool=s.tool,
                    detail=s.detail,
                )
                for s in state.steps
            ],
            decisions=list(state.decisions),
            artifacts=[
                ArtifactRefOut(path=a.path, name=a.name, run_id=a.run_id)
                for a in state.artifacts
            ],
            failures=list(state.failures),
            activity=[
                ActivityOut(tool=a.tool, count=a.count, failed=a.failed, detail=a.detail)
                for a in state.activity
            ],
            current_step_id=state.current_step_id,
            next_action=state.next_action,
            run_count=state.run_count,
            plan_revision=state.plan_revision,
            updated_at=state.updated_at,
            exists=True,
        )


class ScheduleBase(BaseModel):
    name: str = Field(min_length=1)
    task_input: str = Field(min_length=1)
    schedule_type: ScheduleType
    run_at: datetime | None = None
    cron_expr: str | None = None
    interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool = True
    model: str | None = None


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
    model: str | None = None
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
            model=schedule.model,
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
    def of(
        cls,
        run: Run,
        output: Any | None = None,
        input: str = "",
        usage: RunUsage | None = None,
    ) -> RunOut:
        data = run.model_dump()
        data["output"] = output
        data["input"] = input
        if usage is not None:
            # Live usage (executing run) or a merged total — the run's own
            # ``usage`` field is only final, so callers may supply a snapshot.
            data["usage"] = usage.model_dump()
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


class SkillUpdateRequest(BaseModel):
    """Partial skill-registration update."""

    enabled: bool | None = None


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str
    description: str
    path: Path | None
    dependencies: list[str]
    allowed_tools: list[str]
    enabled: bool = True
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
    enabled: bool = True
    exposed_tools: list[str] | None = None


class MCPServerUpdateRequest(BaseModel):
    """Partial server update; omitted fields are left unchanged."""

    description: str | None = None
    endpoint: str | None = None
    exposed_tools: list[str] | None = Field(
        default=None,
        description="Allowlist of tool names; empty list exposes none, omit to keep current",
    )


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
    exposed_tools: list[str] | None = None

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


# ------------------------------------------------------------- model config

ConfigSource = Literal["page", "env"]


class ProviderKeyOut(BaseModel):
    """One provider's API key status; the key itself never crosses the wire."""

    provider: str
    env_var: str
    set: bool
    """True when a key is active from either source."""
    source: ConfigSource | None = None
    hint: str | None = Field(default=None, description="Masked tail of the active key")


class ModelOptionOut(BaseModel):
    """One selectable model spec for the chat picker."""

    spec: str
    """``provider:model`` — what the composer sends."""
    label: str
    provider: str
    model: str
    context_window: int | None = None


class ModelConfigOut(BaseModel):
    model: str | None = None
    """Console-set default model spec (None = not overridden from the page)."""
    model_source: ConfigSource
    effective_model: str
    """The model spec actually used when none is given."""
    local_base_url: str | None = None
    local_base_url_source: ConfigSource | None = None
    api_keys: list[ProviderKeyOut]
    custom_models: list[CustomModelOut] = Field(default_factory=list)
    available_models: list[ModelOptionOut] = Field(default_factory=list)
    """Enabled models across enabled providers — the single list the chat picker
    reads, so the page and the picker can never disagree."""


class ModelConfigUpdate(BaseModel):
    """Partial update; omitted (None) fields are left unchanged, "" clears."""

    model: str | None = Field(
        default=None,
        description="Default model spec ('provider:model'); '' clears the override",
    )
    api_keys: dict[str, str | None] = Field(
        default_factory=dict,
        description="Per-provider keys; '' or null clears the provider's override",
    )
    local_base_url: str | None = Field(
        default=None,
        description="Local provider endpoint; '' clears the override",
    )


class ModelVerifyRequest(BaseModel):
    """Build the (overridden) model and round-trip a tiny completion."""

    model: str | None = Field(default=None, description="Defaults to the effective spec")


class ModelVerifyOut(BaseModel):
    ok: bool
    model: str | None = None
    latency_ms: float | None = None
    reply: str | None = None
    error: str | None = None


# ------------------------------------------------- custom model endpoints


class ModelDiscoverRequest(BaseModel):
    """Probe an OpenAI-compatible endpoint for its model list."""

    base_url: str = Field(min_length=1, description="Endpoint root, e.g. http://host:8000/v1")
    api_format: str = Field(default="openai", description="Wire format (openai compatible)")
    api_key: str | None = Field(default=None, description="Bearer key; omit for open endpoints")


class ModelDiscoverOut(BaseModel):
    ok: bool
    models: list[str] = Field(default_factory=list)
    error: str | None = None


class ModelEntryOut(BaseModel):
    """One model within a provider (id + context window + enabled)."""

    id: str
    context_window: int | None = None
    enabled: bool = True


class ModelEntryIn(BaseModel):
    """Per-model upsert payload; the id comes from the path."""

    context_window: int | None = Field(default=None, gt=0)
    enabled: bool = True


class CustomModelOut(BaseModel):
    """A provider endpoint; the API key never crosses the wire."""

    name: str
    base_url: str
    api_format: str
    models: list[str]
    catalog: list[ModelEntryOut] = Field(default_factory=list)
    key_hint: str | None = None
    """Masked tail of the stored key (None when no key)."""
    builtin: bool = False
    """True for the built-in providers (openai/openrouter/local) — they can be
    overridden/edited but not removed from the list."""
    context_window: int | None = None
    """Provider-level default max input tokens (per-model values override)."""
    enabled: bool = True
    """Whether the provider is offered in the chat picker."""

    @classmethod
    def of(cls, m: CustomModelSpec) -> CustomModelOut:
        from agent_core.config.model_config import mask_secret

        return cls(
            name=m.name,
            base_url=m.base_url,
            api_format=m.api_format,
            models=m.model_ids(),
            catalog=[
                ModelEntryOut(
                    id=e.id, context_window=e.context_window, enabled=e.enabled
                )
                for e in m.catalog
            ],
            key_hint=mask_secret(m.api_key) if m.api_key else None,
            context_window=m.context_window,
            enabled=m.enabled,
            builtin=m.builtin,
        )


class CustomModelUpsertRequest(BaseModel):
    """Create or replace one provider endpoint; the name comes from the path."""

    base_url: str = Field(min_length=1)
    api_format: str = "openai"
    api_key: str | None = None
    models: list[str] = Field(default_factory=list)
    catalog: list[ModelEntryOut] | None = Field(
        default=None,
        description="Per-model entries; when omitted, built from `models`.",
    )
    context_window: int | None = Field(
        default=None,
        description="Provider-level default max input tokens (for context accounting)",
    )
    enabled: bool = True


class ProviderUpdateRequest(BaseModel):
    """A partial edit of one provider (undefined fields are left unchanged)."""

    name: str | None = Field(default=None, min_length=1, description="Rename")
    base_url: str | None = None
    api_format: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    context_window: int | None = None


class ProviderKeyRevealOut(BaseModel):
    """The plaintext key, returned only by the explicit reveal endpoint."""

    name: str
    api_key: str | None = None
    source: ConfigSource | None = None
    """``page`` (stored override) or ``env`` (from the environment)."""


class ProviderModelsAddRequest(BaseModel):
    """Batch-add models to an existing provider (the 探测添加 flow)."""

    models: list[str] = Field(min_length=1)
    context_window: int | None = Field(
        default=None, gt=0, description="Optional window applied to the added models"
    )


# ------------------------------------------------------------------ projects


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, description="Display name of the project")
    path: str = Field(
        min_length=1,
        description="Absolute host directory the agent works in (created if missing)",
    )


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    path: str
    created_at: Any
    metadata: dict[str, Any]

    @classmethod
    def of(cls, project: Project) -> ProjectOut:
        return cls(
            id=project.id,
            name=project.name,
            path=str(project.path),
            created_at=project.created_at,
            metadata=project.metadata,
        )


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scope: str
    scope_id: str | None = None
    type: str
    content: str
    source: str
    task_id: str | None
    source_run_id: str | None = None
    created_by: str = "human"
    confidence: float
    importance: int
    active: bool
    superseded_by: str | None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, memory: Memory) -> MemoryOut:
        return cls.model_validate(memory)


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    scope: str = "user"
    scope_id: str | None = Field(
        default=None,
        description="Owner within the scope (project id / agent id); unused for user/org",
    )
    type: str = "fact"


class MemoryUpdateRequest(BaseModel):
    """Partial edit; omitted fields are left unchanged."""

    content: str | None = None
    scope: str | None = None
    scope_id: str | None = None
    type: str | None = None
