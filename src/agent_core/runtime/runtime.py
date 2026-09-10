"""AgentRuntime: owns the run lifecycle from creation to a terminal state.

This is the entry point business code talks to: create a conversation for an
agent, execute it (directly or as a background task), cancel it, inspect it.
All state transitions go through the domain state machine; every observable
step is emitted as a trace event.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from pydantic import ValidationError

from agent_core.artifacts import (
    claimed_artifacts,
    clear_claims,
    scan_task_artifacts,
    scan_workspace_artifacts,
)
from langchain_core.messages import HumanMessage, RemoveMessage

from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.autonomy import VerificationPolicy
from agent_core.domain.metrics import RunUsage
from agent_core.memory.repository import MemoryRepository
from agent_core.memory.service import MemoryService
from agent_core.runtime.text import extract_text
from agent_core.domain.task import Run, RunStatus, Task, make_title, new_id
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
from agent_core.persistence.checkpointer import build_checkpointer
from agent_core.persistence.store import SqliteStore
from agent_core.registries import AgentRegistry, ProjectRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.builder import AgentBuilder
from agent_core.runtime.context import (
    current_memory_block,
    current_skill_mounts,
    current_model_override,
    current_query,
    current_run,
    current_task_id,
    current_task_root,
)
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
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        projects: ProjectRegistry | None = None,
        memories: MemoryService | None = None,
    ) -> None:
        self.agents = agents
        self.tools = tools
        self.skills = skills
        # `projects or default` would be wrong here: BaseRegistry defines
        # __len__, so an EMPTY registry is falsy and its store would be lost.
        self.projects = projects if projects is not None else ProjectRegistry()
        # Always present: an in-memory service when no store-backed one is
        # injected, so callers never special-case a missing memory system.
        self.memories = memories if memories is not None else MemoryService(MemoryRepository())
        self.tracer = tracer or InMemoryTracer()
        self.bus = bus or EventBus()
        self.fanout = EventFanout(self.tracer, self.bus)
        # Skill capability binding: the policy resolves each bound skill's
        # allowed_tools so the gate can deny out-of-scope tool calls (I-11).
        self.policy = policy or ActionPolicy(skill_allowed_tools=self._skill_allowed_tools)
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
        self._checkpointer = checkpointer
        self._checkpointer_ready = False
        self.builder = builder or AgentBuilder(
            agents,
            tools,
            skills,
            model_factory=model_factory,
            tool_factory=tool_factory or partial(make_gated_tool, gate=self.gate),
            usage_provider=self._live_usage,
            help_tool=make_help_tool(self.gate),
            checkpointer_provider=lambda: self.checkpointer,
            memory_enabled=self.memories is not None,
        )
        self.executor = AgentExecutor(self.fanout)
        self._runs: dict[str, Run] = {}
        self._tasks: dict[str, Task] = {}
        self._running: dict[str, asyncio.Task[Run]] = {}
        self._collectors: dict[str, UsageCollector] = {}
        self._store = store

    @property
    def checkpointer(self) -> BaseCheckpointSaver[Any]:
        """Conversation-state saver, built lazily (AsyncSqliteSaver requires
        a running loop at construction; execute paths always have one)."""
        if self._checkpointer is None:
            self._checkpointer = build_checkpointer(get_settings().database_url)
        return self._checkpointer

    def _live_usage(self) -> RunUsage | None:
        """Live usage of the run executing in the current context (budget middleware)."""
        active = current_run.get()
        if active is None:
            return None
        collector = self._collectors.get(active.id)
        return collector.usage if collector else None

    def _skill_mounts(self) -> tuple[tuple[str, str], ...]:
        """``(skill_id, source_dir)`` for every enabled skill, resolvable path only.

        Shared by the file-tool backend (virtual ``/skills/<id>``) and run_code
        (sandbox ``/skills/<id>``) so both namespaces agree on where a skill
        lives. Skips skills with no on-disk path rather than failing the run.
        """
        mounts: list[tuple[str, str]] = []
        for manifest in self.skills.list():
            if not manifest.enabled or manifest.path is None:
                continue
            if manifest.path.is_dir():
                mounts.append((manifest.id, str(manifest.path)))
        return tuple(mounts)

    async def _heartbeat(self, run: Run) -> None:
        """Emit a periodic liveness event while ``run`` executes.

        A long, silent stretch (slow model inference, a big tool call) would
        otherwise be indistinguishable from a stuck run. The console uses this
        to keep the "已工作" timer honestly advancing.
        """
        interval = 15.0
        try:
            while True:
                await asyncio.sleep(interval)
                elapsed = (datetime.now(UTC) - run.created_at).total_seconds() * 1000
                self.fanout.emit(
                    EventType.RUN_HEARTBEAT,
                    run=run,
                    agent_id=run.agent_id,
                    metadata={"elapsed_ms": elapsed},
                )
        except asyncio.CancelledError:
            return  # the run finished; nothing to report

    def _skill_allowed_tools(self, skill_id: str) -> list[str] | None:
        """A bound skill's allowed_tools, or ``None`` when the skill is unknown.

        Used by :class:`ActionPolicy` to enforce skill capability binding; an
        unknown skill returns ``None`` (unrestricted) so a stale binding never
        silently locks an agent out of all of its tools.
        """
        try:
            return self.skills.get(skill_id).allowed_tools
        except RegistryError:
            return None

    async def _memory_block(self, query: str) -> str:
        """System-prompt block of memories relevant to ``query`` (empty if none).

        Hybrid retrieval (semantic + keyword) — only the top-k entries that
        match the request reach the prompt (MEM-005). Async because the
        semantic channel embeds the query.
        """
        if self.memories is None:
            return ""
        from agent_core.memory import memory_prompt

        return memory_prompt(await self.memories.aretrieve(query))

    # ---------------------------------------------------------------- queries

    def get_run(self, run_id: str) -> Run:
        """Return the run with ``run_id``."""
        try:
            return self._runs[run_id]
        except KeyError:
            raise RegistryError(kind="run", key=run_id, detail="not found") from None

    def live_usage(self, run_id: str) -> RunUsage | None:
        """Usage accrued so far, live for an executing run.

        ``run.usage`` is only written when execution ends (the executor's
        finally block), so a *running* task would otherwise report no stats.
        The live collector (attached by ``execute_run``) accumulates tokens and
        call counts as the graph runs; this surfaces that instead, so the
        console's top stats update while a task is in flight.
        """
        collector = self._collectors.get(run_id)
        if collector is not None:
            return collector.usage
        run = self._runs.get(run_id)
        return run.usage if run is not None else None

    def get_task(self, task_id: str) -> Task:
        """Return the conversation with ``task_id``."""
        try:
            return self._tasks[task_id]
        except KeyError:
            raise RegistryError(kind="task", key=task_id, detail="not found") from None

    def list_tasks(self) -> list[Task]:
        """Snapshot of all conversations, in creation order."""
        return list(self._tasks.values())

    def list_runs(self) -> list[Run]:
        """Snapshot of all runs, in creation order."""
        return list(self._runs.values())

    def task_root_runs(self, task_id: str) -> list[Run]:
        """Root runs of a conversation, in creation order (each is one turn)."""
        return [
            run
            for run in self._runs.values()
            if run.task_id == task_id and run.parent_run_id is None
        ]

    def task_active_run(self, task_id: str) -> Run | None:
        """The conversation's most recently created root run, if any."""
        runs = self.task_root_runs(task_id)
        return runs[-1] if runs else None

    def update_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
        project_id: str | None = None,
    ) -> Task:
        """Rename, pin/unpin or rebind a conversation; returns the updated Task.

        ``project_id`` uses sentinel semantics like the model-config API:
        None keeps the value, "" clears the binding, otherwise it must name a
        registered project.
        """
        task = self.get_task(task_id)
        update: dict[str, Any] = {}
        if title is not None:
            title = title.strip()
            if not title:
                raise StateError(
                    "Task title cannot be empty", details={"task_id": task_id}
                )
            update["title"] = title
        if pinned is not None:
            update["pinned"] = pinned
        if project_id is not None:
            if project_id:
                self.projects.get(project_id)  # fail fast on unknown projects
                update["project_id"] = project_id
            else:
                update["project_id"] = None
        if update:
            updated = task.model_copy(update=update)
            self._tasks[task_id] = updated
            self._save_task(updated)
            return updated
        return task

    def mark_task_read(self, task_id: str) -> Task:
        """Advance the conversation's read marker to its newest turn."""
        task = self.get_task(task_id)
        marker = task.turns[-1].id if task.turns else None
        if marker is not None and task.last_read_turn_id != marker:
            updated = task.model_copy(update={"last_read_turn_id": marker})
            self._tasks[task_id] = updated
            self._save_task(updated)
            return updated
        return task

    async def compact_task(self, task_id: str, *, keep: int = 6) -> dict[str, Any]:
        """Force-summarize the conversation thread (long-conversation rescue).

        The summarization middleware only fires near the context ceiling —
        far later than a conversation actually becomes slow and expensive.
        This shrinks the thread to a summary plus the last ``keep`` messages
        on demand: the raw history is offloaded next to the task so nothing
        is lost, and the follow-up prefill drops accordingly. Running tasks
        are refused; compacting a mid-flight thread would race the agent.
        """
        task = self.get_task(task_id)
        active = self.task_active_run(task_id)
        if active is not None and not active.status.is_terminal:
            raise StateError(
                f"Task '{task_id}' is running; stop it before compacting",
                details={"task_id": task_id, "run_id": active.id},
            )
        if task.thread_id is None:
            raise StateError(
                f"Task '{task_id}' has no conversation thread to compact",
                details={"task_id": task_id},
            )
        spec = self.agents.get(task.agent_id)
        await self._ensure_checkpointer_ready()
        graph = self.builder.build(spec)
        from langchain_core.runnables import RunnableConfig
        config: RunnableConfig = {"configurable": {"thread_id": task.thread_id}}
        state = await graph.aget_state(config)
        messages = list((state.values or {}).get("messages", []))
        before = len(messages)
        if before <= keep + 2:
            return {
                "compacted": False,
                "before": before,
                "reason": f"仅 {before} 条消息，无需压缩",
            }
        transcript = []
        for m in messages[:-keep]:
            content = m.content if isinstance(m.content, str) else extract_text(m.content)
            transcript.append(f"[{getattr(m, 'type', 'message')}] {content[:2000]}")
        prompt = (
            "把以下 agent 工作对话压缩为要点摘要，保留：用户的目标与要求、"
            "已完成的工作与产物（文件名/路径等具体信息）、重要事实与决定、"
            "未完成的事项。用中文要点列表输出，不要寒暄。\n\n"
            + "\n".join(transcript)
        )[:60000]
        from agent_core.runtime.model import build_model

        model = build_model(spec.model)
        result = await model.ainvoke(prompt)
        summary = extract_text(result.content).strip()
        if not summary:
            raise StateError("summarization model returned empty output")
        task_dir = Path(get_settings().workspace_dir) / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        offload = task_dir / f"conversation-history-{stamp}.md"
        offload.write_text("\n\n".join(transcript), encoding="utf-8")
        summary_msg = HumanMessage(
            content=(
                f"（此前 {before} 条消息已压缩为下面的摘要；"
                f"完整原始记录见 {offload.name}）\n\n{summary}"
            )
        )
        await graph.aupdate_state(
            config,
            {
                "messages": [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    summary_msg,
                    *messages[-keep:],
                ]
            },
        )
        return {
            "compacted": True,
            "before": before,
            "after": keep + 1,
            "summary_chars": len(summary),
            "offload": str(offload),
        }

    async def cleanup_orphan_checkpoints(self) -> int:
        """Delete LangGraph threads whose task no longer exists (boot-time GC).

        Every conversation turn appends full-state snapshots to the
        checkpoints database; deleting a task used to strand its thread there
        forever, so long-lived deployments accumulated hundreds of MB of dead
        history. Runs after the delete-fix stop creating orphans; this pass
        reclaims the ones created before it. Best-effort: any failure is
        logged and swallowed — startup must not depend on GC.
        """
        import logging

        import aiosqlite

        from agent_core.persistence.checkpointer import _sibling_checkpoints_file

        if self._store is None or get_settings().database_url is None:
            return 0
        await self._ensure_checkpointer_ready()
        delete_thread = getattr(self.checkpointer, "adelete_thread", None)
        if delete_thread is None:
            return 0
        alive = {task.thread_id for task in self._tasks.values() if task.thread_id}
        path = _sibling_checkpoints_file(str(get_settings().database_url).removeprefix("sqlite:///"))
        async with aiosqlite.connect(str(path)) as con:
            rows = await con.execute_fetchall("SELECT DISTINCT thread_id FROM checkpoints")
        orphans = [tid for (tid,) in rows if tid not in alive]
        for tid in orphans:
            await delete_thread(tid)
        if orphans:
            logging.getLogger(__name__).info(
                "checkpoint GC: removed %d orphaned thread(s)", len(orphans)
            )
        return len(orphans)

    async def delete_task(self, task_id: str) -> None:
        """Delete a conversation, every run it produced, and its checkpoints.

        Rejected while the conversation's active run is still non-terminal —
        deleting a running task would strand its execution. The LangGraph
        thread holds the full replayed message state (hundreds of KB per
        conversation, growing every step); leaving it behind after the task
        is gone made the checkpoints database grow forever.
        """
        self.get_task(task_id)  # 404 on unknown ids
        active = self.task_active_run(task_id)
        if active is not None and not active.status.is_terminal:
            raise StateError(
                f"Task '{task_id}' has an active run in status '{active.status.value}'",
                details={"task_id": task_id, "run_id": active.id},
            )
        task = self._tasks.get(task_id)
        thread_id = task.thread_id if task is not None else None
        for run in self.task_root_runs(task_id):
            self._runs.pop(run.id, None)
            self._running.pop(run.id, None)
            self._collectors.pop(run.id, None)
            if self._store is not None:
                self._store.delete_run(run.id)
        self._tasks.pop(task_id, None)
        if self._store is not None:
            self._store.delete_task(task_id)
        if thread_id is not None:
            await self._ensure_checkpointer_ready()
            delete_thread = getattr(self.checkpointer, "adelete_thread", None)
            if delete_thread is not None:
                await delete_thread(thread_id)

    def task_input(self, run: Run) -> str:
        """The task text a run was created for (empty for restored strangers)."""
        stored = run.metadata.get("input")
        if stored:
            return str(stored)
        task = self._tasks.get(run.task_id)
        return task.input if task else ""

    def task_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        """Aggregate every artifact produced across all of a conversation's runs.

        Each root run records the files it created in ``metadata["artifacts"]``
        at finish; a follow-up message starts a fresh run, so looking at only
        the active run would drop earlier turns' outputs. Merging all runs (in
        task order) keeps the 产物 panel showing the whole conversation's
        deliverables, deduplicated by path. Every entry carries the ``run_id``
        that produced it so the console can build a download URL.

        The ``path`` here is the *task-relative* path (what tools wrote); the
        console prefixes ``tasks/<task_id>/`` when it builds the download URL,
        so files with the same name in different conversations never collide.
        """
        merged: dict[str, dict[str, Any]] = {}
        for run in self._runs.values():
            if run.task_id != task_id:
                continue
            for artifact in run.metadata.get("artifacts") or []:
                entry = dict(artifact)
                entry.setdefault("run_id", run.id)
                merged[str(entry.get("path"))] = entry
        return list(merged.values())

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
            try:
                task = Task.model_validate_json(data)
            except ValidationError:
                # Pre-conversation rows carried only input; keep them as
                # one-shot conversations so their runs still resolve.
                raw = json.loads(data)
                task = Task(
                    id=raw.get("id") or new_id(),
                    agent_id="unknown",
                    title=make_title(raw.get("input", "")),
                    input=raw.get("input", ""),
                    metadata=raw.get("metadata") or {},
                )
                self._save_task(task)
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

    def create_conversation(
        self,
        agent_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> Task:
        """Start a new conversation: create its Task and the first root run."""
        spec = self.agents.get(agent_id)  # fail fast on unknown agents
        if project_id is not None:
            self.projects.get(project_id)  # fail fast on unknown projects
        task = self._new_task(spec.id, text, metadata=metadata, project_id=project_id)
        self.create_run(spec.id, text, task=task)
        return task

    def create_run(
        self,
        agent_id: str,
        task_input: str,
        *,
        parent_run_id: str | None = None,
        thread_id: str | None = None,
        task: Task | None = None,
    ) -> Run:
        """Create (but do not start) a run of ``agent_id`` for ``task_input``.

        - ``task`` attaches a root run to an existing conversation (follow-up);
          it reuses the conversation's thread so the agent sees the whole
          history.
        - ``parent_run_id`` makes a nested run (sub-agent, verifier): it
          inherits the parent's conversation and carries no thread of its own.
        - Neither: a one-shot conversation is created for this run.
        """
        spec = self.agents.get(agent_id)  # fail fast on unknown agents
        if parent_run_id is not None:
            parent = self._runs.get(parent_run_id)
            if parent is not None:
                conversation = task or self._tasks[parent.task_id]
            else:
                conversation = task or self._new_task(spec.id, task_input)
            thread = None
        elif task is not None:
            conversation = task
            thread = thread_id or conversation.thread_id
        else:
            conversation = self._new_task(spec.id, task_input)
            thread = thread_id or conversation.thread_id
        run = Run(
            task_id=conversation.id,
            agent_id=spec.id,
            parent_run_id=parent_run_id,
            thread_id=thread,
        )
        run.metadata["input"] = task_input
        self._runs[run.id] = run
        if run.parent_run_id is None:
            conversation.add_user_turn(task_input, run_id=run.id)
            self._save_task(conversation)
        self._save_run(run)
        return run

    def _new_task(
        self,
        agent_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> Task:
        """Create and register a fresh conversation owned by ``agent_id``."""
        task = Task(
            agent_id=agent_id,
            title=make_title(text),
            input=text,
            thread_id=new_id(),
            project_id=project_id,
            metadata=dict(metadata or {}),
        )
        self._tasks[task.id] = task
        self._save_task(task)
        return task

    def _save_task(self, task: Task) -> None:
        if self._store is not None:
            self._store.save_task(task.id, task.model_dump_json())

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
        task_token = current_task_id.set(run.task_id)
        root_token = current_task_root.set(self.task_root(run.task_id))
        query_token = current_query.set(
            str(run.metadata.get("input") or task.input)
        )
        override = run.metadata.get("model")
        model_token = (
            current_model_override.set(str(override)) if override else None
        )
        collector = UsageCollector()
        self._collectors[run.id] = collector
        heartbeat = asyncio.create_task(self._heartbeat(run))
        memory_token = None
        skills_token = None
        try:
            await self._ensure_checkpointer_ready()
            # Enabled skill sources, so run_code can mount the same read-only
            # /skills/<id> view the file tools see (otherwise a skill script the
            # SKILL.md tells the agent to run is invisible inside the sandbox).
            skills_token = current_skill_mounts.set(self._skill_mounts())
            # Retrieve relevant long-term memory before building the graph: the
            # build is synchronous but semantic retrieval is async, so compute
            # the block here and publish it via a context var.
            if self.memories is not None:
                block = await self._memory_block(str(run.metadata.get("input") or task.input))
                memory_token = current_memory_block.set(block)
            graph = self.builder.build(spec)
            # Static context parts (tool schemas, skill manifests) for the
            # console's context breakdown; message tokens come from the
            # collector's per-call estimates. Stub builders (tests) may not
            # implement it.
            context_breakdown = getattr(self.builder, "context_breakdown", None)
            if context_breakdown is not None:
                run.metadata["context_breakdown"] = context_breakdown(spec)
            output = await self.executor.execute(
                graph,
                run=run,
                input_text=run.metadata.get("input") or task.input,
                spec=spec,
                collector=collector,
                thread_id=run.thread_id if run.parent_run_id is None else None,
            )
            output = await self._self_verify(run, task, spec, graph, output, collector)
            self._transition(run, RunStatus.COMPLETED)
            self.fanout.emit(
                EventType.RUN_FINISHED, run=run, agent_id=run.agent_id, output=output
            )
            if run.parent_run_id is None:
                self._record_assistant_turn(run, output)
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
            heartbeat.cancel()
            self._collect_artifacts(run)
            self._collectors.pop(run.id, None)
            self.loop_guard.forget_run(run.id)
            current_run.reset(run_token)
            current_task_id.reset(task_token)
            current_task_root.reset(root_token)
            current_query.reset(query_token)
            if memory_token is not None:
                current_memory_block.reset(memory_token)
            if skills_token is not None:
                current_skill_mounts.reset(skills_token)
            if model_token is not None:
                current_model_override.reset(model_token)
        return run

    def task_root(self, task_id: str) -> Path | None:
        """The filesystem root a conversation works in, or None for the default.

        Tasks bound to a project work directly inside the project's directory;
        everything else uses the anonymous ``workspace/tasks/<task_id>/``.
        A missing project (removed after the task was bound) falls back to the
        default so old conversations stay runnable.
        """
        task = self._tasks.get(task_id)
        if task is not None and task.project_id is not None:
            try:
                return self.projects.get(task.project_id).path
            except RegistryError:
                return None
        return None

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

    async def _ensure_checkpointer_ready(self) -> None:
        """Run the saver's one-time setup (migrations) before the first use."""
        if self._checkpointer_ready:
            return
        setup = getattr(self.checkpointer, "setup", None)
        if setup is not None:
            result = setup()
            if asyncio.iscoroutine(result):
                await result
        self._checkpointer_ready = True

    def _collect_artifacts(self, run: Run) -> None:
        """Record the files this run created in the task's working directory.

        Only top-level runs collect: nested runs (verifier) share the task
        root and would double-claim the same files. The scan is bounded to the
        task's root — ``workspace/tasks/<task_id>/`` or the bound project
        directory — so a concurrent task's files can never leak in; tools
        that explicitly claimed artifacts (run_code) are merged in and take
        precedence.
        """
        if run.parent_run_id is not None:
            return
        workspace = Path(get_settings().workspace_dir)
        since = run.created_at.timestamp() - 2.0
        merged: dict[str, dict[str, Any]] = {
            str(a["path"]): a for a in claimed_artifacts(run.task_id)
        }
        root = self.task_root(run.task_id)
        if root is not None:
            # Explicit claims take precedence: the scan only fills paths that
            # were not claimed, so the artifact contract (sha256/mime/…) is
            # never clobbered by a bare directory listing (I-06).
            for a in scan_workspace_artifacts(root, since_ts=since):
                merged.setdefault(str(a["path"]), a)
        else:
            for a in scan_task_artifacts(workspace, run.task_id, since_ts=since):
                merged.setdefault(str(a["path"]), a)
        clear_claims(run.task_id)
        if merged:
            # Every artifact gets the explicit contract (id/mime/sha256) even
            # when it was discovered by the directory scan, not an explicit
            # claim — nothing in production calls register_artifact, so this is
            # the only place the manifest can be completed (ART-001).
            from agent_core.artifacts import enrich_artifact

            base = root or (workspace / "tasks" / run.task_id)
            run.metadata["artifacts"] = [
                enrich_artifact(record, base, task_id=run.task_id, run_id=run.id)
                for record in merged.values()
            ]
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
        return await self.executor.execute(
            graph, run=run, input_text=task_input, spec=spec, collector=collector
        )

    def _record_assistant_turn(self, run: Run, output: str) -> None:
        """Append the agent's answer to the conversation (root runs only)."""
        conversation = self._tasks.get(run.task_id)
        if conversation is None:
            return
        # Carry the run id so the console can show that reply's usage/stats.
        conversation.add_assistant_turn(output, run_id=run.id)
        self._save_task(conversation)

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
