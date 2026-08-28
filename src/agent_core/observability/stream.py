"""Run-scoped event streams for live consumers (SSE, WebSockets, tests).

The broker subscribes once to the process-wide :class:`EventBus` and routes
each event to per-subscriber bounded queues. Slow consumers drop events
instead of ever blocking the run that produced them. Everything is single
event loop; cross-thread publishing is out of scope for v1.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from agent_core.domain.trace import TraceEvent
from agent_core.observability.events import EventBus
from agent_core.observability.logger import get_logger

logger = get_logger(__name__)

_CLOSE_SENTINEL: TraceEvent | None = None


class EventStream:
    """One subscriber's live view of events, backed by a bounded queue."""

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[TraceEvent | None] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def push(self, event: TraceEvent) -> None:
        """Enqueue ``event``; drop it if this consumer cannot keep up."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.debug("Event stream dropped event (consumer too slow)")

    def replay(self, events: list[TraceEvent]) -> None:
        """Seed the stream with past events (e.g. from the tracer)."""
        for event in events:
            self.push(event)

    async def events(self) -> AsyncIterator[TraceEvent]:
        """Yield events until the stream is closed."""
        while True:
            event = await self._queue.get()
            if event is None:  # close sentinel
                return
            yield event

    def close(self) -> None:
        """Signal the end of the stream to the consumer."""
        try:
            self._queue.put_nowait(_CLOSE_SENTINEL)
        except asyncio.QueueFull:
            # Make room for the sentinel so the consumer is always released.
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(_CLOSE_SENTINEL)


class EventStreamBroker:
    """Routes bus events to per-subscriber live streams."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._subscriptions: list[tuple[str | None, EventStream]] = []
        bus.subscribe(self.publish)

    def subscribe(self, run_id: str | None = None, *, maxsize: int = 1000) -> EventStream:
        """Open a stream for one run, or for all runs when ``run_id`` is None."""
        stream = EventStream(maxsize=maxsize)
        self._subscriptions.append((run_id, stream))
        return stream

    def unsubscribe(self, stream: EventStream) -> None:
        """Close and forget ``stream``."""
        stream.close()
        self._subscriptions = [(r, s) for r, s in self._subscriptions if s is not stream]

    def publish(self, event: TraceEvent) -> None:
        """Fan one event out to matching subscribers (bus listener entry point)."""
        for want_run, stream in list(self._subscriptions):
            if want_run is None or want_run == event.run_id:
                stream.push(event)
