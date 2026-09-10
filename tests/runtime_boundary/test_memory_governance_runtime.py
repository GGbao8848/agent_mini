"""Memory governance reaches the runtime path (R23).

The policy is unit-tested; this proves the runtime *uses* it: a run only
retrieves memories visible to its own context (its project, its agent, ORG,
USER), and the agent's ``remember`` writes with the right owner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.builtins.memory import make_remember
from agent_core.domain.agent import AgentSpec
from agent_core.domain.memory import MemoryScope, MemoryType
from agent_core.domain.project import Project
from agent_core.errors.exceptions import ToolError
from agent_core.memory import MemoryRepository, MemoryService
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.context import current_run
from agent_core.runtime.runtime import AgentRuntime


def make_runtime() -> AgentRuntime:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="worker", name="Worker"))
    return AgentRuntime(
        agents, ToolRegistry(), SkillRegistry(), memories=MemoryService(MemoryRepository())
    )


async def test_memory_block_is_scoped_to_the_run_context(tmp_path: Path) -> None:
    runtime = make_runtime()
    runtime.memories.add(
        "项目 A 的密钥在 vault-a",
        scope=MemoryScope.PROJECT,
        scope_id="proj-a",
        type=MemoryType.FACT,
    )
    runtime.memories.add(
        "项目 B 的密钥在 vault-b",
        scope=MemoryScope.PROJECT,
        scope_id="proj-b",
        type=MemoryType.FACT,
    )
    runtime.projects.register(Project(id="proj-b", name="B", path=tmp_path))

    # A run bound to project B must NOT see project A's secret.
    task = runtime.create_conversation("worker", "项目密钥在哪", project_id="proj-b")
    block = await runtime._memory_block("密钥", task)  # noqa: SLF001 - testing the path
    assert "vault-b" in block
    assert "vault-a" not in block


def test_write_context_resolves_project_from_task(tmp_path: Path) -> None:
    runtime = make_runtime()
    runtime.projects.register(Project(id="proj-a", name="A", path=tmp_path))
    task = runtime.create_conversation("worker", "hello", project_id="proj-a")
    run = runtime.task_active_run(task.id)
    assert run is not None
    token = current_run.set(run)
    try:
        context = runtime.memory_write_context()
    finally:
        current_run.reset(token)
    assert context.project_id == "proj-a"
    assert context.agent_id == "worker"
    assert context.run_id == run.id


async def test_remember_tool_respects_policy() -> None:
    runtime = make_runtime()
    service = runtime.memories
    _, handler = make_remember(service, context_provider=runtime.memory_write_context)

    # No run in context → no project; a PROJECT write is refused by the policy.
    with pytest.raises(ToolError):
        await handler("这是一个项目记忆", scope="project")

    # USER scope works and records provenance.
    result = await handler("用户偏好中文", scope="user", type="preference")
    assert "已记住" in result
    stored = [m for m in service.list() if "用户偏好中文" in m.content]
    assert stored and stored[0].scope is MemoryScope.USER


async def test_remember_writes_project_memory_when_bound(tmp_path: Path) -> None:
    runtime = make_runtime()
    runtime.projects.register(Project(id="proj-a", name="A", path=tmp_path))
    task = runtime.create_conversation("worker", "hello", project_id="proj-a")
    run = runtime.task_active_run(task.id)
    assert run is not None
    token = current_run.set(run)
    try:
        _, handler = make_remember(
            runtime.memories, context_provider=runtime.memory_write_context
        )
        await handler("本项目端口 8080", scope="project", type="constraint")
    finally:
        current_run.reset(token)
    stored = [m for m in runtime.memories.list() if "端口 8080" in m.content]
    assert stored and stored[0].scope_id == "proj-a"
    assert stored[0].source_run_id == run.id
    assert stored[0].created_by == "worker"


async def test_agent_cannot_write_org_memory() -> None:
    runtime = make_runtime()
    task = runtime.create_conversation("worker", "hello")
    run = runtime.task_active_run(task.id)
    assert run is not None
    token = current_run.set(run)
    try:
        _, handler = make_remember(
            runtime.memories, context_provider=runtime.memory_write_context
        )
        with pytest.raises(ToolError):
            await handler("公司内部政策", scope="org")
    finally:
        current_run.reset(token)
    assert runtime.memories.list() == []
