"""Task and Run domain models.

A :class:`Task` is what the user asked for. A :class:`Run` is one execution of
a task by one agent (sub-agent runs point at their parent via ``parent_run_id``).
Run lifecycle transitions are validated here so the runtime cannot drive a Run
into an illegal state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from agent_core.domain.metrics import RunUsage
from agent_core.errors.exceptions import StateError


def new_id() -> str:
    return uuid4().hex


class RunStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    NEEDS_INPUT = "needs_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


_TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT}
)

_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.PLANNING, RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.PLANNING: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_APPROVAL,
            RunStatus.NEEDS_INPUT,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMEOUT,
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.TIMEOUT}
    ),
    # Task-level human help (request_help / loop guard / verification escalation);
    # the human's answer is fed back to the agent, so it resumes like a pause.
    RunStatus.NEEDS_INPUT: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.TIMEOUT}
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.TIMEOUT: frozenset(),
}


class Task(BaseModel):
    """The user's request, independent of how many times it is executed."""

    id: str = Field(default_factory=new_id)
    input: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Run(BaseModel):
    """One execution of a task by an agent."""

    id: str = Field(default_factory=new_id)
    task_id: str
    agent_id: str
    parent_run_id: str | None = None
    status: RunStatus = RunStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    usage: RunUsage | None = None

    def transition_to(self, new_status: RunStatus) -> None:
        """Move the run to ``new_status``, enforcing the lifecycle state machine."""
        allowed = _ALLOWED_TRANSITIONS[self.status]
        if new_status not in allowed:
            raise StateError(
                f"Illegal run transition {self.status.value} -> {new_status.value}",
                details={"run_id": self.id, "from": self.status.value, "to": new_status.value},
            )
        self.status = new_status
        if new_status.is_terminal:
            self.finished_at = datetime.now(UTC)
