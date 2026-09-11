"""Per-conversation permission mode: how much the agent may do unattended.

Mirrors the editor-agent convention (confirm / auto-edit / plan / full access)
so a user can dial autonomy up for a trusted long task and down when they want
to watch every write. The mode is chosen in the console's composer and travels
with each turn, so it can change mid-conversation.

Enforcement lives in two places:
- :class:`~agent_core.runtime.file_tool_trace.FileToolTraceMiddleware` applies
  it to the framework's built-in file tools (which bypass the ActionGate).
- :class:`~agent_core.permissions.gate.ActionGate` applies it to governed tools
  (``FULL`` lifts the risk-floor approval, never an explicit deny).
"""

from __future__ import annotations

from enum import StrEnum


class PermissionMode(StrEnum):
    """How the agent's edits/actions are gated for one conversation."""

    CONFIRM = "confirm"
    """变更前确认: every file write asks the human first."""

    AUTO = "auto"
    """自动编辑: file writes proceed; governed tools keep their risk gate."""

    PLAN = "plan"
    """计划模式: no writes at all — the agent must present a plan first."""

    FULL = "full"
    """完全访问: no approval prompts (risk-floor approvals are lifted)."""

    @property
    def allows_writes(self) -> bool:
        """False only in PLAN mode, where edits are refused outright."""
        return self is not PermissionMode.PLAN

    @property
    def requires_write_approval(self) -> bool:
        """True when file writes must be confirmed before they run."""
        return self is PermissionMode.CONFIRM

    @property
    def lifts_risk_floor(self) -> bool:
        """True when the gate should stop asking to approve risky tools."""
        return self is PermissionMode.FULL


DEFAULT_PERMISSION_MODE = PermissionMode.CONFIRM
"""New conversations start in 变更前确认 so writes are visible by default."""
