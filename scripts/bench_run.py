"""Benchmark driver: run all cases end-to-end on a real model and write reports.

Builds a small registry — one generalist ("solo"), three workers, and one team
per decomposable case — then executes every case in every allowed mode and
writes bench_results/report.md + bench_results/results.json.

Usage: uv run --env-file .env python scripts/bench_run.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from agent_core.bench import (
    ALL_CASES,
    BenchRunner,
    CaseWiring,
    render_json,
    render_markdown,
)
from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.team import TeamSpec
from agent_core.domain.tool import ToolDefinition
from agent_core.orchestration import compose_team
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime import AgentRuntime

get_settings()  # applies AGENT_CORE_PROXY_URL to HTTP(S)_PROXY before any HTTP client is built

RESULTS_DIR = pathlib.Path("bench_results")


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
            id="solo",
            name="Solo",
            system_prompt="你是一名高效的通用助手，直接完成任务，输出简洁。",
        )
    )
    agents.register(
        AgentSpec(
            id="tool-agent",
            name="Tool Agent",
            tools=["get_weather"],
            system_prompt="回答天气问题前必须先调用 get_weather 工具，然后基于结果作答。",
        )
    )
    for i in (1, 2, 3):
        agents.register(
            AgentSpec(
                id=f"worker-{i}",
                name=f"Worker {i}",
                description="执行一个独立的子任务，输出精炼的结果",
                system_prompt="你是团队中的一名执行者，只完成分配给你的子任务，输出简洁准确。",
            )
        )
    compose_team(
        agents,
        TeamSpec(
            id="summary-team",
            name="Summary Team",
            worker_agent_ids=["worker-1", "worker-2", "worker-3"],
        ),
    )
    compose_team(
        agents,
        TeamSpec(
            id="research-team",
            name="Research Team",
            worker_agent_ids=["worker-1", "worker-2", "worker-3"],
        ),
    )

    wirings = {
        "qa_tool": CaseWiring(single_agent_id="tool-agent"),
        "summarize_multi": CaseWiring(
            single_agent_id="solo",
            coordinator_id="summary-team",
            fanout_worker_ids=("worker-1", "worker-2", "worker-3"),
            fanout_merge_agent_id="solo",
        ),
        "research_brief": CaseWiring(
            single_agent_id="solo",
            coordinator_id="research-team",
            fanout_worker_ids=("worker-1", "worker-2", "worker-3"),
            fanout_merge_agent_id="solo",
        ),
        "extract_structure": CaseWiring(single_agent_id="solo"),
    }

    runner = BenchRunner(runtime)
    results = asyncio.run(runner.run_suite(ALL_CASES, wirings))

    report = render_markdown(results)
    print(report)
    print("sample outputs:")
    for result in results:
        preview = result.output.replace("\n", " ")[:150]
        print(f"  [{result.case_id}/{result.mode}] {preview}")

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "report.md").write_text(report, encoding="utf-8")
    (RESULTS_DIR / "results.json").write_text(render_json(results), encoding="utf-8")
    print(f"\nreports written to {RESULTS_DIR}/")

    return 0 if all(r.status == "completed" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
