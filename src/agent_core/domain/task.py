"""Task and Run domain models.

A :class:`Task` is a conversation: the user's request and every turn that
follows it. A :class:`Run` is one execution of that conversation — a root run
is created for the first turn, and follow-up turns create further root runs
that reuse the conversation's ``thread_id`` so the agent sees the whole
history. Nested runs (sub-agents, verification) point at their parent via
``parent_run_id`` and carry no thread of their own.

Run lifecycle transitions are validated here so the runtime cannot drive a Run
into an illegal state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from agent_core.domain.metrics import RunUsage
from agent_core.errors.exceptions import StateError


def new_id() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


def make_title(text: str, max_chars: int = 24) -> str:
    """First line of a message, trimmed to a sidebar-friendly title."""
    first_line = text.strip().splitlines()[0] if text.strip() else text.strip()
    return first_line if len(first_line) <= max_chars else f"{first_line[: max_chars - 1]}…"


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


class Turn(BaseModel):
    """One message in a conversation: a user request or the agent's answer."""

    id: str = Field(default_factory=new_id)
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    """A conversation: the user's request plus every follow-up turn.

    One Task owns one ``thread_id``; every turn of the conversation executes
    as a run on that thread, so the agent always sees the full history.
    """

    id: str = Field(default_factory=new_id)
    agent_id: str
    title: str
    input: str = ""
    thread_id: str | None = None
    turns: list[Turn] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_user_turn(self, content: str, *, run_id: str | None = None) -> Turn:
        turn = Turn(role="user", content=content)
        if run_id is not None:
            turn.metadata["run_id"] = run_id
        self.turns.append(turn)
        return turn

    def add_assistant_turn(self, content: str, *, run_id: str | None = None) -> Turn:
        turn = Turn(role="assistant", content=content)
        if run_id is not None:
            turn.metadata["run_id"] = run_id
        self.turns.append(turn)
        return turn


class Run(BaseModel):
    """One execution of a conversation by an agent.

    Root runs own the conversation's ``thread_id`` (follow-up turns reuse it so
    the agent sees the whole history). Nested runs (sub-agents, verification)
    have no thread of their own.
    """

    id: str = Field(default_factory=new_id)
    task_id: str
    agent_id: str
    parent_run_id: str | None = None
    thread_id: str | None = None
    status: RunStatus = RunStatus.CREATED
    created_at: datetime = Field(default_factory=_now)
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
            self.finished_at = _now()
