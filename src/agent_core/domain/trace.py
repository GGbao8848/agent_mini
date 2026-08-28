"""Trace / Event domain models.

Every run produces a stream of :class:`TraceEvent` objects. The runtime only
calls ``tracer.emit(event)``; where events go (memory, log, SSE stream) is an
infrastructure concern.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent_core.domain.task import new_id


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    AGENT_STARTED = "agent_started"
    AGENT_THINKING = "agent_thinking"
    AGENT_FINISHED = "agent_finished"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_FINISHED = "subagent_finished"
    SKILL_LOADED = "skill_loaded"
    TOOL_REQUESTED = "tool_requested"
    TOOL_STARTED = "tool_started"
    TOOL_EXECUTED = "tool_executed"
    TOOL_FAILED = "tool_failed"
    ACTION_PENDING = "action_pending"
    ACTION_APPROVED = "action_approved"
    ACTION_REJECTED = "action_rejected"
    RUN_STATUS_CHANGED = "run_status_changed"


class TraceEvent(BaseModel):
    """One observable thing that happened during a run."""

    id: str = Field(default_factory=new_id)
    event_type: EventType
    run_id: str
    parent_run_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float | None = None
    input: Any | None = None
    output: Any | None = None
    tool: str | None = None
    status: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
