"""Action and ApprovalRequest domain models.

An :class:`Action` is a tool invocation requested by an agent. It is the unit
that Permission evaluation, risk evaluation, and the Action Gate operate on.
An :class:`ApprovalRequest` is created when the gate decides a human must
decide before execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.task import new_id


class RiskLevel(StrEnum):
    """Risk classification of an action; drives the default Action Gate policy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Action(BaseModel):
    """A requested tool call, gated before execution."""

    id: str = Field(default_factory=new_id)
    run_id: str
    agent_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    status: ActionStatus = ActionStatus.PENDING
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    result: Any | None = None
    error: str | None = None


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ApprovalKind(StrEnum):
    """What kind of human decision a request represents.

    ``tool_action`` is the classic Action Gate approval for a risky tool call;
    ``task_help`` is a task-level question raised by the autonomy layer (the
    agent's own ``request_help`` tool, the loop guard, or verification
    escalation) — the human's ``resolved_note`` is fed back to the agent as
    guidance rather than gating a specific execution.
    """

    TOOL_ACTION = "tool_action"
    TASK_HELP = "task_help"


class ApprovalRequest(BaseModel):
    """A human decision request created by the Action Gate or autonomy layer."""

    id: str = Field(default_factory=new_id)
    run_id: str
    agent_id: str
    kind: ApprovalKind = ApprovalKind.TOOL_ACTION
    action_id: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    question: str = ""
    reason: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    edited_arguments: dict[str, Any] | None = None
    resolved_note: str | None = None
