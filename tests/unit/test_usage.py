"""Usage accounting tests: collector math, executor wiring, API exposure."""

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agent_core.domain.metrics import RunUsage
from agent_core.runtime.usage import UsageCollector


def _result(input_tokens: int, output_tokens: int, *, with_metadata: bool = True) -> LLMResult:
    message = AIMessage("ok")
    if with_metadata:
        message.usage_metadata = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    return LLMResult(generations=[[ChatGeneration(message=message)]], llm_output={})


class TestUsageCollector:
    def test_accumulates_tokens_and_calls(self) -> None:
        collector = UsageCollector()
        collector.on_chat_model_start()
        collector.on_llm_end(_result(100, 20))
        collector.on_chat_model_start()
        collector.on_llm_end(_result(50, 10))
        collector.on_tool_end()

        usage = collector.usage
        assert usage.input_tokens == 150
        assert usage.output_tokens == 30
        assert usage.total_tokens == 180
        assert usage.model_calls == 2
        assert usage.tool_calls == 1

    def test_falls_back_to_llm_output_token_usage(self) -> None:
        collector = UsageCollector()
        result = LLMResult(
            generations=[[ChatGeneration(message=AIMessage("ok"))]],
            llm_output={
                "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            },
        )
        collector.on_llm_end(result)

        assert collector.usage.input_tokens == 10
        assert collector.usage.output_tokens == 5
        assert collector.usage.total_tokens == 15

    def test_usage_property_is_a_snapshot(self) -> None:
        collector = UsageCollector()
        snapshot = collector.usage
        collector.on_chat_model_start()
        assert snapshot.model_calls == 0
        assert collector.usage.model_calls == 1

    def test_add_merges_instances(self) -> None:
        total = RunUsage(input_tokens=1, output_tokens=2, total_tokens=3, model_calls=1)
        other = RunUsage(
            input_tokens=10, output_tokens=20, total_tokens=30, model_calls=2, tool_calls=4
        )
        total.add(other)
        assert total.model_dump() == {
            "input_tokens": 11,
            "output_tokens": 22,
            "total_tokens": 33,
            "model_calls": 3,
            "tool_calls": 4,
            "duration_ms": None,
        }


class _CallbackAwareGraph:
    """Simulates the LangChain contract: callbacks fire during execution."""

    def __init__(self, reply: str = "done") -> None:
        self.reply = reply
        self.seen_callbacks: list[Any] | None = None

    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        callbacks = (config or {}).get("callbacks") or []
        self.seen_callbacks = callbacks
        for callback in callbacks:
            if isinstance(callback, UsageCollector):
                callback.on_chat_model_start()
                callback.on_llm_end(_result(120, 30))
                callback.on_tool_end()
        return {"messages": [AIMessage(content=self.reply)]}


class TestExecutorWiring:
    async def test_run_usage_populated_and_emitted(self) -> None:
        from agent_core.domain.agent import AgentSpec
        from agent_core.domain.trace import EventType
        from agent_core.observability.trace import InMemoryTracer
        from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
        from agent_core.runtime.runtime import AgentRuntime

        class StubBuilder:
            def build(self, spec: Any) -> Any:
                return graph

        graph = _CallbackAwareGraph()
        agents = AgentRegistry()
        agents.register(AgentSpec(id="helper", name="Helper"))
        tracer = InMemoryTracer()
        runtime = AgentRuntime(
            agents, ToolRegistry(), SkillRegistry(), tracer=tracer, builder=StubBuilder()
        )

        run = runtime.create_run("helper", "hello")
        await runtime.execute_run(run)

        assert run.usage is not None
        assert run.usage.input_tokens == 120
        assert run.usage.output_tokens == 30
        assert run.usage.model_calls == 1
        assert run.usage.tool_calls == 1
        assert run.usage.duration_ms is not None

        finished = [
            event
            for event in tracer.get_events(run.id)
            if event.event_type is EventType.AGENT_FINISHED
        ]
        assert finished[0].metadata["usage"]["total_tokens"] == 150
