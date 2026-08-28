"""Composition root: build a fully wired :class:`AgentCoreService`.

The only place that knows how every concrete piece fits together. Entry
points (the FastAPI app, the CLI, example scripts) call :func:`default_service`
instead of assembling components themselves.
"""

from __future__ import annotations

from agent_core.application.service import AgentCoreService
from agent_core.config.settings import Settings, apply_proxy, get_settings
from agent_core.mcp.credentials import EnvCredentialResolver
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStreamBroker
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime


def default_service(settings: Settings | None = None) -> AgentCoreService:
    """Build an in-memory service with empty registries and default wiring.

    Model provisioning relies on the cached process settings, so ``settings``
    only guarantees the proxy env vars are applied before any client is built.
    """
    resolved = settings or get_settings()
    apply_proxy(resolved)
    agents = AgentRegistry()
    tools = ToolRegistry()
    skills = SkillRegistry()
    runtime = AgentRuntime(agents, tools, skills)
    mcp_registry = MCPRegistry()
    mcp = MCPManager(mcp_registry, tools, credentials=EnvCredentialResolver())
    broker = EventStreamBroker(runtime.bus)
    return AgentCoreService(runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker)
