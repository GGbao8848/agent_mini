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


class InMemoryTracer:
    """Keeps trace events in process memory, bounded per run."""

    def __init__(self, max_events_per_run: int = 10_000) -> None:
        self._max_events_per_run = max_events_per_run
        self._events: dict[str, list[TraceEvent]] = defaultdict(list)

    def emit(self, event: TraceEvent) -> None:
        events = self._events[event.run_id]
        if len(events) >= self._max_events_per_run:
            logger.warning("Trace buffer for run %s is full; dropping event", event.run_id)
            return
        events.append(event)
        logger.debug("event=%s run=%s tool=%s", event.event_type.value, event.run_id, event.tool)

    def get_events(self, run_id: str) -> list[TraceEvent]:
        return list(self._events.get(run_id, []))
