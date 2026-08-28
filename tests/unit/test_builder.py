"""Unit tests for AgentBuilder resolution (graph assembly is offline)."""

from pathlib import Path

import pytest
from langchain_openai import ChatOpenAI

from agent_core.domain.agent import AgentLimits, AgentSpec, SubAgentRef
from agent_core.domain.skill import SkillManifest
from agent_core.domain.tool import ToolDefinition
from agent_core.errors.exceptions import ConfigurationError, RegistryError, SkillError
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.builder import AgentBuilder


def stub_model_factory(model_spec: str | None) -> ChatOpenAI:
    return ChatOpenAI(model="gpt-4o-mini", api_key="test-key")


def make_builder(
    *,
    agents: AgentRegistry | None = None,
    tools: ToolRegistry | None = None,
    skills: SkillRegistry | None = None,
) -> AgentBuilder:
    return AgentBuilder(
        agents or AgentRegistry(),
        tools or ToolRegistry(),
        skills or SkillRegistry(),
        model_factory=stub_model_factory,
    )


def base_spec(**overrides: object) -> AgentSpec:
    values: dict[str, object] = {
        "id": "orchestrator",
        "name": "Orchestrator",
        "model": "openai:gpt-4o-mini",
    }
    values.update(overrides)
    return AgentSpec(**values)  # type: ignore[arg-type]


class TestResolution:
    def test_unknown_tool_fails_fast(self) -> None:
        builder = make_builder()

        with pytest.raises(RegistryError):
            builder.build(base_spec(tools=["nope"]))

    def test_tool_without_handler_fails_fast(self) -> None:
        tools = ToolRegistry()
        tools.register(ToolDefinition(name="noop", description="Noop"))
        builder = make_builder(tools=tools)

        with pytest.raises(RegistryError):
            builder.build(base_spec(tools=["noop"]))

    def test_unknown_subagent_fails_fast(self) -> None:
        builder = make_builder()

        with pytest.raises(RegistryError):
            builder.build(base_spec(subagents=[SubAgentRef(agent_id="ghost")]))

    def test_too_many_subagents_raises(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="worker", name="Worker"))
        builder = make_builder(agents=agents)
        spec = base_spec(
            limits=AgentLimits(max_subagents=1),
            subagents=[SubAgentRef(agent_id="worker"), SubAgentRef(agent_id="worker")],
        )

        with pytest.raises(ConfigurationError):
            builder.build(spec)

    def test_self_delegation_raises(self) -> None:
        agents = AgentRegistry()
        agents.register(base_spec())
        builder = make_builder(agents=agents)

        with pytest.raises(ConfigurationError):
            builder.build(base_spec(subagents=[SubAgentRef(agent_id="orchestrator")]))


class TestBuild:
    def test_happy_path_returns_compiled_graph(self) -> None:
        tools = ToolRegistry()
        tools.register(ToolDefinition(name="noop", description="Noop"), lambda: "ok")
        agents = AgentRegistry()
        agents.register(AgentSpec(id="worker", name="Worker"))
        agents.register(
            base_spec(
                tools=["noop"],
                subagents=[SubAgentRef(agent_id="worker", description="Do work")],
            )
        )
        builder = make_builder(agents=agents, tools=tools)

        graph = builder.build(agents.get("orchestrator"))

        assert hasattr(graph, "ainvoke")

    def test_skills_resolve_to_disk_backend(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "web-research"
        skill_dir.mkdir(parents=True)
        skills = SkillRegistry()
        skills.register(SkillManifest(id="web-research", name="Web Research", path=skill_dir))
        builder = make_builder(skills=skills)

        graph = builder.build(base_spec(skills=["web-research"]))

        assert hasattr(graph, "ainvoke")

    def test_skill_without_path_raises(self) -> None:
        skills = SkillRegistry()
        skills.register(SkillManifest(id="floating", name="Floating"))
        builder = make_builder(skills=skills)

        with pytest.raises(SkillError):
            builder.build(base_spec(skills=["floating"]))

    def test_skill_with_missing_directory_raises(self) -> None:
        skills = SkillRegistry()
        skills.register(SkillManifest(id="gone", name="Gone", path=Path("/nonexistent/skill")))
        builder = make_builder(skills=skills)

        with pytest.raises(SkillError):
            builder.build(base_spec(skills=["gone"]))
