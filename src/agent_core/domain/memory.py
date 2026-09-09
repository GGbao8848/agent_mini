"""Long-term memory: durable facts that outlive a single conversation.

Deliberately minimal — a flat list of short text entries managed by the
human (memory panel) and written by the agent through ``save_memory``. The
whole list is injected into every run's system prompt (bounded), which is
the simplest mechanism that actually closes the loop: the agent sees and
uses its memories without any retrieval machinery. If this ever grows past
a few dozen entries, add retrieval — not before.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from agent_core.domain.task import new_id

MAX_MEMORIES = 100
MAX_CONTENT_CHARS = 2000


class Memory(BaseModel):
    """One durable memory entry."""

    id: str = Field(default_factory=lambda: new_id())
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    source: str = "manual"
    """``manual`` (memory panel) or ``agent`` (save_memory tool)."""
    task_id: str | None = None
    """Conversation that produced it, when the agent wrote it."""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def memories_prompt(memories: list[Memory]) -> str:
    """Render memories for the system prompt, newest first, bounded."""
    if not memories:
        return ""
    ordered = sorted(memories, key=lambda m: m.updated_at, reverse=True)[:MAX_MEMORIES]
    lines = "\n".join(f"- {m.content}" for m in ordered)
    return (
        "\n\n# Long-term memories\n"
        "Durable facts about the user and their projects, kept across "
        "conversations. Treat them as standing context; contradict them only "
        "when the user explicitly says something changed.\n"
        f"{lines}\n"
    )
