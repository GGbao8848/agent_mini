"""Real-task evaluation driver: five realistic tasks on live data + verifiers.

Tasks cover: live weather tool (open-meteo geocoding+forecast), strict JSON
extraction from business text, a buggy-function repair graded by executing
the model's code, an FX briefing run under three orchestration modes
(single / team / fan-out) against a live rates API, and a multi-step holiday
planner chaining an HTTP tool with a calculator.

Usage: uv run --env-file .env python scripts/eval_real.py [--suite full|fx]
         [--judge] [--save-baseline PATH] [--compare PATH]
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import operator
import pathlib
import sys

import httpx

from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.team import TeamSpec
from agent_core.domain.tool import ToolDefinition
from agent_core.eval import (
    ALL_TASKS,
    JUDGE_SYSTEM_PROMPT,
    EvalResult,
    EvalRunner,
    compare,
    load_baseline,
    render_comparison,
)
from agent_core.eval import (
    save_baseline as write_baseline,
)
from agent_core.orchestration import compose_team
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime import AgentRuntime

get_settings()  # applies AGENT_CORE_PROXY_URL to HTTP(S)_PROXY before any HTTP client is built

RESULTS_DIR = pathlib.Path("eval_results")

_TASK_BY_ID = {task.id: task for task in ALL_TASKS}

_WEATHER_CODES = {
    0: "晴",
    1: "基本晴",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "毛毛雨",
    55: "毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    95: "雷暴",
    96: "雷暴伴冰雹",
    99: "雷暴伴冰雹",
}

weather_readings: list[dict[str, object]] = []


def _http_json(url: str, params: dict[str, object]) -> dict[str, object]:
    response = httpx.get(url, params=params, timeout=15.0)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


def real_weather(city: str) -> str:
    try:
        geo = _http_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": city, "count": 1, "language": "zh", "format": "json"},
        )
        results = geo.get("results") or []
        if not results:
            return json.dumps({"error": f"city not found: {city}"}, ensure_ascii=False)
        place = results[0]  # type: ignore[index]
        data = _http_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current_weather": True,
            },
        )
        current = data["current_weather"]  # type: ignore[index]
        code = int(current.get("weathercode") or 0)  # type: ignore[union-attr]
        temp = float(current["temperature"])  # type: ignore[index]
        weather_readings.append({"city": city, "temperature_c": temp, "weathercode": code})
        return json.dumps(
            {
                "city": place.get("name", city),  # type: ignore[union-attr]
                "temperature_c": temp,
                "weather": _WEATHER_CODES.get(code, f"code {code}"),
                "windspeed_kmh": current.get("windspeed"),  # type: ignore[union-attr]
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def fx_rate(base: str, quote: str) -> str:
    try:
        data = _http_json("https://api.frankfurter.dev/v1/latest", {"base": base, "symbols": quote})
        rates = data.get("rates") or {}
        return json.dumps(
            {"base": base, "date": data.get("date"), "rate": rates.get(quote)},
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def public_holidays(year: int, country_code: str) -> str:
    try:
        response = httpx.get(
            f"https://date.nager.at/api/v3/publicholidays/{int(year)}/{country_code.upper()}",
            timeout=15.0,
        )
        response.raise_for_status()
        slim = [
            {"date": item["date"], "name": item["localName"]}
            for item in response.json()
            if isinstance(item, dict)
        ]
        return json.dumps(slim, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


_CALC_OPS: dict[type[ast.operator], object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CALC_UNARY: dict[type[ast.unaryop], object] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))  # type: ignore[operator]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_UNARY:
        return _CALC_UNARY[type(node.op)](_eval_node(node.operand))  # type: ignore[operator]
    raise ValueError(f"unsupported expression element: {ast.dump(node)}")


def calculator(expression: str) -> str:
    try:
        value = _eval_node(ast.parse(expression, mode="eval").body)
        return json.dumps({"expression": expression, "result": value})
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def build_runtime() -> tuple[AgentRuntime, AgentRegistry]:
    agents = AgentRegistry()
    tools = ToolRegistry()

    tools.register(
        ToolDefinition(
            name="real_weather",
            description="查询指定城市的实时天气（真实数据源）",
            input_schema={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名，如 北京"}},
                "required": ["city"],
            },
        ),
        real_weather,
    )
    tools.register(
        ToolDefinition(
            name="fx_rate",
            description="查询两种货币的最新汇率（真实数据源）",
            input_schema={
                "type": "object",
                "properties": {
                    "base": {"type": "string", "description": "基准货币代码，如 USD"},
                    "quote": {"type": "string", "description": "目标货币代码，如 CNY"},
                },
                "required": ["base", "quote"],
            },
        ),
        fx_rate,
    )
    tools.register(
        ToolDefinition(
            name="public_holidays",
            description="查询某国某年的法定节假日列表（真实数据源）",
            input_schema={
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "年份，如 2026"},
                    "country_code": {"type": "string", "description": "国家代码，如 CN"},
                },
                "required": ["year", "country_code"],
            },
        ),
        public_holidays,
    )
    tools.register(
        ToolDefinition(
            name="calculator",
            description="计算算术表达式（支持 + - * / % **）",
            input_schema={
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "如 (3+4)*7"}},
                "required": ["expression"],
            },
        ),
        calculator,
    )

    agents.register(
        AgentSpec(
            id="solo",
            name="Solo",
            tools=["real_weather", "fx_rate", "public_holidays", "calculator"],
            system_prompt=(
                "你是一名严谨的助手。凡是能用工具获得的事实，必须调用工具获取真实数据后再回答；"
                "回答要简洁、数值准确。"
            ),
        )
    )
    for i in (1, 2, 3):
        agents.register(
            AgentSpec(
                id=f"worker-{i}",
                name=f"Worker {i}",
                tools=["fx_rate"],
                description="查询一个汇率数据并报告数值",
                system_prompt="只完成分配给你的子任务，用工具查询后报告准确数值。",
            )
        )
    compose_team(agents, _team_spec("fx-team", "FX Team"))
    agents.register(
        AgentSpec(
            id="judge",
            name="Judge",
            system_prompt=JUDGE_SYSTEM_PROMPT,
        )
    )
    return AgentRuntime(agents, tools, SkillRegistry()), agents


def _team_spec(team_id: str, name: str) -> TeamSpec:
    return TeamSpec(
        id=team_id,
        name=name,
        worker_agent_ids=["worker-1", "worker-2", "worker-3"],
        merge_instructions=(
            "最终答案中的每个汇率数值必须逐字复制对应子任务结果 JSON 里的 rate 字段，"
            "禁止重新计算、换算或修正；每个数值后标注来源 worker。"
        ),
    )


def render_report(results: list[EvalResult]) -> str:
    lines = ["# 真实任务评估报告", ""]
    for result in results:
        verdict = "✅ PASS" if result.passed else "❌ FAIL"
        aspects = "/".join(result.aspects)
        lines.append(f"## {result.task_id} — {result.name} [{aspects}] {verdict}")
        lines.append(
            f"- status: {result.status}, wall: {result.wall_ms:.0f} ms, "
            f"tokens: {result.total_tokens} "
            f"(in {result.input_tokens} / out {result.output_tokens}), "
            f"model calls: {result.model_calls}, tool calls: {result.tool_calls}"
        )
        for check in result.checks:
            mark = "PASS" if check.passed else "FAIL"
            lines.append(f"  - [{mark}] {check.name} — {check.detail}")
        if result.judge is not None:
            if result.judge.parsed:
                dims = ", ".join(f"{k} {v:g}" for k, v in result.judge.dimensions.items())
                summary = f"overall {result.judge.overall:g}/10 ({dims})"
                lines.append(f"  - judge: {summary} — {result.judge.comment}")
            else:
                lines.append(f"  - judge: unparsable — {result.judge.raw[:80]}")
        preview = result.output.replace("\n", " ")[:220]
        lines.append(f"- output: {preview}…")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    runtime, _ = build_runtime()
    runner = EvalRunner(runtime)
    fx_task = _TASK_BY_ID["fx_briefing"]

    async def run_all() -> list[EvalResult]:
        results: list[EvalResult] = []
        context = {"weather_readings": weather_readings}

        if args.suite == "fx":
            for mode, agent_id in (("single", "solo"), ("team", "fx-team")):
                result = await runner.run_task(fx_task, agent_id, context)
                result.aspects = [*result.aspects, mode]
                results.append(result)
            return results

        results.append(await runner.run_task(_TASK_BY_ID["live_weather"], "solo", context))
        results.append(await runner.run_task(_TASK_BY_ID["orders_to_json"], "solo", context))
        results.append(await runner.run_task(_TASK_BY_ID["bugfix_code"], "solo", context))

        for mode, agent_id in (("single", "solo"), ("team", "fx-team")):
            result = await runner.run_task(fx_task, agent_id, context)
            result.aspects = [*result.aspects, mode]
            results.append(result)
        fanout_result = await runner.run_task_fanout(
            fx_task, ["worker-1", "worker-2", "worker-3"], "solo", context
        )
        results.append(fanout_result)

        results.append(await runner.run_task(_TASK_BY_ID["holiday_planner"], "solo", context))
        return results

    results = asyncio.run(run_all())
    if args.judge:
        results = asyncio.run(_apply_judge(runner, results))
    report = render_report(results)
    print(report)

    passed = sum(1 for r in results if r.passed)
    print(f"summary: {passed}/{len(results)} tasks passed all checks")

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "report.md").write_text(report, encoding="utf-8")
    (RESULTS_DIR / "results.json").write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"reports written to {RESULTS_DIR}/")

    exit_code = 0 if passed == len(results) else 1
    if args.save_baseline:
        write_baseline(args.save_baseline, results)
        print(f"baseline written to {args.save_baseline}")
    if args.compare:
        comparisons = compare(results, load_baseline(args.compare))
        comparison_md = render_comparison(comparisons)
        print(comparison_md)
        (RESULTS_DIR / "comparison.md").write_text(comparison_md, encoding="utf-8")
        if any(c.verdict == "regressed" for c in comparisons):
            exit_code = 1
    return exit_code


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real-task evaluation driver")
    parser.add_argument(
        "--suite",
        choices=("full", "fx"),
        default="full",
        help="fx runs only fx_briefing single+team (fast team-tuning loop)",
    )
    parser.add_argument(
        "--judge", action="store_true", help="grade completed outputs with an LLM judge agent"
    )
    parser.add_argument(
        "--save-baseline", metavar="PATH", help="save this run's metrics as a baseline JSON"
    )
    parser.add_argument(
        "--compare", metavar="PATH", help="compare this run against a baseline JSON"
    )
    return parser.parse_args()


async def _apply_judge(runner: EvalRunner, results: list[EvalResult]) -> list[EvalResult]:
    for result in results:
        if result.status != "completed":
            continue
        result.judge = await runner.run_judge("judge", _TASK_BY_ID[result.task_id], result)
    return results


if __name__ == "__main__":
    sys.exit(main())
