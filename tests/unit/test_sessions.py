"""Multi-turn conversation tests: thread continuation via LangGraph checkpointer.

The stub here is a *real* LangGraph graph compiled with the runtime's
checkpointer — that is the mechanism under test (thread_id → state replay).
"""

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import START, MessagesState, StateGraph

from agent_core.application.service import AgentCoreService
from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStreamBroker
from agent_core.observability.trace import InMemoryTracer
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime


def _echo_node(state: MessagesState) -> dict[str, Any]:
    return {"messages": [AIMessage(content=f"saw-{len(state['messages'])}")]}


class EchoBuilder:
    """Compiles a real LangGraph graph with the runtime's checkpointer."""

    def __init__(self, checkpointer: Any) -> None:
        self.checkpointer = checkpointer

    def build(self, spec: Any) -> Any:
        graph = StateGraph(MessagesState)
        graph.add_node("echo", _echo_node)
        graph.add_edge(START, "echo")
        return graph.compile(checkpointer=self.checkpointer)


def make_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AgentRuntime:
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper"))
    runtime = AgentRuntime(agents, ToolRegistry(), SkillRegistry())
    runtime.builder = EchoBuilder(runtime.checkpointer)
    return runtime


def make_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentCoreService:
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper"))
    tracer = InMemoryTracer()
    runtime = AgentRuntime(agents, ToolRegistry(), SkillRegistry(), tracer=tracer)
    runtime.builder = EchoBuilder(runtime.checkpointer)
    mcp_registry = MCPRegistry()
    mcp = MCPManager(mcp_registry, ToolRegistry(), credentials=None)
    broker = EventStreamBroker(runtime.bus)
    return AgentCoreService(runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker)


def service_output(runtime: AgentRuntime, run: Any) -> str:
    from agent_core.domain.trace import EventType

    for event in runtime.tracer.get_events(run.id):
        if event.event_type is EventType.AGENT_FINISHED:
            return str(event.output)
    return ""


class TestThreadContinuation:
    async def test_followup_replays_history(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = make_runtime(tmp_path, monkeypatch)
        first = await runtime.execute_run(runtime.create_run("helper", "hello"))
        assert first.status.value == "completed"

        followup = runtime.create_run("helper", "and now?", thread_id=first.thread_id)
        await runtime.execute_run(followup)

        # The node sees the state BEFORE its own output: run 1 sees [user];
        # run 2 sees replayed [user, ai] + new user = 3 — the checkpointer
        # replayed the stored conversation.
        assert service_output(runtime, first) == "saw-1"
        assert service_output(runtime, followup) == "saw-3"

    async def test_separate_threads_do_not_mix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = make_runtime(tmp_path, monkeypatch)
        await runtime.execute_run(runtime.create_run("helper", "a"))
        run_b = await runtime.execute_run(runtime.create_run("helper", "b"))
        assert service_output(runtime, run_b) == "saw-1"  # fresh thread

    async def test_nested_runs_have_no_thread(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = make_runtime(tmp_path, monkeypatch)
        root = runtime.create_run("helper", "root")
        nested = runtime.create_run("helper", "nested", parent_run_id=root.id)
        assert nested.thread_id is None
        assert root.thread_id is not None


class TestCheckpointerPersistence:
    async def test_history_survives_runtime_recreation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_CORE_DATABASE_URL", f"sqlite:///{tmp_path}/agent.db")
        runtime1 = make_runtime(tmp_path, monkeypatch)
        first = await runtime1.execute_run(runtime1.create_run("helper", "hello"))
        assert service_output(runtime1, first) == "saw-1"

        # "Second process": a brand-new runtime over the same database.
        runtime2 = make_runtime(tmp_path, monkeypatch)
        followup = runtime2.create_run("helper", "and now?", thread_id=first.thread_id)
        await runtime2.execute_run(followup)

        assert service_output(runtime2, followup) == "saw-3"


class TestSendMessageApi:
    async def test_send_message_creates_linked_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        original = await service.submit_run("helper", "hello", wait=True)

        followup = await service.send_message(original.id, "and now?", wait=True)

        assert followup.thread_id == original.thread_id
        assert followup.id != original.id
        assert followup.status.value == "completed"
