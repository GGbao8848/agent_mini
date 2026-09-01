"""AgentBuilder: resolve an AgentSpec into a runnable DeepAgents graph.

Pure resolution + assembly. Unknown tool / skill / sub-agent references fail
fast here, before any LLM call. Sub-agents are declared SubAgent dicts so
DeepAgents keeps owning the delegation loop, skills and HITL machinery.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deepagents import SubAgent, create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from agent_core.artifacts import task_workspace
from agent_core.config.settings import Settings, get_settings
from agent_core.domain.agent import AgentSpec, SubAgentRef
from agent_core.domain.metrics import RunUsage
from agent_core.errors.exceptions import ConfigurationError, SkillError
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.context import get_current_task_id
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
        tools = self._resolve_available_tools(spec)
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

    def _agent_tool_names(self, spec: AgentSpec) -> list[str]:
        """The tool names an agent is bound to.

        An empty ``spec.tools`` means "everything available" — the default for
        agents that don't opt into a capability list. Unavailable tools
        (``metadata["available"] is False``) are excluded from the implicit
        set; an explicit binding still resolves so the call-time error is
        precise about what is missing.
        """
        if spec.tools:
            return list(spec.tools)
        return [
            definition.name
            for definition in self._tools.list()
            if definition.metadata.get("available", True)
        ]

    def _backend_kwargs(self, spec: AgentSpec) -> dict[str, Any]:
        """Root the harness file tools on the workspace the task writes into.

        With a workspace the agent's ``write_file``/``read_file``/... land on
        actual disk (contained by FilesystemBackend), which is what makes
        ``run_code``-built artifacts (pptx, sites, images) possible. When a
        task is executing (the ``current_task_id`` context var is set — build
        runs inside the run), the backend is rooted at the task's private
        directory ``workspace/tasks/<task_id>/`` so every task's outputs stay
        isolated; skills are staged *inside that same directory* (DeepAgents
        serves skills and file tools from ONE backend, and skill source paths
        resolve relative to the backend root).
        """
        settings = self._settings or get_settings()
        workspace = Path(settings.workspace_dir)
        task_id = get_current_task_id()
        backend_root = task_workspace(workspace, task_id) if task_id is not None else workspace
        backend = FilesystemBackend(root_dir=backend_root)
        skill_source = self._stage_skills(backend_root, settings)
        if skill_source is not None:
            return {"skills": [skill_source], "backend": backend}
        return {"backend": backend}

    def _stage_skills(self, stage_root: Path, settings: Settings) -> str | None:
        """Copy every registered skill into ``stage_root``; return their source.

        Skills are a shared pool: anything registered in the SkillRegistry is
        loaded for every agent. The staged copy lives under the *same* root the
        file backend uses (``stage_root/.skills/``), so DeepAgents can find it
        relative to the backend. ``.skills/`` is wiped and rebuilt on every
        build so the staged copy always matches the registry.
        """
        manifests = self._skills.list()
        if not manifests:
            return None
        staged = stage_root / ".skills"
        if staged.exists():
            shutil.rmtree(staged)
        for manifest in manifests:
            source = self._resolve_skill_path(manifest.id)
            shutil.copytree(
                source,
                staged / manifest.id,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        return ".skills"

    def _resolve_tool(self, name: str) -> BaseTool:
        definition = self._tools.get(name)
        return self._tool_factory(definition, self._tools.handler_for(name))

    def _resolve_available_tools(self, spec: AgentSpec) -> list[BaseTool]:
        """Resolve the agent's tools, skipping ones without a live handler.

        A tool may be registered (definition restored from persistence) while
        its handler is process-local and not yet attached — most commonly MCP
        tools whose server is currently disconnected. Instead of failing the
        whole run at build time, those tools are silently dropped; the agent
        still runs with the tools that are actually callable. Unknown tool
        names still fail fast (a typo must surface, not be swallowed).
        """
        tools: list[BaseTool] = []
        for name in self._agent_tool_names(spec):
            self._tools.get(name)  # fail fast on unknown tools
            if not self._tools.has_handler(name):
                continue
            tools.append(self._resolve_tool(name))
        return tools

    def _resolve_subagent(self, ref: SubAgentRef, *, parent_id: str) -> SubAgent:
        sub_spec = self._agents.get(ref.agent_id)
        if sub_spec.id == parent_id:
            raise ConfigurationError(
                f"Agent '{parent_id}' cannot delegate to itself",
                details={"agent_id": parent_id},
            )
        sub_tools = self._resolve_available_tools(sub_spec)
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
