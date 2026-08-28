"""Smoke test: real MCP stdio round trip (no network needed).

Connects Agent Core's MCPManager to the local demo server, discovers its
tools, calls one through the Tool Registry handler, then disconnects.
Usage: uv run python scripts/smoke_mcp.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
from agent_core.mcp import EnvCredentialResolver, MCPManager
from agent_core.registries import MCPRegistry, ToolRegistry

DEMO_SERVER = Path(__file__).parent.parent / "examples" / "mcp_demo_server.py"


async def main() -> int:
    registry = MCPRegistry()
    registry.register(
        MCPServerDefinition(
            id="demo",
            name="Demo MCP Server",
            transport=MCPTransport.STDIO,
            endpoint=f"python {DEMO_SERVER}",
        )
    )
    tools = ToolRegistry()
    manager = MCPManager(registry, tools, credentials=EnvCredentialResolver())

    names = await manager.connect("demo")
    print(f"connected; tools: {names}")

    handler = tools.handler_for("demo_add")
    result = await handler(a=19, b=23)
    print(f"demo_add(19, 23) -> {result!r}")

    await manager.disconnect("demo")
    print(f"disconnected; status={registry.get('demo').status.value}")

    ok = result == "19 + 23 = 42" and not manager.is_connected("demo")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
