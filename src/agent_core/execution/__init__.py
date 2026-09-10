"""Execution policy (R24): the explicit envelope for code execution.

:func:`build_execution_policy` turns the sandbox settings into an
:class:`~agent_core.execution.policy.ExecutionPolicy` that states which files,
network, environment and resources a ``run_code`` call gets — the same
description the argv builder, the console and the acceptance report use.
"""

from agent_core.execution.policy import (
    DEFAULT_FORWARDED_ENV,
    ExecutionMode,
    ExecutionPolicy,
    NetworkMode,
    build_execution_policy,
)

__all__ = [
    "DEFAULT_FORWARDED_ENV",
    "ExecutionMode",
    "ExecutionPolicy",
    "NetworkMode",
    "build_execution_policy",
]
