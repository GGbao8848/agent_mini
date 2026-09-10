"""Runtime context assembly tests (R20).

The system prompt is now a list of named, ordered, budgeted sections rather
than a chain of string concatenations. These tests pin the properties that make
that useful: deterministic order, per-section accounting, and a budget that
drops optional sections whole while never touching the agent's instructions.
"""

from __future__ import annotations

from agent_core.context import ContextBuilder, SectionKind
from agent_core.context.builder import section_from_text


def test_sections_are_ordered_deterministically() -> None:
    ctx = ContextBuilder().build(
        system_prompt="BASE",
        autonomy="AUTONOMY",
        environment="ENV",
        task_state="STATE",
        memory="MEM",
        lesson="LESSON",
    )
    assert [s.kind for s in ctx.sections] == [
        SectionKind.SYSTEM,
        SectionKind.AUTONOMY,
        SectionKind.ENVIRONMENT,
        SectionKind.TASK_STATE,
        SectionKind.MEMORY,
        SectionKind.LESSON,
    ]
    assert ctx.prompt == "BASEAUTONOMYENVSTATEMEMLESSON"


def test_empty_sections_are_omitted() -> None:
    ctx = ContextBuilder().build(system_prompt="BASE", environment="ENV")
    assert [s.kind for s in ctx.sections] == [
        SectionKind.SYSTEM,
        SectionKind.ENVIRONMENT,
    ]


def test_section_tokens_are_estimated() -> None:
    section = section_from_text(SectionKind.MEMORY, "你好世界")
    assert section.tokens >= 4  # ~1 token per CJK char


def test_breakdown_sums_per_kind() -> None:
    ctx = ContextBuilder().build(system_prompt="hello", memory="记忆")
    breakdown = ctx.breakdown()
    assert SectionKind.SYSTEM.value in breakdown
    assert SectionKind.MEMORY.value in breakdown


def test_budget_disabled_keeps_everything() -> None:
    big = "字" * 1000
    ctx = ContextBuilder().build(system_prompt="BASE", memory=big)
    assert ctx.dropped == []
    assert ctx.injected_budget is None


def test_budget_drops_lowest_priority_first() -> None:
    ctx = ContextBuilder(injected_budget=50).build(
        system_prompt="BASE",
        task_state="状态",  # priority 70 — small, should survive the hint
        memory="记忆" * 100,  # priority 40
        lesson="提示" * 100,  # priority 30 — dropped first
    )
    # Lesson (lowest) is dropped before memory, and task state survives.
    assert ctx.dropped == ["lesson", "memory"]
    kinds = [s.kind for s in ctx.sections]
    assert SectionKind.TASK_STATE in kinds
    assert SectionKind.LESSON not in kinds


def test_budget_never_drops_required_section() -> None:
    base = "BASE" * 500
    ctx = ContextBuilder(injected_budget=10).build(system_prompt=base, memory="记忆" * 100)
    assert SectionKind.SYSTEM in [s.kind for s in ctx.sections]
    assert ctx.dropped == ["memory"]


def test_budget_drops_whole_sections_not_truncated() -> None:
    """A dropped section is gone entirely — never a half sentence."""
    memory = "这是一条完整的记忆内容"
    ctx = ContextBuilder(injected_budget=1).build(system_prompt="B", memory=memory)
    assert memory not in ctx.prompt


def test_explain_reports_provenance() -> None:
    ctx = ContextBuilder().build(system_prompt="BASE", memory="MEM")
    explained = ctx.explain()
    assert {"kind", "tokens", "priority", "required", "source"} <= set(explained[0])
    assert explained[0]["required"] is True
