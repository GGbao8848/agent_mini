"""Checkpointer factory: LangGraph conversation-state persistence.

A run's conversation (the full message history) lives in a LangGraph
checkpoint keyed by ``thread_id``. Production uses ``AsyncSqliteSaver`` over
the same database file as the Phase 16 store (its own tables, own
connection, WAL-compatible) — the executor is async end-to-end and the sync
``SqliteSaver`` raises NotImplementedError on async methods. Without a
database the in-memory saver keeps multi-turn working inside one process.

The returned saver's ``setup()`` (which also opens the aiosqlite connection)
is idempotent and is awaited lazily by the runtime before the first run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from agent_core.errors.exceptions import ConfigurationError


def build_checkpointer(database_url: str | None) -> BaseCheckpointSaver[Any]:
    """Checkpointer for ``database_url``; in-memory when persistence is off."""
    if database_url is None:
        return MemorySaver()
    if not database_url.startswith("sqlite:///"):
        raise ConfigurationError(
            f"Checkpointing supports only sqlite databases, got '{database_url}'",
            details={"database_url": database_url},
        )
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    raw = database_url.removeprefix("sqlite:///")
    if raw == ":memory:":
        return AsyncSqliteSaver(aiosqlite.connect(":memory:"))
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver(aiosqlite.connect(str(path)))
