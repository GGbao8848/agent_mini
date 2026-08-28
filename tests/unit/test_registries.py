"""Unit tests for the four registries (register/get/list/remove/duplicate/version)."""

import pytest

from agent_core.domain.agent import AgentSpec
from agent_core.domain.mcp import MCPServerDefinition, MCPServerStatus, MCPTransport
from agent_core.domain.skill import SkillManifest
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry


def make_agent(agent_id: str = "researcher") -> AgentSpec:
    return AgentSpec(id=agent_id, name="Researcher", model="openai:gpt-4o-mini")


def make_tool(name: str = "get_weather") -> ToolDefinition:
    return ToolDefinition(name=name, description="Weather lookup", source=ToolSource.PYTHON)


def make_skill(skill_id: str = "web-research", version: str = "0.1.0") -> SkillManifest:
    return SkillManifest(id=skill_id, name="Web Research", version=version)


def make_server(server_id: str = "filesystem") -> MCPServerDefinition:
    return MCPServerDefinition(
        id=server_id, name="Filesystem", transport=MCPTransport.STDIO, endpoint="python server.py"
    )


class TestAgentRegistry:
    def test_register_get_list_remove_roundtrip(self) -> None:
        registry = AgentRegistry()
        spec = make_agent()

        registry.register(spec)

        assert registry.get("researcher") is spec
        assert registry.list() == [spec]
        assert registry.remove("researcher") is spec
        assert len(registry) == 0

    def test_duplicate_registration_raises(self) -> None:
        registry = AgentRegistry()
        registry.register(make_agent())

        with pytest.raises(RegistryError) as excinfo:
            registry.register(make_agent())

        assert excinfo.value.details["kind"] == "agent"
        assert excinfo.value.details["key"] == "researcher"

    def test_get_missing_raises(self) -> None:
        with pytest.raises(RegistryError):
            AgentRegistry().get("missing")

    def test_remove_missing_raises(self) -> None:
        with pytest.raises(RegistryError):
            AgentRegistry().remove("missing")

    def test_contains(self) -> None:
        registry = AgentRegistry()
        registry.register(make_agent())
        assert "researcher" in registry
        assert "other" not in registry


class TestToolRegistry:
    def test_register_with_handler(self) -> None:
        registry = ToolRegistry()
        handler = lambda **kwargs: kwargs  # noqa: E731

        registry.register(make_tool(), handler)

        assert registry.handler_for("get_weather") is handler

    def test_register_definition_without_handler(self) -> None:
        registry = ToolRegistry()
        registry.register(make_tool())

        assert registry.get("get_weather").name == "get_weather"
        with pytest.raises(RegistryError) as excinfo:
            registry.handler_for("get_weather")
        assert excinfo.value.details["kind"] == "tool"
        assert "no executable handler" in str(excinfo.value)

    def test_handler_for_unknown_tool_raises(self) -> None:
        with pytest.raises(RegistryError):
            ToolRegistry().handler_for("missing")

    def test_set_handler_attaches_to_existing_definition(self) -> None:
        registry = ToolRegistry()
        registry.register(make_tool())
        handler = lambda **kwargs: kwargs  # noqa: E731

        registry.set_handler("get_weather", handler)

        assert registry.handler_for("get_weather") is handler

    def test_set_handler_unknown_tool_raises(self) -> None:
        with pytest.raises(RegistryError):
            ToolRegistry().set_handler("missing", lambda **kwargs: kwargs)

    def test_duplicate_tool_name_raises(self) -> None:
        registry = ToolRegistry()
        registry.register(make_tool())

        with pytest.raises(RegistryError):
            registry.register(make_tool())


class TestSkillRegistry:
    def test_register_and_get_latest_version(self) -> None:
        registry = SkillRegistry()
        v1 = make_skill(version="0.1.0")
        v2 = make_skill(version="0.2.0")

        registry.register(v1)
        registry.register(v2)

        assert registry.get("web-research") is v2
        assert registry.get("web-research", version="0.1.0") is v1
        assert registry.latest_version_of("web-research") == "0.2.0"

    def test_duplicate_id_and_version_raises(self) -> None:
        registry = SkillRegistry()
        registry.register(make_skill())

        with pytest.raises(RegistryError) as excinfo:
            registry.register(make_skill())
        assert excinfo.value.details["key"] == "web-research@0.1.0"

    def test_list_returns_latest_version_only(self) -> None:
        registry = SkillRegistry()
        registry.register(make_skill(version="0.1.0"))
        latest = make_skill(version="0.2.0")
        registry.register(latest)
        registry.register(make_skill(skill_id="other"))

        assert registry.list() == [latest, make_skill(skill_id="other")]

    def test_list_versions_returns_all_versions(self) -> None:
        registry = SkillRegistry()
        v1 = make_skill(version="0.1.0")
        v2 = make_skill(version="0.2.0")
        registry.register(v1)
        registry.register(v2)

        assert registry.list_versions("web-research") == [v1, v2]

    def test_get_unknown_skill_raises(self) -> None:
        with pytest.raises(RegistryError):
            SkillRegistry().get("missing")

    def test_get_unknown_version_raises(self) -> None:
        registry = SkillRegistry()
        registry.register(make_skill())

        with pytest.raises(RegistryError) as excinfo:
            registry.get("web-research", version="9.9.9")
        assert excinfo.value.details["key"] == "web-research@9.9.9"

    def test_remove_single_version_keeps_skill(self) -> None:
        registry = SkillRegistry()
        registry.register(make_skill(version="0.1.0"))
        registry.register(make_skill(version="0.2.0"))

        removed = registry.remove("web-research", version="0.1.0")

        assert removed.version == "0.1.0"
        assert registry.get("web-research").version == "0.2.0"

    def test_remove_last_version_removes_skill(self) -> None:
        registry = SkillRegistry()
        registry.register(make_skill())

        registry.remove("web-research", version="0.1.0")

        assert "web-research" not in registry

    def test_remove_whole_skill(self) -> None:
        registry = SkillRegistry()
        registry.register(make_skill(version="0.1.0"))
        registry.register(make_skill(version="0.2.0"))

        removed = registry.remove("web-research")

        assert removed.version == "0.2.0"
        assert "web-research" not in registry

    def test_remove_missing_raises(self) -> None:
        with pytest.raises(RegistryError):
            SkillRegistry().remove("missing")


class TestMCPRegistry:
    def test_register_get_roundtrip(self) -> None:
        registry = MCPRegistry()
        server = make_server()

        registry.register(server)

        assert registry.get("filesystem") is server

    def test_duplicate_server_raises(self) -> None:
        registry = MCPRegistry()
        registry.register(make_server())

        with pytest.raises(RegistryError) as excinfo:
            registry.register(make_server())
        assert excinfo.value.details["kind"] == "mcp-server"

    def test_set_status_persists(self) -> None:
        registry = MCPRegistry()
        registry.register(make_server())

        updated = registry.set_status("filesystem", MCPServerStatus.HEALTHY)

        assert updated.status == MCPServerStatus.HEALTHY
        assert registry.get("filesystem").status == MCPServerStatus.HEALTHY

    def test_set_status_unknown_server_raises(self) -> None:
        with pytest.raises(RegistryError):
            MCPRegistry().set_status("missing", MCPServerStatus.HEALTHY)
