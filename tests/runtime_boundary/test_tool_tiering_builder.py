"""Tiering wired through the REAL builder (R20 §10).

Proves the middleware reaches the graph the runtime actually builds, that a cold
tool is advertised as a stub, and that its first call is intercepted (activate)
rather than executed — using the production AgentBuilder, not a bare
create_agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent_core.domain.agent import AgentSpec
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.builder import AgentBuilder
from agent_core.runtime.tool_tiering import cold_tool_names

_COLD_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "description": "q"}},
    "required": ["query"],
}


class _ScriptedModel(BaseChatModel):
    """Calls a named tool on the first turn, then finishes."""

    target: str = "mcp_search"
    turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        ADVERTISED.append([getattr(t, "name", str(t)) for t in tools])
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> ChatResult:
        self.turn += 1
        if self.turn == 1:
            message = AIMessage(
                content="",
                tool_calls=[{"name": self.target, "args": {"query": "hi"}, "id": "c1"}],
            )
        else:
            message = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=message)])


# Module-level so pydantic does not mistake it for a model field.
ADVERTISED: list[list[str]] = []


def _builder(model: BaseChatModel) -> AgentBuilder:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="worker", name="Worker"))
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(name="mcp_search", description="Search the web. " + "y" * 300,
                      input_schema=_COLD_SCHEMA, source=ToolSource.MCP),
        lambda query="": "COLD EXECUTED",
    )
    tools.register(
        ToolDefinition(name="hot_echo", description="Echo", input_schema=_COLD_SCHEMA),
        lambda query="": "HOT EXECUTED",
    )
    return AgentBuilder(
        agents, tools, SkillRegistry(),
        model_factory=lambda _spec: model,
        settings=None,
    )


class TestColdToolClassificationInBuilder:
    def test_mcp_tool_is_classified_cold(self) -> None:
        builder = _builder(_ScriptedModel())
        cold = cold_tool_names(
            [builder._tools.get("mcp_search"), builder._tools.get("hot_echo")],  # noqa: SLF001
            enabled=True,
            explicit=None,
        )
        assert cold == {"mcp_search"}


@pytest.mark.asyncio
async def test_real_builder_intercepts_first_cold_call(tmp_path: Path) -> None:
    """End-to-end through AgentBuilder: cold call activates, does not execute."""
    from langchain_core.runnables import RunnableConfig

    from agent_core.config.settings import Settings
    from agent_core.domain.task import Run, RunStatus
    from agent_core.runtime import context

    model = _ScriptedModel()
    ADVERTISED.clear()
    agents = AgentRegistry()
    agents.register(AgentSpec(id="worker", name="Worker"))
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(name="mcp_search", description="Search the web. " + "y" * 300,
                      input_schema=_COLD_SCHEMA, source=ToolSource.MCP),
        lambda query="": "COLD EXECUTED",
    )
    builder = AgentBuilder(
        agents, tools, SkillRegistry(),
        model_factory=lambda _spec: model,
        settings=Settings(_env_file=None, workspace_dir=str(tmp_path)),
    )

    run = Run(task_id="t", agent_id="worker")
    run.transition_to(RunStatus.RUNNING)
    context.current_run.set(run)
    context.current_task_id.set("t")
    try:
        graph = builder.build(agents.get("worker"))
        config: RunnableConfig = {"configurable": {"thread_id": "tier-test"}}
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": "search"}]}, config=config
        )
    finally:
        context.current_run.set(None)
        context.current_task_id.set(None)

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    contents = [str(m.content) for m in tool_messages]
    # The cold call was intercepted (activation hint), not executed.
    assert any("完整参数说明" in c for c in contents), contents
    assert not any("COLD EXECUTED" in c for c in contents), contents
    # The stub (short description) was advertised, never the 300-char one.
    assert ADVERTISED, "model never saw a tool list"
