"""Bench tests: harness metrics collection and report rendering (no network)."""

import asyncio
import json
from typing import Any

from langchain_core.messages import AIMessage

from agent_core.bench import (
    ALL_CASES,
    BenchResult,
    BenchRunner,
    CaseWiring,
    render_json,
    render_markdown,
)
from agent_core.domain.agent import AgentSpec
from agent_core.domain.team import TeamSpec
from agent_core.errors.exceptions import ConfigurationError
from agent_core.orchestration import compose_team
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime
from agent_core.runtime.usage import UsageCollector


class ScriptedGraph:
    """Graph that fires the UsageCollector contract then replies after a delay."""

    def __init__(self, reply: str = "done", delay: float = 0.0) -> None:
        self.reply = reply
        self.delay = delay

    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        for callback in (config or {}).get("callbacks") or []:
            if isinstance(callback, UsageCollector):
                callback.on_chat_model_start()
                callback.on_tool_end()
        await asyncio.sleep(self.delay)
        return {"messages": [AIMessage(content=self.reply)]}


class StubBuilder:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def build(self, spec: Any) -> Any:
        return self._graph


def make_runtime(graph: Any) -> AgentRuntime:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="solo", name="Solo"))
    agents.register(AgentSpec(id="worker-1", name="W1"))
    agents.register(AgentSpec(id="worker-2", name="W2"))
    agents.register(AgentSpec(id="worker-3", name="W3"))
    return AgentRuntime(agents, ToolRegistry(), SkillRegistry(), builder=StubBuilder(graph))


def sample_wiring() -> CaseWiring:
    return CaseWiring(
        single_agent_id="solo",
        coordinator_id="summary-team",
        fanout_worker_ids=("worker-1", "worker-2", "worker-3"),
    )


class TestRunModes:
    async def test_single_mode_records_usage_and_output(self) -> None:
        runtime = make_runtime(ScriptedGraph(reply="answer", delay=0.01))
        runner = BenchRunner(runtime)
        case = ALL_CASES[0]  # qa_tool: single only

        result = await runner.run_case(case, "single", sample_wiring())

        assert result.case_id == "qa_tool"
        assert result.mode == "single"
        assert result.status == "completed"
        assert result.output == "answer"
        assert result.wall_ms > 0
        assert result.total_tokens == 0  # scripted usage counts calls, not tokens
        assert result.model_calls == 1
        assert result.tool_calls == 1

    async def test_team_mode_runs_coordinator(self) -> None:
        runtime = make_runtime(ScriptedGraph(reply="coordinated"))
        agents = runtime.agents
        compose_team(
            agents, TeamSpec(id="summary-team", name="T", worker_agent_ids=["worker-1", "worker-2"])
        )
        runner = BenchRunner(runtime)
        case = ALL_CASES[1]

        result = await runner.run_case(case, "team", sample_wiring())

        assert result.status == "completed"
        assert result.output == "coordinated"
        assert result.model_calls == 1

    async def test_fanout_aggregates_children_and_merge(self) -> None:
        runtime = make_runtime(ScriptedGraph(reply="part", delay=0.1))
        runner = BenchRunner(runtime)
        case = ALL_CASES[1]  # summarize_multi: 3 subtasks

        result = await runner.run_case(case, "fanout", sample_wiring())

        assert result.status == "completed"
        assert result.mode == "fanout"
        # 3 subtask runs + 1 merge run, each with 1 model call + 1 tool call.
        assert result.model_calls == 4
        assert result.tool_calls == 4
        assert result.wall_ms >= 0.1
        assert result.output == "part"

    async def test_mode_wiring_is_validated(self) -> None:
        runtime = make_runtime(ScriptedGraph())
        runner = BenchRunner(runtime)
        case = ALL_CASES[1]
        bare = CaseWiring(single_agent_id="solo")

        try:
            await runner.run_case(case, "team", bare)
        except ConfigurationError:
            pass
        else:
            raise AssertionError("team without coordinator must raise")

        try:
            await runner.run_case(case, "fanout", bare)
        except ConfigurationError:
            pass
        else:
            raise AssertionError("fanout without workers must raise")

        try:
            await runner.run_case(case, "nope", sample_wiring())
        except ConfigurationError:
            pass
        else:
            raise AssertionError("unknown mode must raise")


class TestRunSuite:
    async def test_suite_runs_only_allowed_modes(self) -> None:
        runtime = make_runtime(ScriptedGraph())
        agents = runtime.agents
        compose_team(
            agents, TeamSpec(id="summary-team", name="T", worker_agent_ids=["worker-1", "worker-2"])
        )
        runner = BenchRunner(runtime)

        results = await runner.run_suite(
            ALL_CASES,
            {
                "qa_tool": sample_wiring(),
                "summarize_multi": sample_wiring(),
                "research_brief": sample_wiring(),
                "extract_structure": sample_wiring(),
            },
        )

        assert [(r.case_id, r.mode) for r in results] == [
            ("qa_tool", "single"),
            ("summarize_multi", "single"),
            ("summarize_multi", "team"),
            ("summarize_multi", "fanout"),
            ("research_brief", "single"),
            ("research_brief", "team"),
            ("research_brief", "fanout"),
            ("extract_structure", "single"),
        ]

    async def test_missing_wiring_raises(self) -> None:
        runtime = make_runtime(ScriptedGraph())
        runner = BenchRunner(runtime)
        try:
            await runner.run_suite(ALL_CASES[:1], {})
        except ConfigurationError:
            pass
        else:
            raise AssertionError("missing wiring must raise")

    async def test_mode_filter_narrows_results(self) -> None:
        runtime = make_runtime(ScriptedGraph())
        runner = BenchRunner(runtime)
        wiring = sample_wiring()
        wirings = {case.id: wiring for case in ALL_CASES}

        results = await runner.run_suite(ALL_CASES, wirings, modes=("single",))

        assert [r.mode for r in results] == ["single"] * len(ALL_CASES)


class TestReport:
    def _results(self) -> list[BenchResult]:
        return [
            BenchResult(
                case_id="summarize_multi",
                mode="single",
                status="completed",
                wall_ms=1200.0,
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                model_calls=3,
                tool_calls=0,
            ),
            BenchResult(
                case_id="summarize_multi",
                mode="team",
                status="completed",
                wall_ms=700.0,
                input_tokens=180,
                output_tokens=60,
                total_tokens=240,
                model_calls=4,
                tool_calls=2,
            ),
            BenchResult(
                case_id="summarize_multi",
                mode="fanout",
                status="failed",
                wall_ms=600.0,
                input_tokens=90,
                output_tokens=10,
                total_tokens=100,
                model_calls=2,
                tool_calls=0,
                error="boom",
            ),
        ]

    def test_markdown_table_and_winners_ignore_failed(self) -> None:
        report = render_markdown(self._results())

        assert "| summarize_multi | team | completed | 700 | 180/60 | 4 | 2 |" in report
        assert "fastest = `team` (700 ms)" in report
        assert "cheapest = `single` (150 tokens)" in report  # failed fanout excluded

    def test_single_mode_report_has_no_winner_section(self) -> None:
        report = render_markdown([self._results()[0]])
        assert "Strategy comparison" not in report

    def test_json_round_trip(self) -> None:
        payload = json.loads(render_json(self._results()))
        assert len(payload) == 3
        assert payload[1]["mode"] == "team"
        assert payload[1]["total_tokens"] == 240
