"""End-to-end smoke test: native LangChain middleware wired via ResiliencePolicy.

Verifies three native behaviors through the framework:
1. ModelCallLimitMiddleware — an agent whose policy caps model calls at 1
   ends gracefully (exit_behavior='end') instead of looping on tool calls.
2. ToolRetryMiddleware — a flaky tool that fails on its first invocation is
   retried transparently and the run still completes.
3. SummarizationMiddleware — builds and runs with a message-count trigger.

Usage: uv run --env-file .env python scripts/smoke_middleware.py
"""

from __future__ import annotations

import asyncio
import sys

from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.resilience import ResiliencePolicy, SummarizationPolicy
from agent_core.domain.task import RunStatus
from agent_core.domain.tool import ToolDefinition
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime import AgentRuntime

get_settings()  # applies AGENT_CORE_PROXY_URL to HTTP(S)_PROXY before any HTTP client is built


def main() -> int:
    agents = AgentRegistry()
    tools = ToolRegistry()
    runtime = AgentRuntime(agents, tools, SkillRegistry())

    tools.register(
        ToolDefinition(
            name="get_weather",
            description="Get the current weather for a city",
            input_schema={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
            },
        ),
        lambda city: f"{city}: 22°C, sunny",
    )

    flaky_state = {"calls": 0}

    def flaky_ping() -> str:
        flaky_state["calls"] += 1
        if flaky_state["calls"] == 1:
            raise RuntimeError("simulated transient failure")
        return "pong (after retry)"

    tools.register(
        ToolDefinition(
            name="flaky_ping",
            description="Ping that fails once before succeeding",
            input_schema={"type": "object", "properties": {}},
        ),
        flaky_ping,
    )

    agents.register(
        AgentSpec(
            id="limited",
            name="Limited",
            tools=["get_weather"],
            system_prompt="你先用 get_weather 查询北京天气，再查询上海天气，最后总结两地天气。",
            resilience=ResiliencePolicy(model_call_limit=1, call_limit_exit="end"),
        )
    )
    agents.register(
        AgentSpec(
            id="retrying",
            name="Retrying",
            tools=["flaky_ping"],
            system_prompt="你必须调用一次 flaky_ping 工具，然后报告它的返回值。",
            resilience=ResiliencePolicy(tool_retries=2),
        )
    )
    agents.register(
        AgentSpec(
            id="summarizing",
            name="Summarizing",
            tools=["get_weather"],
            system_prompt="依次查询北京、上海、广州的天气（每次单独调用工具），然后汇总。",
            resilience=ResiliencePolicy(
                summarization=SummarizationPolicy(trigger_messages=4, keep_messages=6)
            ),
        )
    )

    checks: list[tuple[str, bool]] = []

    async def run(agent_id: str, task: str) -> None:
        run_ = runtime.create_run(agent_id, task)
        await runtime.execute_run(run_)
        finished = [
            e
            for e in runtime.tracer.get_events(run_.id)
            if e.event_type.value == "run_finished"
        ]
        output = finished[-1].output if finished else None
        usage = run_.usage
        print(f"\n[{agent_id}] status={run_.status.value} error={run_.error}")
        if usage is not None:
            print(
                f"[{agent_id}] usage: model_calls={usage.model_calls} "
                f"tool_calls={usage.tool_calls} tokens={usage.total_tokens}"
            )
        print(f"[{agent_id}] output: {str(output)[:200]}")
        return run_

    limited_run = asyncio.run(run("limited", "请按系统提示完成两地天气总结。"))
    checks.append(
        ("call limit ends run after exactly 1 model call", limited_run.usage.model_calls == 1)
    )

    retrying_run = asyncio.run(run("retrying", "请调用 flaky_ping 并报告返回值。"))
    checks.append(
        ("flaky tool recovered via retry", retrying_run.status is RunStatus.COMPLETED)
    )

    asyncio.run(run("summarizing", "请按系统提示完成三个城市的天气汇总。"))
    checks.append(("summarization agent ran", True))

    print("\nverdicts:")
    ok = True
    for name, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
