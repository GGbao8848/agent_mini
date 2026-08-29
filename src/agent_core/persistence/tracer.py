"""Persisting tracer: in-memory read side, SQLite write-through.

The API layer (SSE replay, ``final_output``) reads events from the in-memory
buffer exactly as before; every emitted event is additionally mirrored into
the store so a restart can re-seed the buffer and run outputs stay queryable.
"""

from __future__ import annotations

from agent_core.domain.trace import TraceEvent
from agent_core.observability.trace import InMemoryTracer
from agent_core.persistence.store import SqliteStore


class PersistingTracer:
    """A :class:`Tracer` that mirrors every event into the store."""

    def __init__(self, inner: InMemoryTracer, store: SqliteStore) -> None:
        self._inner = inner
        self._store = store

    def emit(self, event: TraceEvent) -> None:
        self._inner.emit(event)
        self._store.append_event(event.run_id, event.model_dump_json())

    def get_events(self, run_id: str) -> list[TraceEvent]:
        return self._inner.get_events(run_id)

    def restore(self) -> None:
        """Re-seed the in-memory buffer with events from previous processes.

        Only the most recent ``max_events_per_run`` events of each run are
        replayed, matching the live buffer's bound.
        """
        events: dict[str, list[TraceEvent]] = {}
        for run_id, data in self._store.load_events():
            events.setdefault(run_id, []).append(TraceEvent.model_validate_json(data))
        cap = self._inner.max_events_per_run
        for run_events in events.values():
            for event in run_events[-cap:]:
                self._inner.emit(event)
