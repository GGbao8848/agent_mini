"""Schedule tests: domain validation, ScheduleManager firing, and the API.

The manager's runner is injected, so these tests exercise arming/firing/
bookkeeping without a model. The API test drives a real service with a stub
graph to prove "run now" creates a real conversation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage
from tzlocal import get_localzone

from agent_core.api.app import create_app
from agent_core.application.scheduler import ScheduleManager, build_trigger
from agent_core.application.service import AgentCoreService
from agent_core.config.settings import Settings
from agent_core.domain.agent import AgentSpec
from agent_core.domain.schedule import Schedule, local_now
from agent_core.errors.exceptions import ScheduleError
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStreamBroker
from agent_core.observability.trace import InMemoryTracer
from agent_core.persistence.store import SqliteStore
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime


class FakeGraph:
    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        return {"messages": [AIMessage(content="done")]}


class StubBuilder:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def build(self, spec: Any) -> Any:
        return self._graph


def make_schedule(**overrides: Any) -> Schedule:
    values: dict[str, Any] = {
        "name": "morning",
        "agent_id": "helper",
        "task_input": "summarize",
        "schedule_type": "interval",
        "interval_minutes": 5,
    }
    values.update(overrides)
    return Schedule(**values)


class TestScheduleValidation:
    def test_valid_interval(self) -> None:
        schedule = make_schedule()
        schedule.validate_trigger()  # does not raise

    def test_valid_cron(self) -> None:
        schedule = make_schedule(schedule_type="cron", cron_expr="0 9 * * 1")
        schedule.validate_trigger()

    def test_invalid_cron_raises(self) -> None:
        schedule = make_schedule(schedule_type="cron", cron_expr="99 25 * *")
        with pytest.raises(ScheduleError):
            schedule.validate_trigger()

    def test_interval_requires_minutes(self) -> None:
        schedule = make_schedule(interval_minutes=None)
        with pytest.raises(ScheduleError):
            schedule.validate_trigger()

    def test_one_time_past_run_at_rejected_when_enabled(self) -> None:
        past = local_now() - timedelta(hours=1)
        schedule = make_schedule(
            schedule_type="one_time", run_at=past, interval_minutes=None
        )
        with pytest.raises(ScheduleError):
            schedule.validate_trigger()

    def test_one_time_future_run_at_accepted(self) -> None:
        future = local_now() + timedelta(hours=1)
        schedule = make_schedule(
            schedule_type="one_time", run_at=future, interval_minutes=None
        )
        schedule.validate_trigger()


class TestScheduleManager:
    async def test_interval_fire_bookkeeping(self) -> None:
        calls: list[tuple[str, str]] = []
        manager = ScheduleManager(runner=_fake_runner(calls))
        schedule = make_schedule()
        manager.add(schedule)

        await manager.run_schedule(manager.get(schedule.id))

        assert calls == [("helper", "summarize")]
        updated = manager.get(schedule.id)
        assert updated.run_count == 1
        assert updated.last_run_at is not None
        assert updated.last_task_id == "task-1"

    async def test_one_time_disables_after_fire(self) -> None:
        calls: list[tuple[str, str]] = []
        manager = ScheduleManager(runner=_fake_runner(calls))
        future = local_now() + timedelta(hours=1)
        schedule = make_schedule(
            schedule_type="one_time", run_at=future, interval_minutes=None
        )
        manager.add(schedule)

        # Fire through the job entry point (simulates the scheduler calling it).
        await manager._fire(schedule.id)  # noqa: SLF001

        assert calls == [("helper", "summarize")]
        updated = manager.get(schedule.id)
        assert updated.enabled is False
        assert updated.next_run_at is None

    async def test_restore_rearms_enabled_schedules(self, tmp_path: Path) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        calls: list[tuple[str, str]] = []
        manager = ScheduleManager(runner=_fake_runner(calls), store=store)
        manager.add(make_schedule(name="keep"))
        manager.add(make_schedule(name="off", enabled=False))
        store.close()

        # "Second process": fresh manager over the same database.
        store2 = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        manager2 = ScheduleManager(runner=_fake_runner(calls), store=store2)
        manager2.restore()

        restored = manager2.list()
        assert {s.name for s in restored} == {"keep", "off"}
        assert next(s for s in restored if s.name == "keep").enabled is True
        assert next(s for s in restored if s.name == "off").enabled is False
        # The enabled one got a job; the disabled one did not.
        assert manager2._scheduler.get_job(f"schedule:{next(s for s in restored if s.name == 'keep').id}") is not None  # noqa: SLF001
        assert manager2._scheduler.get_job(f"schedule:{next(s for s in restored if s.name == 'off').id}") is None  # noqa: SLF001
        manager2.stop()
        store2.close()

    async def test_update_rearms(self) -> None:
        calls: list[tuple[str, str]] = []
        manager = ScheduleManager(runner=_fake_runner(calls))
        schedule = make_schedule(name="first", interval_minutes=5)
        manager.add(schedule)

        changed = schedule.model_copy(update={"interval_minutes": 10})
        manager.update(changed)

        assert manager.get(schedule.id).interval_minutes == 10
        assert manager.get(schedule.id).run_count == 0  # bookkeeping preserved


def _fake_runner(calls: list[tuple[str, str]]) -> Any:
    async def runner(agent_id: str, task_input: str) -> Any:
        calls.append((agent_id, task_input))
        return type("T", (), {"id": "task-1"})()

    return runner


# ------------------------------------------------------------------- api


def make_api_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentCoreService:
    from agent_core.config.settings import get_settings

    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper"))
    runtime = AgentRuntime(
        agents,
        ToolRegistry(),
        SkillRegistry(),
        tracer=InMemoryTracer(),
        builder=StubBuilder(FakeGraph()),
    )
    mcp_registry = MCPRegistry()
    mcp = MCPManager(mcp_registry, ToolRegistry(), credentials=None)
    broker = EventStreamBroker(runtime.bus)
    return AgentCoreService(runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker)


class TestScheduleApi:
    @pytest.fixture()
    async def client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> httpx.AsyncClient:
        service = make_api_service(tmp_path, monkeypatch)
        from agent_core.application.scheduler import ScheduleManager

        service.schedules = ScheduleManager(runner=service.submit_run)
        app = create_app(service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    async def test_create_interval_schedule(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/schedules",
            json={
                "name": "hourly",
                "agent_id": "helper",
                "task_input": "check logs",
                "schedule_type": "interval",
                "interval_minutes": 60,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "hourly"
        assert body["schedule_type"] == "interval"
        assert body["trigger_text"] == "每 60 分钟"
        assert body["run_count"] == 0

    async def test_create_invalid_cron_maps_to_422(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/schedules",
            json={
                "name": "bad",
                "agent_id": "helper",
                "task_input": "x",
                "schedule_type": "cron",
                "cron_expr": "99 99 * *",
            },
        )
        assert response.status_code == 422

    async def test_run_now_creates_task(self, client: httpx.AsyncClient) -> None:
        created = (
            await client.post(
                "/v1/schedules",
                json={
                    "name": "once",
                    "agent_id": "helper",
                    "task_input": "echo hi",
                    "schedule_type": "one_time",
                    "run_at": (local_now() + timedelta(hours=2)).isoformat(),
                },
            )
        ).json()

        run = await client.post(f"/v1/schedules/{created['id']}/run")
        assert run.status_code == 200, run.text
        task_id = run.json()["task_id"]
        # The task exists and is the conversation the schedule created.
        task = (await client.get(f"/v1/tasks/{task_id}")).json()
        assert task["id"] == task_id
        assert task["agent_id"] == "helper"

        # Bookkeeping recorded the manual run but the schedule stays enabled.
        updated = (await client.get(f"/v1/schedules/{created['id']}")).json()
        assert updated["run_count"] == 1
        assert updated["last_task_id"] == task_id
        assert updated["enabled"] is True

    async def test_delete_schedule(self, client: httpx.AsyncClient) -> None:
        created = (
            await client.post(
                "/v1/schedules",
                json={
                    "name": "tmp",
                    "agent_id": "helper",
                    "task_input": "x",
                    "schedule_type": "interval",
                    "interval_minutes": 5,
                },
            )
        ).json()

        deleted = await client.delete(f"/v1/schedules/{created['id']}")
        assert deleted.status_code == 204
        assert (await client.get(f"/v1/schedules/{created['id']}")).status_code == 404
