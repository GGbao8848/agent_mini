"""Tool tiering (R20 §10): advertise heavy tools lightly, expand on use.

Every tool schema rides on EVERY model call, so hundreds of MCP tools would
make the fixed context cost grow linearly with the tool count. This middleware
breaks that: *cold* tools are advertised as a lightweight stub (name + one-line
summary, permissive schema) and their full schema is injected only once the
agent actually reaches for them.

The mechanism relies on a property of the agent loop that was verified against
the real framework (see the R20 §10 notes):

    execution set  ≠  advertisement set

Tools stay fully registered in the graph, so any call resolves; the middleware
only controls what the model is *told* about this turn. Because a model can
only call tools it was advertised (every real provider enforces this), a cold
tool is advertised as a stub — otherwise it would be unreachable.

Flow::

    core tools        -> full schema, every turn
    cold tools        -> name + summary stub (cheap)
    model calls cold  -> middleware intercepts BEFORE the real schema validates
                         the guessed args, marks it activated, returns a
                         synthetic ToolMessage telling the model to retry
    next model turn   -> that tool is advertised with its full schema
    model calls again -> executes normally

So activation costs one extra model turn, but only when a cold tool is actually
needed — and it never depends on the model choosing to "load" anything first.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict

from agent_core.domain.tool import ToolDefinition, ToolSource

_SOURCE_COLD = {ToolSource.MCP}
"""Sources treated as cold when no explicit cold-tool list is configured.

MCP servers are the external, occasional capabilities — the ones that would
otherwise dominate the fixed tool cost as soon as several are connected.
"""


class _ColdStubArgs(BaseModel):
    """Permissive args for a cold stub: the model shapes a guess, we intercept.

    The real schema is not advertised until activation, so the stub must accept
    whatever the model produces; the middleware never executes it anyway.
    """

    model_config = ConfigDict(extra="allow")


def cold_tool_names(
    definitions: list[ToolDefinition], *, enabled: bool, explicit: str | None
) -> set[str]:
    """The tool names to advertise as cold (lightweight) this run.

    ``explicit`` (comma-separated names / prefixes) wins when set; otherwise
    every tool from a cold *source* (MCP) is cold. Disabled ⇒ empty set, i.e.
    today's behaviour with no tiering.
    """
    if not enabled:
        return set()
    patterns = [p.strip() for p in (explicit or "").split(",") if p.strip()]
    if patterns:
        return {
            definition.name
            for definition in definitions
            if any(definition.name == p or definition.name.startswith(p) for p in patterns)
        }
    return {d.name for d in definitions if d.source in _SOURCE_COLD}


def _summary(description: str, limit: int) -> str:
    """A one-line discovery summary from a tool's full description."""
    text = " ".join((description or "").split())
    if not text:
        return ""
    # Prefer the first sentence, then hard-cap.
    for end in (". ", "。", "! ", "！", "? ", "？"):
        idx = text.find(end)
        if 0 < idx < limit:
            return text[: idx + 1]
    return text[:limit]


class ToolTieringMiddleware(AgentMiddleware):
    """Advertise cold tools as stubs; expand the full schema on first use."""

    def __init__(self, cold_names: set[str], *, summary_chars: int = 160) -> None:
        super().__init__()
        self._cold = set(cold_names)
        self._activated: set[str] = set()
        self._summary_chars = summary_chars

    # ------------------------------------------------------------- hooks

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._advertised(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        # The runtime is async end-to-end; without this hook LangChain refuses
        # to use the middleware at all (no automatic sync->async fallback).
        return await handler(self._advertised(request))

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        activated = self._activate(request)
        return activated if activated is not None else handler(request)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        activated = self._activate(request)
        return activated if activated is not None else await handler(request)

    # ------------------------------------------------------------ internals

    def _advertised(self, request: Any) -> Any:
        """Replace not-yet-activated cold tools with lightweight stubs."""
        if not self._cold:
            return request
        tools: list[Any] = []
        changed = False
        for tool in request.tools:
            name = getattr(tool, "name", None)
            if name in self._cold and name not in self._activated:
                tools.append(self._stub(tool))
                changed = True
            else:
                tools.append(tool)
        if not changed:
            return request
        return request.override(tools=tools)

    def _activate(self, request: Any) -> ToolMessage | None:
        """Intercept a cold tool's first call: activate it and ask for a retry.

        Runs before the real tool validates its args, so a shape-guessed call
        (which the stub schema permits) does not fail — it just triggers
        activation, and the retry turn has the full schema to get it right.
        """
        call = getattr(request, "tool_call", None)
        if not isinstance(call, dict):
            return None
        name = call.get("name")
        if name not in self._cold or name in self._activated:
            return None
        self._activated.add(name)
        return ToolMessage(
            content=(
                f"工具「{name}」的完整参数说明已加载。"
                "请现在重新调用该工具（这一次会带上完整参数定义）。"
            ),
            tool_call_id=str(call.get("id") or ""),
        )

    def _stub(self, tool: BaseTool) -> BaseTool:
        """A cheap stand-in that keeps the tool discoverable by name."""

        async def _never_called(**kwargs: Any) -> str:  # pragma: no cover - intercepted
            return f"工具「{tool.name}」尚未激活。"

        return StructuredTool(
            name=tool.name,
            description=(
                _summary(getattr(tool, "description", "") or "", self._summary_chars)
                + "（调用后将加载完整参数说明）"
            ),
            args_schema=_ColdStubArgs,
            coroutine=_never_called,
        )

    @property
    def activated(self) -> set[str]:
        """Names activated so far (this run) — for tests and observability."""
        return set(self._activated)
