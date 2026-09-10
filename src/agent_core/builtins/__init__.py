"""Built-in tools shipped with Agent Core, registered at bootstrap.

Availability is configuration-driven (code sandbox backend). Agents opt in by
listing tool names in ``AgentSpec.tools`` — built-ins get no special treatment
at run time and go through the same Permission → Action Gate path as any other
tool.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_core.builtins.code import RUN_CODE_TOOL
from agent_core.builtins.code import register_builtin_tools as register_code_tools
from agent_core.builtins.packages import ENSURE_PACKAGES_TOOL
from agent_core.builtins.schedules import CREATE_SCHEDULE_TOOL
from agent_core.builtins.skills import INSTALL_SKILL_TOOL
from agent_core.config.settings import Settings
from agent_core.domain.tool import ToolDefinition
from agent_core.registries import ToolRegistry

__all__ = [
    "CREATE_SCHEDULE_TOOL",
    "ENSURE_PACKAGES_TOOL",
    "INSTALL_SKILL_TOOL",
    "RUN_CODE_TOOL",
    "register_builtin_tools",
]


def register_builtin_tools(
    registry: ToolRegistry,
    settings: Settings,
    *,
    compact: Callable[[ToolDefinition], ToolDefinition] | None = None,
) -> list[str]:
    """Register all configured built-in tools; returns the names that were added.

    ``compact`` optionally bounds each definition's model-facing prose before it
    is registered (R20 §10 — see :func:`apply_compaction`).
    """
    return register_code_tools(registry, settings, compact=compact)

