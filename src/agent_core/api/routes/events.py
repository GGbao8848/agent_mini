"""SSE event streams.

``GET /runs/{id}/events`` replays the run's recorded events and then streams
live ones, closing when the run reaches a terminal state — a client that only
wants one run's outcome can just read to EOF. ``GET /events`` is a global
firehose that stays open until the client disconnects. Every payload is a
JSON-serialized :class:`EventOut`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from sse_starlette import EventSourceResponse

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import EventOut
from agent_core.domain.trace import EventType

router = APIRouter(tags=["events"])

# The runtime emits RUN_FAILED (not a distinct event) for timeout outcomes.
_TERMINAL_EVENTS = frozenset(
    {EventType.RUN_FINISHED, EventType.RUN_FAILED, EventType.RUN_CANCELLED}
)


def _sse(event: Any) -> dict[str, str]:
    return {"event": event.event_type.value, "data": EventOut.of(event).model_dump_json()}


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, service: ServiceDep) -> EventSourceResponse:
    service.get_run(run_id)  # fail fast with 404 before opening the stream

    async def generator() -> AsyncIterator[dict[str, str]]:
        stream = service.subscribe_events(run_id)
        try:
            stream.replay(service.trace_events(run_id))
            async for event in stream.events():
                yield _sse(event)
                if event.event_type in _TERMINAL_EVENTS:
                    break
        finally:
            service.unsubscribe_events(stream)

    return EventSourceResponse(generator())


@router.get("/events")
async def stream_all_events(service: ServiceDep) -> EventSourceResponse:
    async def generator() -> AsyncIterator[dict[str, str]]:
        stream = service.subscribe_events()
        try:
            async for event in stream.events():
                yield _sse(event)
        finally:
            service.unsubscribe_events(stream)

    return EventSourceResponse(generator())
