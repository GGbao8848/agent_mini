"""Built-in tools shipped with Agent Core, registered at bootstrap.

Availability is configuration-driven (image API URL, Telegram credentials).
Agents opt in by listing tool names in ``AgentSpec.tools`` — built-ins get no
special treatment at run time and go through the same Permission → Action
Gate path as any other tool.
"""

from __future__ import annotations

from agent_core.builtins.code import RUN_CODE_TOOL
from agent_core.builtins.code import register_builtin_tools as register_code_tools
from agent_core.builtins.image import GENERATE_IMAGE_TOOL, VIEW_IMAGE_TOOL
from agent_core.builtins.image import register_builtin_tools as register_image_tools
from agent_core.builtins.notify import TELEGRAM_NOTIFY_TOOL
from agent_core.builtins.notify import register_builtin_tools as register_telegram_tools
from agent_core.builtins.schedules import CREATE_SCHEDULE_TOOL
from agent_core.config.settings import Settings
from agent_core.registries import ToolRegistry

__all__ = [
    "CREATE_SCHEDULE_TOOL",
    "GENERATE_IMAGE_TOOL",
    "RUN_CODE_TOOL",
    "TELEGRAM_NOTIFY_TOOL",
    "VIEW_IMAGE_TOOL",
    "register_builtin_tools",
]


def register_builtin_tools(registry: ToolRegistry, settings: Settings) -> list[str]:
    """Register all configured built-in tools; returns the names that were added."""
    registered = register_image_tools(registry, settings)
    registered.extend(register_telegram_tools(registry))
    registered.extend(register_code_tools(registry, settings))
    return registered
