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

from agent_core.capabilities import CapabilityResolver
from agent_core.config.settings import Settings, get_settings
from agent_core.context.builder import ContextBuilder
from agent_core.domain.agent import AgentSpec, SubAgentRef
from agent_core.domain.metrics import RunUsage
from agent_core.errors.exceptions import ConfigurationError, SkillError
from agent_core.observability.emitter import EventFanout
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.help_tool import autonomy_prompt_addendum
from agent_core.runtime.middleware import build_middleware
from agent_core.runtime.model import ModelFactory, build_model
from agent_core.runtime.paths import current_task_dir, environment_note
from agent_core.runtime.tooling import ToolFactory, make_direct_tool
from agent_core.workspace import WorkspaceLayout, filesystem_permissions, skills_root

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
        memory_enabled: bool = False,
        capabilities: CapabilityResolver | None = None,
        fanout: EventFanout | None = None,
        gate: Any | None = None,
    ) -> None:
        self._agents = agents
        self._tools = tools
        self._skills = skills
        self._settings = settings
        self._fanout = fanout
        self._gate = gate
        self._model_factory: ModelFactory = model_factory or self._default_model_factory
        self._tool_factory = tool_factory or make_direct_tool
        self._usage_provider = usage_provider
        self._help_tool = help_tool
        self._checkpointer_provider = checkpointer_provider
        self._memory_enabled = memory_enabled
        # R22: the single capability source of truth. Falls back to a local
        # resolver so standalone builders (tests) behave identically.
        self._capabilities = capabilities or CapabilityResolver(
            lambda: self._tools.list(),
            has_handler=self._tools.has_handler,
        )

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
        autonomy_text = ""
        if spec.autonomy is not None:
            # Autonomy adds the escape hatch (request_help) and the rules that
            # keep the agent from spinning or guessing instead of asking.
            tools = tools + ([self._help_tool] if self._help_tool is not None else [])
            autonomy_text = autonomy_prompt_addendum()
        # Environment note regenerated per build: it reflects the ACTUAL
        # working root (project dir when bound, sandbox mapping otherwise) so
        # agents never chase stale hard-coded paths like /work, and it carries
        # the hygiene rules (no full-disk find, ensure_packages first).
        settings = self._settings or get_settings()
        environment_text = environment_note(
            current_task_dir(Path(settings.workspace_dir)),
            settings,
            skills_root(Path(settings.workspace_dir)),
        )
        # Retrieved long-term memory: only the few entries relevant to this
        # request (see agent_core.memory), never the whole store (MEM-005).
        # The runtime precomputes the block asynchronously (hybrid retrieval);
        # this sync build just reads it.
        memory_text = ""
        lesson_text = ""
        if self._memory_enabled:
            from agent_core.runtime.context import get_current_memory_block, get_current_query

            query = get_current_query() or ""
            memory_text = get_current_memory_block()
            # Deterministic correction nudge (R11): only on turns that read like
            # a correction, so ordinary turns pay nothing and record nothing.
            from agent_core.memory.lesson import lesson_hint

            lesson_text = lesson_hint(query)
        # Explicit task progress (R21): a compact record of the plan/status/
        # failures so a long conversation does not have to be re-read to answer
        # "where are we". Empty for a fresh, trivial task.
        from agent_core.runtime.context import (
            current_context,
            get_current_task_state_block,
        )

        task_state_text = get_current_task_state_block()
        # Assemble the prompt as ordered, budgeted sections (R20) — the single
        # place that decides what the model sees and in what order.
        context = self._context_builder().build(
            system_prompt=system_prompt or "",
            autonomy=autonomy_text,
            environment=environment_text,
            task_state=task_state_text,
            memory=memory_text,
            lesson=lesson_text,
        )
        current_context.set(context)
        # Cold tools are advertised as cheap stubs (full schema on first use),
        # so the fixed per-request tool cost does not scale with tool count.
        from agent_core.runtime.tool_tiering import cold_tool_names

        cold = cold_tool_names(
            [self._tools.get(name) for name in self._agent_tool_names(spec)],
            enabled=settings.tool_tiering_enabled,
            explicit=settings.tool_tiering_cold_tools,
        )
        return create_deep_agent(
            model=self._model_factory(spec.model),
            tools=tools,
            system_prompt=context.prompt,
            subagents=[self._resolve_subagent(ref, parent_id=spec.id) for ref in spec.subagents]
            or None,
            middleware=build_middleware(
                spec,
                self._model_factory,
                self._usage_provider,
                cold_tools=cold,
                fanout=self._fanout,
                gate=self._gate,
            ),
            # Read-only mount rule: /inputs is immutable (invariant I-01).
            # /skills is deliberately writable — a skill is a directory the
            # agent owns (see docs/skills-as-directory.md).
            permissions=filesystem_permissions(),
            # Resolved lazily: build() runs inside a loop, construction may not.
            checkpointer=self._checkpointer_provider() if self._checkpointer_provider else None,
            name=spec.name,
            **self._backend_kwargs(spec),
        )

    def _context_builder(self) -> ContextBuilder:
        """The prompt assembler for this run (budget from settings)."""
        settings = self._settings or get_settings()
        return ContextBuilder(injected_budget=settings.context_injected_budget)

    def context_breakdown(self, spec: AgentSpec) -> dict[str, int]:
        """Estimate the static prompt parts for ``spec``: tool schemas and
        skill manifests (see :mod:`agent_core.runtime.context_breakdown`).
        Message-history tokens are dynamic and counted per model call."""
        from agent_core.runtime.context_breakdown import static_breakdown
        from agent_core.runtime.tool_tiering import cold_tool_names

        settings = self._settings or get_settings()
        names = self._agent_tool_names(spec)
        definitions = [self._tools.get(name) for name in names]
        # Cold tools are advertised as stubs, so count them as such — otherwise
        # the breakdown would report a cost that is not actually sent.
        cold = cold_tool_names(
            definitions,
            enabled=settings.tool_tiering_enabled,
            explicit=settings.tool_tiering_cold_tools,
        )
        return static_breakdown(definitions, self._skills.list(), cold_names=cold)

    def _agent_tool_names(self, spec: AgentSpec) -> list[str]:
        """The tool names an agent is bound to (R22: via the resolver).

        The resolver is the single place that decides which tools an agent may
        use; the builder only turns those names into runnable tools. An empty
        ``spec.tools`` still means "everything available", but that rule now
        lives in one object the console can query too.
        """
        return self._capabilities.buildable_names(spec)

    def _backend_kwargs(self, spec: AgentSpec) -> dict[str, Any]:
        """Build the agent's filesystem backend and skill mount.

        The agent gets a *controlled* working environment, not the raw task
        directory: the task root is laid out as ``inputs/`` (read-only),
        ``workspace/``, ``outputs/`` and ``scratch/`` (writable) — see
        :mod:`agent_core.workspace`.

        Skills are a *directory the agent owns*: ``<workspace>/skills`` is
        mounted read-write at ``/skills`` through a :class:`CompositeBackend`
        route, so the agent reads, adds, edits and deletes skills with its
        ordinary file tools — there is no separate registration step. The
        framework's skill discovery lists ``/skills/`` and reads each
        ``/skills/<id>/SKILL.md``, which the route serves directly (no index
        shim needed: the whole directory is one mount).
        """
        from deepagents.backends import CompositeBackend

        from agent_core.workspace.backend import BoundaryBackend

        settings = self._settings or get_settings()
        workspace = Path(settings.workspace_dir)
        backend_root = current_task_dir(workspace)
        WorkspaceLayout.ensure(backend_root)
        backend: Any = FilesystemBackend(root_dir=backend_root)
        root = skills_root(workspace)
        routes: dict[str, Any] = {
            "/skills/": FilesystemBackend(root_dir=root, virtual_mode=True)
        }
        backend = CompositeBackend(default=backend, routes=routes)
        # Data-layer enforcement of the read-only mounts (I-01): the middleware
        # checks the tool wrappers, this also guards direct calls.
        backend = BoundaryBackend(backend)
        return {"skills": ["/skills/"], "backend": backend}

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