"""Unit tests for the event stream broker (SSE data source)."""

import asyncio

from agent_core.domain.task import Run
from agent_core.domain.trace import EventType, TraceEvent
from agent_core.observability.events import EventBus
from agent_core.observability.stream import EventStreamBroker


def make_event(run_id: str, event_type: EventType = EventType.AGENT_THINKING) -> TraceEvent:
    run = Run(task_id="t", agent_id="a")
    run.id = run_id  # deterministic run id for filtering
    return TraceEvent(event_type=event_type, run_id=run_id)


def make_task_event(
    run_id: str, task_id: str, event_type: EventType = EventType.AGENT_THINKING
) -> TraceEvent:
    run = Run(task_id=task_id, agent_id="a")
    run.id = run_id
    return TraceEvent(event_type=event_type, run_id=run_id, task_id=task_id)


async def collect(stream, count: int) -> list[TraceEvent]:
    received: list[TraceEvent] = []
    async for event in stream.events():
        received.append(event)
        if len(received) == count:
            break
    return received


class TestEventStreamBroker:
    async def test_global_subscription_receives_all_events(self) -> None:
        bus = EventBus()
        broker = EventStreamBroker(bus)
        stream = broker.subscribe()
        first, second = make_event("run-1"), make_event("run-2")

        bus.publish(first)
        bus.publish(second)

        received = await collect(stream, 2)
        assert received == [first, second]

    async def test_run_scoped_subscription_filters_other_runs(self) -> None:
        bus = EventBus()
        broker = EventStreamBroker(bus)
        stream = broker.subscribe("run-1")
        mine, other = make_event("run-1"), make_event("run-2")

        bus.publish(other)
        bus.publish(mine)

        received = await collect(stream, 1)
        assert received == [mine]

    async def test_task_scoped_subscription_covers_all_runs_of_the_task(self) -> None:
        """A conversation's stream sees every root run of the task — the fix
        for the console's run detail resetting on each follow-up message."""
        bus = EventBus()
        broker = EventStreamBroker(bus)
        stream = broker.subscribe(task_id="task-1")
        turn1, turn2 = make_task_event("run-1", "task-1"), make_task_event("run-2", "task-1")
        other_task = make_task_event("run-3", "task-2")

        bus.publish(other_task)
        bus.publish(turn1)
        bus.publish(turn2)

        received = await collect(stream, 2)
        assert received == [turn1, turn2]

    async def test_slow_consumer_drops_instead_of_blocking(self) -> None:
        bus = EventBus()
        broker = EventStreamBroker(bus)
        stream = broker.subscribe(maxsize=2)

        for i in range(10):
            bus.publish(make_event(f"run-{i}"))

        assert stream.dropped == 8
        await collect(stream, 2)  # queue still delivers what it kept

    async def test_close_terminates_iteration(self) -> None:
        bus = EventBus()
        broker = EventStreamBroker(bus)
        stream = broker.subscribe()

        async def consume() -> list[TraceEvent]:
            return [event async for event in stream.events()]

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        broker.unsubscribe(stream)

        assert await task == []  # sentinel released the consumer with no events

    async def test_replay_seeds_past_events_before_live_ones(self) -> None:
        bus = EventBus()
        broker = EventStreamBroker(bus)
        stream = broker.subscribe()
        past, live = make_event("run-1"), make_event("run-1")

        stream.replay([past])
        bus.publish(live)

        assert await collect(stream, 2) == [past, live]
