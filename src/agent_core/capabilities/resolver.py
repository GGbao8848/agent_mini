"""Capability resolver (R22): the single source of truth for tool access.

The resolver folds every input that used to be checked in separate places into
one computation:

    agent tool binding
        ∩ skill allowed_tools ∪  (empty = unrestricted)
        ∩ tool availability (a live handler exists)
        ∩ agent permission rules
        ∩ risk floor (allow → require approval)

Consumers:

- the builder asks :meth:`exposed_names` for what the model may see;
- the action gate asks :meth:`decide` at call time;
- the console asks :meth:`effective` to show what the agent actually has.

Because all three read the same object, the UI and the runtime cannot disagree
(this was the R22 defect: `allowed_tools` was declared but never enforced, and
"empty tools" silently meant "everything").
"""

from __future__ import annotations

from collections.abc import Callable

from agent_core.capabilities.model import (
    _STATE_BY_DECISION,
    CapabilityEntry,
    CapabilityState,
    EffectiveCapabilitySet,
)
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
"""Resolve a skill id to its ``allowed_tools`` (``None`` = skill not found)."""


class CapabilityResolver:
    """Computes an agent's effective capabilities and answers access questions."""

    def __init__(
        self,
        definitions: Callable[[], list[ToolDefinition]] | None = None,
        *,
        has_handler: Callable[[str], bool] | None = None,
        skill_allowed_tools: SkillAllowedTools | None = None,
        approval_risk_floor: RiskLevel = RiskLevel.HIGH,
    ) -> None:
        self._definitions = definitions or (lambda: [])
        self._has_handler = has_handler or (lambda _name: True)
        self._skill_allowed_tools = skill_allowed_tools
        self._floor = approval_risk_floor

    # ------------------------------------------------------------- effective

    def bound_names(self, spec: AgentSpec) -> list[str]:
        """The tool names ``spec`` is bound to (binding only, no policy/availability).

        - explicit ``spec.tools`` → verbatim, so a typo fails fast downstream
          (``ToolRegistry.get``) and an explicitly-bound-but-flagged-off tool
          still resolves with a precise call-time error;
        - empty → every registered tool not flagged ``available: False``.
        """
        if spec.tools:
            return list(spec.tools)
        return [
            definition.name
            for definition in self._definitions()
            if definition.metadata.get("available", True) is not False
        ]

    def buildable_names(self, spec: AgentSpec) -> list[str]:
        """Bound names that policy does not deny — what the builder turns into tools.

        Unknown names are kept so the builder still fails fast on a typo;
        handler-less tools are kept too (the builder drops them next), so this
        stays "the names the model may be offered".
        """
        names: list[str] = []
        for name in self.bound_names(spec):
            definition = next((d for d in self._definitions() if d.name == name), None)
            if definition is None:
                names.append(name)  # unknown → builder fails fast
                continue
            if self.decide_with_reason(spec, definition)[0] is PermissionDecision.DENY:
                continue
            names.append(name)
        return names

    def exposed_names(self, spec: AgentSpec) -> list[str]:
        """Tool names that actually become model-visible tools.

        ``buildable_names`` minus tools with no live handler — the exact set
        the builder produces and therefore the exact set the console shows.
        """
        return [
            name
            for name in self.buildable_names(spec)
            if self._has_handler(name)
        ]

    def effective(self, spec: AgentSpec) -> EffectiveCapabilitySet:
        """Diagnostic view: every registered tool and its effective state.

        Unlike :meth:`exposed_names` this includes registered-but-unusable
        tools (no handler → UNAVAILABLE), which is what an operator needs to
        see when asking "why can't the agent call X".
        """
        skill_cap = self._skill_ceiling(spec)

        entries: list[CapabilityEntry] = []
        for definition in self._definitions():
            if not self._has_handler(definition.name):
                entries.append(
                    self._entry(
                        definition,
                        exposed=False,
                        decision=PermissionDecision.DENY,
                        reason="当前不可用（无可用实现）",
                        state=CapabilityState.UNAVAILABLE,
                    )
                )
                continue
            decision, reason = self.decide_with_reason(spec, definition)
            entries.append(
                self._entry(
                    definition,
                    exposed=decision is not PermissionDecision.DENY,
                    decision=decision,
                    reason=reason,
                )
            )

        notes: list[str] = []
        if not spec.tools:
            notes.append("未显式绑定工具：默认暴露所有可用工具")
        if skill_cap is not None:
            notes.append(f"技能绑定收窄了工具范围（{len(skill_cap)} 个）")
        return EffectiveCapabilitySet(agent_id=spec.id, entries=entries, notes=notes)

    def decide(
        self, spec: AgentSpec, tool_name: str, definition: ToolDefinition | None = None
    ) -> PermissionDecision:
        """The call-time decision for ``tool_name`` as ``spec``."""
        resolved = definition or next(
            (d for d in self._definitions() if d.name == tool_name), None
        )
        if resolved is None:
            # No definition to judge: the registry cannot resolve the tool, so
            # there is nothing to execute. Explicit binding still applies first
            # so the error is precise rather than "unknown tool".
            if spec.tools and tool_name not in spec.tools:
                return PermissionDecision.DENY
            return PermissionDecision.DENY
        decision, _ = self.decide_with_reason(spec, resolved)
        return decision

    def decide_with_reason(
        self,
        spec: AgentSpec,
        definition: ToolDefinition,
        *,
        lift_risk_floor: bool = False,
    ) -> tuple[PermissionDecision, str]:
        """The decision plus a human-readable reason (shared by all callers).

        ``lift_risk_floor`` (完全访问 permission mode) stops the risk floor from
        turning an allow into an approval prompt. Explicit deny rules and
        capability bindings still win — the mode reduces prompts, it does not
        grant new or forbidden capabilities.
        """
        if spec.tools and definition.name not in spec.tools:
            return PermissionDecision.DENY, "不在该 agent 的工具绑定中"
        skill_cap = self._skill_ceiling(spec)
        if skill_cap is not None and definition.name not in skill_cap:
            return PermissionDecision.DENY, "超出所绑技能的 allowed_tools 范围"
        return self._policy_decision(
            spec, definition, lift_risk_floor=lift_risk_floor
        )

    def explain(self, spec: AgentSpec, tool_name: str) -> str:
        """Why ``tool_name`` has its state for ``spec`` (for errors/UI)."""
        definition = next((d for d in self._definitions() if d.name == tool_name), None)
        if definition is None:
            return "工具未注册"
        return self.decide_with_reason(spec, definition)[1]

    # --------------------------------------------------------------- helpers

    def _skill_ceiling(self, spec: AgentSpec) -> set[str] | None:
        """Union of bound skills' allowed_tools, or None when unrestricted.

        A skill with an empty ``allowed_tools`` lifts the cap entirely (it
        declares no narrow capabilities). Unknown skills are ignored rather
        than locking the agent out of everything.
        """
        if self._skill_allowed_tools is None or not spec.skills:
            return None
        allowed: set[str] = set()
        restricted = False
        for skill_id in spec.skills:
            tools = self._skill_allowed_tools(skill_id)
            if tools is None:
                continue
            if not tools:
                return None
            restricted = True
            allowed.update(tools)
        return allowed if restricted else None

    def _policy_decision(
        self,
        spec: AgentSpec,
        definition: ToolDefinition,
        *,
        lift_risk_floor: bool = False,
    ) -> tuple[PermissionDecision, str]:
        if spec.permissions is not None:
            decision = spec.permissions.evaluate(definition.name)
            reason = "agent 权限规则"
        else:
            decision = PermissionDecision.ALLOW
            reason = "默认允许"
        if (
            not lift_risk_floor
            and decision is PermissionDecision.ALLOW
            and _RISK_ORDER[definition.risk_level] >= _RISK_ORDER[self._floor]
        ):
            return PermissionDecision.REQUIRE_APPROVAL, "风险等级达到审批阈值"
        return decision, reason

    def _entry(
        self,
        definition: ToolDefinition,
        *,
        exposed: bool,
        decision: PermissionDecision,
        reason: str,
        state: CapabilityState | None = None,
    ) -> CapabilityEntry:
        return CapabilityEntry(
            name=definition.name,
            description=definition.description,
            source=definition.source.value,
            risk_level=definition.risk_level,
            exposed=exposed,
            decision=decision,
            state=state or _STATE_BY_DECISION[decision],
            reason=reason,
        )
