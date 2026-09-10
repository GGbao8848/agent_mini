"""Memory repository: registry-backed storage for :class:`Memory` entries.

Reuses :class:`~agent_core.registries.base.BaseRegistry` for in-memory reads
with write-through persistence, so memories survive a restart via ``hydrate``
without a second storage mechanism.
"""

from __future__ import annotations

from agent_core.domain.memory import Memory
from agent_core.registries.base import BaseRegistry


class MemoryRepository(BaseRegistry[Memory]):
    """Stores memory entries keyed by their id."""

    kind = "memory"
    model_cls = Memory

    def key_for(self, item: Memory) -> str:
        return item.id
