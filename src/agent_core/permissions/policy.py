"""ActionPolicy: permission decision + risk floor for one tool invocation."""

from __future__ import annotations

from collections.abc import Callable

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

SkillAllowedTools = Callable[[str], list[str] | None]
"""Resolve a skill id to its ``allowed_tools`` (``None`` = not found)."""


class ActionPolicy:
    """Combines the agent's PermissionSpec with a risk floor.

    ``ALLOW`` decisions are upgraded to ``REQUIRE_APPROVAL`` when the tool's
    risk level is at or above the floor (default HIGH) — an explicit allow
    rule cannot bypass the floor. ``DENY`` always wins.

    Additionally enforces **skill capability binding**: when an agent is bound
    to skills that declare ``allowed_tools``, a call to any tool outside the
    union of those allowlists is denied. A skill with an empty ``allowed_tools``
    means "unrestricted", so the capability boundary only tightens when a skill
    explicitly narrows it. This is real enforcement (runtime invariant I-11),
    not a prompt-level suggestion.
    """

    def __init__(
        self,
        approval_risk_floor: RiskLevel = RiskLevel.HIGH,
        *,
        skill_allowed_tools: SkillAllowedTools | None = None,
    ) -> None:
        self._floor = approval_risk_floor
        self._skill_allowed_tools = skill_allowed_tools

    def evaluate(self, spec: AgentSpec, tool: ToolDefinition) -> PermissionDecision:
        """Return the gate decision for invoking ``tool`` as ``spec``."""
        if self._violates_skill_binding(spec, tool.name):
            return PermissionDecision.DENY
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

    def _violates_skill_binding(self, spec: AgentSpec, tool_name: str) -> bool:
        """True when bound skills restrict capabilities and ``tool_name`` is outside them."""
        if self._skill_allowed_tools is None or not spec.skills:
            return False
        allowed: set[str] = set()
        restricted = False
        for skill_id in spec.skills:
            tools = self._skill_allowed_tools(skill_id)
            if tools is None:
                continue
            if not tools:
                # An unrestricted skill in the binding lifts the cap entirely:
                # the agent is allowed to use the full toolset this skill needs.
                return False
            restricted = True
            allowed.update(tools)
        return restricted and tool_name not in allowed
