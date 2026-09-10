"""Memory repository: registry-backed storage + a derived embedding index.

Memory entries ride :class:`~agent_core.registries.base.BaseRegistry` (in-memory
reads, write-through persistence, ``hydrate`` on restart). Embeddings live in a
separate SQLite table because a 4096-dim float32 vector would bloat every
registry JSON row; they are a *derived* index — rebuildable from the text — so
losing them is a recall downgrade, never data loss.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_core.domain.memory import Memory
from agent_core.persistence.store import SqliteStore
from agent_core.registries.base import BaseRegistry


class MemoryRepository(BaseRegistry[Memory]):
    """Stores memory entries keyed by their id, plus an embedding sidecar."""

    kind = "memory"
    model_cls = Memory

    def __init__(self, store: SqliteStore | None = None) -> None:
        super().__init__(store)
        self._vectors: dict[str, list[float]] = {}

    def key_for(self, item: Memory) -> str:
        return item.id

    # ------------------------------------------------------------ embeddings

    def store_vector(self, memory_id: str, vector: Sequence[float]) -> None:
        """Cache and persist ``memory_id``'s embedding."""
        values = [float(x) for x in vector]
        self._vectors[memory_id] = values
        if self._store is not None:
            import struct

            blob = struct.pack(f"<{len(values)}f", *values)
            self._store.save_embedding(memory_id, blob, len(values))

    def vector(self, memory_id: str) -> list[float] | None:
        return self._vectors.get(memory_id)

    def vectors(self) -> dict[str, list[float]]:
        """All cached embeddings keyed by memory id."""
        return self._vectors

    def drop_vector(self, memory_id: str) -> None:
        self._vectors.pop(memory_id, None)
        if self._store is not None:
            self._store.delete_embedding(memory_id)

    def hydrate_vectors(self) -> int:
        """Load persisted embeddings into the cache; returns how many loaded."""
        if self._store is None:
            return 0
        import struct

        loaded = 0
        for memory_id, dim, blob in self._store.load_embeddings():
            self._vectors[memory_id] = list(struct.unpack(f"<{dim}f", blob))
            loaded += 1
        return loaded

    def remove(self, key: str) -> Memory:
        item = super().remove(key)
        self.drop_vector(key)
        return item
