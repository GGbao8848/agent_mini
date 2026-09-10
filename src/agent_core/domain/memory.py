"""Long-term memory domain model.

A :class:`Memory` is a durable fact that outlives one conversation. Unlike the
first attempt (a flat list injected wholesale into every prompt, later rolled
back), entries now carry an explicit ``scope``/``type`` and are *retrieved*
per query rather than dumped in full — see :mod:`agent_core.memory`.

Lifecycle fields make governance possible: a newer fact can ``supersede`` an
older one, an entry can be soft-deactivated (``active=False``) or given an
``expires_at``. Retrieval only ever considers active, non-superseded entries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from agent_core.domain.task import new_id

MAX_CONTENT_CHARS = 2000


class MemoryScope(StrEnum):
    """Who a memory is about — keeps scopes from bleeding into each other."""

    USER = "user"
    PROJECT = "project"
    AGENT = "agent"
    ORG = "org"


class MemoryType(StrEnum):
    """What kind of durable knowledge an entry holds."""

    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    LESSON = "lesson"
    CONSTRAINT = "constraint"
    ERROR_FIX = "error_fix"


class Memory(BaseModel):
    """One durable memory entry."""

    id: str = Field(default_factory=lambda: new_id())
    scope: MemoryScope = MemoryScope.USER
    scope_id: str | None = None
    """The concrete owner within ``scope``: the project id for PROJECT, the
    agent id for AGENT, the user id for USER, ``None`` for ORG (org-wide).

    Without this a PROJECT memory belonged to *no* project, so retrieval could
    not keep project A's facts out of project B's conversation (R23)."""
    type: MemoryType = MemoryType.FACT
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    source: str = "manual"
    """``manual`` (console), ``agent`` (remember tool) or ``lesson`` (R11 loop)."""
    task_id: str | None = None
    """Conversation that produced it, when not manually entered."""
    source_run_id: str | None = None
    """The run that wrote it — lets "why does the agent remember this?" be
    traced back to a concrete execution, not just a conversation."""
    created_by: str = "human"
    """Who authored it: ``human`` (console) or the writing agent's id."""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    importance: int = Field(default=0, ge=0, le=10)
    active: bool = True
    superseded_by: str | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def belongs_to(self, scope: MemoryScope, scope_id: str | None) -> bool:
        """True when this entry lives in exactly ``(scope, scope_id)``."""
        return self.scope is scope and self.scope_id == scope_id

    def is_live(self, *, now: datetime | None = None) -> bool:
        """True when the entry should participate in retrieval."""
        moment = now or datetime.now(UTC)
        if not self.active or self.superseded_by is not None:
            return False
        if self.expires_at is not None and self.expires_at <= moment:
            return False
        return True
