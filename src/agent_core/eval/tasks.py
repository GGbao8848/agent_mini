"""The five real evaluation tasks and their deterministic verifiers.

A task's ``verifier`` receives the agent's final answer plus a ``context``
dict the driver fills while tools run (e.g. the live weather reading) so
answers can be checked against ground truth captured at execution time.
Verifiers are pure functions — no network, no runtime objects.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_core.eval.model import Check

Verifier = Callable[[str, dict[str, object]], list[Check]]


@dataclass(frozen=True)
class RealTask:
    """One realistic end-to-end evaluation task."""

    id: str
    name: str
    aspects: tuple[str, ...]
    prompt: str
    verifier: Verifier
    tool_names: tuple[str, ...] = ()
    context_keys: tuple[str, ...] = field(default=tuple())
    subtasks: tuple[str, ...] = ()


# ---------------------------------------------------------------- T1: live tool QA
def verify_weather(output: str, context: dict[str, object]) -> list[Check]:
    checks: list[Check] = []
    raw = context.get("weather_readings")
    readings = raw if isinstance(raw, list) else []
    checks.append(
        Check(
            name="real tool called",
            passed=bool(readings),
            detail=f"{len(readings)} live reading(s) captured",
        )
    )
    temps = re.findall(r"(-?\d+(?:\.\d+)?)\s*(?:°C|度|摄氏)", output)
    if readings and temps:
        actual = float(readings[0]["temperature_c"])
        reported = max(temps, key=float)
        checks.append(
            Check(
                name="reported temp matches live data (±3°C)",
                passed=abs(float(reported) - actual) <= 3.0,
                detail=f"answer={reported}°C, live={actual}°C",
            )
        )
    elif readings:
        checks.append(
            Check(
                name="answer contains a temperature",
                passed=False,
                detail="no 'N °C/度' pattern found in answer",
            )
        )
    return checks


# ---------------------------------------------------------- T2: structured extraction
_ORDER_TEXT = """客服内部记录（顺序混乱，含备注）：
- 张伟 3 月 5 号下单，订单 A-1001，蓝牙耳机 ¥299，已发货
- 订单 A-1002 是李娜的，金额 1299 元（华为手机），2 月 28 日创建，状态是已取消
- 王强 A-1003 电动牙刷 89 块钱，3 月 1 日，已签收
- A-1004，赵敏，机械键盘 549，3 月 2 号下单；备注：地址写错了，待修改后再发货
金额都是人民币。"""

_JSON_INSTRUCTION = (
    "从上面的记录中抽取全部订单，只输出一个 JSON 对象（不要多余文字），格式：\n"
    '{"orders": [{"id": "...", "customer": "...", "amount": 数字, "date": "YYYY-MM-DD", '
    '"status": "..."}], "total_amount": 数字}\n'
    "status 从 已发货/已取消/已签收/待修改 中选。total_amount 是所有订单金额之和。"
)


def _extract_json(text: str) -> dict[str, object] | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    brace = text.find("{")
    if brace >= 0:
        candidates.append(text[brace : text.rfind("}") + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None


def verify_orders(output: str, context: dict[str, object]) -> list[Check]:
    del context
    data = _extract_json(output)
    if data is None:
        return [Check(name="output parses as JSON", passed=False, detail=output[:120])]
    orders = data.get("orders")
    checks = [Check(name="output parses as JSON", passed=True, detail="ok")]
    typed_orders = [order for order in orders if isinstance(order, dict)] if isinstance(
        orders, list
    ) else []
    ok_orders = len(typed_orders) == 4
    checks.append(Check(name="exactly 4 orders", passed=ok_orders, detail=str(orders)[:120]))
    if ok_orders:
        required = {"id", "customer", "amount", "date", "status"}
        complete = all(required.issubset(order) for order in typed_orders)
        checks.append(
            Check(
                name="all fields present", passed=complete, detail="id/customer/amount/date/status"
            )
        )
        total = data.get("total_amount")
        try:
            sum_ok = abs(float(total) - 2236.0) < 0.01  # type: ignore[arg-type]
        except (TypeError, ValueError):
            sum_ok = False
        checks.append(Check(name="total_amount == 2236", passed=sum_ok, detail=str(total)))
        iso = all(
            isinstance(order.get("date"), str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", order["date"]) is not None
            for order in typed_orders
        )
        checks.append(Check(name="dates normalized to ISO", passed=bool(iso), detail="YYYY-MM-DD"))
    return checks


# ------------------------------------------------------------- T3: buggy code repair
_BUGGY_CODE = '''def chunk_list(items, size):
    """把列表按 size 切块，例如 chunk_list([1,2,3,4,5], 2) -> [[1,2],[3,4],[5]]"""
    return [items[i:i + size + 1] for i in range(0, len(items), size + 1)]
'''


def verify_bugfix(output: str, context: dict[str, object]) -> list[Check]:
    del context
    block = re.search(r"```python\s*(.*?)```", output, re.S)
    if block is None:
        return [Check(name="answer contains a ```python block", passed=False, detail=output[:120])]
    code = block.group(1)
    namespace: dict[str, object] = {}
    try:
        exec(code, namespace)  # noqa: S102 - evaluator runs model code locally on purpose
    except Exception as exc:  # pragma: no cover - depends on model output
        return [Check(name="fixed code executes", passed=False, detail=repr(exc))]
    checks = [Check(name="fixed code executes", passed=True, detail="ok")]
    chunk = namespace.get("chunk_list")
    if not callable(chunk):
        checks.append(
            Check(name="chunk_list defined", passed=False, detail="missing from code block")
        )
        return checks

    def expected(items: list[object], size: int) -> list[list[object]]:
        return [items[i : i + size] for i in range(0, len(items), size)]

    cases: tuple[tuple[list[int], int], ...] = (
        ([1, 2, 3, 4, 5], 2),
        ([1, 2, 3, 4, 5, 6, 7], 3),
        ([], 3),
        ([1, 2], 5),
    )
    for items, size in cases:
        want = expected(list(items), size)
        try:
            got = chunk(list(items), size)
            checks.append(
                Check(
                    name=f"chunk_list({items}, {size})",
                    passed=got == want,
                    detail=f"got={got}, want={want}",
                )
            )
        except Exception as exc:
            checks.append(
                Check(name=f"chunk_list({items}, {size})", passed=False, detail=repr(exc))
            )
    return checks


# ----------------------------------------------------------- T4: multi-source briefing
def verify_fx(output: str, context: dict[str, object]) -> list[Check]:
    del context
    checks: list[Check] = []
    # USD/CNY ~6-9, EUR/CNY ~7-11, JPY/CNY ~0.02-0.09
    for base, low, high in (("USD", 5.5, 9.5), ("EUR", 6.5, 11.5), ("JPY", 0.015, 0.09)):
        found = re.search(re.escape(base) + r"[^\d]{0,12}(\d+\.\d+)", output)
        rate = float(found.group(1)) if found else None
        plausible = rate is not None and low <= rate <= high
        checks.append(
            Check(
                name=f"{base}→CNY rate plausible",
                passed=plausible,
                detail=f"found={rate}, expected in [{low}, {high}]",
            )
        )
    return checks


# -------------------------------------------------------------- T5: multi-step planner
def verify_holiday(output: str, context: dict[str, object]) -> list[Check]:
    del context
    return [
        Check(
            name="mentions a real 2026 holiday",
            passed=any(term in output for term in ("国庆", "春节", "中秋", "元旦", "劳动")),
            detail="keyword search",
        ),
        Check(
            name="gives a concrete day count",
            passed=bool(re.search(r"\d+\s*天", output)),
            detail="'N 天' pattern",
        ),
    ]


TASKS: tuple[RealTask, ...] = (
    RealTask(
        id="live_weather",
        name="Live weather QA (real HTTP tool)",
        aspects=("实时工具", "单跳问答"),
        prompt="调用 real_weather 工具查询北京现在的天气，用一句话报出当前气温（°C）和天气现象。",
        verifier=verify_weather,
        tool_names=("real_weather",),
        context_keys=("weather_readings",),
    ),
    RealTask(
        id="orders_to_json",
        name="Business text → strict JSON",
        aspects=("结构化抽取", "指令遵循"),
        prompt=_ORDER_TEXT + "\n\n" + _JSON_INSTRUCTION,
        verifier=verify_orders,
    ),
    RealTask(
        id="bugfix_code",
        name="Fix an off-by-one bug (verified by execution)",
        aspects=("代码能力", "客观验证"),
        prompt=(
            "下面这个 Python 函数有 bug，切块大小不对：\n\n```python\n" + _BUGGY_CODE + "```\n\n"
            "请修复它（保持函数名 chunk_list 和签名不变），"
            "把修复后的完整函数放在 ```python 代码块里，并用一句话说明 bug 原因。"
        ),
        verifier=verify_bugfix,
    ),
    RealTask(
        id="fx_briefing",
        name="Multi-source FX briefing (orchestration comparison)",
        aspects=("编排对比", "实时数据", "并行"),
        prompt=(
            "分别查询 USD、EUR、JPY 兑 CNY 的最新汇率（用 fx_rate 工具，quote 填 CNY），"
            "然后写一份简短中文简报：三组汇率数值 + 一句趋势提示。"
        ),
        verifier=verify_fx,
        tool_names=("fx_rate",),
        subtasks=(
            "用 fx_rate 工具查询 USD 兑 CNY 的最新汇率（base=USD, quote=CNY），"
            "只报告汇率数值和日期。",
            "用 fx_rate 工具查询 EUR 兑 CNY 的最新汇率（base=EUR, quote=CNY），"
            "只报告汇率数值和日期。",
            "用 fx_rate 工具查询 JPY 兑 CNY 的最新汇率（base=JPY, quote=CNY），"
            "只报告汇率数值和日期。",
        ),
    ),
    RealTask(
        id="holiday_planner",
        name="Holiday planning with tool chain + calculator",
        aspects=("多步规划", "工具链", "计算"),
        prompt=(
            "用 public_holidays 工具（country_code=CN, year=2026）查询中国 2026 年法定节假日，"
            "再用 calculator 工具计算其中 10 月假日共有几天，最后回答：如果用 5 天年假拼接连休，"
            "10 月最多能连休多少天？给出方案。"
        ),
        verifier=verify_holiday,
        tool_names=("public_holidays", "calculator"),
    ),
)

ALL_TASKS: tuple[RealTask, ...] = TASKS
