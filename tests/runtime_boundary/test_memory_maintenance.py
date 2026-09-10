"""Auto memory maintenance in conversation (dedup / update / delete).

Exercises the three memory tools the agent uses mid-conversation:
``remember`` (add + dedup + supersede), ``recall_memories`` and
``forget_memories``, plus the short-id references the prompt exposes.
"""

from __future__ import annotations

import asyncio

from agent_core.builtins.memory import (
    make_forget_memories,
    make_recall_memories,
    make_remember,
)
from agent_core.memory import MemoryRepository, MemoryService, memory_prompt


def _tools() -> tuple[MemoryService, object, object, object]:
    service = MemoryService(MemoryRepository())
    return (
        service,
        make_remember(service)[1],
        make_recall_memories(service)[1],
        make_forget_memories(service)[1],
    )


def test_remember_dedupes_without_a_twin() -> None:
    service, remember, _, _ = _tools()

    asyncio.run(remember(content="用户叫宋奎"))
    asyncio.run(remember(content="用户叫宋奎，"))  # same after normalization

    assert len(service.list()) == 1


def test_remember_with_supersedes_retires_the_old_fact() -> None:
    """The correction path: one new entry, the old one deactivated (MEM-007)."""
    service, remember, _, _ = _tools()
    asyncio.run(remember(content="用户偏好 Markdown 输出"))
    old = service.list()[0]

    result = asyncio.run(
        remember(content="用户以后要求 DOCX 输出", supersedes=[old.id[:8]])
    )

    assert "退役" in result
    live = service.list(live_only=True)
    assert [m.content for m in live] == ["用户以后要求 DOCX 输出"]
    assert service.get(old.id).superseded_by is not None


def test_supersedes_accepts_short_prefix() -> None:
    service, remember, _, _ = _tools()
    asyncio.run(remember(content="用户偏好短回复"))
    old = service.list()[0]

    asyncio.run(remember(content="用户偏好长回复", supersedes=[f"#{old.id[:8]}"]))

    assert len(service.list(live_only=True)) == 1


def test_supersedes_ambiguous_prefix_does_not_retire_anything() -> None:
    """An ambiguous prefix must not silently pick a victim."""
    from agent_core.domain.memory import Memory

    repo = MemoryRepository()
    repo.register(Memory(id="abc11111", content="事实甲"))
    repo.register(Memory(id="abc22222", content="事实乙"))
    service = MemoryService(repo)
    remember = make_remember(service)[1]

    asyncio.run(remember(content="事实丙", supersedes=["abc"]))  # shared prefix

    # Nothing retired: both originals stay live and the new one is added.
    assert len(service.list(live_only=True)) == 3
    assert service.get("abc11111").superseded_by is None


def test_forget_memories_removes_on_request() -> None:
    service, remember, _, forget = _tools()
    asyncio.run(remember(content="用户电话号码是 12345"))
    target = service.list()[0]

    result = asyncio.run(forget(ids=[target.id[:8]]))

    assert "已删除" in result
    assert service.list() == []


def test_recall_memories_lists_and_searches() -> None:
    _, remember, recall, _ = _tools()
    async def seed() -> None:
        await remember(content="项目代号 ALPHA-001")
        await remember(content="用户喜欢简洁回复")
    asyncio.run(seed())

    listed = asyncio.run(recall())
    assert "ALPHA-001" in listed and "简洁" in listed

    searched = asyncio.run(recall(query="项目代号是什么"))
    assert "ALPHA-001" in searched


def test_prompt_exposes_short_ids_for_maintenance() -> None:
    service, remember, _, _ = _tools()
    asyncio.run(remember(content="用户叫宋奎"))
    memory = service.list()[0]

    block = memory_prompt([memory])

    assert f"#{memory.id[:8]}" in block
    assert "supersedes" in block and "forget_memories" in block


def test_forget_unknown_id_reports_instead_of_raising() -> None:
    _, _, _, forget = _tools()

    result = asyncio.run(forget(ids=["deadbeef"]))

    assert "未找到" in result
