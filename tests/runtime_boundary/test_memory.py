"""Memory invariants (R10): scoped retrieval, governed writes, behavior change.

MEM-001/005: retrieval returns only the relevant top-k, never the whole store.
MEM-004: scopes keep facts from bleeding into each other.
MEM-007: a newer fact supersedes the old one.
MEM-008: a forgotten memory stops being retrieved.
"""

from __future__ import annotations

from pathlib import Path

from agent_core.domain.memory import MemoryScope, MemoryType
from agent_core.memory import MemoryRepository, MemoryService, memory_prompt
from agent_core.memory.retriever import retrieve


def service() -> MemoryService:
    return MemoryService(MemoryRepository())


def test_duplicate_content_refreshes_instead_of_duplicating() -> None:
    """The old memory attempt stored the same fact 3×; writes now dedupe."""
    mem = service()
    first = mem.add("用户叫宋奎，在江苏北人工作。", source="agent")
    second = mem.add("用户叫宋奎，在江苏北人工作。", source="agent")

    assert first.id == second.id
    assert len(mem.list()) == 1


def test_retrieval_returns_only_relevant_topk() -> None:
    """Only entries overlapping the query come back; unrelated ones do not."""
    mem = service()
    mem.add("用户偏好所有回复控制在三句话以内。", type=MemoryType.PREFERENCE)
    mem.add("项目代号是 ALPHA-001。", type=MemoryType.FACT)
    mem.add("生产库是 PostgreSQL 15。", type=MemoryType.FACT)

    hits = mem.retrieve("请把回复写短一点，遵守我的偏好", limit=3)

    assert [m.content for m in hits] == ["用户偏好所有回复控制在三句话以内。"]


def test_retrieval_is_bounded_not_whole_store() -> None:
    """1000 memories: a fresh query returns at most the limit (MEM-005)."""
    mem = service()
    for index in range(1000):
        mem.add(f"无关的记忆条目编号 {index}", type=MemoryType.FACT)
    target = mem.add("用户叫宋奎，负责江苏北人的项目。", importance=8)

    hits = mem.retrieve("宋奎 负责什么项目", limit=5)

    assert len(hits) <= 5
    assert target.id in {m.id for m in hits}


def test_scope_filtering() -> None:
    """A project-scoped query does not surface user-scoped noise (MEM-004)."""
    mem = service()
    mem.add("用户叫宋奎。", scope=MemoryScope.USER)
    project = mem.add("项目代号 ALPHA-001。", scope=MemoryScope.PROJECT)

    hits = mem.retrieve("代号", scopes=[MemoryScope.PROJECT])

    assert [m.id for m in hits] == [project.id]


def test_supersede_replaces_old_fact() -> None:
    mem = service()
    old = mem.add("用户偏好 Markdown 输出。", type=MemoryType.PREFERENCE)

    new = mem.supersede(old.id, "用户以后要求 DOCX 输出。", type=MemoryType.PREFERENCE)

    assert old.superseded_by == new.id
    assert not old.is_live()
    hits = mem.retrieve("输出格式 偏好")
    assert [m.content for m in hits] == ["用户以后要求 DOCX 输出。"]


def test_forget_removes_from_retrieval() -> None:
    mem = service()
    mem.add("用户电话号码是 12345。")

    # Find and forget the one entry.
    entry = mem.list()[0]
    mem.forget(entry.id)

    assert mem.retrieve("电话号码") == []


def test_memory_prompt_empty_when_nothing_relevant() -> None:
    mem = service()
    mem.add("用户偏好 Markdown。")

    block = memory_prompt(mem.retrieve("帮我写一个排序算法"))

    assert block == ""


def test_prompt_block_renders_retrieved_entries_only() -> None:
    mem = service()
    mem.add("用户偏好 Markdown。", type=MemoryType.PREFERENCE)

    block = memory_prompt(mem.retrieve("输出格式偏好 Markdown"))

    assert "用户偏好 Markdown。" in block
    assert "长期记忆" in block


def test_memories_persist_through_repository_hydrate(tmp_path: Path) -> None:
    from agent_core.persistence.store import SqliteStore

    store = SqliteStore(f"sqlite:///{tmp_path / 'mem.db'}")
    first = MemoryService(MemoryRepository(store))
    first.add("用户叫宋奎。", scope=MemoryScope.USER)

    second = MemoryService(MemoryRepository(store))
    second.hydrate()
    store.close()

    assert [m.content for m in second.list()] == ["用户叫宋奎。"]
