"""Benchmark cases: common task types with their strategy-relevant shapes.

A case carries everything that defines the workload — the user-facing input
and, when the task is decomposable, the independent subtasks used by the
fan-out mode. Which modes make sense per case is declared here too: a
single-shot tool QA has nothing to parallelize, while multi-document
summarization is the canonical parallel workload.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Execution strategies the harness knows about.
BENCH_MODES = ("single", "team", "fanout")


@dataclass(frozen=True)
class BenchCase:
    """One benchmark workload."""

    id: str
    name: str
    description: str
    input: str
    modes: tuple[str, ...]
    subtasks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown = set(self.modes) - set(BENCH_MODES)
        if unknown:
            raise ValueError(f"case '{self.id}' has unknown modes: {sorted(unknown)}")
        if "fanout" in self.modes and not self.subtasks:
            raise ValueError(f"case '{self.id}' allows fanout but has no subtasks")


_WEATHER_QA = BenchCase(
    id="qa_tool",
    name="Single-shot tool QA",
    description="One question answered with one deterministic tool call.",
    input="北京今天的天气怎么样？请用一句话回答。",
    modes=("single",),
)

_PASSAGES = (
    "光合作用是植物、藻类和某些细菌利用光能将二氧化碳和水转化为有机物并释放氧气的过程。"
    "它是地球上绝大多数生命能量的最初来源，每年固定的碳以百亿吨计。",
    "光合作用主要发生在叶绿体中，类囊体膜上进行光反应，将光能转化为ATP和NADPH；"
    "基质中进行暗反应（卡尔文循环），将二氧化碳固定为葡萄糖。",
    "研究光合作用不仅揭示了生命如何捕获能量，也为人工光合作用、"
    "提高农作物产量以及应对气候变化提供了关键思路。",
)

_SUMMARY_INPUT = (
    "请分别用一句话概括以下三段材料，然后把三句概括融合成一段不超过100字的中文总结。\n\n"
    + "\n\n".join(f"材料{i}：{text}" for i, text in enumerate(_PASSAGES, start=1))
)

_SUMMARIZE = BenchCase(
    id="summarize_multi",
    name="Multi-document summarization",
    description="Summarize three independent passages, then merge into one brief.",
    input=_SUMMARY_INPUT,
    subtasks=tuple(f"用一句话概括下面这段材料：\n{text}" for text in _PASSAGES),
    modes=("single", "team", "fanout"),
)

_TOPICS = (
    "IPv4 地址耗尽问题产生的原因和现状",
    "IPv6 的地址结构与主要特性",
    "从 IPv4 过渡到 IPv6 的主要技术（双栈、隧道、翻译）",
)

_SECTIONS = "\n".join(f"{i}. {topic}" for i, topic in enumerate(_TOPICS, start=1))
_RESEARCH = BenchCase(
    id="research_brief",
    name="Multi-topic mini research",
    description="Gather three independent topic summaries and synthesize a brief.",
    input=(f"请围绕以下三个要点各写两句话的说明，并汇总成一份简短的中文简报：\n{_SECTIONS}"),
    subtasks=tuple(f"请用两句话说明：{topic}" for topic in _TOPICS),
    modes=("single", "team", "fanout"),
)

_MEETING_NOTES = (
    "周五站会记录（有删改，顺序较乱）：\n"
    "- 小王说支付对账脚本还差报表导出，下周三前上线\n"
    "- 运营提出活动页文案要改，周五前给结论（负责人：小李）\n"
    "- 老板问上次说的监控告警怎么样了；小张确认已接入值班群，本周补文档\n"
    "- 小王补充：报表导出依赖数据组接口，需要小刘协调，周三前给接口\n"
    "- 下次站会改到周一上午十点"
)

_EXTRACT = BenchCase(
    id="extract_structure",
    name="Structured extraction",
    description="Extract decisions and owners from messy meeting notes.",
    input=(
        "请从下面的会议记录中提取所有待办事项，输出编号列表，每项包含负责人和截止时间；"
        "没有提到的不写。\n\n" + _MEETING_NOTES
    ),
    modes=("single",),
)

ALL_CASES: tuple[BenchCase, ...] = (
    _WEATHER_QA,
    _SUMMARIZE,
    _RESEARCH,
    _EXTRACT,
)
