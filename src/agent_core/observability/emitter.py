"""Event emission seam shared by runtime components.

Every observable action becomes a :class:`TraceEvent` that is written to the
Tracer (run-scoped record) and published on the EventBus (live fan-out).
Components depend on this one seam instead of touching both by hand.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.task import Run
from agent_core.domain.trace import EventType, TraceEvent
from agent_core.observability.events import EventBus
from agent_core.observability.trace import Tracer


class EventFanout:
    """Writes each event to the Tracer and publishes it on the EventBus."""

    def __init__(self, tracer: Tracer | None = None, bus: EventBus | None = None) -> None:
        self._tracer = tracer
        self._bus = bus

    def emit(
        self,
        event_type: EventType,
        *,
        run: Run,
        agent_id: str | None = None,
        **fields: Any,
    ) -> TraceEvent:
        """Create and distribute one event attributed to ``run``."""
        event = TraceEvent(
            event_type=event_type,
            run_id=run.id,
            task_id=run.task_id,
            parent_run_id=run.parent_run_id,
            agent_id=agent_id,
            **fields,
        )
        if self._tracer is not None:
            self._tracer.emit(event)
        if self._bus is not None:
            self._bus.publish(event)
        return event
