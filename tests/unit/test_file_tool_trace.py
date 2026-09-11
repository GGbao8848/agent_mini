"""The built-in filesystem tools must show up in the run trace.

They bypass the ActionGate, so before this middleware a file-heavy stretch of a
run rendered as a long 思考 block with no visible work in the console's 已工作
chain. These tests pin the observation contract.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_core.domain.task import Run
from agent_core.domain.trace import EventType
from agent_core.observability.emitter import EventFanout
from agent_core.observability.events import EventBus
from agent_core.observability.trace import InMemoryTracer
from agent_core.runtime.context import current_run
from agent_core.runtime.file_tool_trace import FileToolTraceMiddleware


class _Request:
    def __init__(self, name: str, args: dict[str, Any] | None = None) -> None:
        self.tool_call = {"name": name, "args": args or {}, "id": "c1"}


def _setup() -> tuple[FileToolTraceMiddleware, InMemoryTracer, Run]:
    tracer = InMemoryTracer()
    fanout = EventFanout(tracer, EventBus())
    run = Run(task_id="t", agent_id="avatar")
    return FileToolTraceMiddleware(fanout), tracer, run


async def _ok_handler(request: _Request) -> str:
    return "file contents"


@pytest.mark.asyncio
async def test_builtin_file_tool_emits_started_and_executed() -> None:
    middleware, tracer, run = _setup()
    token = current_run.set(run)

    result = await middleware.awrap_tool_call(
        _Request("read_file", {"file_path": "outputs/a.pptx"}), _ok_handler
    )

    assert result == "file contents"
    events = tracer.get_events(run.id)
    assert [e.event_type for e in events] == [
        EventType.TOOL_STARTED,
        EventType.TOOL_EXECUTED,
    ]
    assert events[0].tool == "read_file"
    assert events[0].input == {"file_path": "outputs/a.pptx"}
    assert events[1].output == "file contents"
    current_run.reset(token)


@pytest.mark.asyncio
async def test_non_filesystem_tool_is_untouched() -> None:
    """Registered tools already emit through the gate — no double events."""
    middleware, tracer, run = _setup()
    token = current_run.set(run)

    await middleware.awrap_tool_call(_Request("run_code"), _ok_handler)

    assert tracer.get_events(run.id) == []
    current_run.reset(token)


@pytest.mark.asyncio
async def test_failure_is_recorded_and_reraised() -> None:
    middleware, tracer, run = _setup()
    token = current_run.set(run)

    async def _boom(request: _Request) -> str:
        raise PermissionError("write denied")

    with pytest.raises(PermissionError):
        await middleware.awrap_tool_call(_Request("write_file"), _boom)

    events = tracer.get_events(run.id)
    assert [e.event_type for e in events] == [
        EventType.TOOL_STARTED,
        EventType.TOOL_FAILED,
    ]
    assert "write denied" in (events[1].error or "")
    current_run.reset(token)


@pytest.mark.asyncio
async def test_large_structured_result_is_capped() -> None:
    middleware, tracer, run = _setup()
    token = current_run.set(run)

    async def _big(request: _Request) -> dict[str, str]:
        return {"entries": "x" * 20000}

    await middleware.awrap_tool_call(_Request("ls"), _big)

    executed = [e for e in tracer.get_events(run.id) if e.event_type is EventType.TOOL_EXECUTED]
    # 20 KB in, ~4 KB (+ a short truncation marker) out: the trace payload is
    # bounded so one verbose ls/glob cannot bloat every future prefill.
    assert executed and len(executed[0].output or "") < 5000
    current_run.reset(token)
