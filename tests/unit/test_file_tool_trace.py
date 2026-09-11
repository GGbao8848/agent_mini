"""The built-in filesystem tools must show up in the run trace.

They bypass the ActionGate, so before this middleware a file-heavy stretch of a
run rendered as a long 思考 block with no visible work in the console's 已工作
chain. These tests pin the observation contract.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_core.domain.permission_mode import PermissionMode
from agent_core.domain.task import Run
from agent_core.domain.trace import EventType
from agent_core.observability.emitter import EventFanout
from agent_core.observability.events import EventBus
from agent_core.observability.trace import InMemoryTracer
from agent_core.runtime.context import current_permission_mode, current_run
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


# ---------------------------------------------------- permission modes


class _FakeGate:
    """Records approval asks; optionally rejects them."""

    def __init__(self, reject: bool = False) -> None:
        self.asked: list[str] = []
        self._reject = reject

    async def request_approval_for(self, *, run: Any, tool_name: str, **_: Any) -> None:
        self.asked.append(tool_name)
        if self._reject:
            from agent_core.errors.exceptions import ApprovalRejectedError

            raise ApprovalRejectedError("a1", "user")


def _wrote(handler_calls: list[Any]):
    async def _handler(request: _Request, _calls: list[Any] = handler_calls) -> str:
        _calls.append(request.tool_call.get("name"))
        return "written"

    return _handler


async def _run_write(mode: PermissionMode, gate: _FakeGate | None) -> tuple[Any, list[Any], InMemoryTracer, Run, Any]:
    tracer = InMemoryTracer()
    mw = FileToolTraceMiddleware(EventFanout(tracer, EventBus()), gate)
    run = Run(task_id="t", agent_id="avatar")
    calls: list[Any] = []
    token_run = current_run.set(run)
    token_mode = current_permission_mode.set(mode)
    result = await mw.awrap_tool_call(
        _Request("write_file", {"file_path": "a.txt", "content": "x"}), _wrote(calls)
    )
    current_permission_mode.reset(token_mode)
    current_run.reset(token_run)
    return result, calls, tracer, run, token_run


@pytest.mark.asyncio
async def test_plan_mode_refuses_writes_without_running_them() -> None:
    result, calls, tracer, run, _ = await _run_write(PermissionMode.PLAN, _FakeGate())
    assert calls == []  # the write never executed
    assert "计划模式" in getattr(result, "content", "")


@pytest.mark.asyncio
async def test_confirm_mode_asks_then_runs_on_approval() -> None:
    gate = _FakeGate()
    result, calls, _tracer, _run_, _ = await _run_write(PermissionMode.CONFIRM, gate)
    assert gate.asked == ["write_file"]
    assert calls == ["write_file"]  # approved → ran
    assert result == "written"


@pytest.mark.asyncio
async def test_confirm_mode_refusal_blocks_the_write() -> None:
    gate = _FakeGate(reject=True)
    result, calls, _tracer, _run_, _ = await _run_write(PermissionMode.CONFIRM, gate)
    assert gate.asked == ["write_file"]
    assert calls == []  # rejected → did not run
    assert "拒绝" in getattr(result, "content", "")


@pytest.mark.asyncio
async def test_auto_and_full_modes_write_without_asking() -> None:
    for mode in (PermissionMode.AUTO, PermissionMode.FULL):
        gate = _FakeGate()
        _result, calls, _tracer, _run_, _ = await _run_write(mode, gate)
        assert gate.asked == [], f"{mode} must not prompt"
        assert calls == ["write_file"]


@pytest.mark.asyncio
async def test_reads_are_never_gated() -> None:
    gate = _FakeGate()
    tracker = InMemoryTracer()
    mw = FileToolTraceMiddleware(EventFanout(tracker, EventBus()), gate)
    run = Run(task_id="t", agent_id="avatar")
    token_run = current_run.set(run)
    token_mode = current_permission_mode.set(PermissionMode.PLAN)
    calls: list[Any] = []
    result = await mw.awrap_tool_call(
        _Request("read_file", {"file_path": "a.txt"}), _wrote(calls)
    )
    current_permission_mode.reset(token_mode)
    current_run.reset(token_run)
    assert result == "written"
    assert calls == ["read_file"]
    assert gate.asked == []
