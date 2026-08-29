"""Application service: use-case layer between transports and the runtime.

One method per use case (submit a run, resolve an approval, connect an MCP
server, ...). Depends on the runtime, registries and MCP manager — never on
HTTP types — so the FastAPI layer stays a thin transport adapter and other
frontends (CLI, gRPC, queues) reuse the same seam.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.action import ApprovalRequest, ApprovalStatus
from agent_core.domain.mcp import MCPServerDefinition
from agent_core.domain.task import Run
from agent_core.domain.trace import EventType, TraceEvent
from agent_core.errors.exceptions import ApprovalError
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStream, EventStreamBroker
from agent_core.persistence.store import SqliteStore
from agent_core.registries import MCPRegistry
from agent_core.runtime.runtime import AgentRuntime

# Decisions a human may make on a pending request; PENDING/EXPIRED are states,
# not decisions.
_RESOLVABLE_DECISIONS = frozenset(
    {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EDITED,
        ApprovalStatus.CANCELLED,
    }
)


class AgentCoreService:
    """The single object transports talk to; owns no state of its own."""

    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        mcp: MCPManager,
        mcp_registry: MCPRegistry,
        broker: EventStreamBroker,
        store: SqliteStore | None = None,
    ) -> None:
        self.runtime = runtime
        self.mcp = mcp
        self.mcp_registry = mcp_registry
        self.broker = broker
        self.store = store

    # ------------------------------------------------------------------ runs

    async def submit_run(
        self,
        agent_id: str,
        task_input: str,
        *,
        parent_run_id: str | None = None,
        wait: bool = False,
    ) -> Run:
        """Create and start a run; with ``wait`` return it in a terminal state."""
        run = self.runtime.create_run(agent_id, task_input, parent_run_id=parent_run_id)
        task = self.runtime.submit_run(run)
        if wait:
            await task
        return run

    def get_run(self, run_id: str) -> Run:
        return self.runtime.get_run(run_id)

    def list_runs(self, agent_id: str | None = None) -> list[Run]:
        runs = self.runtime.list_runs()
        if agent_id is not None:
            runs = [run for run in runs if run.agent_id == agent_id]
        return runs

    def cancel_run(self, run_id: str) -> Run:
        return self.runtime.cancel_run(run_id)

    def final_output(self, run_id: str) -> Any | None:
        """Output payload of the run's AGENT_FINISHED event, if it has one."""
        for event in self.trace_events(run_id):
            if event.event_type is EventType.AGENT_FINISHED:
                return event.output
        return None

    # -------------------------------------------------------------- approvals

    def list_pending_approvals(self) -> list[ApprovalRequest]:
        return self.runtime.approvals.list_pending()

    def resolve_approval(
        self,
        approval_id: str,
        decision: ApprovalStatus,
        *,
        resolved_by: str = "user",
        edited_arguments: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Resolve a pending approval and wake the run waiting on it."""
        if decision not in _RESOLVABLE_DECISIONS:
            raise ApprovalError(
                f"'{decision.value}' is not a valid approval decision",
                details={"approval_id": approval_id, "decision": decision.value},
            )
        return self.runtime.approvals.resolve(
            approval_id,
            decision,
            resolved_by=resolved_by,
            edited_arguments=edited_arguments,
        )

    # -------------------------------------------------------------------- mcp

    def list_servers(self) -> list[MCPServerDefinition]:
        return self.mcp_registry.list()

    def register_server(self, definition: MCPServerDefinition) -> MCPServerDefinition:
        self.mcp_registry.register(definition)
        return definition

    async def connect_server(self, server_id: str) -> list[str]:
        """Connect and return the names of the tools the server exposes."""
        return await self.mcp.connect(server_id)

    async def disconnect_server(self, server_id: str) -> None:
        await self.mcp.disconnect(server_id)

    # ----------------------------------------------------------------- events

    def trace_events(self, run_id: str) -> list[TraceEvent]:
        return self.runtime.tracer.get_events(run_id)

    def subscribe_events(self, run_id: str | None = None) -> EventStream:
        """Live event stream for one run, or for all runs when ``run_id`` is None."""
        return self.broker.subscribe(run_id)

    def unsubscribe_events(self, stream: EventStream) -> None:
        self.broker.unsubscribe(stream)
