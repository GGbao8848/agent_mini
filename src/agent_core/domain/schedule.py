"""Schedule domain model: a recurring or one-time automation trigger.

A :class:`Schedule` is pure data describing *when* to run an agent task and
with what input. Executing a schedule creates a fresh conversation (Task) —
the same shape a manual conversation has — so the resulting task shows up in
the console and can be continued by hand.

Time fields are timezone-aware; the server's local timezone is the authority
(``ZoneInfo`` from :mod:`tzlocal`). Trigger shapes:

- ``one_time`` — run once at ``run_at`` (must be in the future to arm).
- ``cron`` — standard 5-field cron expression (minute hour dom month dow).
- ``interval`` — every ``interval_minutes`` minutes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from agent_core.errors.exceptions import ScheduleError

ScheduleType = Literal["one_time", "cron", "interval"]


def new_id() -> str:
    return uuid4().hex


def local_now() -> datetime:
    """Current time in the server's local timezone (the schedule authority)."""
    from tzlocal import get_localzone

    return datetime.now(get_localzone())


def validate_cron(expr: str) -> None:
    """Raise ScheduleError when ``expr`` is not a valid 5-field cron expression."""
    try:
        from apscheduler.triggers.cron import CronTrigger

        CronTrigger.from_crontab(expr)
    except ValueError as exc:
        raise ScheduleError(f"Invalid cron expression '{expr}': {exc}") from exc


class Schedule(BaseModel):
    """When and how an agent task should run, plus its execution bookkeeping."""

    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    task_input: str = Field(min_length=1)
    schedule_type: ScheduleType
    run_at: datetime | None = None
    cron_expr: str | None = None
    interval_minutes: int | None = Field(default=None, ge=1)
    enabled: bool = True
    created_at: datetime = Field(default_factory=local_now)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_task_id: str | None = None
    run_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schedule_type")
    @classmethod
    def _validate_trigger(cls, value: str) -> str:
        if value not in ("one_time", "cron", "interval"):
            raise ValueError(f"unknown schedule_type '{value}'")
        return value

    def validate_trigger(self) -> None:
        """Cross-field validation: the fields matching the type must be present."""
        if self.schedule_type == "one_time" and self.run_at is None:
            raise ScheduleError(
                f"Schedule '{self.id}' is one_time but has no run_at",
                details={"schedule_id": self.id},
            )
        if self.schedule_type == "cron":
            if not self.cron_expr:
                raise ScheduleError(
                    f"Schedule '{self.id}' is cron but has no cron_expr",
                    details={"schedule_id": self.id},
                )
            validate_cron(self.cron_expr)
        if self.schedule_type == "interval" and self.interval_minutes is None:
            raise ScheduleError(
                f"Schedule '{self.id}' is interval but has no interval_minutes",
                details={"schedule_id": self.id},
            )
        if self.enabled and self.schedule_type == "one_time" and self.run_at is not None:
            from tzlocal import get_localzone

            if self.run_at.astimezone(get_localzone()) < local_now():
                raise ScheduleError(
                    f"Schedule '{self.id}' run_at is in the past",
                    details={"schedule_id": self.id, "run_at": self.run_at.isoformat()},
                )

    def describe_trigger(self) -> str:
        """Human-readable trigger description for the console."""
        if self.schedule_type == "one_time":
            return self.run_at.strftime("%Y-%m-%d %H:%M") if self.run_at else "—"
        if self.schedule_type == "cron":
            return f"cron {self.cron_expr}"
        return f"每 {self.interval_minutes} 分钟" if self.interval_minutes else "—"
