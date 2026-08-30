"""End-to-end smoke test: the FastAPI layer over a real model and real MCP.

Drives the actual HTTP routes (via ASGI transport) to register an MCP server,
connect it to examples/mcp_demo_server.py, run an agent with a real
OpenRouter model, and consume the SSE event stream.
Usage: uv run --env-file .env python scripts/smoke_api.py
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from agent_core.api.app import create_app
from agent_core.application.bootstrap import default_service
from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec

get_settings()  # applies AGENT_CORE_PROXY_URL to HTTP(S)_PROXY before clients connect

MODEL = "openrouter:minimax/minimax-m3:free"
MCP_ENDPOINT = "python examples/mcp_demo_server.py"


async def main() -> int:
    service = default_service()
    service.runtime.agents.register(
        AgentSpec(
            id="calculator",
            name="Calculator",
            model=MODEL,
            system_prompt="Use the add tool when asked about sums.",
            tools=["demo_add"],
        )
    )
    app = create_app(service)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = (await client.get("/healthz")).json()
        print("healthz:", health)

        servers = await client.get("/v1/mcp/servers")
        print("servers before:", servers.json())

        response = await client.post(
            "/v1/mcp/servers",
            json={"id": "demo", "name": "Demo", "transport": "stdio", "endpoint": MCP_ENDPOINT},
        )
        assert response.status_code == 201, response.text

        response = await client.post("/v1/mcp/servers/demo/connect")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "healthy"
        tools = (await client.get("/v1/tools")).json()
        print("tools after connect:", [tool["name"] for tool in tools])
        assert "demo_add" in [tool["name"] for tool in tools]

        response = await client.post(
            "/v1/tasks",
            params={"wait": "true"},
            json={"agent_id": "calculator", "input": "What is 19 + 23? Use the add tool."},
        )
        assert response.status_code == 201, response.text
        task = response.json()
        print("task status:", task["status"])
        print("task active_run_id:", task["active_run_id"])
        assert task["status"] == "completed", task
        run_id = task["active_run_id"]
        run = (await client.get(f"/v1/runs/{run_id}")).json()
        assert run["status"] == "completed", run
        assert "42" in str(run["output"]), run["output"]

        async with client.stream("GET", f"/v1/runs/{run_id}/events") as stream:
            text = "".join([chunk async for chunk in stream.aiter_text()])
        event_types = [
            line.removeprefix("event: ")
            for line in text.splitlines()
            if line.startswith("event: ")
        ]
        print("sse events:", event_types)
        assert "run_finished" in event_types

        response = await client.post("/v1/mcp/servers/demo/disconnect")
        assert response.status_code == 200
        print("disconnected; status:", response.json()["status"])

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
