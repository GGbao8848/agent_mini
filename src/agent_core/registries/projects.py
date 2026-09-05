"""Project registry: host directories conversations can be bound to."""

from __future__ import annotations

from agent_core.domain.project import Project
from agent_core.persistence.store import SqliteStore
from agent_core.registries.base import BaseRegistry


class ProjectRegistry(BaseRegistry[Project]):
    """Projects keyed by id; persisted write-through like the other registries."""

    kind = "project"
    model_cls = Project

    def __init__(self, store: SqliteStore | None = None) -> None:
        super().__init__(store)

    def key_for(self, item: Project) -> str:
        return item.id
