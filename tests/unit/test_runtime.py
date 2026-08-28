"""Unit tests for AgentRuntime: run lifecycle, events, timeout, cancellation."""

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agent_core.domain.agent import AgentLimits, AgentSpec
from agent_core.domain.task import RunStatus
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import AgentError, RegistryError, StateError
from agent_core.observability.trace import InMemoryTracer
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.context import current_agent_id, current_run_id
from agent_core.runtime.runtime import AgentRuntime


class FakeGraph:
    """Stands in for a compiled DeepAgents graph."""

    def __init__(self, reply: str = "done", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.seen_run_id: str | None = None
        self.seen_agent_id: str | None = None
        self.last_input: Any = None

    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        self.seen_run_id = current_run_id.get()
        self.seen_agent_id = current_agent_id.get()
        self.last_input = state
        if self.error is not None:
            raise self.error
        return {"messages": [AIMessage(content=self.reply)]}


class SlowGraph:
    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        await asyncio.sleep(5)
        return {"messages": [AIMessage(content="late")]}


class StubBuilder:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def build(self, spec: Any) -> Any:
        return self._graph


def make_runtime(graph: Any) -> tuple[AgentRuntime, InMemoryTracer]:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper", model="openai:gpt-4o-mini"))
    tracer = InMemoryTracer()
    runtime = AgentRuntime(
        agents, ToolRegistry(), SkillRegistry(), tracer=tracer, builder=StubBuilder(graph)
    )
    return runtime, tracer


def event_types(tracer: InMemoryTracer, run_id: str) -> list[EventType]:
    return [event.event_type for event in tracer.get_events(run_id)]


class TestExecuteRun:
    async def test_happy_path_completes_and_traces(self) -> None:
        graph = FakeGraph(reply="all done")
        runtime, tracer = make_runtime(graph)
        run = runtime.create_run("helper", "hello")

        result = await runtime.execute_run(run)

        assert result.status is RunStatus.COMPLETED
        assert result.finished_at is not None
        assert graph.last_input == {"messages": [{"role": "user", "content": "hello"}]}
        assert event_types(tracer, run.id) == [
            EventType.RUN_STATUS_CHANGED,
            EventType.RUN_STARTED,
            EventType.AGENT_STARTED,
            EventType.AGENT_FINISHED,
            EventType.RUN_STATUS_CHANGED,
            EventType.RUN_FINISHED,
        ]

    async def test_context_vars_visible_to_graph(self) -> None:
        graph = FakeGraph()
        runtime, _ = make_runtime(graph)
        run = runtime.create_run("helper", "hello")

        await runtime.execute_run(run)

        assert graph.seen_run_id == run.id
        assert graph.seen_agent_id == "helper"

    async def test_agent_error_fails_run(self) -> None:
        runtime, tracer = make_runtime(FakeGraph(error=AgentError("boom")))
        run = runtime.create_run("helper", "hello")

        result = await runtime.execute_run(run)

        assert result.status is RunStatus.FAILED
        assert result.error == "boom"
        assert EventType.RUN_FAILED in event_types(tracer, run.id)

    async def test_unexpected_error_is_normalized_and_fails_run(self) -> None:
        runtime, _ = make_runtime(FakeGraph(error=ValueError("crash")))
        run = runtime.create_run("helper", "hello")

        result = await runtime.execute_run(run)

        assert result.status is RunStatus.FAILED
        assert "crash" in (result.error or "")

    async def test_timeout_transitions_to_timeout(self) -> None:
        agents = AgentRegistry()
        agents.register(
            AgentSpec(id="slow", name="Slow", limits=AgentLimits(timeout_seconds=0.05))
        )
        runtime = AgentRuntime(
            agents, ToolRegistry(), SkillRegistry(), builder=StubBuilder(SlowGraph())
        )
        run = runtime.create_run("slow", "hello")

        result = await runtime.execute_run(run)

        assert result.status is RunStatus.TIMEOUT
        assert "timed out" in (result.error or "")

    async def test_executing_terminal_run_raises(self) -> None:
        runtime, _ = make_runtime(FakeGraph())
        run = runtime.create_run("helper", "hello")
        await runtime.execute_run(run)

        with pytest.raises(StateError):
            await runtime.execute_run(run)

    async def test_unknown_agent_raises(self) -> None:
        runtime, _ = make_runtime(FakeGraph())

        with pytest.raises(RegistryError):
            runtime.create_run("ghost", "hello")


class TestCancellation:
    async def test_cancel_running_run(self) -> None:
        runtime, _ = make_runtime(SlowGraph())
        run = runtime.create_run("helper", "hello")

        task = runtime.submit_run(run)
        await asyncio.sleep(0.05)
        runtime.cancel_run(run.id)
        await task

        assert run.status is RunStatus.CANCELLED

    async def test_cancel_created_run_without_executing(self) -> None:
        runtime, _ = make_runtime(FakeGraph())
        run = runtime.create_run("helper", "hello")

        runtime.cancel_run(run.id)

        assert run.status is RunStatus.CANCELLED

    async def test_cancel_terminal_run_raises(self) -> None:
        runtime, _ = make_runtime(FakeGraph())
        run = runtime.create_run("helper", "hello")
        await runtime.execute_run(run)

        with pytest.raises(StateError):
            runtime.cancel_run(run.id)

    async def test_get_run_unknown_raises(self) -> None:
        runtime, _ = make_runtime(FakeGraph())

        with pytest.raises(RegistryError):
            runtime.get_run("missing")
