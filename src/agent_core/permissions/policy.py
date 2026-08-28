"""ActionPolicy: permission decision + risk floor for one tool invocation."""

from __future__ import annotations

from agent_core.domain.action import RiskLevel
from agent_core.domain.agent import AgentSpec
from agent_core.domain.permission import PermissionDecision
from agent_core.domain.tool import ToolDefinition

_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class ActionPolicy:
    """Combines the agent's PermissionSpec with a risk floor.

    ``ALLOW`` decisions are upgraded to ``REQUIRE_APPROVAL`` when the tool's
    risk level is at or above the floor (default HIGH) — an explicit allow
    rule cannot bypass the floor. ``DENY`` always wins.
    """

    def __init__(self, approval_risk_floor: RiskLevel = RiskLevel.HIGH) -> None:
        self._floor = approval_risk_floor

    def evaluate(self, spec: AgentSpec, tool: ToolDefinition) -> PermissionDecision:
        """Return the gate decision for invoking ``tool`` as ``spec``."""
        if spec.permissions is not None:
            decision = spec.permissions.evaluate(tool.name)
        else:
            decision = PermissionDecision.ALLOW
        if (
            decision is PermissionDecision.ALLOW
            and _RISK_ORDER[tool.risk_level] >= _RISK_ORDER[self._floor]
        ):
            return PermissionDecision.REQUIRE_APPROVAL
        return decision
