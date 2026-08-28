"""End-to-end smoke test: Action Gate HITL with a real OpenRouter model.

A HIGH-risk tool forces REQUIRE_APPROVAL; the run pauses in
WAITING_APPROVAL, a background "human" approves, the run completes.
Usage: uv run --env-file .env python scripts/smoke_approval.py
"""

from __future__ import annotations

import asyncio
import sys

from agent_core.config.settings import get_settings

get_settings()  # applies AGENT_CORE_PROXY_URL to HTTP(S)_PROXY

from agent_core.domain.action import ApprovalStatus, RiskLevel
from agent_core.domain.agent import AgentSpec
from agent_core.domain.task import RunStatus
from agent_core.domain.tool import ToolDefinition
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime import AgentRuntime

MODEL = "openrouter:minimax/minimax-m3:free"


async def main() -> int:
    agents = AgentRegistry()
    tools = ToolRegistry()
    runtime = AgentRuntime(agents, tools, SkillRegistry())

    tools.register(
        ToolDefinition(
            name="deploy_service",
            description="Deploy a service to production",
            risk_level=RiskLevel.HIGH,
            input_schema={
                "type": "object",
                "properties": {"service": {"type": "string"}},
                "required": ["service"],
            },
        ),
        lambda service: f"{service} deployed to production, rollout 100% healthy",
    )
    agents.register(
        AgentSpec(
            id="ops-agent",
            name="Ops Agent",
            model=MODEL,
            system_prompt="You must call the deploy_service tool when asked to deploy. Be brief.",
            tools=["deploy_service"],
        )
    )

    run = runtime.create_run("ops-agent", "把 web-api 服务部署到生产环境")
    task = asyncio.create_task(runtime.execute_run(run))

    # Simulate the human approving after the gate pauses the run.
    while not runtime.approvals.list_pending():
        if task.done():
            break
        await asyncio.sleep(0.2)
    pending = runtime.approvals.list_pending()
    if pending:
        request = pending[0]
        print(f"approval requested: tool={request.tool_name} args={request.arguments} "
              f"risk={request.risk_level.value}")
        runtime.approvals.resolve(request.id, ApprovalStatus.APPROVED, resolved_by="songkui")

    result = await task
    finished = [
        e for e in runtime.tracer.get_events(run.id) if e.event_type.value == "run_finished"
    ]
    print(f"\nstatus: {result.status.value}  error: {result.error}")
    print(f"output: {str(finished[-1].output if finished else None)[:200]}")
    print("events:")
    for event in runtime.tracer.get_events(run.id):
        print(f"  {event.event_type.value:<22} tool={event.tool}")
    return 0 if result.status is RunStatus.COMPLETED else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
