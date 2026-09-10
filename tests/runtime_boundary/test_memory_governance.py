"""Memory governance tests (R23, invariants I-24/I-25).

Before R23 the ``scope`` enum was decorative: an agent could write an ORG fact,
and retrieval ran unscoped, so a PROJECT memory written in one project could
surface in another project's conversation. These tests pin the enforcement:

- an agent cannot write ORG, nor PROJECT without a bound project;
- retrieval only sees the scopes that belong to the run's own context;
- every entry records its provenance (owner, run, author).
"""

from __future__ import annotations

import pytest

from agent_core.domain.memory import Memory, MemoryScope, MemoryType
from agent_core.errors.exceptions import PermissionDeniedError
from agent_core.memory import MemoryOrigin, MemoryPolicy, MemoryRepository, MemoryService, ScopeRef

USER = "user-1"
PROJECT_A = "proj-a"
PROJECT_B = "proj-b"
AGENT = "agent-1"


def make_service() -> MemoryService:
    return MemoryService(MemoryRepository())


# ------------------------------------------------------------------- writes


def test_agent_cannot_write_org_scope() -> None:
    """I-24: org-wide facts are a control-plane change, human-only."""
    policy = MemoryPolicy()
    assert (
        policy.can_write(scope=MemoryScope.ORG, origin=MemoryOrigin.AGENT).value == "deny"
    )
    assert (
        policy.can_write(scope=MemoryScope.ORG, origin=MemoryOrigin.HUMAN).value == "allow"
    )


def test_human_may_write_any_scope() -> None:
    policy = MemoryPolicy()
    for scope in MemoryScope:
        assert policy.can_write(scope=scope, origin=MemoryOrigin.HUMAN).value == "allow"


def test_agent_cannot_write_project_scope_without_project() -> None:
    policy = MemoryPolicy()
    assert (
        policy.can_write(
            scope=MemoryScope.PROJECT, origin=MemoryOrigin.AGENT, project_id=None
        ).value
        == "deny"
    )
    assert (
        policy.can_write(
            scope=MemoryScope.PROJECT, origin=MemoryOrigin.AGENT, project_id=PROJECT_A
        ).value
        == "allow"
    )


def test_add_governed_raises_on_denied_scope() -> None:
    service = make_service()
    with pytest.raises(PermissionDeniedError):
        service.add_governed(
            "组织级内部政策",
            scope=MemoryScope.ORG,
            type=MemoryType.CONSTRAINT,
            origin=MemoryOrigin.AGENT,
            agent_id=AGENT,
        )


def test_add_governed_records_provenance() -> None:
    service = make_service()
    memory = service.add_governed(
        "本项目用 pytest",
        scope=MemoryScope.PROJECT,
        scope_id=PROJECT_A,
        type=MemoryType.CONSTRAINT,
        origin=MemoryOrigin.AGENT,
        agent_id=AGENT,
        project_id=PROJECT_A,
        task_id="t1",
        source_run_id="r1",
        created_by=AGENT,
    )
    assert memory.scope_id == PROJECT_A
    assert memory.source_run_id == "r1"
    assert memory.created_by == AGENT
    assert memory.source == "agent"


# -------------------------------------------------------------------- reads


def test_visible_scopes_include_own_project_only() -> None:
    policy = MemoryPolicy()
    refs = policy.visible_scopes(agent_id=AGENT, project_id=PROJECT_A, user_id=USER)
    assert ScopeRef(MemoryScope.ORG, None) in refs
    assert ScopeRef(MemoryScope.AGENT, AGENT) in refs
    assert ScopeRef(MemoryScope.PROJECT, PROJECT_A) in refs
    assert ScopeRef(MemoryScope.PROJECT, PROJECT_B) not in refs


def test_unbound_run_has_no_project_scope() -> None:
    policy = MemoryPolicy()
    refs = policy.visible_scopes(agent_id=AGENT, project_id=None, user_id=USER)
    assert all(ref.scope is not MemoryScope.PROJECT for ref in refs)


def test_retrieval_is_isolated_between_projects() -> None:
    """I-25: project A's memory must not surface in project B's conversation."""
    service = make_service()
    service.add(
        "项目 A 的部署端口是 8080",
        scope=MemoryScope.PROJECT,
        scope_id=PROJECT_A,
        type=MemoryType.FACT,
    )
    policy = service.policy
    refs_b = policy.visible_scopes(agent_id=AGENT, project_id=PROJECT_B)
    hits = service.retrieve("部署端口", scope_refs=refs_b)
    assert hits == []

    refs_a = policy.visible_scopes(agent_id=AGENT, project_id=PROJECT_A)
    hits_a = service.retrieve("部署端口", scope_refs=refs_a)
    assert [m.content for m in hits_a] == ["项目 A 的部署端口是 8080"]


def test_unscoped_retrieval_still_works_for_legacy_and_tests() -> None:
    """Omitting scope_refs keeps the pre-R23 behaviour (unrestricted)."""
    service = make_service()
    service.add("任意项目都能看到", scope=MemoryScope.PROJECT, scope_id=PROJECT_B)
    assert service.retrieve("任意项目") != []


def test_org_memory_is_visible_to_every_context() -> None:
    service = make_service()
    service.add("公司统一用中文回复", scope=MemoryScope.ORG, type=MemoryType.CONSTRAINT)
    for project in (PROJECT_A, PROJECT_B, None):
        refs = service.policy.visible_scopes(agent_id=AGENT, project_id=project)
        hits = service.retrieve("中文回复", scope_refs=refs)
        assert [m.content for m in hits] == ["公司统一用中文回复"]


def test_context_visibility_filter() -> None:
    policy = MemoryPolicy()
    refs = policy.visible_scopes(agent_id=AGENT, project_id=PROJECT_A)
    assert policy.can_read(MemoryScope.PROJECT, PROJECT_A, refs) is True
    assert policy.can_read(MemoryScope.PROJECT, PROJECT_B, refs) is False
    assert policy.can_read(MemoryScope.ORG, None, refs) is True


def test_legacy_memory_without_scope_id_is_not_visible_scoped() -> None:
    """A pre-R23 PROJECT row (scope_id=None) is inert under scoped retrieval.

    It stays reachable through unscoped retrieval, so nothing is lost, but it
    cannot leak into an arbitrary project's conversation.
    """
    service = make_service()
    service.add("旧数据没有项目归属", scope=MemoryScope.PROJECT, scope_id=None)
    refs = service.policy.visible_scopes(agent_id=AGENT, project_id=PROJECT_A)
    assert service.retrieve("旧数据", scope_refs=refs) == []
    assert service.retrieve("旧数据") != []


def test_supersede_inherits_scope_id() -> None:
    service = make_service()
    old = service.add("端口 8080", scope=MemoryScope.PROJECT, scope_id=PROJECT_A)
    new = service.supersede_many([old.id], "端口 9090")
    assert new.scope_id == PROJECT_A
    refs = service.policy.visible_scopes(agent_id=AGENT, project_id=PROJECT_A)
    hits = service.retrieve("端口", scope_refs=refs)
    assert [m.content for m in hits] == ["端口 9090"]


def test_memory_defaults_scope_id_none() -> None:
    memory = Memory(content="普通用户事实")
    assert memory.scope_id is None
    assert memory.created_by == "human"
    assert memory.source_run_id is None
