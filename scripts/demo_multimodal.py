"""End-to-end multimodal demo: the agent generates an image, then LOOKS at it.

Runs the full stack (real model, real Action Gate, real txt2img service):

  1. bootstrap a default service (settings from .env: local model + image API)
  2. register an agent with the built-in generate_image / view_image tools
  3. ask it to generate a picture and visually verify its own output

Usage: uv run --env-file .env python scripts/demo_multimodal.py
"""

from __future__ import annotations

import asyncio

from agent_core.application.bootstrap import default_service
from agent_core.domain.agent import AgentSpec
from agent_core.observability.trace import InMemoryTracer

TASK = (
    "请用 generate_image 工具生成一张图：a red cube on a white table, "
    "minimalist photo style。生成后必须调用 view_image 查看图片，"
    "然后用一句话描述你实际看到的画面，并判断颜色是否符合要求。"
)


async def main() -> None:
    service = default_service()
    service.runtime.agents.register(
        AgentSpec(
            id="avatar",
            name="Avatar",
            tools=["generate_image", "view_image"],
            system_prompt="你是一个能画图也能看图的助手。完成视觉任务时必须用工具核实，不要凭想象回答。",
        )
    )
    tracer = service.runtime.tracer
    if not isinstance(tracer, InMemoryTracer):
        raise SystemExit("demo expects the in-memory tracer")

    run = await service.submit_run("avatar", TASK, wait=True)
    print(f"run {run.id}: {run.status.value}")
    if run.usage:
        print(
            f"usage: {run.usage.total_tokens} tokens, "
            f"{run.usage.model_calls} model calls, {run.usage.tool_calls} tool calls"
        )
    output = service.final_output(run.id)
    print(f"\n--- final output ---\n{output}")
    print("\n--- tool events ---")
    for event in tracer.get_events(run.id):
        if event.event_type.value.startswith(("tool_", "action_")):
            print(f"  {event.event_type.value:<16} {event.tool or ''}")


if __name__ == "__main__":
    asyncio.run(main())
