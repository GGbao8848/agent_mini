"""Memory retrieval + governance invariants (R10).

MEM-002/003: a relevant memory is retrievable for a new request and injected;
the whole store never is.
MEM-004/007/008: scopes, supersede and forget.
API CRUD lives in ``test_api.py`` (shared async ``client`` fixture).
"""

from __future__ import annotations

from agent_core.domain.memory import MemoryScope, MemoryType
from agent_core.memory import MemoryRepository, MemoryService, memory_prompt


def test_retrieved_memory_reaches_the_prompt_block() -> None:
    """MEM-002/003: a relevant memory is retrievable for a new request."""
    service = MemoryService(MemoryRepository())
    service.add("用户偏好所有回复控制在三句话以内。", type=MemoryType.PREFERENCE)

    block = memory_prompt(service.retrieve("帮我总结这份报告，注意我的偏好"))

    assert "三句话以内" in block


def test_irrelevant_memory_is_not_injected() -> None:
    """The whole store is never dumped: an unrelated request injects nothing."""
    service = MemoryService(MemoryRepository())
    service.add("用户偏好 Markdown 输出。", type=MemoryType.PREFERENCE)

    assert memory_prompt(service.retrieve("计算 17 乘 23")) == ""


def test_superseding_fact_replaces_the_old_one() -> None:
    """MEM-007: the new preference wins, the old one is no longer retrieved."""
    service = MemoryService(MemoryRepository())
    old = service.add("用户偏好 Markdown 输出。", type=MemoryType.PREFERENCE)

    service.supersede(old.id, "用户以后要求 DOCX 输出。", type=MemoryType.PREFERENCE)

    block = memory_prompt(service.retrieve("输出格式偏好"))
    assert "DOCX" in block
    assert "Markdown" not in block


def test_scope_isolates_user_and_project_facts() -> None:
    """MEM-004: scopes do not bleed into each other."""
    service = MemoryService(MemoryRepository())
    service.add("用户叫宋奎。", scope=MemoryScope.USER)
    service.add("项目代号 ALPHA-001。", scope=MemoryScope.PROJECT)

    project_hits = service.retrieve("代号", scopes=[MemoryScope.PROJECT])

    assert [m.content for m in project_hits] == ["项目代号 ALPHA-001。"]
