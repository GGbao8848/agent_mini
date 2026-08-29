"""Orchestration tests: team composition, parallel fan-out, subagent tracing."""

import asyncio
import time
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agent_core.domain.agent import AgentSpec
from agent_core.domain.team import TeamSpec
from agent_core.domain.trace import EventType
from agent_core.observability.emitter import EventFanout
from agent_core.observability.trace import InMemoryTracer
from agent_core.orchestration import Job, compose_team, run_parallel
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime
from agent_core.runtime.subagent_trace import SubagentTraceHandler
from agent_core.runtime.usage import UsageCollector


class StubBuilder:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def build(self, spec: Any) -> Any:
        return self._graph


class ScriptedGraph:
    """Graph that calls the UsageCollector contract then replies after a delay."""

    def __init__(self, reply: str = "done", delay: float = 0.0) -> None:
        self.reply = reply
        self.delay = delay

    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        for callback in (config or {}).get("callbacks") or []:
            if isinstance(callback, UsageCollector):
                callback.on_chat_model_start()
                callback.on_tool_end()
        await asyncio.sleep(self.delay)
        return {"messages": [AIMessage(content=self.reply)]}


def make_runtime(graph: Any) -> AgentRuntime:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="researcher", name="Researcher", description="Finds facts fast"))
    agents.register(AgentSpec(id="writer", name="Writer", description="Writes polished text"))
    return AgentRuntime(agents, ToolRegistry(), SkillRegistry(), builder=StubBuilder(graph))


class TestComposeTeam:
    def test_generated_coordinator_lists_workers_and_registers(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="researcher", name="Researcher", description="Finds facts"))
        agents.register(AgentSpec(id="writer", name="Writer", description="Writes"))

        spec = compose_team(
            agents,
            TeamSpec(id="team-a", name="Team A", worker_agent_ids=["researcher", "writer"]),
        )

        assert spec.id == "team-a"
        assert [ref.agent_id for ref in spec.subagents] == ["researcher", "writer"]
        assert spec.subagents[0].description == "Finds facts"
        assert "issue the ``task`` tool calls" in spec.system_prompt
        assert "- researcher: Finds facts" in spec.system_prompt
        assert agents.get("team-a").id == "team-a"
        assert spec.limits.max_subagents == 2

    def test_recomposition_is_idempotent(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="w", name="W"))
        team = TeamSpec(id="team", name="T", worker_agent_ids=["w"])
        compose_team(agents, team)
        compose_team(agents, team)  # duplicate register must not raise
        assert len(agents.list()) == 2  # worker + replaced coordinator

    def test_lead_cannot_be_own_worker(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="lead", name="Lead"))
        with pytest.raises(Exception, match="cannot also be a worker"):
            compose_team(
                agents,
                TeamSpec(
                    id="team",
                    name="T",
                    lead_agent_id="lead",
                    worker_agent_ids=["lead"],
                ),
            )

    def test_existing_agent_as_lead_keeps_prompt(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="lead", name="Lead", system_prompt="MY STYLE"))
        agents.register(AgentSpec(id="w", name="W"))

        spec = compose_team(
            agents,
            TeamSpec(id="team", name="T", lead_agent_id="lead", worker_agent_ids=["w"]),
        )

        assert spec.system_prompt == "MY STYLE"
        assert [ref.agent_id for ref in spec.subagents] == ["w"]

    def test_coordinator_prompt_demands_verbatim_merge(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="w", name="W"))

        spec = compose_team(agents, TeamSpec(id="team", name="T", worker_agent_ids=["w"]))

        assert "EXACTLY as the worker that" in spec.system_prompt
        assert "never recompute" in spec.system_prompt
        assert "Merge rules for this team" not in spec.system_prompt

    def test_merge_instructions_are_appended(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="w", name="W"))

        spec = compose_team(
            agents,
            TeamSpec(
                id="team",
                name="T",
                worker_agent_ids=["w"],
                merge_instructions="汇率数值必须逐字引用子任务结果",
            ),
        )

        assert "Merge rules for this team:" in spec.system_prompt
        assert "汇率数值必须逐字引用子任务结果" in spec.system_prompt


class TestRunParallel:
    async def test_children_run_concurrently_with_parent_link(self) -> None:
        graph = ScriptedGraph(delay=0.3)
        runtime = make_runtime(graph)
        parent = runtime.create_run("researcher", "parent task")

        started = time.monotonic()
        runs = await run_parallel(
            runtime,
            [Job(agent_id="researcher", input="a"), Job(agent_id="writer", input="b")],
            parent=parent,
        )
        elapsed = time.monotonic() - started

        assert [run.status.value for run in runs] == ["completed", "completed"]
        assert all(run.parent_run_id == parent.id for run in runs)
        assert elapsed < 0.55  # sequential would be ~0.6s
        assert all(run.usage is not None and run.usage.model_calls == 1 for run in runs)

    async def test_concurrency_cap_limits_overlap(self) -> None:
        runtime = make_runtime(ScriptedGraph(delay=0.2))
        jobs = [Job(agent_id="researcher", input=str(i)) for i in range(4)]

        started = time.monotonic()
        await run_parallel(runtime, jobs, max_concurrency=2)
        elapsed = time.monotonic() - started

        assert elapsed >= 0.4  # 4 jobs / 2 slots * 0.2s

    async def test_child_failure_does_not_raise(self) -> None:
        class BoomGraph(ScriptedGraph):
            async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
                raise RuntimeError("boom")

        class PerAgentBuilder:
            def __init__(self, graphs: dict[str, Any]) -> None:
                self._graphs = graphs

            def build(self, spec: Any) -> Any:
                return self._graphs[spec.id]

        agents = AgentRegistry()
        agents.register(AgentSpec(id="bad", name="Bad"))
        agents.register(AgentSpec(id="researcher", name="Researcher"))
        runtime = AgentRuntime(
            agents,
            ToolRegistry(),
            SkillRegistry(),
            builder=PerAgentBuilder({"bad": BoomGraph(), "researcher": ScriptedGraph()}),
        )

        runs = await run_parallel(
            runtime, [Job(agent_id="bad", input="x"), Job(agent_id="researcher", input="y")]
        )

        assert [run.status.value for run in runs] == ["failed", "completed"]
        assert "boom" in (runs[0].error or "")

    async def test_terminal_parent_rejected(self) -> None:
        runtime = make_runtime(ScriptedGraph())
        parent = runtime.create_run("researcher", "x")
        await runtime.execute_run(parent)

        with pytest.raises(ValueError, match="already terminal"):
            await run_parallel(runtime, [Job(agent_id="researcher", input="y")], parent=parent)


class TestSubagentTraceHandler:
    def _handler(self) -> tuple[SubagentTraceHandler, InMemoryTracer, Any]:
        tracer = InMemoryTracer()
        run = RunStub()
        handler = SubagentTraceHandler(EventFanout(tracer), run, {"worker"})
        return handler, tracer, run

    async def test_one_pair_per_delegation(self) -> None:
        import uuid

        handler, tracer, run = self._handler()
        root = uuid.uuid4()

        # Root lead chain: lc_agent_name matches name but lead is not in names.
        handler.on_chain_start(
            {}, {}, run_id=root, name="team-lead", metadata={"lc_agent_name": "team-lead"}
        )
        # Nested middleware node inside the worker: lc_agent_name matches, name differs.
        nested = uuid.uuid4()
        handler.on_chain_start(
            {},
            {},
            run_id=nested,
            name="PatchToolCalls.before_agent",
            metadata={"lc_agent_name": "worker"},
        )
        # The worker's top-level chain.
        worker = uuid.uuid4()
        handler.on_chain_start(
            {}, {}, run_id=worker, name="worker", metadata={"lc_agent_name": "worker"}
        )
        handler.on_chain_end({"messages": [AIMessage(content="sub result")]}, run_id=worker)

        events = tracer.get_events(run.id)
        kinds = [event.event_type for event in events]
        assert kinds == [EventType.SUBAGENT_STARTED, EventType.SUBAGENT_FINISHED]
        assert events[0].metadata["subagent"] == "worker"
        assert events[1].output == "sub result"

    async def test_error_event(self) -> None:
        import uuid

        handler, tracer, run = self._handler()
        worker = uuid.uuid4()
        handler.on_chain_start(
            {}, {}, run_id=worker, name="worker", metadata={"lc_agent_name": "worker"}
        )
        handler.on_chain_error(RuntimeError("sub blew up"), run_id=worker)

        events = tracer.get_events(run.id)
        assert events[-1].error == "sub blew up"


class RunStub:
    """Minimal run stand-in for fanout.emit."""

    id = "stub-run"
    task_id = "stub-task"
    parent_run_id = None
    agent_id = "coordinator"


class TestTeamEndToEnd:
    async def test_team_run_traces_subagents_and_usage(self) -> None:
        """Full team path with a graph simulating two parallel task calls."""

        class TeamGraph:
            async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
                callbacks = (config or {}).get("callbacks") or []
                collector = next(c for c in callbacks if isinstance(c, UsageCollector))
                for handler in callbacks:
                    if isinstance(handler, SubagentTraceHandler):
                        import uuid as _uuid

                        for name in ("researcher", "writer"):
                            run_id = _uuid.uuid4()
                            handler.on_chain_start(
                                {}, {}, run_id=run_id, name=name, metadata={"lc_agent_name": name}
                            )
                            handler.on_chain_end(
                                {"messages": [AIMessage(content=f"{name} result")]}, run_id=run_id
                            )
                collector.on_chat_model_start()
                collector.on_tool_end()
                return {"messages": [AIMessage(content="merged answer")]}

        agents = AgentRegistry()
        agents.register(AgentSpec(id="researcher", name="Researcher", description="Finds facts"))
        agents.register(AgentSpec(id="writer", name="Writer", description="Writes"))
        team = compose_team(
            agents, TeamSpec(id="team", name="Team", worker_agent_ids=["researcher", "writer"])
        )
        tracer = InMemoryTracer()
        runtime = AgentRuntime(
            agents, ToolRegistry(), SkillRegistry(), tracer=tracer, builder=StubBuilder(TeamGraph())
        )

        run = runtime.create_run(team.id, "produce a report")
        await runtime.execute_run(run)

        assert run.status.value == "completed"
        kinds = [event.event_type for event in tracer.get_events(run.id)]
        assert kinds.count(EventType.SUBAGENT_STARTED) == 2
        assert kinds.count(EventType.SUBAGENT_FINISHED) == 2
        assert run.usage is not None and run.usage.model_calls >= 1
