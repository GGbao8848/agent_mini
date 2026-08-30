"""ScheduleManager: own the lifecycle of persistent schedules via APScheduler.

Wraps an ``AsyncIOScheduler`` (in-process, no external service). Every
schedule gets a job keyed ``schedule:{id}`` whose trigger is derived from the
schedule's type:

- one_time → ``date(run_date=run_at)``
- cron → ``CronTrigger.from_crontab(expr)`` (5-field)
- interval → ``interval(minutes=N)``

The manager owns no knowledge of the runtime: it calls the injected
``runner(agent_id, task_input)`` when a job fires. In the app this is wired to
``service.submit_run``, which creates a fresh conversation (Task) and starts
it — the console picks it up through the normal task list + SSE. A one-time
schedule disables itself after firing; every firing records ``last_run_at`` /
``run_count`` / ``last_task_id`` back to the store.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from tzlocal import get_localzone

from agent_core.domain.schedule import Schedule, local_now
from agent_core.errors.exceptions import RegistryError, ScheduleError
from agent_core.persistence.store import SqliteStore

Runner = Callable[[str, str], Awaitable[Any]]
"""Signature of a schedule execution: (agent_id, task_input) → new task."""


def build_trigger(schedule: Schedule) -> Any:
    """Return the APScheduler trigger for ``schedule`` (must be validated)."""
    if schedule.schedule_type == "one_time":
        if schedule.run_at is None:
            raise ScheduleError(f"Schedule '{schedule.id}' is one_time but has no run_at")
        return DateTrigger(run_date=schedule.run_at.astimezone(get_localzone()))
    if schedule.schedule_type == "cron":
        if not schedule.cron_expr:
            raise ScheduleError(f"Schedule '{schedule.id}' is cron but has no cron_expr")
        return CronTrigger.from_crontab(schedule.cron_expr, timezone=get_localzone())
    if schedule.interval_minutes is None:
        raise ScheduleError(f"Schedule '{schedule.id}' is interval but has no interval_minutes")
    return IntervalTrigger(minutes=schedule.interval_minutes)


class ScheduleManager:
    """Arms, fires and tracks schedules; pairs with the SqliteStore mirror."""

    def __init__(
        self,
        runner: Runner,
        store: SqliteStore | None = None,
    ) -> None:
        self._runner = runner
        self._store = store
        self._scheduler = AsyncIOScheduler(timezone=get_localzone())
        self._schedules: dict[str, Schedule] = {}

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start the scheduler (called from the app lifespan startup)."""
        if not self._scheduler.running:
            self._scheduler.start()

    def stop(self) -> None:
        """Shut the scheduler down (app lifespan shutdown)."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ------------------------------------------------------------ queries

    def get(self, schedule_id: str) -> Schedule:
        try:
            return self._schedules[schedule_id]
        except KeyError:
            raise RegistryError(kind="schedule", key=schedule_id, detail="not found") from None

    def list(self) -> list[Schedule]:
        return list(self._schedules.values())

    # ------------------------------------------------------------- mutate

    def add(self, schedule: Schedule) -> Schedule:
        """Register (or replace) a schedule and arm its job."""
        schedule.validate_trigger()
        self._schedules[schedule.id] = schedule
        self._persist(schedule)
        if schedule.enabled:
            self._arm(schedule)
        else:
            self._disarm(schedule.id)
        return schedule

    def update(self, schedule: Schedule) -> Schedule:
        """Replace an existing schedule (re-arming when enabled)."""
        existing = self.get(schedule.id)
        schedule.created_at = existing.created_at
        schedule.last_run_at = existing.last_run_at
        schedule.last_task_id = existing.last_task_id
        schedule.run_count = existing.run_count
        schedule.validate_trigger()
        self._schedules[schedule.id] = schedule
        self._persist(schedule)
        if schedule.enabled:
            self._arm(schedule)
        else:
            self._disarm(schedule.id)
        return schedule

    def remove(self, schedule_id: str) -> None:
        self.get(schedule_id)  # 404 on unknown ids
        self._disarm(schedule_id)
        self._schedules.pop(schedule_id, None)
        if self._store is not None:
            self._store.delete_schedule(schedule_id)

    def restore(self) -> None:
        """Re-arm persisted schedules after a restart (enabled ones only)."""
        if self._store is None:
            return
        for data in self._store.load_schedules():
            schedule = Schedule.model_validate_json(data)
            if schedule.enabled:
                try:
                    schedule.validate_trigger()
                except ScheduleError:
                    # A persisted schedule with a now-invalid trigger (e.g. a
                    # one-time run_at that passed while the process was down)
                    # cannot be re-armed; disable it instead of crashing boot.
                    schedule.enabled = False
                    self._persist(schedule)
            self._schedules[schedule.id] = schedule
            if schedule.enabled:
                self._arm(schedule)

    # --------------------------------------------------------------- firing

    async def run_schedule(self, schedule: Schedule) -> Any:
        """Execute one schedule firing; returns the created task (if any).

        Shared by the scheduler job and the manual "run now" action — the
        manual path does not re-arm or disable a one-time schedule.
        """
        result = await self._runner(schedule.agent_id, schedule.task_input)
        schedule.last_run_at = local_now()
        schedule.run_count += 1
        task_id = getattr(result, "id", None)
        if task_id is not None:
            schedule.last_task_id = task_id
        self._persist(schedule)
        return result

    async def _fire(self, schedule_id: str) -> None:
        """Job entry point: fire, then handle one-time self-disable."""
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            return
        await self.run_schedule(schedule)
        if schedule.schedule_type == "one_time":
            schedule.enabled = False
            schedule.next_run_at = None
            self._disarm(schedule_id)
            self._persist(schedule)

    # -------------------------------------------------------------- internal

    def _arm(self, schedule: Schedule) -> None:
        self._disarm(schedule.id)
        job = self._scheduler.add_job(
            self._fire,
            trigger=build_trigger(schedule),
            id=f"schedule:{schedule.id}",
            args=[schedule.id],
            replace_existing=True,
        )
        # next_run_time is only computed once the scheduler is running (jobs
        # added before start() don't have it yet).
        schedule.next_run_at = getattr(job, "next_run_time", None)
        self._persist(schedule)

    def _disarm(self, schedule_id: str) -> None:
        job_id = f"schedule:{schedule_id}"
        if self._scheduler.get_job(job_id) is not None:
            self._scheduler.remove_job(job_id)

    def _persist(self, schedule: Schedule) -> None:
        if self._store is not None:
            self._store.save_schedule(schedule.id, schedule.model_dump_json())
