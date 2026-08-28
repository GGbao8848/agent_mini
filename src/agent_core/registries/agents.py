"""Agent Registry: AgentSpec definitions keyed by spec id."""

from __future__ import annotations

from agent_core.domain.agent import AgentSpec
from agent_core.registries.base import BaseRegistry


class AgentRegistry(BaseRegistry[AgentSpec]):
    """Lookup table for agent definitions; the only way to obtain an AgentSpec."""

    kind = "agent"

    def key_for(self, item: AgentSpec) -> str:
        return item.id
