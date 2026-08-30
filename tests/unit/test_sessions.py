"""Multi-turn conversation tests: thread continuation via LangGraph checkpointer.

The stub here is a *real* LangGraph graph compiled with the runtime's
checkpointer — that is the mechanism under test (thread_id → state replay).

A conversation (Task) owns one thread; every turn executes as a root run on
that thread, so the sidebar shows one entry per conversation no matter how
many turns it has.
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
        conversation = runtime.create_conversation("helper", "hello")
        first = runtime.task_active_run(conversation.id)
        assert first is not None
        await runtime.execute_run(first)
        assert first.status.value == "completed"

        followup = runtime.create_run("helper", "and now?", task=conversation)
        assert followup.thread_id == first.thread_id  # same conversation thread
        await runtime.execute_run(followup)

        # The node sees the state BEFORE its own output: run 1 sees [user];
        # run 2 sees replayed [user, ai] + new user = 3 — the checkpointer
        # replayed the stored conversation.
        assert service_output(runtime, first) == "saw-1"
        assert service_output(runtime, followup) == "saw-3"

        # The conversation records every turn; the sidebar has one entry.
        assert [turn.role for turn in conversation.turns] == [
            "user", "assistant", "user", "assistant",
        ]
        assert len(runtime.list_tasks()) == 1
        assert len(runtime.task_root_runs(conversation.id)) == 2

    async def test_separate_conversations_do_not_mix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = make_runtime(tmp_path, monkeypatch)
        conversation_a = runtime.create_conversation("helper", "a")
        run_a = runtime.task_active_run(conversation_a.id)
        assert run_a is not None
        await runtime.execute_run(run_a)

        conversation_b = runtime.create_conversation("helper", "b")
        run_b = runtime.task_active_run(conversation_b.id)
        assert run_b is not None
        await runtime.execute_run(run_b)

        assert service_output(runtime, run_a) == "saw-1"  # fresh threads
        assert service_output(runtime, run_b) == "saw-1"
        assert run_a.thread_id != run_b.thread_id

    async def test_nested_runs_have_no_thread(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = make_runtime(tmp_path, monkeypatch)
        root = runtime.create_run("helper", "root")
        nested = runtime.create_run("helper", "nested", parent_run_id=root.id)
        assert nested.thread_id is None
        assert root.thread_id is not None
        # Nested runs share the parent's conversation and record no turns.
        assert nested.task_id == root.task_id
        assert len(runtime.get_task(root.task_id).turns) == 1  # user turn only


class TestCheckpointerPersistence:
    async def test_history_survives_runtime_recreation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_CORE_DATABASE_URL", f"sqlite:///{tmp_path}/agent.db")
        runtime1 = make_runtime(tmp_path, monkeypatch)
        conversation = runtime1.create_conversation("helper", "hello")
        first = runtime1.task_active_run(conversation.id)
        assert first is not None
        await runtime1.execute_run(first)
        assert service_output(runtime1, first) == "saw-1"

        # "Second process": a brand-new runtime over the same database; the
        # thread state (what the follow-up needs) survives in the checkpointer.
        runtime2 = make_runtime(tmp_path, monkeypatch)
        followup = runtime2.create_run("helper", "and now?", thread_id=first.thread_id)
        await runtime2.execute_run(followup)

        assert service_output(runtime2, followup) == "saw-3"


class TestConversationApi:
    async def test_send_message_continues_same_conversation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        conversation = await service.submit_run("helper", "hello", wait=True)
        assert conversation.turns[0].role == "user"
        assert conversation.turns[-1].role == "assistant"
        first = service.runtime.task_active_run(conversation.id)
        assert first is not None
        assert first.status.value == "completed"

        followup = await service.send_message(conversation.id, "and now?", wait=True)

        # Same conversation object, one more turn; still a single sidebar entry.
        assert followup.id == conversation.id
        assert [turn.role for turn in followup.turns] == [
            "user", "assistant", "user", "assistant",
        ]
        runs = service.runtime.task_root_runs(conversation.id)
        assert len(runs) == 2
        assert runs[0].thread_id == runs[1].thread_id  # same conversation thread
        assert runs[1].status.value == "completed"
        assert len(service.list_tasks()) == 1
        assert len(service.list_runs()) == 2

    async def test_cancel_task_cancels_active_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        # Created but not yet executed — cancellation is deterministic.
        conversation = service.runtime.create_conversation("helper", "hello")
        cancelled = service.cancel_task(conversation.id)
        run = service.runtime.task_active_run(conversation.id)
        assert run is not None and run.status.value == "cancelled"
        assert cancelled.id == conversation.id
