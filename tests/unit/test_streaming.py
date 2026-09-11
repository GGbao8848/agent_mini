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

    async def test_replay_is_lossless_past_queue_capacity(self) -> None:
        """A long run's history must survive a reconnect (page refresh).

        Replayed events used to go through the bounded live queue, so a run
        with more events than its capacity silently lost the newest ones on
        refresh while older steps still showed. History is never dropped.
        """
        bus = EventBus()
        broker = EventStreamBroker(bus)
        stream = broker.subscribe(maxsize=10)
        events = [make_event("run-1") for _ in range(250)]

        stream.replay(events)

        got = await collect(stream, 250)
        assert got == events
        assert stream.dropped == 0


class TestThinkingStreamHandler:
    def test_tokens_buffer_into_deltas(self) -> None:
        from agent_core.observability.emitter import EventFanout
        from agent_core.observability.events import EventBus
        from agent_core.observability.trace import InMemoryTracer
        from agent_core.runtime.thinking import ThinkingStreamHandler

        tracer = InMemoryTracer()
        fanout = EventFanout(tracer, EventBus())
        run = Run(task_id="t", agent_id="a")
        handler = ThinkingStreamHandler(fanout, run)

        payload = "abcdefghij" * 8  # 80 chars → crosses the 32-char flush bound
        for ch in payload:
            handler.on_llm_new_token(ch)
        handler.on_llm_end()

        thinking = [
            e for e in tracer.get_events(run.id) if e.event_type is EventType.AGENT_THINKING
        ]
        assert thinking, "expected at least one agent_thinking delta"
        assert "".join(e.output or "" for e in thinking) == payload
        # Chunked (not one event per token, not one giant blob).
        assert 1 < len(thinking) < len(payload)
        assert all(len(e.output or "") <= 64 for e in thinking)

    def test_empty_tokens_ignored(self) -> None:
        from agent_core.observability.emitter import EventFanout
        from agent_core.observability.events import EventBus
        from agent_core.observability.trace import InMemoryTracer
        from agent_core.runtime.thinking import ThinkingStreamHandler

        tracer = InMemoryTracer()
        fanout = EventFanout(tracer, EventBus())
        run = Run(task_id="t", agent_id="a")
        handler = ThinkingStreamHandler(fanout, run)
        handler.on_llm_new_token("")
        handler.on_llm_end()
        assert tracer.get_events(run.id) == []


class TestReasoningCapture:
    """Reasoning deltas (vLLM/DeepSeek) must reach agent_thinking, not be lost.

    langchain-openai's chunk parser reads only content/tool_calls, so the
    chain-of-thought that vLLM streams in ``delta.reasoning`` (or DeepSeek's
    ``delta.reasoning_content``) used to vanish: the console showed a final
    answer with no 思考. The subclass preserves it on the chunk's
    ``generation_info`` and the handler prefers it over the empty content token.
    """

    def test_reasoning_delta_reads_both_field_names(self) -> None:
        from agent_core.runtime.reasoning import reasoning_delta

        assert reasoning_delta({"choices": [{"delta": {"reasoning": "abc"}}]}) == "abc"
        assert (
            reasoning_delta({"choices": [{"delta": {"reasoning_content": "xyz"}}]}) == "xyz"
        )
        # Content-only chunks (the normal answer) carry no reasoning.
        assert reasoning_delta({"choices": [{"delta": {"content": "hi"}}]}) == ""
        assert reasoning_delta({}) == ""
        assert reasoning_delta({"choices": []}) == ""

    def test_chunk_conversion_preserves_reasoning_out_of_content(self) -> None:
        from langchain_core.messages import AIMessageChunk

        from agent_core.runtime.reasoning import (
            ReasoningChatOpenAI,
            generation_chunk_reasoning,
        )

        model = ReasoningChatOpenAI(
            model="qwen-test", api_key="k", base_url="http://localhost:1/v1"
        )
        chunk = model._convert_chunk_to_generation_chunk(  # noqa: SLF001 - unit-testing the override
            {"choices": [{"delta": {"reasoning": "step 1"}, "index": 0}]},
            AIMessageChunk,
            {},
        )

        assert chunk is not None
        # The reasoning token must not be conflated with the answer content.
        assert chunk.text == ""
        assert generation_chunk_reasoning(chunk) == "step 1"

    def test_handler_emits_reasoning_instead_of_empty_token(self) -> None:
        from langchain_core.messages import AIMessageChunk

        from agent_core.observability.emitter import EventFanout
        from agent_core.observability.events import EventBus
        from agent_core.observability.trace import InMemoryTracer
        from agent_core.runtime.reasoning import ReasoningChatOpenAI
        from agent_core.runtime.thinking import ThinkingStreamHandler

        tracer = InMemoryTracer()
        fanout = EventFanout(tracer, EventBus())
        run = Run(task_id="t", agent_id="a")
        handler = ThinkingStreamHandler(fanout, run)

        model = ReasoningChatOpenAI(
            model="qwen-test", api_key="k", base_url="http://localhost:1/v1"
        )
        for token in ("step ", "one ", "and step two"):
            chunk = model._convert_chunk_to_generation_chunk(  # noqa: SLF001
                {"choices": [{"delta": {"reasoning": token}, "index": 0}]},
                AIMessageChunk,
                {},
            )
            assert chunk is not None
            handler.on_llm_new_token(chunk.text, chunk=chunk)
        handler.on_llm_end()

        thinking = "".join(
            e.output or ""
            for e in tracer.get_events(run.id)
            if e.event_type is EventType.AGENT_THINKING
        )
        assert thinking == "step one and step two"
