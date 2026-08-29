"""Eval tests: verifier logic and runner wiring (no network)."""

import json
import pathlib
from typing import Any

from langchain_core.messages import AIMessage

from agent_core.domain.agent import AgentSpec
from agent_core.domain.resilience import ResiliencePolicy
from agent_core.eval import (
    ALL_TASKS,
    Check,
    EvalResult,
    EvalRunner,
    RealTask,
    compare,
    load_baseline,
    parse_judge_output,
    render_comparison,
    save_baseline,
    snapshot,
)
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.middleware import build_middleware
from agent_core.runtime.runtime import AgentRuntime
from agent_core.runtime.usage import UsageCollector


class ScriptedGraph:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        for callback in (config or {}).get("callbacks") or []:
            if isinstance(callback, UsageCollector):
                callback.on_chat_model_start()
                callback.on_tool_end()
        return {"messages": [AIMessage(content=self.reply)]}


class StubBuilder:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def build(self, spec: Any) -> Any:
        return self._graph


def runtime_with_reply(reply: str) -> AgentRuntime:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="solo", name="Solo"))
    agents.register(AgentSpec(id="worker-1", name="W1"))
    return AgentRuntime(
        agents, ToolRegistry(), SkillRegistry(), builder=StubBuilder(ScriptedGraph(reply))
    )


GOOD_JSON = json.dumps(
    {
        "orders": [
            {
                "id": "A-1001",
                "customer": "张伟",
                "amount": 299,
                "date": "2026-03-05",
                "status": "已发货",
            },
            {
                "id": "A-1002",
                "customer": "李娜",
                "amount": 1299,
                "date": "2026-02-28",
                "status": "已取消",
            },
            {
                "id": "A-1003",
                "customer": "王强",
                "amount": 89,
                "date": "2026-03-01",
                "status": "已签收",
            },
            {
                "id": "A-1004",
                "customer": "赵敏",
                "amount": 549,
                "date": "2026-03-02",
                "status": "待修改",
            },
        ],
        "total_amount": 2236,
    },
    ensure_ascii=False,
)


class TestOrderVerifier:
    task = next(t for t in ALL_TASKS if t.id == "orders_to_json")

    def test_good_answer_passes_all_checks(self) -> None:
        checks = self.task.verifier(GOOD_JSON, {})
        assert all(c.passed for c in checks)
        assert len(checks) == 5  # parses + 4 orders + fields + total + ISO dates

    def test_fenced_json_also_passes(self) -> None:
        checks = self.task.verifier(f"好的，结果如下：\n```json\n{GOOD_JSON}\n```", {})
        assert all(c.passed for c in checks)

    def test_wrong_count_fails(self) -> None:
        truncated = GOOD_JSON.replace('"A-1004"', '"X"')  # still 4 orders; drop one instead
        data = json.loads(GOOD_JSON)
        data["orders"] = data["orders"][:3]
        truncated = json.dumps(data, ensure_ascii=False)
        checks = self.task.verifier(truncated, {})
        assert not next(c for c in checks if c.name == "exactly 4 orders").passed

    def test_wrong_total_fails(self) -> None:
        data = json.loads(GOOD_JSON)
        data["total_amount"] = 999
        checks = self.task.verifier(json.dumps(data, ensure_ascii=False), {})
        assert not next(c for c in checks if c.name == "total_amount == 2236").passed

    def test_non_json_fails(self) -> None:
        checks = self.task.verifier("抱歉，我无法解析这份记录。", {})
        assert not checks[0].passed


BUGGY = (
    "```python\ndef chunk_list(items, size):\n"
    "    return [items[i:i + size + 1] for i in range(0, len(items), size + 1)]\n```"
)
FIXED = (
    "```python\ndef chunk_list(items, size):\n"
    "    return [items[i:i + size] for i in range(0, len(items), size)]\n```"
)


class TestBugfixVerifier:
    task = next(t for t in ALL_TASKS if t.id == "bugfix_code")

    def test_fixed_code_passes_all_cases(self) -> None:
        checks = self.task.verifier(f"原因是 step 写成了 size+1：\n{FIXED}", {})
        assert all(c.passed for c in checks)
        assert len(checks) == 5  # executes + 4 cases

    def test_buggy_code_still_executes_but_cases_fail(self) -> None:
        checks = self.task.verifier(BUGGY, {})
        assert next(c for c in checks if c.name == "fixed code executes").passed
        failed = [c for c in checks if not c.passed]
        assert failed  # wrong chunks caught

    def test_no_code_block_fails(self) -> None:
        checks = self.task.verifier("直接把 range 的步长改一下就行。", {})
        assert not checks[0].passed


class TestFxVerifier:
    task = next(t for t in ALL_TASKS if t.id == "fx_briefing")

    def test_plausible_briefing_passes(self) -> None:
        output = "USD/CNY 7.12，EUR/CNY 8.02，JPY/CNY 0.048，美元走强。"
        assert all(c.passed for c in self.task.verifier(output, {}))

    def test_missing_rate_fails(self) -> None:
        output = "USD/CNY 7.12，EUR/CNY 8.02。"
        checks = self.task.verifier(output, {})
        assert not next(c for c in checks if "JPY" in c.name).passed

    def test_implausible_rate_fails(self) -> None:
        checks = self.task.verifier("USD/CNY 71.2，EUR/CNY 8.02，JPY/CNY 0.048", {})
        assert not next(c for c in checks if "USD" in c.name).passed

    def test_per_hundred_quote_is_normalized(self) -> None:
        output = "JPY 汇率 0.04209；趋势：100 JPY ≈ ¥4.21。"
        checks = self.task.verifier(output, {})
        assert next(c for c in checks if "JPY" in c.name).passed


class TestHolidayVerifier:
    task = next(t for t in ALL_TASKS if t.id == "holiday_planner")

    def test_good_answer(self) -> None:
        assert all(
            c.passed
            for c in self.task.verifier("10 月国庆假期共 3 天法定假日，拼假可连休 8 天。", {})
        )

    def test_missing_count_fails(self) -> None:
        assert any(not c.passed for c in self.task.verifier("2026 年有国庆节和春节。", {}))


class TestRunner:
    async def test_run_task_grades_checks_and_metrics(self) -> None:
        task = next(t for t in ALL_TASKS if t.id == "orders_to_json")
        runner = EvalRunner(runtime_with_reply(GOOD_JSON))

        result = await runner.run_task(task, "solo", {})

        assert result.passed is True
        assert result.status == "completed"
        assert result.model_calls == 1
        assert result.total_tokens == 0  # scripted usage counts calls only

    async def test_run_task_failed_run_marks_failed(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="solo", name="Solo"))

        class BoomGraph:
            async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
                raise RuntimeError("boom")

        runtime = AgentRuntime(
            agents, ToolRegistry(), SkillRegistry(), builder=StubBuilder(BoomGraph())
        )
        runner = EvalRunner(runtime)
        task = next(t for t in ALL_TASKS if t.id == "orders_to_json")

        result = await runner.run_task(task, "solo", {})

        assert result.passed is False
        assert len(result.checks) == 1 and result.checks[0].passed is False
        assert "boom" in result.checks[0].detail
        assert "boom" in (result.error or "")

    async def test_run_task_fanout_aggregates_children(self) -> None:
        agents = AgentRegistry()
        agents.register(AgentSpec(id="solo", name="Solo"))
        agents.register(AgentSpec(id="worker-1", name="W1"))
        agents.register(AgentSpec(id="worker-2", name="W2"))
        runtime = AgentRuntime(
            agents,
            ToolRegistry(),
            SkillRegistry(),
            builder=StubBuilder(ScriptedGraph("USD/CNY 7.12, EUR/CNY 8.02, JPY/CNY 0.048")),
        )
        runner = EvalRunner(runtime)
        task = next(t for t in ALL_TASKS if t.id == "fx_briefing")

        result = await runner.run_task_fanout(task, ["worker-1", "worker-2"], "solo", {})

        assert "fanout" in result.aspects
        assert result.model_calls == 4  # 3 children + merge
        assert result.status == "completed"
        assert result.passed is True  # reply contains all three plausible rates

    async def test_fanout_without_subtasks_raises(self) -> None:
        task = RealTask(id="x", name="X", aspects=(), prompt="p", verifier=lambda o, c: [])
        runner = EvalRunner(runtime_with_reply("ok"))
        try:
            await runner.run_task_fanout(task, ["worker-1"], "solo", {})
        except ValueError:
            pass
        else:
            raise AssertionError("fanout without subtasks must raise")


def test_resilience_policy_still_wires_middleware() -> None:
    spec = AgentSpec(id="a", name="A", resilience=ResiliencePolicy(model_call_limit=2))
    assert len(build_middleware(spec, lambda m: None)) == 1


JUDGE_JSON = json.dumps(
    {
        "dimensions": {
            "accuracy": 9,
            "completeness": 8,
            "conciseness": 7,
            "instruction_following": 9,
        },
        "overall": 8.3,
        "comment": "内容准确，稍显冗长",
    },
    ensure_ascii=False,
)


class TestJudgeParsing:
    def test_parses_plain_and_fenced_json(self) -> None:
        verdict = parse_judge_output(JUDGE_JSON)

        assert verdict.parsed
        assert verdict.overall == 8.3
        assert verdict.dimensions["accuracy"] == 9
        assert parse_judge_output(f"评审结果：\n```json\n{JUDGE_JSON}\n```").parsed

    def test_garbage_is_unparsable(self) -> None:
        verdict = parse_judge_output("这个输出写得很好。")

        assert not verdict.parsed
        assert verdict.overall == 0.0

    def test_scores_clamped_and_overall_inferred(self) -> None:
        verdict = parse_judge_output('{"dimensions": {"accuracy": 15, "conciseness": 4}}')

        assert verdict.parsed
        assert verdict.dimensions["accuracy"] == 10.0
        assert verdict.overall == 7.0  # mean of the given dimensions

    def test_fallback_parses_broken_json_with_inner_quotes(self) -> None:
        broken = '{"dimensions": {"accuracy": 8}, "overall": 8, "comment": "仅用"偏弱"过于笼统"}'

        verdict = parse_judge_output(broken)

        assert verdict.parsed
        assert verdict.overall == 8.0
        assert verdict.dimensions["accuracy"] == 8.0
        assert "偏弱" in verdict.comment


class TestJudgeRunner:
    async def test_run_judge_returns_parsed_verdict(self) -> None:
        runner = EvalRunner(runtime_with_reply(JUDGE_JSON))
        task = next(t for t in ALL_TASKS if t.id == "orders_to_json")

        result = await runner.run_task(task, "solo", {})
        verdict = await runner.run_judge("solo", task, result)

        assert verdict.parsed
        assert verdict.overall == 8.3
        assert "冗长" in verdict.comment

    async def test_run_judge_retries_after_empty_reply(self) -> None:
        class FlakyJudgeGraph(ScriptedGraph):
            def __init__(self) -> None:
                super().__init__(reply=JUDGE_JSON)
                self.calls = 0

            async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
                self.calls += 1
                if self.calls == 1:
                    return {"messages": [AIMessage(content="")]}
                return await super().ainvoke(state, config)

        graph = FlakyJudgeGraph()
        agents = AgentRegistry()
        agents.register(AgentSpec(id="judge", name="Judge"))
        runtime = AgentRuntime(agents, ToolRegistry(), SkillRegistry(), builder=StubBuilder(graph))
        runner = EvalRunner(runtime)
        task = next(t for t in ALL_TASKS if t.id == "orders_to_json")

        verdict = await runner.run_judge("judge", task, _result())

        assert verdict.parsed and verdict.overall == 8.3
        assert graph.calls == 2


def _result(
    task_id: str = "t1",
    *,
    passed: bool = True,
    wall_ms: float = 100.0,
    total_tokens: int = 1000,
) -> EvalResult:
    return EvalResult(
        task_id=task_id,
        name=task_id,
        aspects=[],
        status="completed" if passed else "failed",
        passed=passed,
        wall_ms=wall_ms,
        total_tokens=total_tokens,
        checks=[Check(name="c", passed=passed)],
    )


class TestBaseline:
    def test_save_and_load_round_trip(self, tmp_path: pathlib.Path) -> None:
        results = [_result("t1"), _result("t2", passed=False, wall_ms=50.0, total_tokens=500)]
        path = tmp_path / "baseline.json"

        save_baseline(path, results)
        loaded = load_baseline(path)

        assert loaded.created_at
        assert [(e.task_id, e.passed) for e in loaded.entries] == [
            ("t1", True),
            ("t2", False),
        ]

    def test_quality_regressions_and_improvements(self) -> None:
        baseline = snapshot([_result("good"), _result("bad", passed=False)])
        current = [_result("good", passed=False), _result("bad")]

        verdicts = {c.task_id: c.verdict for c in compare(current, baseline)}

        assert verdicts["good"] == "regressed"
        assert verdicts["bad"] == "improved"

    def test_cost_regression_beyond_tolerance(self) -> None:
        baseline = snapshot([_result("t1")])
        current = [_result("t1", wall_ms=200.0, total_tokens=1500)]  # +100% / +50%

        assert compare(current, baseline)[0].verdict == "regressed"

    def test_within_tolerance_unchanged(self) -> None:
        baseline = snapshot([_result("t1")])
        current = [_result("t1", wall_ms=110.0, total_tokens=1100)]  # +10%

        assert compare(current, baseline)[0].verdict == "unchanged"

    def test_new_and_missing_tasks(self) -> None:
        baseline = snapshot([_result("old")])
        current = [_result("fresh")]

        verdicts = {c.task_id: c.verdict for c in compare(current, baseline)}

        assert verdicts == {"fresh": "new", "old": "missing"}

    def test_comparison_label_includes_aspects(self) -> None:
        baseline = snapshot([_result("fx")])
        current = [_result("fx", wall_ms=300.0)]
        current[0].aspects = ["编排", "single"]

        comparisons = compare(current, baseline)

        assert "single" in comparisons[0].label

    def test_render_lists_every_comparison(self) -> None:
        baseline = snapshot([_result("t1")])

        text = render_comparison(compare([_result("t1", wall_ms=300.0)], baseline))

        assert "t1" in text
        assert "regressed" in text
