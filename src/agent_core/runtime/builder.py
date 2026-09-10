"""AgentBuilder: resolve an AgentSpec into a runnable DeepAgents graph.

Pure resolution + assembly. Unknown tool / skill / sub-agent references fail
fast here, before any LLM call. Sub-agents are declared SubAgent dicts so
DeepAgents keeps owning the delegation loop, skills and HITL machinery.
"""

from __future__ import annotations

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
from agent_core.runtime.paths import current_task_dir, environment_note
from agent_core.runtime.tooling import ToolFactory, make_direct_tool
from agent_core.workspace import WorkspaceLayout, filesystem_permissions

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
        from agent_core.runtime.context import get_current_model_override

        # A per-run override (composer model picker) wins over the agent spec.
        override = get_current_model_override()
        return build_model(
            override or model_spec, settings=self._settings or get_settings()
        )

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
        # Environment note regenerated per build: it reflects the ACTUAL
        # working root (project dir when bound, sandbox mapping otherwise) so
        # agents never chase stale hard-coded paths like /work, and it carries
        # the hygiene rules (no full-disk find, ensure_packages first).
        settings = self._settings or get_settings()
        system_prompt = (system_prompt or "") + environment_note(
            current_task_dir(Path(settings.workspace_dir)), settings
        )
        return create_deep_agent(
            model=self._model_factory(spec.model),
            tools=tools,
            system_prompt=system_prompt,
            subagents=[self._resolve_subagent(ref, parent_id=spec.id) for ref in spec.subagents]
            or None,
            middleware=build_middleware(spec, self._model_factory, self._usage_provider),
            # Read-only mounts and write-path rules: inputs/skills are immutable
            # to the agent (runtime invariant I-01/I-02).
            permissions=filesystem_permissions(),
            # Resolved lazily: build() runs inside a loop, construction may not.
            checkpointer=self._checkpointer_provider() if self._checkpointer_provider else None,
            name=spec.name,
            **self._backend_kwargs(spec),
        )

    def context_breakdown(self, spec: AgentSpec) -> dict[str, int]:
        """Estimate the static prompt parts for ``spec``: tool schemas and
        skill manifests (see :mod:`agent_core.runtime.context_breakdown`).
        Message-history tokens are dynamic and counted per model call."""
        from agent_core.runtime.context_breakdown import static_breakdown

        names = self._agent_tool_names(spec)
        definitions = [self._tools.get(name) for name in names]
        return static_breakdown(definitions, self._skills.list())

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
        """Build the agent's filesystem backend and skill mount.

        The agent gets a *controlled* working environment, not the raw task
        directory: the task root is laid out as ``inputs/`` (read-only),
        ``workspace/``, ``outputs/`` and ``tmp/`` (writable) — see
        :mod:`agent_core.workspace`. Skills are **not** copied in: each enabled
        skill is mounted read-only at ``/skills/<id>`` through a
        :class:`CompositeBackend` route straight to its registry source, so the
        agent can read skill material but the source on disk is never mutated
        (invariants I-02/I-03).
        """
        from deepagents.backends import CompositeBackend

        from agent_core.workspace.backend import BoundaryBackend

        settings = self._settings or get_settings()
        workspace = Path(settings.workspace_dir)
        backend_root = current_task_dir(workspace)
        WorkspaceLayout.ensure(backend_root)
        backend: Any = FilesystemBackend(root_dir=backend_root)
        routes: dict[str, Any] = {}
        for manifest in self._skills.list():
            if not manifest.enabled:
                continue
            source = self._resolve_skill_path(manifest.id)
            routes[f"/skills/{manifest.id}/"] = FilesystemBackend(
                root_dir=source, virtual_mode=True
            )
        if routes:
            backend = CompositeBackend(default=backend, routes=routes)
        # Data-layer enforcement of the read-only mounts (I-01/I-02): the
        # middleware checks the tool wrappers, this also guards direct calls.
        backend = BoundaryBackend(backend)
        if routes:
            return {"skills": ["/skills/"], "backend": backend}
        return {"backend": backend}

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
