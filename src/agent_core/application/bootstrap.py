"""Composition root: build a fully wired :class:`AgentCoreService`.

The only place that knows how every concrete piece fits together. Entry
points (the FastAPI app, the CLI, example scripts) call :func:`default_service`
instead of assembling components themselves.

When ``AGENT_CORE_DATABASE_URL`` is set to a ``sqlite:///`` URL, all mutating
components are wired to a shared :class:`SqliteStore` and the facts persisted
by previous processes (registries, run/task records, trace events, approvals)
are restored before the service is returned.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.scheduler import ScheduleManager
from agent_core.application.service import AgentCoreService
from agent_core.builtins import register_builtin_tools
from agent_core.builtins.memory import (
    make_forget_memories,
    make_recall_memories,
    make_remember,
)
from agent_core.builtins.plan import make_update_plan
from agent_core.builtins.schedules import make_create_schedule
from agent_core.builtins.skills import make_install_skill
from agent_core.config.model_config import load_model_config
from agent_core.config.settings import Settings, apply_proxy, get_settings
from agent_core.domain.mcp import MCPServerStatus
from agent_core.mcp.credentials import EnvCredentialResolver
from agent_core.mcp.manager import MCPManager
from agent_core.memory import MemoryRepository, MemoryService
from agent_core.memory.embedding import EmbeddingClient
from agent_core.observability.stream import EventStreamBroker
from agent_core.observability.trace import InMemoryTracer
from agent_core.permissions.approval import ApprovalManager
from agent_core.persistence import PersistingTracer, open_store
from agent_core.persistence.store import SqliteStore
from agent_core.registries import (
    AgentRegistry,
    MCPRegistry,
    ProjectRegistry,
    SkillRegistry,
    ToolRegistry,
)
from agent_core.runtime.runtime import AgentRuntime
from agent_core.task_state import TaskStateRepository, TaskStateService


def default_service(settings: Settings | None = None) -> AgentCoreService:
    """Build a service with empty (or restored) registries and default wiring.

    Model provisioning relies on the cached process settings, so ``settings``
    only guarantees the proxy env vars are applied before any client is built.
    """
    resolved = settings or get_settings()
    apply_proxy(resolved)
    store = open_store(resolved.database_url)
    # Console-set model overrides (default spec, API keys, local endpoint) are
    # consulted by build_model before env/Settings — load them before anything
    # can build a model.
    load_model_config(store)
    agents = AgentRegistry(store)
    tools = ToolRegistry(store)
    skills = SkillRegistry(store)
    register_builtin_tools(tools, resolved)
    if resolved.sandbox != "podman":
        # Host backend: run_code driving a system package manager touches the
        # host itself, so those commands need a human even though run_code is
        # otherwise below the approval risk floor.
        from agent_core.builtins.code import RUN_CODE_TOOL, is_system_install
        from agent_core.permissions.arg_risk import register_argument_risk_rule

        register_argument_risk_rule(
            RUN_CODE_TOOL, lambda args: is_system_install(str(args.get("command", "")))
        )

    approvals = ApprovalManager(store)
    projects = ProjectRegistry(store)
    # Semantic memory retrieval is optional: with no endpoint configured the
    # service degrades to keyword scoring (see agent_core.memory).
    embedding = EmbeddingClient(
        base_url=resolved.memory_embedding_base_url,
        model=resolved.memory_embedding_model,
        api_key=resolved.memory_embedding_api_key,
        timeout_seconds=resolved.memory_embedding_timeout_ms / 1000,
        enabled=resolved.memory_embedding_enabled,
    )
    memories = MemoryService(
        MemoryRepository(store),
        embedding=embedding,
        semantic_weight=resolved.memory_semantic_weight,
        semantic_threshold=resolved.memory_semantic_threshold,
    )
    task_states = TaskStateService(TaskStateRepository(store))
    memory_tracer = InMemoryTracer()
    tracer: InMemoryTracer | PersistingTracer = memory_tracer
    if store is not None:
        _restore(
            store, agents=agents, tools=tools, skills=skills, approvals=approvals,
            projects=projects,
        )
        memories.hydrate()
        tracer = PersistingTracer(memory_tracer, store)
        tracer.restore()  # re-seed event history so run outputs stay queryable

    runtime = AgentRuntime(
        agents, tools, skills, tracer=tracer, approvals=approvals, store=store,
        projects=projects, memories=memories, task_states=task_states,
    )
    if store is not None:
        runtime.hydrate()
    mcp_registry = MCPRegistry(store)
    if store is not None:
        mcp_registry.hydrate()
        # Connections are process-local; a restored server needs a reconnect.
        for server in mcp_registry.list():
            if server.status is MCPServerStatus.HEALTHY:
                mcp_registry.set_status(server.id, MCPServerStatus.UNKNOWN)
    mcp = MCPManager(mcp_registry, tools, credentials=EnvCredentialResolver())
    broker = EventStreamBroker(runtime.bus)
    service = AgentCoreService(
        runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker, store=store
    )
    # The schedule runner creates a conversation and starts it — the same path
    # a manual task goes through, so scheduled work lands in the console. The
    # wrapper forwards the schedule's provenance so created tasks can be
    # grouped under their schedule in the sidebar.
    async def _schedule_runner(agent_id: str, text: str, metadata: dict[str, Any] | None) -> Any:
        data = dict(metadata or {})
        model = data.pop("model", None)
        return await service.submit_run(agent_id, text, metadata=data or None, model=model)

    schedules = ScheduleManager(runner=_schedule_runner, store=store)
    if store is not None:
        schedules.restore()
    service.schedules = schedules
    # Register service-bound tools (schedule + skill creation + memory + plan)
    # against the fully built service.
    for definition, handler in (
        make_create_schedule(service),
        make_install_skill(service),
        make_remember(memories),
        make_recall_memories(memories),
        make_forget_memories(memories),
        make_update_plan(runtime.fanout),
    ):
        try:
            tools.register(definition, handler)
        except Exception:
            # Definition persisted from a previous boot: re-attach the executable.
            tools.replace_with_handler(definition, handler)
    return service


def _restore(
    store: SqliteStore,
    *,
    agents: AgentRegistry,
    tools: ToolRegistry,
    skills: SkillRegistry,
    approvals: ApprovalManager,
    projects: ProjectRegistry,
) -> None:
    """Replay persisted facts into the in-memory components."""
    agents.hydrate()
    tools.hydrate()  # definitions only — handlers are process-local callables
    skills.hydrate()
    approvals.hydrate()
    projects.hydrate()
