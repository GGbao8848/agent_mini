"""End-to-end smoke test: AgentRuntime + DeepAgents + a free OpenRouter model.

Exercises the full Phase 3 path: registries -> AgentBuilder (create_deep_agent)
-> AgentExecutor -> run lifecycle + trace events, with a real tool call.
Usage: uv run --env-file .env python scripts/smoke_runtime.py
"""

from __future__ import annotations

import asyncio
import sys

from agent_core.config.settings import get_settings

get_settings()  # applies AGENT_CORE_PROXY_URL to HTTP(S)_PROXY

from agent_core.domain.agent import AgentSpec
from agent_core.domain.task import RunStatus
from agent_core.domain.tool import ToolDefinition
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime import AgentRuntime

MODEL = "openrouter:minimax/minimax-m3:free"


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
    agents.register(
        AgentSpec(
            id="weather-agent",
            name="Weather Agent",
            model=MODEL,
            system_prompt="You must call the get_weather tool before answering weather questions.",
            tools=["get_weather"],
        )
    )

    run = runtime.create_run("weather-agent", "北京今天天气怎么样？")
    result = asyncio.run(runtime.execute_run(run))

    finished = [e for e in runtime.tracer.get_events(run.id) if e.event_type.value == "run_finished"]
    output = finished[-1].output if finished else None
    print(f"\nstatus: {result.status.value}  error: {result.error}")
    print(f"output: {str(output)[:300]}")
    print("events:")
    for event in runtime.tracer.get_events(run.id):
        print(f"  {event.event_type.value:<22} tool={event.tool}")
    return 0 if result.status is RunStatus.COMPLETED else 1


if __name__ == "__main__":
    sys.exit(main())
