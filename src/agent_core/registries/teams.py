"""Team Registry: in-memory store of composed teams."""

from __future__ import annotations

from agent_core.domain.team import TeamSpec
from agent_core.registries.base import BaseRegistry


class TeamRegistry(BaseRegistry[TeamSpec]):
    """Teams keyed by :attr:`TeamSpec.id`."""

    kind = "team"

    def key_for(self, item: TeamSpec) -> str:
        return item.id
