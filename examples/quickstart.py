"""Quickstart: the smallest programmatic tour of Agent Core.

Registers one agent with one local tool, runs it with the real model
(OPENAI_API_KEY / OPENROUTER_API_KEY per AGENT_CORE_MODEL), and prints the
run lifecycle and final output.

Usage: uv run --env-file .env python examples/quickstart.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from agent_core.application.bootstrap import default_service
from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.tool import ToolDefinition


def current_time() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def main() -> int:
    # 1. Build the fully wired service (registries + runtime + gate + broker).
    service = default_service()

    # 2. Register a capability (a local Python tool; MCP tools appear the same way).
    service.runtime.tools.register(
        ToolDefinition(
            name="current_time",
            description="Returns the current local time as an ISO timestamp.",
            input_schema={"type": "object", "properties": {}},
        ),
        handler=current_time,
    )

    # 3. Register an agent that may use it.
    service.runtime.agents.register(
        AgentSpec(
            id="assistant",
            name="Assistant",
            model=get_settings().model,
            system_prompt="Answer briefly. Use the current_time tool for time questions.",
            tools=["current_time"],
        )
    )

    # 4. Run it; every lifecycle step also landed on the tracer as events.
    run = await service.submit_run("assistant", "What time is it right now?", wait=True)
    print(f"run {run.id}: {run.status.value}")
    print(f"output: {service.final_output(run.id)}")
    if run.usage:
        print(
            f"usage: {run.usage.total_tokens} tokens "
            f"(in={run.usage.input_tokens}, out={run.usage.output_tokens}), "
            f"{run.usage.model_calls} model calls, {run.usage.tool_calls} tool calls, "
            f"{run.usage.duration_ms:.0f} ms"
        )
    print("events:")
    for event in service.trace_events(run.id):
        print(f"  {event.event_type.value:<18} tool={event.tool or '-'}")
    return 0 if run.status.value == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
