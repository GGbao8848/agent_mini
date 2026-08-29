"""Persisting tracer: in-memory read side, SQLite write-through.

The API layer (SSE replay, ``final_output``) reads events from the in-memory
buffer exactly as before; every emitted event is additionally mirrored into
the store so a restart can re-seed the buffer and run outputs stay queryable.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.trace import TraceEvent
from agent_core.observability.trace import InMemoryTracer
from agent_core.persistence.store import SqliteStore


def _trim(value: Any, limit: int = 100_000) -> Any:
    """Cap giant strings (base64 image data) in persisted event payloads."""
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:80]}...[truncated {len(value)} chars]"
    if isinstance(value, dict):
        return {key: _trim(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_trim(item, limit) for item in value]
    return value


class PersistingTracer:
    """A :class:`Tracer` that mirrors every event into the store."""

    def __init__(self, inner: InMemoryTracer, store: SqliteStore) -> None:
        self._inner = inner
        self._store = store

    _MAX_FIELD_CHARS = 100_000

    def emit(self, event: TraceEvent) -> None:
        self._inner.emit(event)
        # The persisted mirror drops giant inline payloads (base64 images in
        # view_image results can be ~1MB each — the run's artifact files hold
        # the real content). The in-memory buffer keeps the full event.
        trimmed = event.model_copy(
            update={
                "input": _trim(event.input),
                "output": _trim(event.output),
                "metadata": _trim(event.metadata),
            }
        )
        self._store.append_event(event.run_id, trimmed.model_dump_json())

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
