"""End-to-end smoke test: model-driven team orchestration with native parallel subagents.

Registers three worker agents, composes a coordinator team via compose_team, and runs
a task that naturally splits into independent subquestions. DeepAgents runs the
coordinator's multiple ``task`` tool calls concurrently, so the SUBAGENT_* trace
events should show overlapping start times.

Usage: uv run --env-file .env python scripts/smoke_team.py
"""

from __future__ import annotations

import asyncio
import sys
import time

from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.task import RunStatus
from agent_core.domain.team import TeamSpec
from agent_core.orchestration import compose_team
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime import AgentRuntime

get_settings()  # applies AGENT_CORE_PROXY_URL to HTTP(S)_PROXY before any HTTP client is built

MODEL = "openrouter:minimax/minimax-m3:free"

TASK = (
    "分别用一句话介绍以下三个主题：1) 人工智能的起源；2) 机器学习的定义；"
    "3) 深度学习的特点。然后把三句话融合成一段连贯的中文总结。"
)


def main() -> int:
    agents = AgentRegistry()
    agents.register(
        AgentSpec(
            id="researcher",
            name="Researcher",
            description="给出简明的历史背景与事实（起源、时间线）",
        )
    )
    agents.register(
        AgentSpec(
            id="definer",
            name="Definer",
            description="给出准确的术语定义与解释",
        )
    )
    agents.register(
        AgentSpec(
            id="characterist",
            name="Characterist",
            description="提炼事物的关键特点与对比",
        )
    )

    team = compose_team(
        agents,
        TeamSpec(id="ai-team", name="AI Research Team", worker_agent_ids=[
            "researcher", "definer", "characterist"
        ]),
    )

    runtime = AgentRuntime(agents, ToolRegistry(), SkillRegistry())
    run = runtime.create_run(team.id, TASK)

    started = time.monotonic()
    result = asyncio.run(runtime.execute_run(run))
    elapsed = time.monotonic() - started

    events = runtime.tracer.get_events(run.id)
    sub_starts = [e for e in events if e.event_type.value == "subagent_started"]
    sub_finished = [e for e in events if e.event_type.value == "subagent_finished"]

    finished = [e for e in events if e.event_type.value == "run_finished"]
    output = finished[-1].output if finished else None

    print(f"\nstatus: {result.status.value}  error: {result.error}")
    print(f"wall time: {elapsed:.1f}s")
    usage = result.usage
    if usage is not None:
        print(
            f"usage: {usage.total_tokens} tokens (in={usage.input_tokens}, "
            f"out={usage.output_tokens}), {usage.model_calls} model calls, "
            f"{usage.tool_calls} tool calls"
        )
    print(f"subagents delegated: {len(sub_starts)}")
    for event in sub_starts:
        print(f"  STARTED {event.metadata.get('subagent')}  at {event.timestamp.time()}")
    for event in sub_finished:
        print(
            f"  FINISHED {event.metadata.get('subagent')}  "
            f"output={str(event.output)[:80]!r}"
        )

    # Parallelism signal: with concurrent task calls the second subagent starts
    # before the first finishes. Timestamps are second-resolution; overlap check
    # is informational only.
    if len(sub_starts) >= 2:
        start_times = [e.timestamp for e in sub_starts]
        end_times = sorted(e.timestamp for e in sub_finished)
        overlapped = max(start_times) <= min(end_times)
        print(f"parallel-ish (last start <= first finish): {overlapped}")

    print(f"\noutput: {str(output)[:500]}")
    return 0 if result.status is RunStatus.COMPLETED else 1


if __name__ == "__main__":
    sys.exit(main())
