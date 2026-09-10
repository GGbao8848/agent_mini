"""Task State domain model (R21).

A :class:`TaskState` answers the question a long conversation otherwise loses
the answer to: *where is this task right now?* It is deliberately separate from
the conversation (``Task``/checkpoint, i.e. "what was said") because a growing
message history is a poor progress record — the model re-derives it every turn
and drifts.

The state is a **projection of two sources**, never of LLM recall:

- *intent* — the goal and the step plan, declared explicitly by the agent
  through the ``update_plan`` tool (``steps``);
- *evidence* — status, failures, artifacts and the recorded tool activity,
  derived deterministically from the runtime trace event stream (``activity``).

At read time the model is handed a compact block; it never recomputes progress
from dozens of turns of chat.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class StepStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStep(BaseModel):
    """One planned unit of work (the agent's declared plan)."""

    id: str = Field(min_length=1)
    description: str
    status: StepStatus = StepStatus.PENDING
    tool: str | None = None
    detail: str = ""
    updated_at: datetime = Field(default_factory=_now)


class ActivityRef(BaseModel):
    """Evidence: a tool actually ran, merged by name with a call count."""

    tool: str
    count: int = 1
    failed: bool = False
    detail: str = ""
    last_at: datetime = Field(default_factory=_now)


class ArtifactRef(BaseModel):
    """A produced file, mirrored from the run's artifact manifest."""

    path: str
    name: str = ""
    run_id: str | None = None


class TaskState(BaseModel):
    """The explicit, persisted progress of one conversation."""

    task_id: str
    goal: str = ""
    status: str = "created"
    """Mirrors the latest root run's status value (running/completed/...)."""

    steps: list[TaskStep] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    activity: list[ActivityRef] = Field(default_factory=list)
    current_step_id: str | None = None
    next_action: str | None = None
    run_count: int = 0
    plan_revision: int = 0
    updated_at: datetime = Field(default_factory=_now)

    # ------------------------------------------------------------- accessors

    @property
    def current_step(self) -> TaskStep | None:
        if self.current_step_id is None:
            return None
        return next((s for s in self.steps if s.id == self.current_step_id), None)

    def completed(self) -> list[TaskStep]:
        return [s for s in self.steps if s.status is StepStatus.DONE]

    def outstanding(self) -> list[TaskStep]:
        return [
            s for s in self.steps if s.status in (StepStatus.PENDING, StepStatus.ACTIVE)
        ]

    def failed_steps(self) -> list[TaskStep]:
        return [s for s in self.steps if s.status is StepStatus.FAILED]

    @property
    def has_content(self) -> bool:
        """True when there is anything worth showing the model or the console."""
        return bool(self.steps or self.failures or self.artifacts or self.run_count > 1)
