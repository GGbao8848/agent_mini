"""Tracer abstraction.

The runtime depends only on the :class:`Tracer` protocol. The in-memory
implementation keeps events per run for tests and the API layer (Phase 7);
later backends (log shipper, database) implement the same protocol.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from agent_core.domain.trace import TraceEvent
from agent_core.observability.logger import get_logger

logger = get_logger(__name__)


class Tracer(Protocol):
    def emit(self, event: TraceEvent) -> None: ...

    def get_events(self, run_id: str) -> list[TraceEvent]:
        """Recorded events for ``run_id`` (read side used by the API layer)."""
        ...

    def get_task_events(self, task_id: str) -> list[TraceEvent]:
        """Recorded events for every run of ``task_id``, in emission order."""
        ...


class InMemoryTracer:
    """Keeps trace events in process memory, bounded per run."""

    def __init__(self, max_events_per_run: int = 10_000) -> None:
        self._max_events_per_run = max_events_per_run
        self._events: dict[str, list[TraceEvent]] = defaultdict(list)

    @property
    def max_events_per_run(self) -> int:
        """Buffer bound per run (used by restoring backends to match it)."""
        return self._max_events_per_run

    def emit(self, event: TraceEvent) -> None:
        events = self._events[event.run_id]
        if len(events) >= self._max_events_per_run:
            logger.warning("Trace buffer for run %s is full; dropping event", event.run_id)
            return
        events.append(event)
        logger.debug("event=%s run=%s tool=%s", event.event_type.value, event.run_id, event.tool)

    def get_events(self, run_id: str) -> list[TraceEvent]:
        return list(self._events.get(run_id, []))

    def get_task_events(self, task_id: str) -> list[TraceEvent]:
        """All recorded events whose run belongs to ``task_id``.

        Events are buffered per run and each carries the conversation it
        belongs to (nested sub-agent events inherit the root run's task), so a
        conversation's full timeline is the union of its runs' events, ordered
        by emission timestamp.
        """
        events = [
            event
            for run_events in self._events.values()
            for event in run_events
            if event.task_id == task_id
        ]
        events.sort(key=lambda event: (event.timestamp, event.id))
        return events
