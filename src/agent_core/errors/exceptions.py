"""Unified exception hierarchy for Agent Core.

Every error carries a ``retryable`` flag so the retry layer (Phase 4+) can
distinguish transient failures (network timeout, MCP unavailable) from
permanent ones (permission denied, invalid arguments, user rejection).

Exceptions never leak raw Python tracebacks to agents: infrastructure layers
catch arbitrary exceptions and convert them into one of these types.
"""

from __future__ import annotations

from typing import Any


class AgentError(Exception):
    """Base class for all Agent Core errors."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.details: dict[str, Any] = details or {}


class ConfigurationError(AgentError):
    """Invalid configuration or missing required settings. Never retryable."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, retryable=False, details=details)


class StateError(AgentError):
    """Illegal state transition or corrupted state. Never retryable."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, retryable=False, details=details)


class ToolError(AgentError):
    """A tool invocation failed. Retryability depends on the concrete cause."""


class ToolTimeoutError(ToolError):
    """A tool invocation exceeded its time budget. Transient, so retryable."""

    def __init__(self, tool_name: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Tool '{tool_name}' timed out after {timeout_seconds}s",
            retryable=True,
            details={"tool": tool_name, "timeout_seconds": timeout_seconds},
        )


class ToolInvalidArgumentsError(ToolError):
    """Tool arguments failed validation. Retrying with the same input is pointless."""

    def __init__(self, tool_name: str, detail: str) -> None:
        super().__init__(
            f"Invalid arguments for tool '{tool_name}': {detail}",
            retryable=False,
            details={"tool": tool_name},
        )


class MCPError(AgentError):
    """An MCP server interaction failed."""


class MCPUnavailableError(MCPError):
    """An MCP server is temporarily unreachable. Transient, so retryable."""

    def __init__(self, server_id: str, detail: str) -> None:
        super().__init__(
            f"MCP server '{server_id}' unavailable: {detail}",
            retryable=True,
            details={"server_id": server_id},
        )


class SkillError(AgentError):
    """A skill could not be loaded, resolved, or executed."""


class AgentExecutionError(AgentError):
    """An agent run failed inside the harness (model error, graph crash)."""


class RunTimeoutError(AgentError):
    """A run exceeded its time budget. Transient, so retryable."""

    def __init__(self, run_id: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Run '{run_id}' timed out after {timeout_seconds}s",
            retryable=True,
            details={"run_id": run_id, "timeout_seconds": timeout_seconds},
        )


class PermissionDeniedError(AgentError):
    """A permission policy denied the action. Retrying will not change the outcome."""

    def __init__(self, agent_id: str, tool_name: str) -> None:
        super().__init__(
            f"Agent '{agent_id}' is not permitted to use tool '{tool_name}'",
            retryable=False,
            details={"agent_id": agent_id, "tool": tool_name},
        )


class ApprovalError(AgentError):
    """Base class for approval (Action Gate) errors."""


class ApprovalRejectedError(ApprovalError):
    """A human rejected (or cancelled) the pending action. Never retryable."""

    def __init__(self, approval_id: str, resolved_by: str = "user") -> None:
        super().__init__(
            f"Approval '{approval_id}' was rejected by {resolved_by}",
            retryable=False,
            details={"approval_id": approval_id},
        )


class RegistryError(AgentError):
    """Duplicate registration or lookup miss on a registry."""

    def __init__(self, kind: str, key: str, detail: str) -> None:
        super().__init__(
            f"{kind} registry error for '{key}': {detail}",
            retryable=False,
            details={"kind": kind, "key": key},
        )
