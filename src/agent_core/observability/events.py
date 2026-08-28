"""In-process event bus.

A thin pub/sub layer over :class:`TraceEvent`. The streaming API (SSE,
Phase 7) subscribes here; nothing in the runtime knows about transports.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from agent_core.domain.trace import EventType, TraceEvent
from agent_core.observability.logger import get_logger

logger = get_logger(__name__)

Listener = Callable[[TraceEvent], None]

E = TypeVar("E", bound=TraceEvent)


class EventBus:
    """Synchronous in-process fan-out of trace events."""

    def __init__(self) -> None:
        self._listeners: dict[EventType | None, list[Listener]] = defaultdict(list)

    def subscribe(self, listener: Listener, event_type: EventType | None = None) -> None:
        """Register ``listener``; ``event_type=None`` receives all events."""
        self._listeners[event_type].append(listener)

    def publish(self, event: TraceEvent) -> None:
        for listener in [*self._listeners[None], *self._listeners[event.event_type]]:
            try:
                listener(event)
            except Exception:
                # Listener failures must never break the run that emitted the event.
                logger.exception("Event listener failed for event %s", event.event_type)
