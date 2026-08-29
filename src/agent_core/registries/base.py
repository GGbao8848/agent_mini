"""Shared registry primitives: in-memory store with optional write-through.

Registries are the application layer's source of truth for named artifacts
(agents, tools, skills, MCP servers). Reads always come from the in-memory
dict; when a :class:`~agent_core.persistence.store.SqliteStore` is injected,
every mutation is additionally mirrored so ``hydrate`` can restore the
registry after a process restart.
"""

from __future__ import annotations

from typing import Generic, TypeVar, cast

from pydantic import BaseModel

from agent_core.errors.exceptions import RegistryError
from agent_core.persistence.store import SqliteStore

V = TypeVar("V")


class BaseRegistry(Generic[V]):
    """Item store keyed by a key derived from the item itself.

    Subclasses declare :meth:`key_for` and (for persistence) ``model_cls``;
    duplicate registration and lookup misses both raise :class:`RegistryError`
    so misconfiguration surfaces immediately instead of silently overwriting.
    """

    kind: str = "item"
    model_cls: type[BaseModel] | None = None

    def __init__(self, store: SqliteStore | None = None) -> None:
        self._items: dict[str, V] = {}
        self._store = store

    def key_for(self, item: V) -> str:
        """Return the registry key under which ``item`` is stored."""
        raise NotImplementedError

    def register(self, item: V) -> None:
        """Store ``item``; registering the same key twice is an error."""
        key = self.key_for(item)
        if key in self._items:
            raise RegistryError(kind=self.kind, key=key, detail="already registered")
        self._items[key] = item
        if self._store is not None:
            self._store.save_item(self.kind, key, self.serialize(item))

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
            item = self._items.pop(key)
        except KeyError:
            raise RegistryError(kind=self.kind, key=key, detail="not found") from None
        if self._store is not None:
            self._store.delete_item(self.kind, key)
        return item

    def hydrate(self) -> None:
        """Load items persisted by a previous process (no-op without a store)."""
        if self._store is None:
            return
        for key, data in self._store.load_items(self.kind):
            if key not in self._items:
                self._items[key] = self.deserialize(data)

    def serialize(self, item: V) -> str:
        """JSON payload for the store; works for any pydantic registry value."""
        if isinstance(item, BaseModel):
            return item.model_dump_json()
        raise TypeError(f"{type(item).__name__} cannot be persisted")

    def deserialize(self, data: str) -> V:
        if self.model_cls is None:
            raise TypeError(
                f"{type(self).__name__} declares no model_cls and cannot be restored"
            )
        return cast(V, self.model_cls.model_validate_json(data))

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)
