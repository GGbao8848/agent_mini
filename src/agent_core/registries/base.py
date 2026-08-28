"""Shared in-memory registry primitives.

Registries are the application layer's source of truth for named artifacts
(agents, tools, skills, MCP servers). v1 keeps everything in process memory;
a persistent backend later only has to re-implement this contract.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from agent_core.errors.exceptions import RegistryError

V = TypeVar("V")


class BaseRegistry(Generic[V]):
    """Item store keyed by a key derived from the item itself.

    Subclasses declare :meth:`key_for`; duplicate registration and lookup
    misses both raise :class:`RegistryError` so misconfiguration surfaces
    immediately instead of silently overwriting.
    """

    kind: str = "item"

    def __init__(self) -> None:
        self._items: dict[str, V] = {}

    def key_for(self, item: V) -> str:
        """Return the registry key under which ``item`` is stored."""
        raise NotImplementedError

    def register(self, item: V) -> None:
        """Store ``item``; registering the same key twice is an error."""
        key = self.key_for(item)
        if key in self._items:
            raise RegistryError(kind=self.kind, key=key, detail="already registered")
        self._items[key] = item

    def get(self, key: str) -> V:
        """Return the item registered under ``key``."""
        try:
            return self._items[key]
        except KeyError:
            raise RegistryError(kind=self.kind, key=key, detail="not found") from None

    def list(self) -> list[V]:
        """Snapshot of all registered items in registration order."""
        return list(self._items.values())

    def remove(self, key: str) -> V:
        """Remove and return the item registered under ``key``."""
        try:
            return self._items.pop(key)
        except KeyError:
            raise RegistryError(kind=self.kind, key=key, detail="not found") from None

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)
