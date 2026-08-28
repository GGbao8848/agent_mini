"""SUBAGENT_* trace events from DeepAgents delegation chains.

Contract (verified against deepagents 0.7.10): the root chain of a delegated
subagent fires ``on_chain_start`` with ``name`` equal to the subagent name
and ``metadata['lc_agent_name']`` equal to the same value; nested middleware
nodes inside the subagent carry ``lc_agent_name`` but a different ``name``.
Matching both pins the subagent's top-level chain exactly, so exactly one
STARTED/FINISHED pair is emitted per delegation. Because callbacks propagate
to subagents automatically, one handler on the root run observes the whole
team.
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from agent_core.domain.task import Run
from agent_core.domain.trace import EventType
from agent_core.observability.emitter import EventFanout
from agent_core.runtime.text import last_message_text


class SubagentTraceHandler(BaseCallbackHandler):
    """Emits SUBAGENT_STARTED / SUBAGENT_FINISHED for delegated workers."""

    def __init__(self, fanout: EventFanout, run: Run, names: set[str]) -> None:
        self._fanout = fanout
        self._run = run
        self._names = names
        self._active: dict[uuid.UUID, str] = {}

    def on_chain_start(
        self, serialized: Any, inputs: Any, *, run_id: uuid.UUID, name: str = "", **kwargs: Any
    ) -> None:
        metadata = kwargs.get("metadata") or {}
        if name not in self._names or metadata.get("lc_agent_name") != name:
            return
        if run_id in self._active:
            return
        self._active[run_id] = name
        self._fanout.emit(
            EventType.SUBAGENT_STARTED,
            run=self._run,
            agent_id=self._run.agent_id,
            metadata={"subagent": name},
        )

    def on_chain_end(self, outputs: Any, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        name = self._active.pop(run_id, None)
        if name is None:
            return
        self._fanout.emit(
            EventType.SUBAGENT_FINISHED,
            run=self._run,
            agent_id=self._run.agent_id,
            output=last_message_text(outputs),
            metadata={"subagent": name},
        )

    def on_chain_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        name = self._active.pop(run_id, None)
        if name is None:
            return
        self._fanout.emit(
            EventType.SUBAGENT_FINISHED,
            run=self._run,
            agent_id=self._run.agent_id,
            error=str(error),
            metadata={"subagent": name},
        )
