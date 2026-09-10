"""Effective capability model (R22).

Several modules used to answer "can this agent call tool X?" independently:
the builder's tool whitelist, the skill-binding check in ``ActionPolicy``, the
permission rules, the risk floor and the MCP allowlist. They could disagree —
the console showed one set while the runtime enforced another.

:class:`EffectiveCapabilitySet` is the single computed answer. Every entry
records not just *whether* a tool is available but *why*: which binding exposed
it, what the call-time decision is (allow / require approval / deny) and the
reason. ``can_call`` on the resolver is the one function anything should ask.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agent_core.domain.action import RiskLevel
from agent_core.domain.permission import PermissionDecision


class CapabilityState(StrEnum):
    """Why a tool is (not) available to an agent, in one word."""

    AVAILABLE = "available"
    """Exposed to the model and callable without extra review."""

    RESTRICTED = "restricted"
    """Exposed, but a call needs human approval (risk floor / rules)."""

    UNAVAILABLE = "unavailable"
    """Registered but not callable right now (e.g. MCP server disconnected)."""

    DENIED = "denied"
    """Explicitly outside the agent's capability set (binding/permission)."""


_STATE_BY_DECISION = {
    PermissionDecision.ALLOW: CapabilityState.AVAILABLE,
    PermissionDecision.REQUIRE_APPROVAL: CapabilityState.RESTRICTED,
    PermissionDecision.DENY: CapabilityState.DENIED,
}


class CapabilityEntry(BaseModel):
    """One tool's effective state for one agent."""

    name: str
    description: str = ""
    source: str = "python"
    risk_level: RiskLevel = RiskLevel.LOW
    exposed: bool = Field(
        default=False,
        description="Becomes a tool the model can see (present + not denied).",
    )
    decision: PermissionDecision = PermissionDecision.ALLOW
    state: CapabilityState = CapabilityState.AVAILABLE
    reason: str = ""


class EffectiveCapabilitySet(BaseModel):
    """The computed capabilities of one agent at one point in time."""

    agent_id: str
    entries: list[CapabilityEntry] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    """Human-readable caveats (e.g. 'implicit: no explicit tool binding')."""

    def exposed(self) -> list[CapabilityEntry]:
        """Entries that become model-visible tools."""
        return [entry for entry in self.entries if entry.exposed]

    def exposed_names(self) -> list[str]:
        return [entry.name for entry in self.exposed()]

    def get(self, tool_name: str) -> CapabilityEntry | None:
        return next((e for e in self.entries if e.name == tool_name), None)

    def can_call(self, tool_name: str) -> bool:
        """True when a call would be permitted (allow or approval)."""
        entry = self.get(tool_name)
        return entry is not None and entry.state in (
            CapabilityState.AVAILABLE,
            CapabilityState.RESTRICTED,
        )
