"""Unified exception hierarchy."""

from agent_core.errors.exceptions import (
    AgentError,
    ApprovalError,
    ApprovalRejectedError,
    ConfigurationError,
    MCPError,
    MCPUnavailableError,
    PermissionDeniedError,
    RegistryError,
    SkillError,
    StateError,
    ToolError,
    ToolInvalidArgumentsError,
    ToolTimeoutError,
)

__all__ = [
    "AgentError",
    "ApprovalError",
    "ApprovalRejectedError",
    "ConfigurationError",
    "MCPError",
    "MCPUnavailableError",
    "PermissionDeniedError",
    "RegistryError",
    "SkillError",
    "StateError",
    "ToolError",
    "ToolInvalidArgumentsError",
    "ToolTimeoutError",
]
