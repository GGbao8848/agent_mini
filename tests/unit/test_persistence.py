"""Persistence tests: SQLite write-through, hydration, and restart semantics.

Enabled components keep their in-memory dicts as the read side and mirror
every change into the store; the tests build a second set of components over
the same database file to simulate a process restart.
"""

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agent_core.application.bootstrap import default_service
from agent_core.config.settings import Settings
from agent_core.domain.action import Action, ApprovalStatus, RiskLevel
from agent_core.domain.agent import AgentSpec
from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
from agent_core.domain.skill import SkillManifest
from agent_core.domain.task import RunStatus
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import ConfigurationError, RegistryError
from agent_core.observability.trace import InMemoryTracer
from agent_core.permissions.approval import ApprovalManager
from agent_core.persistence import PersistingTracer, open_store
from agent_core.persistence.store import SqliteStore, parse_sqlite_url
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.context import current_run
from agent_core.runtime.runtime import AgentRuntime


class FakeGraph:
    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        assert current_run.get() is not None
        return {"messages": [AIMessage(content=f"echo: {state['messages'][-1]['content']}")]}


class StubBuilder:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def build(self, spec: Any) -> Any:
        return self._graph


def make_agent(agent_id: str = "helper") -> AgentSpec:
    return AgentSpec(id=agent_id, name="Helper", model="openai:gpt-4o-mini")


def make_action(run_id: str, tool_name: str = "shell") -> Action:
    return Action(
        run_id=run_id,
        agent_id="helper",
        tool_name=tool_name,
        arguments={"cmd": "rm -rf /"},
        risk_level=RiskLevel.HIGH,
    )


def sqlite_settings(path: Path) -> Settings:
    return Settings(_env_file=None, database_url=f"sqlite:///{path}")


# --------------------------------------------------------------------- store


class TestStore:
    def test_open_store_none_disables_persistence(self) -> None:
        assert open_store(None) is None

    def test_non_sqlite_url_is_a_configuration_error(self) -> None:
        with pytest.raises(ConfigurationError):
            open_store("postgres://localhost/db")

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("sqlite:///relative.db", Path("relative.db")),
            ("sqlite:////absolute.db", Path("/absolute.db")),
            ("sqlite:///:memory:", ":memory:"),
        ],
    )
    def test_parse_sqlite_url(self, url: str, expected: str) -> None:
        assert parse_sqlite_url(url) == expected

    def test_parse_sqlite_url_empty_path_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_sqlite_url("sqlite:///")

    def test_schema_initialization_is_idempotent(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path}/agent.db"
        SqliteStore(url).close()
        SqliteStore(url).close()  # second open re-runs migration on the same file

    def test_migration_from_v1_adds_schedules(self, tmp_path: Path) -> None:
        """A v1 database (no schedules table) upgrades to v2 in place."""
        import sqlite3

        url = f"sqlite:///{tmp_path}/agent.db"
        conn = sqlite3.connect(tmp_path / "agent.db")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS registry_items (
                kind TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY (kind, key)
            );
            CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trace_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, data TEXT NOT NULL);
            """
        )
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()

        store = SqliteStore(url)  # migration v1 -> v2
        store.save_schedule("s1", '{"id": "s1", "name": "x"}')
        assert store.load_schedules() == ['{"id": "s1", "name": "x"}']
        store.delete_schedule("s1")
        assert store.load_schedules() == []
        store.close()

    def test_schedule_roundtrip(self, tmp_path: Path) -> None:
        from agent_core.domain.schedule import Schedule

        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        schedule = Schedule(
            name="hourly", agent_id="helper", task_input="check", schedule_type="interval",
            interval_minutes=60,
        )
        store.save_schedule(schedule.id, schedule.model_dump_json())

        restored = Schedule.model_validate_json(store.load_schedules()[0])
        assert restored.name == "hourly"
        assert restored.interval_minutes == 60
        store.close()

    def test_task_and_run_delete(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        store.save_task("t1", '{"id": "t1"}')
        store.save_run("r1", "completed", '{"id": "r1"}')

        store.delete_run("r1")
        assert store.load_runs() == []
        assert store.load_tasks() == ['{"id": "t1"}']

        store.delete_task("t1")
        assert store.load_tasks() == []
        store.close()

    def test_generic_roundtrips(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")

        store.save_item("agent", "a1", '{"id": "a1"}')
        store.save_item("agent", "a1", '{"id": "a1", "v": 2}')  # upsert
        store.save_item("agent", "a2", '{"id": "a2"}')
        store.save_task("t1", '{"id": "t1"}')
        store.save_run("r1", "running", '{"id": "r1"}')
        store.save_approval("ap1", "pending", '{"id": "ap1"}')
        store.append_event("r1", '{"e": 1}')
        store.append_event("r1", '{"e": 2}')

        assert store.load_items("agent") == [("a1", '{"id": "a1", "v": 2}'), ("a2", '{"id": "a2"}')]
        assert store.load_items("tool") == []
        store.delete_item("agent", "a2")
        assert store.load_items("agent") == [("a1", '{"id": "a1", "v": 2}')]
        assert store.load_tasks() == ['{"id": "t1"}']
        assert store.load_runs() == ['{"id": "r1"}']
        assert store.load_approvals() == ['{"id": "ap1"}']
        assert store.load_events() == [("r1", '{"e": 1}'), ("r1", '{"e": 2}')]
        store.close()


# ---------------------------------------------------------------- registries


class TestRegistryPersistence:
    def test_write_through_and_hydrate(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        registry = AgentRegistry(store)
        registry.register(make_agent())

        restored = AgentRegistry(SqliteStore(f"sqlite:///{tmp_path}/agent.db"))
        restored.hydrate()

        assert restored.get("helper") == make_agent()
        assert restored.list() == [make_agent()]

    def test_hydrated_registry_enforces_duplicate_rule(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        AgentRegistry(store).register(make_agent())

        restored = AgentRegistry(SqliteStore(f"sqlite:///{tmp_path}/agent.db"))
        restored.hydrate()

        with pytest.raises(RegistryError) as excinfo:
            restored.register(make_agent())
        assert excinfo.value.details["key"] == "helper"

    def test_remove_deletes_from_store(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        registry = AgentRegistry(store)
        registry.register(make_agent())
        registry.remove("helper")

        restored = AgentRegistry(store)
        restored.hydrate()

        assert len(restored) == 0

    def test_tool_definitions_restore_without_handlers(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        registry = ToolRegistry(store)
        registry.register(
            ToolDefinition(
                name="get_weather", description="Weather lookup", source=ToolSource.PYTHON
            ),
            handler=lambda **_: "sunny",
        )

        restored = ToolRegistry(store)
        restored.hydrate()

        assert restored.get("get_weather").name == "get_weather"
        with pytest.raises(RegistryError) as excinfo:
            restored.handler_for("get_weather")
        assert "no executable handler registered" in excinfo.value.message

    def test_skill_versions_roundtrip_with_latest_order(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        registry = SkillRegistry(store)
        registry.register(SkillManifest(id="greet", name="Greet", version="0.1.0"))
        registry.register(SkillManifest(id="greet", name="Greet", version="0.2.0"))

        restored = SkillRegistry(store)
        restored.hydrate()

        assert restored.get("greet").version == "0.2.0"
        assert restored.list_versions("greet") == [
            SkillManifest(id="greet", name="Greet", version="0.1.0"),
            SkillManifest(id="greet", name="Greet", version="0.2.0"),
        ]

        restored.remove("greet", "0.1.0")
        final = SkillRegistry(store)
        final.hydrate()
        assert [m.version for m in final.list_versions("greet")] == ["0.2.0"]

    def test_mcp_status_changes_persist(self, tmp_path: Path) -> None:
        from agent_core.domain.mcp import MCPServerStatus

        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        registry = MCPRegistry(store)
        registry.register(
            MCPServerDefinition(
                id="demo", name="Demo", transport=MCPTransport.STDIO, endpoint="python demo.py"
            )
        )
        registry.set_status("demo", MCPServerStatus.HEALTHY)

        restored = MCPRegistry(store)
        restored.hydrate()

        assert restored.get("demo").status is MCPServerStatus.HEALTHY


# -------------------------------------------------------------------- runtime


class TestRunPersistence:
    async def test_completed_run_roundtrip_with_output(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path}/agent.db"
        store = SqliteStore(url)
        agents = AgentRegistry(store)
        agents.register(make_agent())
        runtime = AgentRuntime(
            agents,
            ToolRegistry(store),
            SkillRegistry(store),
            tracer=PersistingTracer(InMemoryTracer(), store),
            store=store,
            builder=StubBuilder(FakeGraph()),
        )

        run = runtime.create_run("helper", "hi")
        finished = await runtime.execute_run(run)
        assert finished.status is RunStatus.COMPLETED
        store.close()

        # "Second process": fresh components over the same database file.
        store2 = SqliteStore(url)
        agents2 = AgentRegistry(store2)
        agents2.hydrate()
        tracer2 = PersistingTracer(InMemoryTracer(), store2)
        tracer2.restore()
        runtime2 = AgentRuntime(agents2, ToolRegistry(store2), SkillRegistry(store2), store=store2)
        runtime2.hydrate()

        restored_run = runtime2.get_run(run.id)
        assert restored_run.status is RunStatus.COMPLETED
        assert restored_run.usage is not None
        finished_events = [
            e for e in tracer2.get_events(run.id) if e.event_type is EventType.AGENT_FINISHED
        ]
        assert finished_events and finished_events[0].output == "echo: hi"
        store2.close()

    async def test_task_events_aggregate_across_follow_up_runs(
        self, tmp_path: Path
    ) -> None:
        """get_task_events() reconstructs a whole conversation's timeline from
        the SQLite mirror — even when the in-memory buffer has been dropped."""
        url = f"sqlite:///{tmp_path}/agent.db"
        store = SqliteStore(url)
        agents = AgentRegistry(store)
        agents.register(make_agent())
        runtime = AgentRuntime(
            agents,
            ToolRegistry(store),
            SkillRegistry(store),
            tracer=PersistingTracer(InMemoryTracer(), store),
            store=store,
            builder=StubBuilder(FakeGraph()),
        )

        first = runtime.create_run("helper", "hi")
        await runtime.execute_run(first)
        task_id = first.task_id
        follow = runtime.create_run(
            "helper", "again", task=runtime.get_task(task_id)
        )
        await runtime.execute_run(follow)
        assert follow.id != first.id
        assert follow.task_id == task_id
        store.close()

        # Fresh components over the same file: in-memory buffer gone, but the
        # persisted mirror still reconstructs both runs' events.
        store2 = SqliteStore(url)
        tracer2 = PersistingTracer(InMemoryTracer(), store2)
        tracer2.restore()
        events = tracer2.get_task_events(task_id)
        run_ids = {event.run_id for event in events}
        assert first.id in run_ids
        assert follow.id in run_ids
        assert {event.event_type for event in events} >= {
            EventType.RUN_STARTED,
            EventType.RUN_FINISHED,
        }
        store2.close()

    async def test_created_run_becomes_failed_after_restart(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path}/agent.db"
        store = SqliteStore(url)
        agents = AgentRegistry(store)
        agents.register(make_agent())
        runtime = AgentRuntime(agents, ToolRegistry(store), SkillRegistry(store), store=store)

        run = runtime.create_run("helper", "hi")
        assert run.status is RunStatus.CREATED
        runtime.cancel_run(run.id)  # cancel path persists too
        store.close()

        store2 = SqliteStore(url)
        runtime2 = AgentRuntime(
            AgentRegistry(store2), ToolRegistry(store2), SkillRegistry(store2), store=store2
        )
        runtime2.hydrate()

        restored = runtime2.get_run(run.id)
        assert restored.status is RunStatus.CANCELLED  # terminal states are kept as-is
        assert restored.finished_at is not None

    async def test_nonterminal_run_marked_failed_on_restore(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path}/agent.db"
        store = SqliteStore(url)
        agents = AgentRegistry(store)
        agents.register(make_agent())
        runtime = AgentRuntime(agents, ToolRegistry(store), SkillRegistry(store), store=store)
        runtime.create_run("helper", "hi")
        store.close()

        store2 = SqliteStore(url)
        runtime2 = AgentRuntime(
            AgentRegistry(store2), ToolRegistry(store2), SkillRegistry(store2), store=store2
        )
        runtime2.hydrate()

        (restored,) = runtime2.list_runs()
        assert restored.status is RunStatus.FAILED
        assert restored.error == "interrupted by process restart"
        # The override is persisted so later restarts are stable.
        assert store2.load_runs() and '"failed"' in store2.load_runs()[0]
        store2.close()


# ----------------------------------------------------------------- approvals


class TestApprovalPersistence:
    async def test_resolved_approval_kept_pending_one_rejected(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        manager = ApprovalManager(store)
        approved = manager.create(make_action("run-1"), reason="risky")
        manager.resolve(approved.id, ApprovalStatus.APPROVED, resolved_by="alice")
        pending = manager.create(make_action("run-2"), reason="risky")

        restored = ApprovalManager(store)
        restored.hydrate()

        assert restored.get(approved.id).status is ApprovalStatus.APPROVED
        assert restored.get(approved.id).resolved_by == "alice"
        assert restored.list_pending() == []
        rejected = restored.get(pending.id)
        assert rejected.status is ApprovalStatus.REJECTED
        assert rejected.resolved_by == "restart"
        assert rejected.resolved_at is not None


# ----------------------------------------------------------------- bootstrap


class TestBootstrapWiring:
    def test_without_database_url_service_is_pure_memory(self) -> None:
        service = default_service(Settings(_env_file=None))
        assert service.store is None

    async def test_restart_preserves_registries_runs_and_output(self, tmp_path: Path) -> None:
        settings = sqlite_settings(tmp_path / "agent.db")

        service = default_service(settings)
        service.runtime.agents.register(make_agent())
        # Swap in a stub graph so the run completes without a model provider.
        service.runtime.builder = StubBuilder(FakeGraph())
        conversation = await service.submit_run("helper", "hi", wait=True)
        run = service.runtime.task_active_run(conversation.id)
        assert run is not None
        run_id = run.id
        service.store.close()

        restored = default_service(settings)

        assert restored.store is not None
        assert restored.runtime.agents.get("helper").name == "Helper"
        # The conversation and its run both survived the restart.
        restored_task = restored.get_task(conversation.id)
        assert [turn.role for turn in restored_task.turns] == ["user", "assistant"]
        finished = restored.get_run(run_id)
        assert finished.status is RunStatus.COMPLETED
        assert restored.final_output(run_id) == "echo: hi"
        restored.store.close()
