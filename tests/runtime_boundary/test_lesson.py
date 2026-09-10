"""Error→Lesson loop invariants (R11): a correction becomes a durable lesson.

The loop: a user correction nudges the agent to record a lesson; a later
conversation retrieves it, so the same mistake is not repeated. These tests
cover the deterministic parts — the nudge fires only on corrections, and a
recorded lesson is retrievable in a fresh conversation.
"""

from __future__ import annotations

from agent_core.domain.memory import MemoryType
from agent_core.memory import MemoryRepository, MemoryService, lesson_hint, memory_prompt
from agent_core.memory.lesson import looks_like_correction


def test_nudge_fires_only_on_corrections() -> None:
    assert looks_like_correction("不对，生成 PPT 后要先确认文件存在")
    assert looks_like_correction("以后都要先检查再回复")
    assert looks_like_correction("记住：报告用中文")
    # Ordinary turns must not nudge (no cost, nothing recorded).
    assert not looks_like_correction("帮我看看这个报表")
    assert lesson_hint("帮我看看这个报表") == ""


def test_correction_hint_mentions_remember_and_lesson_types() -> None:
    hint = lesson_hint("以后生成 PPT 前先验证文件存在")

    assert "remember" in hint
    assert "lesson" in hint


def test_lesson_is_retrievable_in_a_later_conversation() -> None:
    """Full loop: record a lesson, then a new request surfaces it."""
    service = MemoryService(MemoryRepository())
    # Conversation A: the user corrects the agent, which records a lesson.
    service.add(
        "生成 PPT 后必须先确认目标文件真实存在，再向用户报告成功。",
        type=MemoryType.LESSON,
        source="agent",
    )

    # Conversation B: a fresh request about PPT generation.
    block = memory_prompt(service.retrieve("帮我生成一个季度汇报 PPT"))

    assert "先确认目标文件真实存在" in block


def test_lesson_records_as_error_fix_type() -> None:
    service = MemoryService(MemoryRepository())
    memory = service.add(
        "运行 run_code 前先检查工作目录，避免在错误的目录写文件。",
        type=MemoryType.ERROR_FIX,
        source="agent",
    )

    assert memory.type is MemoryType.ERROR_FIX
    hits = service.retrieve("run_code 写文件目录不对")
    assert [m.id for m in hits] == [memory.id]
