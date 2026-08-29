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

from agent_core.application.service import AgentCoreService
from agent_core.builtins import register_builtin_tools
from agent_core.config.settings import Settings, apply_proxy, get_settings
from agent_core.domain.mcp import MCPServerStatus
from agent_core.mcp.credentials import EnvCredentialResolver
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStreamBroker
from agent_core.observability.trace import InMemoryTracer
from agent_core.permissions.approval import ApprovalManager
from agent_core.persistence import PersistingTracer, open_store
from agent_core.persistence.store import SqliteStore
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime


def default_service(settings: Settings | None = None) -> AgentCoreService:
    """Build a service with empty (or restored) registries and default wiring.

    Model provisioning relies on the cached process settings, so ``settings``
    only guarantees the proxy env vars are applied before any client is built.
    """
    resolved = settings or get_settings()
    apply_proxy(resolved)
    store = open_store(resolved.database_url)
    agents = AgentRegistry(store)
    tools = ToolRegistry(store)
    skills = SkillRegistry(store)
    register_builtin_tools(tools, resolved)

    approvals = ApprovalManager(store)
    memory_tracer = InMemoryTracer()
    tracer: InMemoryTracer | PersistingTracer = memory_tracer
    if store is not None:
        _restore(store, agents=agents, tools=tools, skills=skills, approvals=approvals)
        tracer = PersistingTracer(memory_tracer, store)
        tracer.restore()  # re-seed event history so run outputs stay queryable

    runtime = AgentRuntime(agents, tools, skills, tracer=tracer, approvals=approvals, store=store)
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
    return AgentCoreService(
        runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker, store=store
    )


def _restore(
    store: SqliteStore,
    *,
    agents: AgentRegistry,
    tools: ToolRegistry,
    skills: SkillRegistry,
    approvals: ApprovalManager,
) -> None:
    """Replay persisted facts into the in-memory components."""
    agents.hydrate()
    tools.hydrate()  # definitions only — handlers are process-local callables
    skills.hydrate()
    approvals.hydrate()
