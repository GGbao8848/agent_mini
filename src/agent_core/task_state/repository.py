"""Task State repository: write-through persistence for task states.

Task states ride the generic ``registry_items`` table (``kind="task_state"``,
key = task id) — they are one JSON document per conversation, exactly the shape
that table stores. No dedicated table is needed, and deleting a task can drop
its state with a single ``delete_item`` call.
"""

from __future__ import annotations

from agent_core.persistence.store import SqliteStore
from agent_core.task_state.domain import TaskState

KIND = "task_state"


class TaskStateRepository:
    """In-memory read side with optional write-through to the store."""

    def __init__(self, store: SqliteStore | None = None) -> None:
        self._store = store
        self._states: dict[str, TaskState] = {}

    def get(self, task_id: str) -> TaskState | None:
        return self._states.get(task_id)

    def save(self, state: TaskState) -> None:
        self._states[state.task_id] = state
        if self._store is not None:
            self._store.save_item(KIND, state.task_id, state.model_dump_json())

    def delete(self, task_id: str) -> None:
        self._states.pop(task_id, None)
        if self._store is not None:
            self._store.delete_item(KIND, task_id)

    def hydrate(self) -> int:
        """Load states persisted by a previous process; returns how many."""
        if self._store is None:
            return 0
        loaded = 0
        for key, data in self._store.load_items(KIND):
            self._states[key] = TaskState.model_validate_json(data)
            loaded += 1
        return loaded
