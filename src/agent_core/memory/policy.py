"""Memory access policy (R23): who may read and write which scope.

Memory already had a ``scope`` but nothing enforced it: an agent could write an
ORG fact, and retrieval ran *unscoped*, so a PROJECT memory written in one
project could surface in an unrelated project's conversation. The scope enum
was decorative.

:class:`MemoryPolicy` makes it load-bearing. A memory's identity is the pair
``(scope, scope_id)`` — the kind of owner and which owner:

- ``USER``    / user id      — about the human
- ``PROJECT`` / project id   — about one bound project
- ``AGENT``   / agent id     — about one agent's own behaviour
- ``ORG``     / ``None``     — organization-wide, human-curated

The policy answers two questions:

- **can this writer write to that scope?** Agents may write USER/PROJECT/AGENT
  but never ORG — organization-wide facts are a control-plane change, made by a
  human in the console (mirrors the ``install_skill`` review gate).
- **what may this run read?** Exactly the scopes that belong to its own
  context: the user scope, its bound project's PROJECT scope, its own AGENT
  scope, plus ORG. Another project's or agent's entries are invisible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_core.domain.memory import MemoryScope


class MemoryOrigin(StrEnum):
    """Who is attempting the operation."""

    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class WriteDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


# Scopes an agent may author on its own. ORG is deliberately absent: it is
# visible to everyone, so only a human may create one.
_AGENT_WRITABLE = frozenset(
    {MemoryScope.USER, MemoryScope.PROJECT, MemoryScope.AGENT}
)


@dataclass(frozen=True)
class ScopeRef:
    """A concrete memory location: the scope kind plus its owner id."""

    scope: MemoryScope
    scope_id: str | None

    def __str__(self) -> str:
        return f"{self.scope.value}:{self.scope_id or '*'}"


class MemoryPolicy:
    """Read/write governance over memory scopes (R23)."""

    def __init__(self, *, agent_writable: frozenset[MemoryScope] | None = None) -> None:
        self._agent_writable = agent_writable if agent_writable is not None else _AGENT_WRITABLE

    # ---------------------------------------------------------------- writes

    def can_write(
        self,
        *,
        scope: MemoryScope,
        origin: MemoryOrigin,
        agent_id: str | None = None,
        project_id: str | None = None,
    ) -> WriteDecision:
        """May ``origin`` write to ``scope``?"""
        if origin is MemoryOrigin.HUMAN or origin is MemoryOrigin.SYSTEM:
            return WriteDecision.ALLOW
        if scope not in self._agent_writable:
            return WriteDecision.DENY
        # An agent may only write into the project it is actually working in:
        # a PROJECT memory with no project bound would leak across projects.
        if scope is MemoryScope.PROJECT and not project_id:
            return WriteDecision.DENY
        return WriteDecision.ALLOW

    def deny_reason(self, scope: MemoryScope) -> str:
        if scope is MemoryScope.ORG:
            return "组织级记忆只能由人工在控制台维护，agent 不能写入"
        if scope is MemoryScope.PROJECT:
            return "该会话未绑定项目，无法写入项目级记忆"
        return f"agent 不能写入 {scope.value} 范围的记忆"

    # ---------------------------------------------------------------- reads

    def visible_scopes(
        self,
        *,
        agent_id: str,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> list[ScopeRef]:
        """The concrete scopes a run with this context may read."""
        refs = [
            ScopeRef(MemoryScope.ORG, None),
            ScopeRef(MemoryScope.USER, user_id),
            ScopeRef(MemoryScope.AGENT, agent_id),
        ]
        if project_id:
            refs.append(ScopeRef(MemoryScope.PROJECT, project_id))
        return refs

    def can_read(
        self, entry_scope: MemoryScope, entry_scope_id: str | None, refs: list[ScopeRef]
    ) -> bool:
        """True when an entry at ``(scope, scope_id)`` is visible under ``refs``."""
        return any(
            ref.scope is entry_scope and ref.scope_id == entry_scope_id for ref in refs
        )
