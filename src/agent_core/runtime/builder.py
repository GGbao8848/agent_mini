"""AgentBuilder: resolve an AgentSpec into a runnable DeepAgents graph.

Pure resolution + assembly. Unknown tool / skill / sub-agent references fail
fast here, before any LLM call. Sub-agents are declared SubAgent dicts so
DeepAgents keeps owning the delegation loop, skills and HITL machinery.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deepagents import SubAgent, create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from agent_core.config.settings import Settings, get_settings
from agent_core.domain.agent import AgentSpec, SubAgentRef
from agent_core.domain.metrics import RunUsage
from agent_core.errors.exceptions import ConfigurationError, SkillError
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.help_tool import autonomy_prompt_addendum
from agent_core.runtime.middleware import build_middleware
from agent_core.runtime.model import ModelFactory, build_model
from agent_core.runtime.tooling import ToolFactory, make_direct_tool

CompiledGraph = CompiledStateGraph[Any, Any, Any, Any]
"""Fully parameterized alias; concrete state types are DeepAgents internals."""


class AgentBuilder:
    """Resolves a spec against the registries and assembles the graph."""

    def __init__(
        self,
        agents: AgentRegistry,
        tools: ToolRegistry,
        skills: SkillRegistry,
        *,
        model_factory: ModelFactory | None = None,
        tool_factory: ToolFactory | None = None,
        settings: Settings | None = None,
        usage_provider: Callable[[], RunUsage | None] | None = None,
        help_tool: BaseTool | None = None,
        checkpointer_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._agents = agents
        self._tools = tools
        self._skills = skills
        self._settings = settings
        self._model_factory: ModelFactory = model_factory or self._default_model_factory
        self._tool_factory = tool_factory or make_direct_tool
        self._usage_provider = usage_provider
        self._help_tool = help_tool
        self._checkpointer_provider = checkpointer_provider

    def _default_model_factory(self, model_spec: str | None) -> BaseChatModel:
        return build_model(model_spec, settings=self._settings or get_settings())

    def build(self, spec: AgentSpec) -> CompiledGraph:
        """Resolve ``spec`` and return the compiled DeepAgents graph."""
        if len(spec.subagents) > spec.limits.max_subagents:
            raise ConfigurationError(
                f"Agent '{spec.id}' declares {len(spec.subagents)} sub-agents, "
                f"above its limit of {spec.limits.max_subagents}",
                details={"agent_id": spec.id},
            )
        tools = [self._resolve_tool(name) for name in spec.tools]
        system_prompt = spec.system_prompt or None
        if spec.autonomy is not None:
            # Autonomy adds the escape hatch (request_help) and the rules that
            # keep the agent from spinning or guessing instead of asking.
            tools = tools + ([self._help_tool] if self._help_tool is not None else [])
            system_prompt = (system_prompt or "") + autonomy_prompt_addendum()
        return create_deep_agent(
            model=self._model_factory(spec.model),
            tools=tools,
            system_prompt=system_prompt,
            subagents=[self._resolve_subagent(ref, parent_id=spec.id) for ref in spec.subagents]
            or None,
            middleware=build_middleware(spec, self._model_factory, self._usage_provider),
            # Resolved lazily: build() runs inside a loop, construction may not.
            checkpointer=self._checkpointer_provider() if self._checkpointer_provider else None,
            name=spec.name,
            **self._backend_kwargs(spec),
        )

    def _backend_kwargs(self, spec: AgentSpec) -> dict[str, Any]:
        """Root the harness file tools on the real workspace when configured.

        With a workspace the agent's ``write_file``/``read_file``/... land on
        actual disk (contained by FilesystemBackend), which is what makes
        ``run_code``-built artifacts (pptx, sites, images) possible. Skill
        resolution keeps precedence: it computes its own backend root.
        """
        skill_kwargs = self._resolve_skills(spec.skills)
        if skill_kwargs:
            return skill_kwargs
        settings = self._settings or get_settings()
        return {"backend": FilesystemBackend(root_dir=settings.workspace_dir)}

    def _resolve_tool(self, name: str) -> BaseTool:
        definition = self._tools.get(name)
        return self._tool_factory(definition, self._tools.handler_for(name))

    def _resolve_subagent(self, ref: SubAgentRef, *, parent_id: str) -> SubAgent:
        sub_spec = self._agents.get(ref.agent_id)
        if sub_spec.id == parent_id:
            raise ConfigurationError(
                f"Agent '{parent_id}' cannot delegate to itself",
                details={"agent_id": parent_id},
            )
        sub_tools = [self._resolve_tool(name) for name in sub_spec.tools]
        if sub_spec.autonomy is not None and self._help_tool is not None:
            sub_tools.append(self._help_tool)
        return SubAgent(
            name=sub_spec.id,
            description=ref.description or sub_spec.description or sub_spec.name,
            system_prompt=sub_spec.system_prompt,
            tools=sub_tools,
            model=self._model_factory(sub_spec.model),
        )

    def _resolve_skill_path(self, skill_id: str) -> Path:
        """Validate a skill reference and return its on-disk directory."""
        path = self._skills.get(skill_id).path
        if path is None:
            raise SkillError(
                f"Skill '{skill_id}' has no path on disk", details={"skill": skill_id}
            )
        if not path.is_dir():
            raise SkillError(
                f"Skill '{skill_id}' path does not exist: {path}",
                details={"skill": skill_id},
            )
        return path

    def _resolve_skills(self, skill_ids: list[str]) -> dict[str, Any]:
        """Map skill ids to DeepAgents skill source dirs served by a disk backend."""
        if not skill_ids:
            return {}
        parents = {self._resolve_skill_path(skill_id).parent for skill_id in skill_ids}
        if len(parents) == 1:
            parent = parents.pop()
            root, sources = parent.parent, [parent.name]
        else:
            root = Path(os.path.commonpath([str(p) for p in parents]))
            sources = sorted(p.relative_to(root).as_posix() for p in parents)
        return {"skills": sources, "backend": FilesystemBackend(root_dir=str(root))}
