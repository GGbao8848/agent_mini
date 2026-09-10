"""ActionPolicy: permission decision + risk floor for one tool invocation.

Since R22 this is a thin adapter over :class:`CapabilityResolver`, which is the
single place that decides whether an agent may call a tool. The policy exists so
the action gate keeps its ``evaluate(spec, tool)`` seam while the actual rules
(agent binding ∩ skill binding ∩ permission rules ∩ risk floor) live in one
auditable object shared with the builder and the console.
"""

from __future__ import annotations

from agent_core.capabilities.resolver import CapabilityResolver, SkillAllowedTools
from agent_core.domain.action import RiskLevel
from agent_core.domain.agent import AgentSpec
from agent_core.domain.permission import PermissionDecision
from agent_core.domain.tool import ToolDefinition


class ActionPolicy:
    """Combines an agent's capability bindings with a risk floor.

    ``ALLOW`` decisions are upgraded to ``REQUIRE_APPROVAL`` when the tool's
    risk level is at or above the floor (default HIGH) — an explicit allow rule
    cannot bypass the floor. ``DENY`` always wins. Skill ``allowed_tools`` and
    the agent's own tool list are hard boundaries (runtime invariant I-11).
    """

    def __init__(
        self,
        approval_risk_floor: RiskLevel = RiskLevel.HIGH,
        *,
        skill_allowed_tools: SkillAllowedTools | None = None,
        resolver: CapabilityResolver | None = None,
    ) -> None:
        self._floor = approval_risk_floor
        self._resolver = resolver or CapabilityResolver(
            skill_allowed_tools=skill_allowed_tools,
            approval_risk_floor=approval_risk_floor,
        )

    @property
    def resolver(self) -> CapabilityResolver:
        """The capability resolver this policy delegates to (single truth)."""
        return self._resolver

    def evaluate(self, spec: AgentSpec, tool: ToolDefinition) -> PermissionDecision:
        """Return the gate decision for invoking ``tool`` as ``spec``."""
        return self._resolver.decide_with_reason(spec, tool)[0]
