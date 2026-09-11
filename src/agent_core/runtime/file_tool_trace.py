"""Make deepagents' built-in filesystem tools visible — and governable.

deepagents supplies ``ls`` / ``read_file`` / ``write_file`` / ``edit_file`` /
``glob`` / ``grep`` internally: they never pass through the in-house
:class:`~agent_core.permissions.gate.ActionGate`, so they (a) emitted no
``tool_started`` / ``tool_executed`` events — the console's 已工作 chain then
showed only ``run_code`` steps while the agent was in fact reading and writing
files — and (b) were never subject to the conversation's permission mode.

This middleware wraps each built-in file tool and does two things:

1. **Observe**: emit the same ``tool_started`` / ``tool_executed`` /
   ``tool_failed`` events the gate emits for registered tools.
2. **Govern writes**: apply the in-flight run's :class:`PermissionMode` —
   ``plan`` refuses the write, ``confirm`` asks the human first via the same
   approval gate, ``auto`` / ``full`` proceed.

Reads are never gated (only ``write_file`` / ``edit_file`` reach the approval
path). deepagents' own filesystem-permission middleware still runs *inside*
this wrapper, so the workspace boundary is enforced exactly as before; this
adds the missing approval layer on top, it does not replace it.
"""

from __future__ import annotations

import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from agent_core.domain.action import Action
from agent_core.domain.permission_mode import PermissionMode
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import ApprovalRejectedError
from agent_core.observability.emitter import EventFanout
from agent_core.runtime.context import get_current_permission_mode, get_current_run
from agent_core.runtime.text import cap_result

FS_TOOL_NAMES = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}
)
"""The framework-provided filesystem tool names this middleware observes."""

WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file"})
"""The subset that mutates the workspace and is subject to the permission mode."""

_PLAN_REFUSAL = (
    "权限模式为「计划模式」：不能修改文件。请先给出计划，待用户切换到"
    "「自动编辑」或「完全访问」后再执行写入。"
)


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
    """Trace the built-in file tools and gate their writes by permission mode."""

    def __init__(self, fanout: EventFanout, gate: Any | None = None) -> None:
        super().__init__()
        self._fanout = fanout
        # The ActionGate owns approval creation/waiting; injected so the mode
        # logic reuses one approval path instead of a parallel one. Optional so
        # tests can exercise tracing without a full gate.
        self._gate = gate

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        # The runtime is async end-to-end; only the async hook is registered.
        return handler(request)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = getattr(request, "tool_call", None)
        name = call.get("name") if isinstance(call, dict) else None
        run = get_current_run()
        if name not in FS_TOOL_NAMES or run is None:
            return await handler(request)

        arguments = call.get("args") if call and isinstance(call.get("args"), dict) else {}

        if name in WRITE_TOOL_NAMES:
            assert isinstance(call, dict)  # name came from it
            blocked = await self._guard_write(name, call, arguments)
            if blocked is not None:
                return blocked

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

    async def _guard_write(
        self, name: str, call: dict[str, Any], arguments: dict[str, Any]
    ) -> ToolMessage | None:
        """Return a refusal ToolMessage, or None to let the write proceed."""
        run = get_current_run()
        if run is None:  # checked by the caller; belt-and-braces
            return None
        mode = get_current_permission_mode() or PermissionMode.CONFIRM
        if not mode.allows_writes:
            return self._refuse(call, _PLAN_REFUSAL)
        if mode.requires_write_approval and self._gate is not None:
            try:
                await self._gate.request_approval_for(
                    run=run,
                    tool_name=name,
                    arguments=arguments,
                    reason=f"{name} 写入文件（变更前确认模式）",
                )
            except ApprovalRejectedError:
                return self._refuse(call, "用户拒绝了这次写入。")
        return None

    @staticmethod
    def _refuse(call: dict[str, Any], message: str) -> ToolMessage:
        return ToolMessage(
            content=message,
            tool_call_id=str(call.get("id") or ""),
            name=str(call.get("name") or ""),
        )
