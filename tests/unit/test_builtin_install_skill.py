"""Tests for the agent-facing ``install_skill`` builtin tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.application.service import AgentCoreService
from agent_core.builtins.skills import INSTALL_SKILL_TOOL, make_install_skill
from agent_core.config.settings import Settings, get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.tool import ToolDefinition
from agent_core.errors.exceptions import ToolError
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStreamBroker
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime


def make_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentCoreService:
    """Service with a real SkillRegistry + workspace rooted in tmp_path.

    ``install_skill`` reads the workspace from the cached global settings, so
    the test pins that cache to the tmp workspace for the duration.
    """
    get_settings.cache_clear()
    monkeypatch.setattr(
        "agent_core.builtins.skills.get_settings",
        lambda: Settings(_env_file=None, workspace_dir=str(tmp_path / "workspace")),
    )
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper"))
    skills = SkillRegistry()
    tools = ToolRegistry()
    runtime = AgentRuntime(agents, tools, skills)
    mcp_registry = MCPRegistry()
    mcp = MCPManager(mcp_registry, tools)
    broker = EventStreamBroker(runtime.bus)
    return AgentCoreService(runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker)


def write_skill(workspace: Path, skill_id: str) -> Path:
    """Create a valid skill directory inside the workspace."""
    skill_dir = workspace / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: Does a thing. 适用时机：when asked.\n"
        f"---\n\n# {skill_id}\n\nDo the thing.\n",
        encoding="utf-8",
    )
    return skill_dir


class TestInstallSkill:
    def test_definition_shape(self) -> None:
        definition, _ = make_install_skill(object())  # type: ignore[arg-type]
        assert isinstance(definition, ToolDefinition)
        assert definition.name == INSTALL_SKILL_TOOL
        assert definition.source.value == "internal"
        assert definition.metadata["builtin"] is True

    async def test_registers_skill_from_workspace_relative_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        write_skill(tmp_path / "workspace", "my-tool")
        definition, handler = make_install_skill(service)

        result = await handler(path="my-tool")

        assert "installed" in result
        skill = service.runtime.skills.get("my-tool")
        assert skill.id == "my-tool"
        assert skill.path == (tmp_path / "workspace" / "my-tool")

    async def test_registers_skill_from_absolute_in_workspace_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        write_skill(tmp_path / "workspace", "abs-tool")
        definition, handler = make_install_skill(service)

        result = await handler(path=str(tmp_path / "workspace" / "abs-tool"))

        assert "installed" in result
        assert service.runtime.skills.get("abs-tool").name == "abs-tool"

    async def test_skill_outside_workspace_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "SKILL.md").write_text("---\nname: evil\n---\n")
        definition, handler = make_install_skill(service)

        with pytest.raises(ToolError) as excinfo:
            await handler(path=str(outside))
        assert "outside the workspace" in excinfo.value.message

    async def test_missing_skill_md_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        (tmp_path / "workspace" / "empty").mkdir(parents=True)
        definition, handler = make_install_skill(service)

        with pytest.raises(ToolError) as excinfo:
            await handler(path="empty")
        assert "No SKILL.md" in excinfo.value.message

    async def test_bad_frontmatter_name_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        skill_dir = tmp_path / "workspace" / "bad-name"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: bad name with spaces\n---\n")
        definition, handler = make_install_skill(service)

        with pytest.raises(ToolError) as excinfo:
            await handler(path="bad-name")
        assert "valid 'name'" in excinfo.value.message

    async def test_duplicate_version_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        write_skill(tmp_path / "workspace", "dup")
        definition, handler = make_install_skill(service)
        await handler(path="dup")

        with pytest.raises(ToolError) as excinfo:
            await handler(path="dup")
        assert "already registered" in excinfo.value.message

    async def test_new_version_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        write_skill(tmp_path / "workspace", "ver")
        definition, handler = make_install_skill(service)
        await handler(path="ver", version="0.1.0")

        result = await handler(path="ver", version="0.2.0")

        assert "installed" in result
        assert service.runtime.skills.latest_version_of("ver") == "0.2.0"
