"""Permission domain model.

A permission policy is attached to an agent and evaluated *before* any tool
execution. Evaluation is first-match-wins over an ordered rule list; rules may
match a tool by exact name or by fnmatch glob pattern (e.g. ``delete_*``).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PermissionRule(BaseModel):
    """A single rule mapping a tool pattern to a decision."""

    tool: str = Field(min_length=1, description="Tool name or fnmatch glob pattern")
    decision: PermissionDecision


class PermissionSpec(BaseModel):
    """Ordered permission rules plus the default decision when nothing matches."""

    rules: list[PermissionRule] = Field(default_factory=list)
    default: PermissionDecision = PermissionDecision.ALLOW

    def evaluate(self, tool_name: str) -> PermissionDecision:
        """Return the decision for ``tool_name``; first matching rule wins."""
        for rule in self.rules:
            if _matches(rule.tool, tool_name):
                return rule.decision
        return self.default


def _matches(pattern: str, tool_name: str) -> bool:
    if pattern == tool_name:
        return True
    from fnmatch import fnmatch

    return fnmatch(tool_name, pattern)
