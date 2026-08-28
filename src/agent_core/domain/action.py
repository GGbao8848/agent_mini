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


class ApprovalRequest(BaseModel):
    """A human decision request created by the Action Gate."""

    id: str = Field(default_factory=new_id)
    run_id: str
    agent_id: str
    action_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel
    reason: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    edited_arguments: dict[str, Any] | None = None
