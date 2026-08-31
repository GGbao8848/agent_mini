"""API layer tests: every router, the error funnel, and SSE, over ASGI.

The service under test is the real one (real runtime with a stub graph, real
MCP manager with a fake session opener) so the tests exercise the full
transport → application → runtime path without a model provider.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from agent_core.api.app import create_app
from agent_core.application.service import AgentCoreService
from agent_core.domain.action import Action, RiskLevel
from agent_core.domain.agent import AgentSpec
from agent_core.domain.skill import SkillManifest
from agent_core.domain.tool import ToolDefinition
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStreamBroker
from agent_core.observability.trace import InMemoryTracer
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.context import current_run
from agent_core.runtime.runtime import AgentRuntime


class FakeGraph:
    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        assert current_run.get() is not None
        return {"messages": [AIMessage(content=f"echo: {state['messages'][-1]['content']}")]}


class SlowGraph:
    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {"messages": [AIMessage(content="late")]}


class StubBuilder:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def build(self, spec: Any) -> Any:
        return self._graph


class FakeSession:
    async def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="demo_echo",
                description="Echo",
                input_schema={"type": "object"},
                source="mcp",
                metadata={"mcp_server": "demo", "mcp_tool": "echo"},
            )
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return json.dumps(arguments)


def fake_opener(session: Any) -> Any:
    @asynccontextmanager
    async def opener(definition: Any, credential: str | None) -> AsyncIterator[Any]:
        yield session

    return opener


def broken_opener() -> Any:
    @asynccontextmanager
    async def opener(definition: Any, credential: str | None) -> AsyncIterator[Any]:
        raise RuntimeError("connection refused")
        yield  # pragma: no cover

    return opener


SERVER_PAYLOAD = {"id": "demo", "name": "Demo", "transport": "stdio", "endpoint": "python demo.py"}


def make_service(graph: Any = None, *, broken_mcp: bool = False) -> AgentCoreService:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper"))
    agents.register(AgentSpec(id="greeter", name="Greeter"))
    tools = ToolRegistry()
    skills = SkillRegistry()
    skills.register(SkillManifest(id="greet", name="Greet", description="Say hello"))
    tracer = InMemoryTracer()
    runtime = AgentRuntime(
        agents, tools, skills, tracer=tracer, builder=StubBuilder(graph or FakeGraph())
    )
    mcp_registry = MCPRegistry()
    opener = broken_opener() if broken_mcp else fake_opener(FakeSession())
    mcp = MCPManager(mcp_registry, tools, credentials=None, opener=opener)
    broker = EventStreamBroker(runtime.bus)
    return AgentCoreService(runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker)


@pytest.fixture()
def service() -> AgentCoreService:
    return make_service()


@pytest.fixture()
def client(service: AgentCoreService) -> Any:
    app = create_app(service)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_healthz(client: Any) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class TestRegistryRoutes:
    async def test_list_and_get_agents(self, client: Any) -> None:
        response = await client.get("/v1/agents")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == ["helper", "greeter"]

        response = await client.get("/v1/agents/helper")
        assert response.status_code == 200
        assert response.json()["name"] == "Helper"

    async def test_get_unknown_agent_maps_to_404(self, client: Any) -> None:
        response = await client.get("/v1/agents/nope")
        assert response.status_code == 404
        body = response.json()["error"]
        assert body["code"] == "RegistryError"
        assert body["retryable"] is False

    async def test_list_skills(self, client: Any) -> None:
        response = await client.get("/v1/skills")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == ["greet"]

    async def test_upload_skill_zip(self, client: Any, tmp_path: Any, monkeypatch: Any) -> None:
        """POST /v1/skills/upload installs a skill from an uploaded zip."""
        from agent_core.api.routes import skills as skills_route
        from agent_core.config.settings import Settings

        # Route resolves the workspace via get_settings() — point it at tmp.
        monkeypatch.setattr(
            skills_route,
            "get_settings",
            lambda: Settings(_env_file=None, workspace_dir=str(tmp_path)),
        )

        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "SKILL.md",
                "---\nname: upload-demo\ndescription: 上传的技能\n---\n# Demo\n",
            )
            zf.writestr("scripts/x.py", "print('x')\n")

        response = await client.post(
            "/v1/skills/upload",
            files={"file": ("skill.zip", buf.getvalue(), "application/zip")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["id"] == "upload-demo"
        assert (tmp_path / ".skills-upload" / "upload-demo" / "SKILL.md").is_file()
        assert "upload-demo" in [s["id"] for s in (await client.get("/v1/skills")).json()]

    async def test_list_tools_includes_availability(self, client: Any) -> None:
        """ToolOut carries available/availability_reason on the wire."""
        from agent_core.domain.tool import ToolDefinition

        client._transport.app.state.service.runtime.tools.register(  # type: ignore[attr-defined]
            ToolDefinition(
                name="flaky",
                description="Flaky",
                metadata={"available": False, "availability_reason": "missing key"},
            ),
            lambda: "ok",
        )

        tools = (await client.get("/v1/tools")).json()
        flaky = next(t for t in tools if t["name"] == "flaky")
        assert flaky["available"] is False
        assert flaky["availability_reason"] == "missing key"
        # Built-ins default to available.
        assert all(t["available"] is True for t in tools if t["name"] != "flaky")


class TestMCPRoutes:
    async def test_register_and_get_server(self, client: Any) -> None:
        payload = {
            "id": "demo",
            "name": "Demo",
            "transport": "streamable_http",
            "endpoint": "http://localhost:9000/mcp",
            "auth_ref": "DEMO_TOKEN",
        }
        response = await client.post("/v1/mcp/servers", json=payload)
        assert response.status_code == 201
        assert response.json()["status"] == "unknown"

        response = await client.get("/v1/mcp/servers/demo")
        assert response.json()["auth_ref"] == "DEMO_TOKEN"

    async def test_duplicate_registration_maps_to_409(self, client: Any) -> None:
        await client.post("/v1/mcp/servers", json=SERVER_PAYLOAD)
        response = await client.post("/v1/mcp/servers", json=SERVER_PAYLOAD)
        assert response.status_code == 409

    async def test_connect_disconnect_cycle(self, client: Any) -> None:
        await client.post("/v1/mcp/servers", json=SERVER_PAYLOAD)

        response = await client.post("/v1/mcp/servers/demo/connect")
        assert response.json()["status"] == "healthy"
        names = [tool["name"] for tool in (await client.get("/v1/tools")).json()]
        assert "demo_echo" in names

        response = await client.post("/v1/mcp/servers/demo/disconnect")
        assert response.json()["status"] == "unknown"
        names = [tool["name"] for tool in (await client.get("/v1/tools")).json()]
        assert "demo_echo" not in names

    async def test_connect_unknown_server_maps_to_404(self, client: Any) -> None:
        response = await client.post("/v1/mcp/servers/ghost/connect")
        assert response.status_code == 404

    async def test_unreachable_server_maps_to_503_retryable(self) -> None:
        app = create_app(make_service(broken_mcp=True))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/v1/mcp/servers", json=SERVER_PAYLOAD)
            response = await client.post("/v1/mcp/servers/demo/connect")
            assert response.status_code == 503
            assert response.json()["error"]["retryable"] is True


class TestTaskRoutes:
    async def test_create_task_wait_returns_completed_with_output(self, client: Any) -> None:
        response = await client.post(
            "/v1/tasks", params={"wait": "true"}, json={"agent_id": "helper", "input": "hi"}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "completed"
        assert body["active_run_id"] is not None
        # The conversation records user + assistant turns.
        assert [turn["role"] for turn in body["turns"]] == ["user", "assistant"]
        assert body["turns"][-1]["content"] == "echo: hi"

    async def test_create_task_unknown_agent_maps_to_404(self, client: Any) -> None:
        response = await client.post("/v1/tasks", json={"agent_id": "ghost", "input": "hi"})
        assert response.status_code == 404

    async def test_get_task_and_list_filter(self, client: Any) -> None:
        body = (
            await client.post(
                "/v1/tasks", params={"wait": "true"}, json={"agent_id": "helper", "input": "yo"}
            )
        ).json()

        response = await client.get(f"/v1/tasks/{body['id']}")
        assert response.json()["id"] == body["id"]
        assert response.json()["agent_id"] == "helper"

        response = await client.get("/v1/tasks", params={"agent_id": "greeter"})
        assert response.json() == []

    async def test_get_run_read_endpoint(self, client: Any) -> None:
        body = (
            await client.post(
                "/v1/tasks", params={"wait": "true"}, json={"agent_id": "helper", "input": "yo"}
            )
        ).json()
        run_id = body["active_run_id"]

        response = await client.get(f"/v1/runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["task_id"] == body["id"]
        assert response.json()["status"] == "completed"

    async def test_send_message_continues_conversation(self, client: Any) -> None:
        body = (
            await client.post(
                "/v1/tasks", params={"wait": "true"}, json={"agent_id": "helper", "input": "hi"}
            )
        ).json()
        task_id = body["id"]

        response = await client.post(
            f"/v1/tasks/{task_id}/messages",
            params={"wait": "true"},
            json={"input": "and now?"},
        )
        assert response.status_code == 201
        followup = response.json()
        assert followup["id"] == task_id  # same conversation
        assert followup["status"] == "completed"
        assert len(followup["turns"]) == 4
        assert followup["active_run_id"] != body["active_run_id"]

        # The sidebar still shows exactly one entry for this conversation.
        tasks = (await client.get("/v1/tasks")).json()
        assert [task["id"] for task in tasks] == [task_id]

    async def test_rename_and_pin_task(self, client: Any) -> None:
        body = (
            await client.post(
                "/v1/tasks", params={"wait": "true"}, json={"agent_id": "helper", "input": "yo"}
            )
        ).json()
        task_id = body["id"]

        renamed = await client.patch(f"/v1/tasks/{task_id}", json={"title": "新名字"})
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "新名字"

        pinned = await client.patch(f"/v1/tasks/{task_id}", json={"pinned": True})
        assert pinned.json()["pinned"] is True
        assert pinned.json()["title"] == "新名字"  # partial update keeps values

    async def test_delete_task(self, client: Any) -> None:
        body = (
            await client.post(
                "/v1/tasks", params={"wait": "true"}, json={"agent_id": "helper", "input": "yo"}
            )
        ).json()
        task_id = body["id"]
        run_id = body["active_run_id"]

        deleted = await client.delete(f"/v1/tasks/{task_id}")
        assert deleted.status_code == 204
        assert (await client.get(f"/v1/tasks/{task_id}")).status_code == 404
        assert (await client.get(f"/v1/runs/{run_id}")).status_code == 404  # runs gone too

    async def test_delete_running_task_maps_to_409(self) -> None:
        app = create_app(make_service(SlowGraph()))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = (await client.post("/v1/tasks", json={"agent_id": "helper", "input": "x"})).json()
            deleted = await client.delete(f"/v1/tasks/{body['id']}")
            assert deleted.status_code == 409
            assert deleted.json()["error"]["code"] == "StateError"

    async def test_cancel_running_task(self) -> None:
        app = create_app(make_service(SlowGraph()))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = (await client.post("/v1/tasks", json={"agent_id": "helper", "input": "x"})).json()
            response = await client.post(f"/v1/tasks/{body['id']}/cancel")
            assert response.status_code == 200

            status = "running"
            for _ in range(100):
                status = (await client.get(f"/v1/tasks/{body['id']}")).json()["status"]
                if status == "cancelled":
                    break
                await asyncio.sleep(0.02)
            assert status == "cancelled"

    async def test_cancel_terminal_task_maps_to_409(self, client: Any) -> None:
        body = (
            await client.post(
                "/v1/tasks", params={"wait": "true"}, json={"agent_id": "helper", "input": "x"}
            )
        ).json()
        response = await client.post(f"/v1/tasks/{body['id']}/cancel")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "StateError"


class TestApprovalRoutes:
    async def test_resolve_flow(self, client: Any, service: AgentCoreService) -> None:
        run = service.runtime.create_run("helper", "hi")
        action = Action(
            run_id=run.id, agent_id="helper", tool_name="delete_all", risk_level=RiskLevel.HIGH
        )
        request = service.runtime.approvals.create(action, reason="risky")

        pending = (await client.get("/v1/approvals/pending")).json()
        assert [item["id"] for item in pending] == [request.id]
        assert pending[0]["risk_level"] == "high"

        response = await client.post(
            f"/v1/approvals/{request.id}/resolve",
            json={"decision": "approved", "resolved_by": "alice"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"
        assert response.json()["resolved_by"] == "alice"

        response = await client.post(
            f"/v1/approvals/{request.id}/resolve", json={"decision": "rejected"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ApprovalError"

    async def test_resolve_unknown_maps_to_404(self, client: Any) -> None:
        response = await client.post("/v1/approvals/ghost/resolve", json={"decision": "approved"})
        assert response.status_code == 404

    async def test_edited_decision_requires_arguments(self, client: Any) -> None:
        response = await client.post("/v1/approvals/whatever/resolve", json={"decision": "edited"})
        assert response.status_code == 422

    async def test_invalid_decision_rejected_by_schema(self, client: Any) -> None:
        response = await client.post(
            "/v1/approvals/whatever/resolve", json={"decision": "expired"}
        )
        assert response.status_code == 422


class TestSSEEvents:
    async def test_run_stream_replays_then_closes(self, client: Any) -> None:
        body = (
            await client.post(
                "/v1/tasks", params={"wait": "true"}, json={"agent_id": "helper", "input": "hi"}
            )
        ).json()
        run_id = body["active_run_id"]

        async with client.stream("GET", f"/v1/runs/{run_id}/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            text = "".join([chunk async for chunk in response.aiter_text()])

        lines = text.splitlines()
        assert "event: run_started" in lines
        assert "event: run_finished" in lines
        data_line = lines[lines.index("event: run_finished") + 1]
        assert data_line.startswith("data: ")
        assert json.loads(data_line.removeprefix("data: "))["output"] == "echo: hi"

    async def test_stream_unknown_run_maps_to_404(self, client: Any) -> None:
        response = await client.get("/v1/runs/ghost/events")
        assert response.status_code == 404
