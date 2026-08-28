from agent_core.domain.trace import EventType, TraceEvent
from agent_core.observability.events import EventBus
from agent_core.observability.trace import InMemoryTracer


def make_event(event_type: EventType, run_id: str = "run1") -> TraceEvent:
    return TraceEvent(event_type=event_type, run_id=run_id)


def test_tracer_keeps_events_per_run() -> None:
    tracer = InMemoryTracer()
    tracer.emit(make_event(EventType.RUN_STARTED))
    tracer.emit(make_event(EventType.AGENT_STARTED))
    tracer.emit(make_event(EventType.RUN_STARTED, run_id="run2"))

    assert len(tracer.get_events("run1")) == 2
    assert len(tracer.get_events("run2")) == 1
    assert tracer.get_events("missing") == []


def test_tracer_respects_bound() -> None:
    tracer = InMemoryTracer(max_events_per_run=3)
    for _ in range(5):
        tracer.emit(make_event(EventType.AGENT_THINKING))
    assert len(tracer.get_events("run1")) == 3


def test_event_bus_fans_out_to_all_listeners() -> None:
    bus = EventBus()
    seen: list[EventType] = []
    bus.subscribe(lambda e: seen.append(e.event_type))
    bus.publish(make_event(EventType.RUN_STARTED))
    bus.publish(make_event(EventType.TOOL_EXECUTED))
    assert seen == [EventType.RUN_STARTED, EventType.TOOL_EXECUTED]


def test_event_bus_type_filtering() -> None:
    bus = EventBus()
    tool_events: list[TraceEvent] = []
    bus.subscribe(tool_events.append, event_type=EventType.TOOL_EXECUTED)
    bus.publish(make_event(EventType.RUN_STARTED))
    bus.publish(make_event(EventType.TOOL_EXECUTED))
    assert len(tool_events) == 1


def test_listener_failure_does_not_break_publishing() -> None:
    bus = EventBus()
    seen: list[EventType] = []

    def broken(event: TraceEvent) -> None:
        raise RuntimeError("listener bug")

    bus.subscribe(broken)
    bus.subscribe(lambda e: seen.append(e.event_type))
    bus.publish(make_event(EventType.RUN_STARTED))
    assert seen == [EventType.RUN_STARTED]
