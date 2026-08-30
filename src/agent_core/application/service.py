"""Application service: use-case layer between transports and the runtime.

One method per use case (submit a run, resolve an approval, connect an MCP
server, ...). Depends on the runtime, registries and MCP manager — never on
HTTP types — so the FastAPI layer stays a thin transport adapter and other
frontends (CLI, gRPC, queues) reuse the same seam.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.scheduler import ScheduleManager
from agent_core.domain.action import ApprovalRequest, ApprovalStatus
from agent_core.domain.agent import AgentSpec
from agent_core.domain.mcp import MCPServerDefinition
from agent_core.domain.schedule import Schedule
from agent_core.domain.task import Run, Task
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
        schedules: ScheduleManager | None = None,
    ) -> None:
        self.runtime = runtime
        self.mcp = mcp
        self.mcp_registry = mcp_registry
        self.broker = broker
        self.store = store
        self.schedules = schedules

    # ------------------------------------------------------------------ tasks

    def default_agent(self) -> str:
        """The default (first registered) agent id — usually the avatar."""
        agents = self.runtime.agents.list()
        if not agents:
            raise ApprovalError("no agents registered")
        return agents[0].id

    async def submit_run(
        self,
        agent_id: str | None,
        task_input: str,
        *,
        parent_run_id: str | None = None,
        wait: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Start a new conversation; with ``wait`` return it fully answered."""
        resolved_agent = agent_id or self.default_agent()
        task = self.runtime.create_conversation(resolved_agent, task_input, metadata=metadata)
        run = self.runtime.task_active_run(task.id)
        if run is not None:
            execution = self.runtime.submit_run(run)
            if wait:
                await execution
        return task

    def get_task(self, task_id: str) -> Task:
        return self.runtime.get_task(task_id)

    def list_tasks(self, agent_id: str | None = None) -> list[Task]:
        tasks = self.runtime.list_tasks()
        if agent_id is not None:
            tasks = [task for task in tasks if task.agent_id == agent_id]
        return tasks

    def get_run(self, run_id: str) -> Run:
        return self.runtime.get_run(run_id)

    def list_runs(self, agent_id: str | None = None) -> list[Run]:
        runs = self.runtime.list_runs()
        if agent_id is not None:
            runs = [run for run in runs if run.agent_id == agent_id]
        return runs

    def cancel_task(self, task_id: str) -> Task:
        """Cancel the conversation's active run; returns the conversation."""
        run = self.runtime.task_active_run(task_id)
        if run is not None:
            self.runtime.cancel_run(run.id)
        return self.runtime.get_task(task_id)

    async def send_message(self, task_id: str, text: str, *, wait: bool = False) -> Task:
        """Continue the conversation of ``task_id`` with a new user turn.

        The follow-up run reuses the conversation's thread, so the agent
        continues where it left off with the whole history in context.
        """
        conversation = self.runtime.get_task(task_id)
        run = self.runtime.create_run(
            conversation.agent_id, text, task=conversation
        )
        execution = self.runtime.submit_run(run)
        if wait:
            await execution
        return conversation

    def task_input(self, run_id: str) -> str:
        run = self.get_run(run_id)
        return self.runtime.task_input(run)

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
        note: str | None = None,
    ) -> ApprovalRequest:
        """Resolve a pending approval and wake the run waiting on it.

        ``note`` is the human's answer for task-help requests; it is fed back
        to the agent as guidance.
        """
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
            note=note,
        )

    def update_agent(
        self, agent_id: str, *, tools: list[str] | None = None, skills: list[str] | None = None
    ) -> AgentSpec:
        """Update an agent's tool/skill binding; takes effect on the next run.

        Skills are validated against the Skill Registry. Tools are not — MCP
        tools exist only while their server is connected — but a run with an
        unregistered tool fails fast with a clear error.
        """
        spec = self.runtime.agents.get(agent_id)
        update: dict[str, Any] = {}
        if tools is not None:
            update["tools"] = tools
        if skills is not None:
            for skill_id in skills:
                self.runtime.skills.get(skill_id)  # 404 on unknown skills
            update["skills"] = skills
        updated = spec.model_copy(update=update)
        self.runtime.agents.replace(updated)
        return updated

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

    # ---------------------------------------------------------------- events

    def trace_events(self, run_id: str) -> list[TraceEvent]:
        return self.runtime.tracer.get_events(run_id)

    def subscribe_events(self, run_id: str | None = None) -> EventStream:
        """Live event stream for one run, or for all runs when ``run_id`` is None."""
        return self.broker.subscribe(run_id)

    def unsubscribe_events(self, stream: EventStream) -> None:
        self.broker.unsubscribe(stream)

    # -------------------------------------------------------------- schedules

    def list_schedules(self) -> list[Schedule]:
        if self.schedules is None:
            return []
        return self.schedules.list()

    def get_schedule(self, schedule_id: str) -> Schedule:
        if self.schedules is None:
            raise ApprovalError("schedules are not available", details={"schedule_id": schedule_id})
        return self.schedules.get(schedule_id)

    def create_schedule(self, schedule: Schedule) -> Schedule:
        if self.schedules is None:
            raise ApprovalError("schedules are not available")
        return self.schedules.add(schedule)

    def update_schedule(self, schedule: Schedule) -> Schedule:
        if self.schedules is None:
            raise ApprovalError("schedules are not available")
        return self.schedules.update(schedule)

    def delete_schedule(self, schedule_id: str) -> None:
        if self.schedules is None:
            raise ApprovalError("schedules are not available")
        self.schedules.remove(schedule_id)

    async def run_schedule_now(self, schedule_id: str) -> Task:
        """Execute a schedule immediately as a fresh conversation (manual run).

        Returns the created task so the console can jump into the conversation.
        """
        if self.schedules is None:
            raise ApprovalError("schedules are not available")
        schedule = self.schedules.get(schedule_id)
        return await self.schedules.run_schedule(schedule)
