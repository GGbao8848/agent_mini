"""Persistence: optional SQLite write-through for registries, runs, approvals, events.

Enabled by setting ``AGENT_CORE_DATABASE_URL`` (``sqlite:///./agent_core.db``).
Without it every component behaves exactly as the pure in-memory v1.
"""

from agent_core.persistence.store import SqliteStore, open_store
from agent_core.persistence.tracer import PersistingTracer

__all__ = ["PersistingTracer", "SqliteStore", "open_store"]
