"""AgentRuntime: owns the run lifecycle from creation to a terminal state.

This is the entry point business code talks to: create a run for an agent,
execute it (directly or as a background task), cancel it, inspect it. All
state transitions go through the domain state machine; every observable step
is emitted as a trace event.
"""

from __future__ import annotations

import asyncio
from functools import partial

from agent_core.domain.task import Run, RunStatus, Task
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import AgentError, RegistryError, RunTimeoutError, StateError
from agent_core.observability.emitter import EventFanout
from agent_core.observability.events import EventBus
from agent_core.observability.trace import InMemoryTracer, Tracer
from agent_core.permissions.approval import ApprovalManager
from agent_core.permissions.gate import ActionGate
from agent_core.permissions.policy import ActionPolicy
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.builder import AgentBuilder
from agent_core.runtime.context import current_run
from agent_core.runtime.executor import AgentExecutor
from agent_core.runtime.model import ModelFactory
from agent_core.runtime.tool_executor import ToolExecutor
from agent_core.runtime.tooling import ToolFactory, make_gated_tool


class AgentRuntime:
    """Facade binding registries, builder, executor and the run state machine."""

    def __init__(
        self,
        agents: AgentRegistry,
        tools: ToolRegistry,
        skills: SkillRegistry,
        *,
        tracer: Tracer | None = None,
        bus: EventBus | None = None,
        model_factory: ModelFactory | None = None,
        tool_factory: ToolFactory | None = None,
        policy: ActionPolicy | None = None,
        approvals: ApprovalManager | None = None,
        builder: AgentBuilder | None = None,
    ) -> None:
        self.agents = agents
        self.tools = tools
        self.skills = skills
        self.tracer = tracer or InMemoryTracer()
        self.bus = bus or EventBus()
        self.fanout = EventFanout(self.tracer, self.bus)
        self.policy = policy or ActionPolicy()
        self.approvals = approvals or ApprovalManager()
        self.tool_executor = ToolExecutor()
        self.gate = ActionGate(
            agents, tools, self.policy, self.approvals, self.tool_executor, self.fanout
        )
        self.builder = builder or AgentBuilder(
            agents,
            tools,
            skills,
            model_factory=model_factory,
            tool_factory=tool_factory or partial(make_gated_tool, gate=self.gate),
        )
        self.executor = AgentExecutor(self.fanout)
        self._runs: dict[str, Run] = {}
        self._tasks: dict[str, Task] = {}
        self._running: dict[str, asyncio.Task[Run]] = {}

    # ---------------------------------------------------------------- queries

    def get_run(self, run_id: str) -> Run:
        """Return the run with ``run_id``."""
        try:
            return self._runs[run_id]
        except KeyError:
            raise RegistryError(kind="run", key=run_id, detail="not found") from None

    def list_runs(self) -> list[Run]:
        """Snapshot of all runs, in creation order."""
        return list(self._runs.values())

    # -------------------------------------------------------------- lifecycle

    def create_run(
        self, agent_id: str, task_input: str, *, parent_run_id: str | None = None
    ) -> Run:
        """Create (but do not start) a run of ``agent_id`` for ``task_input``."""
        spec = self.agents.get(agent_id)  # fail fast on unknown agents
        task = Task(input=task_input)
        run = Run(task_id=task.id, agent_id=spec.id, parent_run_id=parent_run_id)
        self._tasks[task.id] = task
        self._runs[run.id] = run
        return run

    async def execute_run(self, run: Run) -> Run:
        """Drive ``run`` to a terminal state and return it."""
        if run.status != RunStatus.CREATED:
            raise StateError(
                f"Run '{run.id}' is not executable in status '{run.status.value}'",
                details={"run_id": run.id, "status": run.status.value},
            )
        spec = self.agents.get(run.agent_id)
        task = self._tasks[run.task_id]
        self._transition(run, RunStatus.RUNNING)
        self.fanout.emit(
            EventType.RUN_STARTED, run=run, agent_id=run.agent_id, input=task.input
        )
        run_token = current_run.set(run)
        try:
            graph = self.builder.build(spec)
            output = await self.executor.execute(graph, run=run, task=task, spec=spec)
            self._transition(run, RunStatus.COMPLETED)
            self.fanout.emit(
                EventType.RUN_FINISHED, run=run, agent_id=run.agent_id, output=output
            )
        except asyncio.CancelledError:
            # Deliberate cancellation is a normal outcome, not an error.
            self._transition(run, RunStatus.CANCELLED)
            self.fanout.emit(EventType.RUN_CANCELLED, run=run, agent_id=run.agent_id)
            return run
        except RunTimeoutError as exc:
            self._finish_with_error(run, exc, RunStatus.TIMEOUT)
        except AgentError as exc:
            self._finish_with_error(run, exc, RunStatus.FAILED)
        finally:
            current_run.reset(run_token)
        return run

    def submit_run(self, run: Run) -> asyncio.Task[Run]:
        """Execute ``run`` as a background task so ``cancel_run`` can stop it."""
        existing = self._running.get(run.id)
        if existing is not None and not existing.done():
            raise StateError(
                f"Run '{run.id}' is already executing", details={"run_id": run.id}
            )
        task = asyncio.create_task(self.execute_run(run))
        self._running[run.id] = task
        return task

    def cancel_run(self, run_id: str) -> Run:
        """Cancel a created or in-flight run; returns it in CANCELLED state."""
        run = self.get_run(run_id)
        if run.status.is_terminal:
            raise StateError(
                f"Run '{run_id}' already finished", details={"run_id": run.id}
            )
        task = self._running.get(run_id)
        if task is not None and not task.done():
            task.cancel()  # execute_run performs the transition
            return run
        self._transition(run, RunStatus.CANCELLED)
        self.fanout.emit(EventType.RUN_CANCELLED, run=run, agent_id=run.agent_id)
        return run

    # --------------------------------------------------------------- internal

    def _transition(self, run: Run, status: RunStatus) -> None:
        previous = run.status
        run.transition_to(status)
        self.fanout.emit(
            EventType.RUN_STATUS_CHANGED,
            run=run,
            agent_id=run.agent_id,
            metadata={"from": previous.value, "to": status.value},
        )

    def _finish_with_error(self, run: Run, exc: AgentError, status: RunStatus) -> None:
        run.error = exc.message
        self._transition(run, status)
        self.fanout.emit(
            EventType.RUN_FAILED,
            run=run,
            agent_id=run.agent_id,
            error=exc.message,
            status=status.value,
        )
