"""Permission, Action Gate and approval components."""

from agent_core.permissions.approval import ApprovalManager
from agent_core.permissions.gate import ActionGate
from agent_core.permissions.policy import ActionPolicy

__all__ = ["ActionGate", "ActionPolicy", "ApprovalManager"]
