"""AgentRuntime: owns the run lifecycle from creation to a terminal state.

This is the entry point business code talks to: create a run for an agent,
execute it (directly or as a background task), cancel it, inspect it. All
state transitions go through the domain state machine; every observable step
is emitted as a trace event.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_core.artifacts import scan_workspace_artifacts
from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.autonomy import VerificationPolicy
from agent_core.domain.metrics import RunUsage
from agent_core.domain.task import Run, RunStatus, Task
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import (
    AgentError,
    ApprovalRejectedError,
    RegistryError,
    RunTimeoutError,
    StateError,
)
from agent_core.observability.emitter import EventFanout
from agent_core.observability.events import EventBus
from agent_core.observability.trace import InMemoryTracer, Tracer
from agent_core.permissions.approval import ApprovalManager
from agent_core.permissions.gate import ActionGate
from agent_core.permissions.loop_guard import LoopGuard
from agent_core.permissions.policy import ActionPolicy
from agent_core.persistence.store import SqliteStore
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.builder import AgentBuilder
from agent_core.runtime.context import current_run
from agent_core.runtime.executor import AgentExecutor
from agent_core.runtime.help_tool import make_help_tool
from agent_core.runtime.model import ModelFactory
from agent_core.runtime.tool_executor import ToolExecutor
from agent_core.runtime.tooling import ToolFactory, make_gated_tool
from agent_core.runtime.usage import UsageCollector
from agent_core.runtime.verification import (
    VERIFIER_SYSTEM_PROMPT,
    attempt_record,
    build_fix_input,
    build_verification_input,
    parse_verifier_output,
    verification_question,
)
from agent_core.runtime.verification import (
    passed as verification_passed,
)

if TYPE_CHECKING:
    # Import-time cycle: agent_core.eval pulls in orchestration → runtime.
    from agent_core.eval.judge import JudgeResult


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
        store: SqliteStore | None = None,
    ) -> None:
        self.agents = agents
        self.tools = tools
        self.skills = skills
        self.tracer = tracer or InMemoryTracer()
        self.bus = bus or EventBus()
        self.fanout = EventFanout(self.tracer, self.bus)
        self.policy = policy or ActionPolicy()
        self.approvals = approvals or ApprovalManager()
        self.loop_guard = LoopGuard()
        self.tool_executor = ToolExecutor()
        self.gate = ActionGate(
            agents,
            tools,
            self.policy,
            self.approvals,
            self.tool_executor,
            self.fanout,
            loop_guard=self.loop_guard,
        )
        self.builder = builder or AgentBuilder(
            agents,
            tools,
            skills,
            model_factory=model_factory,
            tool_factory=tool_factory or partial(make_gated_tool, gate=self.gate),
            usage_provider=self._live_usage,
            help_tool=make_help_tool(self.gate),
        )
        self.executor = AgentExecutor(self.fanout)
        self._runs: dict[str, Run] = {}
        self._tasks: dict[str, Task] = {}
        self._running: dict[str, asyncio.Task[Run]] = {}
        self._collectors: dict[str, UsageCollector] = {}
        self._store = store

    def _live_usage(self) -> RunUsage | None:
        """Live usage of the run executing in the current context (budget middleware)."""
        active = current_run.get()
        if active is None:
            return None
        collector = self._collectors.get(active.id)
        return collector.usage if collector else None

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

    def task_input(self, run: Run) -> str:
        """The task text a run was created for (empty for restored strangers)."""
        task = self._tasks.get(run.task_id)
        return task.input if task else ""

    # ---------------------------------------------------------------- restore

    def hydrate(self) -> None:
        """Restore run/task facts persisted by a previous process.

        Facts are restored as records, not live executions: runs that were not
        terminal when the process ended are marked FAILED directly (restore is
        not a lifecycle transition, so the state machine is bypassed) — their
        graph state and any in-process approval wait cannot be serialized.
        """
        if self._store is None:
            return
        for data in self._store.load_tasks():
            task = Task.model_validate_json(data)
            self._tasks[task.id] = task
        for data in self._store.load_runs():
            run = Run.model_validate_json(data)
            if not run.status.is_terminal:
                run.status = RunStatus.FAILED
                run.error = "interrupted by process restart"
                run.finished_at = datetime.now(UTC)
                self._save_run(run)
            self._runs[run.id] = run

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
        if self._store is not None:
            self._store.save_task(task.id, task.model_dump_json())
            self._save_run(run)
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
        collector = UsageCollector()
        self._collectors[run.id] = collector
        try:
            graph = self.builder.build(spec)
            output = await self.executor.execute(
                graph, run=run, task=task, spec=spec, collector=collector
            )
            output = await self._self_verify(run, task, spec, graph, output, collector)
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
            self._collect_artifacts(run)
            self._collectors.pop(run.id, None)
            self.loop_guard.forget_run(run.id)
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

    def _collect_artifacts(self, run: Run) -> None:
        """Record the workspace files this run created (the console's 产物窗口).

        Only top-level runs collect: nested runs (verifier) share the workspace
        and would double-claim the same files. A small clock-skew allowance
        keeps files written microseconds after run creation from being missed.
        """
        if run.parent_run_id is not None:
            return
        workspace = Path(get_settings().workspace_dir)
        since = run.created_at.timestamp() - 2.0
        files = scan_workspace_artifacts(workspace, since_ts=since)
        if files:
            run.metadata["artifacts"] = files
            self._save_run(run)

    async def _self_verify(
        self,
        run: Run,
        task: Task,
        spec: AgentSpec,
        graph: Any,
        output: str,
        collector: UsageCollector,
    ) -> str:
        """Verify the finished output; self-fix, then escalate or accept."""
        policy = spec.autonomy.verification if spec.autonomy else None
        if policy is None or not policy.enabled:
            return output
        attempts: list[dict[str, Any]] = []
        rounds = 0
        while True:
            result = await self._verify_once(run, policy, task.input, output, collector)
            attempts.append(attempt_record(result))
            if verification_passed(result, policy):
                run.metadata["verification"] = {
                    "passed": True, "rounds": rounds, "attempts": attempts,
                }
                self._save_run(run)
                return output
            if rounds >= policy.max_rounds:
                break
            rounds += 1
            feedback = (
                result.comment
                if result is not None and result.parsed
                else "the answer was judged insufficient"
            )
            output = await self._rerun_graph(
                run, spec, graph, build_fix_input(task.input, output, feedback), collector
            )
        # Self-fix exhausted: escalate to a human or complete marked unverified.
        if policy.on_fail == "accept":
            run.metadata["verification"] = {
                "passed": False, "rounds": rounds, "attempts": attempts,
            }
            self._save_run(run)
            return output
        try:
            note = await self.gate.request_help(
                run=run,
                question=verification_question(task.input, output, attempts),
                reason="verification failed",
            )
        except ApprovalRejectedError:
            run.metadata["verification"] = {
                "passed": False, "rounds": rounds, "attempts": attempts,
                "escalation": "rejected",
            }
            self._save_run(run)
            return output
        output = await self._rerun_graph(
            run, spec, graph, build_fix_input(task.input, output, note), collector
        )
        result = await self._verify_once(run, policy, task.input, output, collector)
        attempts.append(attempt_record(result))
        run.metadata["verification"] = {
            "passed": verification_passed(result, policy),
            "rounds": rounds + 1,
            "attempts": attempts,
            "escalation": "resolved",
        }
        self._save_run(run)
        return output

    async def _verify_once(
        self,
        run: Run,
        policy: VerificationPolicy,
        task_input: str,
        output: str,
        collector: UsageCollector,
    ) -> JudgeResult | None:
        """Judge the output via a nested verifier run; None when unavailable."""
        judge_input = build_verification_input(task_input, output)
        try:
            judge_run = self.create_run(
                policy.judge_agent_id, judge_input, parent_run_id=run.id
            )
        except RegistryError:
            self.agents.register(
                AgentSpec(
                    id=policy.judge_agent_id,
                    name="Verifier",
                    system_prompt=VERIFIER_SYSTEM_PROMPT,
                )
            )
            judge_run = self.create_run(
                policy.judge_agent_id, judge_input, parent_run_id=run.id
            )
        finished = await self.execute_run(judge_run)
        if finished.status is not RunStatus.COMPLETED or finished.usage is None:
            return None  # verifier failed/unavailable: fail open, never block
        collector.merge(finished.usage)
        if run.usage is not None:
            run.usage.add(finished.usage)
        judge_output: str | None = None
        for event in self.tracer.get_events(finished.id):
            if event.event_type is EventType.AGENT_FINISHED and isinstance(event.output, str):
                judge_output = event.output
        if judge_output is None:
            return None
        return parse_verifier_output(judge_output)

    async def _rerun_graph(
        self, run: Run, spec: AgentSpec, graph: Any, task_input: str, collector: UsageCollector
    ) -> str:
        """One more execution of the same graph for a fix round."""
        fix_task = Task(input=task_input)
        return await self.executor.execute(
            graph, run=run, task=fix_task, spec=spec, collector=collector
        )

    def _transition(self, run: Run, status: RunStatus) -> None:
        previous = run.status
        run.transition_to(status)
        # The transition is the last mutation point of a run (usage/error are
        # set by the executor/gate before it), so persisting here captures the
        # full record for every lifecycle change.
        self._save_run(run)
        self.fanout.emit(
            EventType.RUN_STATUS_CHANGED,
            run=run,
            agent_id=run.agent_id,
            metadata={"from": previous.value, "to": status.value},
        )

    def _save_run(self, run: Run) -> None:
        if self._store is not None:
            self._store.save_run(run.id, run.status.value, run.model_dump_json())

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
