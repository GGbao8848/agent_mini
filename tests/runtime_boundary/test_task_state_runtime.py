"""Task-state integration with the real runtime (R21).

The reducer is pure and unit-tested; these tests prove the *runtime* wires it
up: a run's lifecycle/plan events reach the persisted state, the task-state
block is injected into the next turn's system prompt, and the API surfaces it.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from agent_core.api.app import create_app
from agent_core.application.service import AgentCoreService
from agent_core.domain.agent import AgentSpec
from agent_core.domain.trace import EventType
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStreamBroker
from agent_core.observability.trace import InMemoryTracer
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.context import current_run, get_current_task_state_block
from agent_core.runtime.runtime import AgentRuntime


class SimpleGraph:
    """Stub graph that declares a plan (as ``update_plan`` would) then finishes."""

    def __init__(self, runtime: AgentRuntime, *, capture: list[str] | None = None) -> None:
        self._runtime = runtime
        self._capture = capture

    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        run = current_run.get()
        assert run is not None
        if self._capture is not None:
            self._capture.append(get_current_task_state_block())
        self._runtime.fanout.emit(
            EventType.PLAN_UPDATED,
            run=run,
            agent_id=run.agent_id,
            tool="update_plan",
            metadata={
                "steps": [{"description": "步骤一"}, {"description": "步骤二"}],
                "current_index": 1,
                "next_action": "做第二步",
            },
        )
        return {"messages": [AIMessage(content="done")]}


class StubBuilder:
    def __init__(self, runtime: AgentRuntime, *, capture: list[str] | None = None) -> None:
        self._runtime = runtime
        self._capture = capture

    def build(self, spec: Any) -> Any:
        return SimpleGraph(self._runtime, capture=self._capture)


def make_service(*, capture: list[str] | None = None) -> AgentCoreService:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="worker", name="Worker"))
    tools = ToolRegistry()
    skills = SkillRegistry()
    runtime = AgentRuntime(agents, tools, skills, tracer=InMemoryTracer())
    runtime.builder = StubBuilder(runtime, capture=capture)
    mcp_registry = MCPRegistry()
    mcp = MCPManager(mcp_registry, tools, credentials=None)
    broker = EventStreamBroker(runtime.bus)
    return AgentCoreService(
        runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker
    )


@pytest.fixture()
def service() -> AgentCoreService:
    return make_service()


@pytest.fixture()
def client(service: AgentCoreService) -> Any:
    app = create_app(service)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_run_records_task_state() -> None:
    """I-20/I-21: a completed run leaves a retrievable, evidence-based state."""
    service = make_service()
    task = await service.submit_run("worker", "写一份报告", wait=True)
    state = service.runtime.task_state(task.id)
    assert state is not None
    assert state.goal == "写一份报告"
    assert state.status == "completed"
    assert state.run_count == 1
    assert [s.description for s in state.steps] == ["步骤一", "步骤二"]
    assert state.next_action == "做第二步"


async def test_task_state_block_injected_next_turn() -> None:
    """The recorded plan reaches the next turn's system prompt."""
    captured: list[str] = []
    service = make_service(capture=captured)
    task = await service.submit_run("worker", "写一份报告", wait=True)
    captured.clear()  # discard the first turn's (empty) block
    await service.send_message(task.id, "继续", wait=True)
    assert captured, "graph did not run"
    assert "任务状态" in captured[-1]
    assert "步骤一" in captured[-1]


async def test_task_state_endpoint(client: Any) -> None:
    created = await client.post("/v1/tasks", json={"agent_id": "worker", "input": "做报表"})
    task_id = created.json()["id"]
    response = await client.get(f"/v1/tasks/{task_id}/state")
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["goal"] == "做报表"
    assert [s["description"] for s in body["steps"]] == ["步骤一", "步骤二"]


async def test_task_state_endpoint_unknown_task_404(client: Any) -> None:
    response = await client.get("/v1/tasks/nope/state")
    assert response.status_code == 404


async def test_delete_task_removes_state() -> None:
    service = make_service()
    task = await service.submit_run("worker", "写一份报告", wait=True)
    assert service.runtime.task_state(task.id) is not None
    await service.runtime.delete_task(task.id)
    assert service.runtime.task_state(task.id) is None
