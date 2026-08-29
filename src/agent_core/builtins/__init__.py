"""Built-in tools shipped with Agent Core, registered at bootstrap.

Availability is configuration-driven: ``generate_image`` appears when
``AGENT_CORE_IMAGE_API_BASE_URL`` is set, ``view_image`` always. Agents opt in
by listing the tool names in ``AgentSpec.tools`` — built-ins get no special
treatment at run time and go through the same Permission → Action Gate path.
"""

from agent_core.builtins.image import (
    GENERATE_IMAGE_TOOL,
    VIEW_IMAGE_TOOL,
    register_builtin_tools,
)

__all__ = ["GENERATE_IMAGE_TOOL", "VIEW_IMAGE_TOOL", "register_builtin_tools"]
