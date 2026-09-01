"""Unit tests for the MCP manager (fake sessions, no real servers)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from agent_core.domain.mcp import MCPServerDefinition, MCPServerStatus, MCPTransport
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import MCPUnavailableError, RegistryError
from agent_core.mcp import EnvCredentialResolver, MCPManager
from agent_core.mcp.client import MCPSession
from agent_core.mcp.connection import SessionOpener
from agent_core.registries import MCPRegistry, ToolRegistry


class FakeSession:
    def __init__(self, tools: list[ToolDefinition], results: dict[str, Any]) -> None:
        self.tools = tools
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[ToolDefinition]:
        return list(self.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        result = self.results[name]
        if isinstance(result, Exception):
            raise result
        return result


def fake_opener(session: FakeSession, *, fail: bool = False) -> SessionOpener:
    @asynccontextmanager
    async def opener(
        definition: MCPServerDefinition, credential: str | None
    ) -> AsyncIterator[MCPSession]:
        if fail:
            raise OSError("connection refused")
        yield session  # type: ignore[misc]

    return opener


def echo_tool() -> ToolDefinition:
    return ToolDefinition(
        name="demo_echo",
        description="Echo text back",
        source=ToolSource.MCP,
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        metadata={"mcp_server": "demo", "mcp_tool": "echo"},
    )


def demo_registry() -> MCPRegistry:
    registry = MCPRegistry()
    registry.register(
        MCPServerDefinition(
            id="demo", name="Demo", transport=MCPTransport.STDIO, endpoint="python demo.py"
        )
    )
    return registry


def make_manager(
    *,
    opener: SessionOpener,
    registry: MCPRegistry | None = None,
    credentials: Any = None,
) -> tuple[MCPManager, ToolRegistry, MCPRegistry]:
    mcp_registry = registry or demo_registry()
    tools = ToolRegistry()
    manager = MCPManager(mcp_registry, tools, credentials=credentials, opener=opener)
    return manager, tools, mcp_registry


class TestEnvCredentialResolver:
    def test_reads_env_var_named_by_auth_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEMO_TOKEN", "sekrit")
        assert EnvCredentialResolver().resolve("DEMO_TOKEN") == "sekrit"

    def test_missing_ref_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOPE", raising=False)
        assert EnvCredentialResolver().resolve("NOPE") is None


class TestMCPManager:
    async def test_connect_registers_namespaced_tools(self) -> None:
        session = FakeSession([echo_tool()], {"echo": "echo: {text}"})
        manager, tools, registry = make_manager(opener=fake_opener(session))

        names = await manager.connect("demo")

        assert names == ["demo_echo"]
        assert registry.get("demo").status is MCPServerStatus.HEALTHY
        definition = tools.get("demo_echo")
        assert definition.source is ToolSource.MCP
        assert definition.metadata["mcp_tool"] == "echo"

    async def test_handler_routes_to_session_with_original_tool_name(self) -> None:
        session = FakeSession([echo_tool()], {"echo": "echoed"})
        manager, tools, _ = make_manager(opener=fake_opener(session))
        await manager.connect("demo")

        handler = tools.handler_for("demo_echo")
        result = await handler(text="hi")

        assert result == "echoed"
        assert session.calls == [("echo", {"text": "hi"})]

    async def test_connect_failure_marks_unreachable_and_raises(self) -> None:
        manager, _, registry = make_manager(opener=fake_opener(FakeSession([], {}), fail=True))

        with pytest.raises(MCPUnavailableError):
            await manager.connect("demo")

        assert registry.get("demo").status is MCPServerStatus.UNREACHABLE
        assert not manager.is_connected("demo")

    async def test_double_connect_raises(self) -> None:
        session = FakeSession([], {})
        manager, _, _ = make_manager(opener=fake_opener(session))
        await manager.connect("demo")

        with pytest.raises(RegistryError):
            await manager.connect("demo")

    async def test_unknown_server_raises(self) -> None:
        manager, _, _ = make_manager(opener=fake_opener(FakeSession([], {})))

        with pytest.raises(RegistryError):
            await manager.connect("ghost")

    async def test_auto_connect_all_connects_every_server(self) -> None:
        registry = MCPRegistry()
        registry.register(
            MCPServerDefinition(
                id="demo", name="Demo", transport=MCPTransport.STDIO, endpoint="python demo.py"
            )
        )
        registry.register(
            MCPServerDefinition(
                id="other", name="Other", transport=MCPTransport.STDIO, endpoint="python other.py"
            )
        )
        manager, tools, _ = make_manager(
            opener=fake_opener(FakeSession([echo_tool()], {"echo": "echoed"})),
            registry=registry,
        )

        results = await manager.auto_connect_all()

        assert results == {"demo": ["demo_echo"], "other": ["demo_echo"]}
        assert manager.is_connected("demo")
        assert manager.is_connected("other")
        assert registry.get("demo").status is MCPServerStatus.HEALTHY

    async def test_auto_connect_all_skips_failed_servers(self) -> None:
        registry = MCPRegistry()
        registry.register(
            MCPServerDefinition(
                id="good", name="Good", transport=MCPTransport.STDIO, endpoint="python g.py"
            )
        )
        registry.register(
            MCPServerDefinition(
                id="bad", name="Bad", transport=MCPTransport.STDIO, endpoint="python b.py"
            )
        )

        @asynccontextmanager
        async def per_server_opener(
            definition: MCPServerDefinition, credential: str | None
        ) -> AsyncIterator[MCPSession]:
            if definition.id == "bad":
                raise OSError("connection refused")
            yield FakeSession([echo_tool()], {"echo": "echoed"})  # type: ignore[misc]

        manager, tools, _ = make_manager(opener=per_server_opener, registry=registry)

        results = await manager.auto_connect_all()

        assert results["good"] == ["demo_echo"]
        assert results["bad"] is None
        assert not manager.is_connected("bad")
        assert registry.get("bad").status is MCPServerStatus.UNREACHABLE

    async def test_reconnect_replaces_handler_for_restored_definition(self) -> None:
        """A definition restored from persistence has no handler; reconnecting
        must attach one in place rather than tripping the duplicate rule."""
        registry = MCPRegistry()
        registry.register(
            MCPServerDefinition(
                id="demo", name="Demo", transport=MCPTransport.STDIO, endpoint="python demo.py"
            )
        )
        manager, tools, _ = make_manager(
            opener=fake_opener(FakeSession([echo_tool()], {"echo": "echoed"})),
            registry=registry,
        )
        # Simulate the restored state: definition + tool metadata, no handler.
        tools.register(echo_tool())
        with pytest.raises(RegistryError):
            tools.handler_for("demo_echo")

        names = await manager.connect("demo")

        assert names == ["demo_echo"]
        assert tools.has_handler("demo_echo")

    async def test_disconnect_removes_tools_and_marks_unknown(self) -> None:
        session = FakeSession([echo_tool()], {"echo": "echoed"})
        manager, tools, registry = make_manager(opener=fake_opener(session))
        await manager.connect("demo")

        await manager.disconnect("demo")

        assert registry.get("demo").status is MCPServerStatus.UNKNOWN
        with pytest.raises(RegistryError):
            tools.get("demo_echo")

    async def test_handler_after_connection_lost_is_unavailable(self) -> None:
        session = FakeSession([echo_tool()], {"echo": "echoed"})
        manager, tools, _ = make_manager(opener=fake_opener(session))
        await manager.connect("demo")
        manager._connections.clear()  # simulate a dropped connection

        handler = tools.handler_for("demo_echo")
        with pytest.raises(MCPUnavailableError):
            await handler(text="hi")

    async def test_disconnect_not_connected_raises(self) -> None:
        manager, _, _ = make_manager(opener=fake_opener(FakeSession([], {})))

        with pytest.raises(RegistryError):
            await manager.disconnect("demo")

    async def test_credential_resolved_and_passed_to_opener(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEMO_TOKEN", "sekrit")
        registry = demo_registry()
        registry.get("demo").auth_ref = "DEMO_TOKEN"
        captured: dict[str, str | None] = {}
        session = FakeSession([], {})

        @asynccontextmanager
        async def opener(
            definition: MCPServerDefinition, credential: str | None
        ) -> AsyncIterator[MCPSession]:
            captured["credential"] = credential
            yield session  # type: ignore[misc]

        manager, _, _ = make_manager(
            registry=registry, opener=opener, credentials=EnvCredentialResolver()
        )
        await manager.connect("demo")

        assert captured["credential"] == "sekrit"
