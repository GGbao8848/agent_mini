"""Long-term memory: storage, prompt injection, bounds."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_core.domain.agent import AgentSpec
from agent_core.domain.memory import Memory, memories_prompt
from agent_core.errors.exceptions import RegistryError, StateError
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime


def make_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, store: bool = False) -> AgentRuntime:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_CORE_DATABASE_URL", f"sqlite:///{tmp_path}/a.db")
    get_settings.cache_clear()
    agents = AgentRegistry()
    agents.register(AgentSpec(id="h", name="H"))
    from agent_core.persistence.store import SqliteStore

    return AgentRuntime(
        agents,
        ToolRegistry(),
        SkillRegistry(),
        store=SqliteStore(f"sqlite:///{tmp_path}/a.db") if store else None,
    )


from agent_core.config.settings import get_settings


class TestDomainMemory:
    def test_prompt_empty_when_no_memories(self) -> None:
        assert memories_prompt([]) == ""

    def test_prompt_lists_newest_first_and_bounds(self) -> None:
        old = Memory(content="old fact", updated_at=datetime.now(UTC) - timedelta(days=1))
        new = Memory(content="new fact")
        text = memories_prompt([old, new])
        assert text.index("new fact") < text.index("old fact")
        many = [
            Memory(content=f"m{i}", updated_at=datetime.now(UTC) + timedelta(seconds=i))
            for i in range(150)
        ]
        assert memories_prompt(many).count("\n- ") <= 100


class TestRuntimeMemory:
    def test_add_list_update_delete_roundtrip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = make_runtime(tmp_path, monkeypatch, store=True)

        first = runtime.add_memory("用户偏好中文", source="agent", task_id="t1")
        runtime.add_memory("项目用 pnpm")
        assert len(runtime.list_memories()) == 2

        runtime.update_memory(first.id, "用户偏好繁体中文")  # updated_at → newest
        assert runtime.list_memories()[0].content == "用户偏好繁体中文"

        runtime.delete_memory(first.id)
        assert [m.content for m in runtime.list_memories()] == ["项目用 pnpm"]
        with pytest.raises(RegistryError):
            runtime.delete_memory("nope")
        with pytest.raises(RegistryError):
            runtime.update_memory("nope", "x")

        # Write-through + hydrate: a fresh runtime sees the same memories.
        fresh = AgentRuntime(
            AgentRegistry([AgentSpec(id="h", name="H")]),
            ToolRegistry(),
            SkillRegistry(),
            store=__import__("agent_core.persistence.store", fromlist=["SqliteStore"]).SqliteStore(
                f"sqlite:///{tmp_path}/a.db"
            ),
        )
        fresh.hydrate()
        assert [m.content for m in fresh.list_memories()] == ["项目用 pnpm"]

    def test_add_rejects_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        runtime = make_runtime(tmp_path, monkeypatch)
        with pytest.raises(StateError):
            runtime.add_memory("   ")


class TestBuilderInjection:
    def test_memories_reach_system_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The builder appends the memories block to the system prompt."""
        runtime = make_runtime(tmp_path, monkeypatch)
        runtime.add_memory("测试记忆条目")
        from agent_core.domain.memory import memories_prompt

        prompt = memories_prompt(runtime.list_memories())
        assert "测试记忆条目" in prompt
        assert "# Long-term memories" in prompt


class TestAutoExtraction:
    """After each completed turn a cheap call decides whether the turn
    produced a durable fact; silence (NONE / empty) means nothing stored."""

    def _runtime_with_stub_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str) -> AgentRuntime:
        from agent_core.config.settings import get_settings

        runtime = make_runtime(tmp_path, monkeypatch)

        class StubModel:
            async def ainvoke(self, prompt: str):
                from langchain_core.messages import AIMessage

                return AIMessage(content=reply)

        import agent_core.runtime.model as model_module

        monkeypatch.setattr(model_module, "build_model", lambda spec=None: StubModel())
        get_settings.cache_clear()
        return runtime

    async def test_turn_with_a_fact_is_extracted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = self._runtime_with_stub_model(tmp_path, monkeypatch, "用户偏好 pnpm 作为包管理器")
        run = runtime.create_run("h", "以后项目都用 pnpm")
        await runtime.execute_run(run)
        assert [m.content for m in runtime.list_memories()] == ["用户偏好 pnpm 作为包管理器"]
        assert runtime.list_memories()[0].source == "agent"

    async def test_silent_turn_stores_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = self._runtime_with_stub_model(tmp_path, monkeypatch, "NONE")
        run = runtime.create_run("h", "今天天气怎么样")
        await runtime.execute_run(run)
        assert runtime.list_memories() == []

    async def test_duplicate_facts_deduplicate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = self._runtime_with_stub_model(tmp_path, monkeypatch, "用户偏好 pnpm 作为包管理器")
        for _ in range(2):
            run = runtime.create_run("h", "记得：项目统一用 pnpm")
            await runtime.execute_run(run)
        assert len(runtime.list_memories()) == 1
