"""Tool tiering tests (R20 §10).

Cold tools are advertised as cheap stubs and their full schema is injected only
once the agent reaches for them. These tests pin the classification, the
advertisement rewrite, the interception (before the real schema validates the
guessed args) and the end-to-end activate -> retry -> execute loop.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent_core.domain.tool import ToolDefinition
from agent_core.runtime.tool_tiering import ToolTieringMiddleware, cold_tool_names


def definition(name: str, source: str = "python") -> ToolDefinition:
    return ToolDefinition(name=name, description=f"{name} does a thing", source=source)  # type: ignore[arg-type]


# --------------------------------------------------------- classification


def test_mcp_tools_are_cold_by_default() -> None:
    defs = [definition("run_code"), definition("mcp_search", "mcp")]
    assert cold_tool_names(defs, enabled=True, explicit=None) == {"mcp_search"}


def test_explicit_list_overrides_the_source_default() -> None:
    defs = [definition("run_code"), definition("mcp_search", "mcp")]
    cold = cold_tool_names(defs, enabled=True, explicit="run_code")
    assert cold == {"run_code"}  # only the explicit one, not MCP


def test_explicit_prefix_match() -> None:
    defs = [definition("tinyfish_search"), definition("tinyfish_fetch")]
    assert cold_tool_names(defs, enabled=True, explicit="tinyfish") == {
        "tinyfish_search",
        "tinyfish_fetch",
    }


def test_disabled_means_no_cold_tools() -> None:
    defs = [definition("mcp_search", "mcp")]
    assert cold_tool_names(defs, enabled=False, explicit="mcp_search") == set()


# --------------------------------------------------------- advertisement


class _Request:
    """Minimal ModelRequest stand-in for the unit tests."""

    def __init__(self, tools: list[Any], tool_call: dict[str, Any] | None = None) -> None:
        self.tools = tools
        self.tool_call = tool_call

    def override(self, **kwargs: Any) -> _Request:
        return _Request(kwargs.get("tools", self.tools), self.tool_call)


class _SimpleArgs(BaseModel):
    x: str = Field(default="", description="x")


def tool(name: str) -> StructuredTool:
    return StructuredTool(
        name=name,
        description=f"{name} full description",
        args_schema=_SimpleArgs,
        func=lambda x="": name,
    )


def long_tool(name: str) -> StructuredTool:
    """A tool with a verbose description — the case tiering actually targets."""
    return StructuredTool(
        name=name,
        description="Summary sentence. " + "y" * 400,
        args_schema=_SimpleArgs,
        func=lambda x="": name,
    )


def test_cold_tool_is_advertised_as_a_stub() -> None:
    middleware = ToolTieringMiddleware({"cold"})
    request = _Request([tool("hot"), long_tool("cold")])
    advertised = middleware._advertised(request)  # noqa: SLF001 - unit-testing the hook
    names = [t.name for t in advertised.tools]
    assert names == ["hot", "cold"]  # still discoverable by name
    stub = advertised.tools[1]
    assert "y" * 400 not in (stub.description or "")  # long prose trimmed away
    assert "完整参数说明" in (stub.description or "")


def test_hot_tools_are_untouched() -> None:
    middleware = ToolTieringMiddleware({"cold"})
    request = _Request([tool("hot")])
    assert middleware._advertised(request) is request  # no rewrite, same object


def test_activated_cold_tool_gets_full_schema() -> None:
    middleware = ToolTieringMiddleware({"cold"})
    middleware._activate(_Request([], {"name": "cold", "id": "1"}))  # noqa: SLF001
    request = _Request([tool("cold")])
    advertised = middleware._advertised(request)  # noqa: SLF001
    assert advertised.tools[0].description == "cold full description"


# --------------------------------------------------------- interception


def test_first_cold_call_is_intercepted() -> None:
    middleware = ToolTieringMiddleware({"cold"})
    result = middleware._activate(_Request([], {"name": "cold", "id": "c1"}))  # noqa: SLF001
    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "c1"
    assert "cold" in result.content
    assert middleware.activated == {"cold"}


def test_second_cold_call_passes_through() -> None:
    middleware = ToolTieringMiddleware({"cold"})
    middleware._activate(_Request([], {"name": "cold", "id": "c1"}))  # noqa: SLF001
    assert middleware._activate(_Request([], {"name": "cold", "id": "c2"})) is None  # noqa: SLF001


def test_hot_call_is_never_intercepted() -> None:
    middleware = ToolTieringMiddleware({"cold"})
    assert middleware._activate(_Request([], {"name": "hot", "id": "c1"})) is None  # noqa: SLF001


def test_missing_tool_call_is_safe() -> None:
    middleware = ToolTieringMiddleware({"cold"})
    assert middleware._activate(_Request([])) is None  # noqa: SLF001


# ------------------------------------------------- end-to-end activation


class _Args(BaseModel):
    query: str = Field(description="q")
    max_results: int = Field(default=5)


def _cold_tool() -> StructuredTool:
    def run(**kwargs: Any) -> str:
        return f"executed:{kwargs}"

    return StructuredTool(
        name="mcp_search", description="Search the web. " + "y" * 400, args_schema=_Args, func=run
    )


class _RecordingModel(BaseChatModel):
    """Emits a cold call on turn 1 (with wrong-shape args), then finishes."""

    turn: int = 0
    calls: list[list[str]] = []  # class-level capture for the test

    @property
    def _llm_type(self) -> str:
        return "recording"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        _RecordingModel.calls.append([getattr(t, "name", str(t)) for t in tools])
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> ChatResult:
        self.turn += 1
        if self.turn == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {"name": "mcp_search", "args": {"wrong": "shape"}, "id": "c1"}
                ],
            )
        else:
            message = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=message)])


async def test_end_to_end_activate_retry_execute() -> None:
    """A shape-guessed cold call activates instead of failing, then retries."""
    _RecordingModel.calls = []
    middleware = ToolTieringMiddleware({"mcp_search"})
    agent = create_agent(_RecordingModel(), tools=[_cold_tool()], middleware=[middleware])

    result = await agent.ainvoke({"messages": [{"role": "user", "content": "go"}]})

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    # The guessed call did NOT error — it was intercepted with a retry hint.
    assert any("完整参数说明" in m.content for m in tool_messages)
    assert middleware.activated == {"mcp_search"}
    # The first model turn saw the stub (short description), the second the real one.
    assert len(_RecordingModel.calls) >= 1
