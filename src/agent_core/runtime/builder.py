"""AgentBuilder: resolve an AgentSpec into a runnable DeepAgents graph.

Pure resolution + assembly. Unknown tool / skill / sub-agent references fail
fast here, before any LLM call. Sub-agents are declared SubAgent dicts so
DeepAgents keeps owning the delegation loop, skills and HITL machinery.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from deepagents import SubAgent, create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from agent_core.config.settings import Settings, get_settings
from agent_core.domain.agent import AgentSpec, SubAgentRef
from agent_core.errors.exceptions import ConfigurationError, SkillError
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
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
    ) -> None:
        self._agents = agents
        self._tools = tools
        self._skills = skills
        self._settings = settings
        self._model_factory: ModelFactory = model_factory or self._default_model_factory
        self._tool_factory = tool_factory or make_direct_tool

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
        return create_deep_agent(
            model=self._model_factory(spec.model),
            tools=[self._resolve_tool(name) for name in spec.tools],
            system_prompt=spec.system_prompt or None,
            subagents=[self._resolve_subagent(ref, parent_id=spec.id) for ref in spec.subagents]
            or None,
            name=spec.name,
            **self._resolve_skills(spec.skills),
        )

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
        return SubAgent(
            name=sub_spec.id,
            description=ref.description or sub_spec.description or sub_spec.name,
            system_prompt=sub_spec.system_prompt,
            tools=[self._resolve_tool(name) for name in sub_spec.tools],
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
