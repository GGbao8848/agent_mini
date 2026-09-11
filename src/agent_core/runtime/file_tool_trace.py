"""Make the framework's built-in filesystem tools visible in the run trace.

deepagents supplies ``ls`` / ``read_file`` / ``write_file`` / ``edit_file`` /
``glob`` / ``grep`` internally: they never pass through the in-house
:class:`~agent_core.permissions.gate.ActionGate`, so they emit no
``tool_started`` / ``tool_executed`` events. The console's 已工作 chain then
shows only ``run_code`` steps while the agent is in fact reading and writing
files the whole time — and a long file-heavy stretch looks like an unexplained
gap with no visible work.

This middleware only *observes* them: it wraps each built-in tool call, emits
the same ``tool_started`` / ``tool_executed`` / ``tool_failed`` events the gate
emits for registered tools, and otherwise passes the call straight through
(no permission or approval logic — that stays in the gate for registered
tools). It cannot reorder or swallow a call.

Filesystem permission enforcement is untouched: deepagents runs its own
permission middleware *inside* this wrapper, so a denied read/write still
raises exactly as before.
"""

from __future__ import annotations

import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from agent_core.domain.trace import EventType
from agent_core.observability.emitter import EventFanout
from agent_core.runtime.context import get_current_run
from agent_core.runtime.text import cap_result

FS_TOOL_NAMES = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}
)
"""The framework-provided filesystem tool names to surface in the trace."""


def _result_text(result: Any) -> str:
    """A short, capped string form of a tool result for the trace event.

    ``read_file`` / ``grep`` results are plain strings; the structured tools
    (``ls``, ``glob``) return an object whose ``str`` form can be huge, so it
    is capped the same way the gate caps registered-tool results.
    """
    if result is None:
        return ""
    capped = cap_result(result if isinstance(result, str) else str(result))
    return capped if isinstance(capped, str) else str(capped)


class FileToolTraceMiddleware(AgentMiddleware):
    """Emit tool_started/tool_executed for deepagents' built-in file tools."""

    def __init__(self, fanout: EventFanout) -> None:
        super().__init__()
        self._fanout = fanout

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        # The runtime is async end-to-end; the sync hook simply delegates so
        # LangChain does not complain about a partially-implemented middleware.
        return await self._trace(request, handler)

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        # The runtime is async end-to-end; only the async hook is registered.
        return handler(request)

    async def _trace(self, request: Any, handler: Any) -> Any:
        call = getattr(request, "tool_call", None)
        name = call.get("name") if isinstance(call, dict) else None
        run = get_current_run()
        if name not in FS_TOOL_NAMES or run is None:
            return await handler(request)

        arguments = call.get("args") if call and isinstance(call.get("args"), dict) else {}
        self._fanout.emit(
            EventType.TOOL_STARTED,
            run=run,
            agent_id=run.agent_id,
            tool=name,
            input=arguments,
        )
        started = time.monotonic()
        try:
            result = await handler(request)
        except Exception as exc:  # noqa: BLE001 — surface any failure, re-raise
            self._fanout.emit(
                EventType.TOOL_FAILED,
                run=run,
                agent_id=run.agent_id,
                tool=name,
                error=str(exc),
                duration_ms=(time.monotonic() - started) * 1000,
            )
            raise
        self._fanout.emit(
            EventType.TOOL_EXECUTED,
            run=run,
            agent_id=run.agent_id,
            tool=name,
            output=_result_text(result),
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return result
