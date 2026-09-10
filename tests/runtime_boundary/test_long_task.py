"""Long-task observability invariants (R-B).

- A TimeoutError raised *inside* the graph (socket/HTTP/subprocess) must not be
  reported as the run's own deadline — it used to masquerade as "timed out
  after 5400s" for runs that only lasted minutes.
- A running run emits periodic heartbeat events so a long silent stretch is
  distinguishable from a stuck run.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_core.domain.agent import AgentSpec
from agent_core.domain.task import Run, RunStatus
from agent_core.errors.exceptions import AgentExecutionError, RunTimeoutError
from agent_core.runtime.executor import AgentExecutor


class _FakeGraph:
    """A graph whose ainvoke either raises a given error or blocks."""

    def __init__(self, *, raises: BaseException | None = None, delay: float = 0.0) -> None:
        self._raises = raises
        self._delay = delay

    async def ainvoke(self, *_args: Any, **_kwargs: Any) -> Any:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        from langchain_core.messages import AIMessage

        return {"messages": [AIMessage(content="done")]}


def _run() -> Run:
    return Run(id="r1", task_id="t1", agent_id="a1", status=RunStatus.RUNNING)


def _spec(timeout: float) -> AgentSpec:
    spec = AgentSpec(id="a1", name="A", model="openai:gpt-4o-mini")
    spec.limits.timeout_seconds = timeout
    return spec


async def test_inner_timeout_is_not_reported_as_run_deadline() -> None:
    """A socket/step timeout surfaces as a step failure, not a 5400s run timeout."""
    graph = _FakeGraph(raises=TimeoutError("socket read timed out"))
    executor = AgentExecutor()

    with pytest.raises(AgentExecutionError) as excinfo:
        await executor.execute(
            graph, run=_run(), input_text="hi", spec=_spec(5400.0)  # type: ignore[arg-type]
        )

    assert "step inside the run timed out" in str(excinfo.value)
    assert not isinstance(excinfo.value, RunTimeoutError)


async def test_outer_deadline_is_reported_as_run_timeout() -> None:
    """Only the real deadline produces RunTimeoutError."""
    graph = _FakeGraph(delay=5.0)
    executor = AgentExecutor()

    with pytest.raises(RunTimeoutError):
        await executor.execute(
            graph, run=_run(), input_text="hi", spec=_spec(0.05)  # type: ignore[arg-type]
        )


def test_heartbeat_event_type_is_registered() -> None:
    from agent_core.domain.trace import EventType

    assert EventType.RUN_HEARTBEAT.value == "run_heartbeat"
