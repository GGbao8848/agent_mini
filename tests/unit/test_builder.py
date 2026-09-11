"""Unit tests for AgentBuilder resolution (graph assembly is offline)."""

from pathlib import Path

import pytest
from langchain_openai import ChatOpenAI

from agent_core.domain.agent import AgentLimits, AgentSpec, SubAgentRef
from agent_core.domain.resilience import ResiliencePolicy, SummarizationPolicy
from agent_core.domain.tool import ToolDefinition
from agent_core.errors.exceptions import ConfigurationError, RegistryError
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.builder import AgentBuilder


def stub_model_factory(model_spec: str | None) -> ChatOpenAI:
    return ChatOpenAI(model="gpt-4o-mini", api_key="test-key")


def make_builder(
    *,
    agents: AgentRegistry | None = None,
    tools: ToolRegistry | None = None,
    skills: SkillRegistry | None = None,
    workspace: Path | None = None,
    memory_enabled: bool = False,
) -> AgentBuilder:
    settings = None
    if workspace is not None:
        from agent_core.config.settings import Settings

        settings = Settings(_env_file=None, workspace_dir=str(workspace))
    return AgentBuilder(
        agents or AgentRegistry(),
        tools or ToolRegistry(),
        skills or SkillRegistry(),
        model_factory=stub_model_factory,
        settings=settings,
        memory_enabled=memory_enabled,
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

    def test_tool_without_handler_is_skipped(self) -> None:
        """A registered tool without a live handler (e.g. MCP while its server
        is disconnected) is dropped from the build instead of failing it."""
        tools = ToolRegistry()
        tools.register(ToolDefinition(name="noop", description="Noop"))
        tools.register(ToolDefinition(name="ready", description="Ready"), lambda: "ok")
        builder = make_builder(tools=tools)

        resolved = builder._resolve_available_tools(base_spec(tools=["noop", "ready"]))

        assert [tool.name for tool in resolved] == ["ready"]

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

    def test_build_publishes_runtime_context(self) -> None:
        """R20: a real build assembles and publishes the sectioned context."""
        from agent_core.runtime.context import current_context

        builder = make_builder()
        try:
            builder.build(base_spec(system_prompt="你是助手"))
            context = current_context.get()
            assert context is not None
            kinds = {s.kind.value for s in context.sections}
            assert "system" in kinds
            assert "environment" in kinds
        finally:
            current_context.set(None)

    def test_build_includes_task_state_and_memory_blocks(self) -> None:
        """R20/R21: the injected task-state and memory blocks reach the prompt."""
        from agent_core.runtime.context import (
            current_context,
            current_memory_block,
            current_task_state_block,
        )

        builder = make_builder(memory_enabled=True)
        mem = current_memory_block.set("## 长期记忆\n- 用户偏好简洁")
        state = current_task_state_block.set("## 任务状态\n- 目标：写报告")
        try:
            builder.build(base_spec(system_prompt="你是助手"))
            context = current_context.get()
            assert context is not None
            assert "任务状态" in context.prompt
            assert "长期记忆" in context.prompt
        finally:
            current_context.set(None)
            current_memory_block.reset(mem)
            current_task_state_block.reset(state)

    def test_empty_tools_expands_to_all_available(self) -> None:
        tools = ToolRegistry()
        tools.register(ToolDefinition(name="a", description="A"), lambda: "ok")
        tools.register(ToolDefinition(name="b", description="B"), lambda: "ok")
        tools.register(
            ToolDefinition(
                name="c", description="C", metadata={"available": False}
            ),
            lambda: "nope",
        )
        builder = make_builder(tools=tools)
        spec = base_spec(tools=[])  # empty = everything available

        names = builder._agent_tool_names(spec)

        assert names == ["a", "b"]  # unavailable tool excluded

    def test_explicit_tools_stay_a_whitelist(self) -> None:
        tools = ToolRegistry()
        tools.register(ToolDefinition(name="a", description="A"), lambda: "ok")
        tools.register(
            ToolDefinition(name="b", description="B", metadata={"available": False}),
            lambda: "ok",
        )
        builder = make_builder(tools=tools)

        # Explicitly binding an unavailable tool still resolves (the call-time
        # handler raises a precise error); explicit list is not filtered.
        assert builder._agent_tool_names(base_spec(tools=["b"])) == ["b"]

    def test_empty_tools_with_no_registry_is_empty(self) -> None:
        builder = make_builder()  # empty ToolRegistry

        assert builder._agent_tool_names(base_spec()) == []

    def test_skills_mount_the_shared_directory_without_copying(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        skill_dir = workspace / "skills" / "web-research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Web Research")
        second_dir = workspace / "skills" / "data-plot"
        second_dir.mkdir(parents=True)
        (second_dir / "SKILL.md").write_text("# Data Plot")
        builder = make_builder(workspace=workspace)

        # The whole skills directory is one writable mount at /skills; nothing is
        # copied into a task root. Invariant I-03 (single source of truth).
        spec = base_spec()
        graph = builder.build(spec)

        assert hasattr(graph, "ainvoke")
        kwargs = builder._backend_kwargs(spec)
        assert kwargs["skills"] == ["/skills/"]
        assert (skill_dir / "SKILL.md").is_file()
        assert list((workspace / "tasks").rglob("SKILL.md")) == []

    def test_skills_mount_is_writable(self, tmp_path: Path) -> None:
        builder = make_builder(workspace=tmp_path / "workspace")

        backend = builder._backend_kwargs(base_spec())["backend"]

        written = backend.write("/skills/new-skill/SKILL.md", "---\nname: new-skill\n---\n")
        assert written.error is None, written
        assert (tmp_path / "workspace" / "skills" / "new-skill" / "SKILL.md").is_file()

    def test_no_registered_skills_still_mounts_the_skills_dir(self, tmp_path: Path) -> None:
        builder = make_builder(workspace=tmp_path / "workspace")

        kwargs = builder._backend_kwargs(base_spec())

        # The skills mount exists even with no skills yet (the directory is the
        # source of truth, and the agent writes into it) — not backend-only.
        assert kwargs["skills"] == ["/skills/"]

    def test_resilience_policy_builds_with_middleware(self) -> None:
        spec = base_spec(
            resilience=ResiliencePolicy(
                summarization=SummarizationPolicy(trigger_messages=10),
                model_call_limit=5,
                tool_retries=1,
            )
        )
        builder = make_builder()

        graph = builder.build(spec)

        assert hasattr(graph, "ainvoke")
