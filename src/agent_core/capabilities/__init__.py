"""Capabilities (R22): one source of truth for what an agent can call.

The :class:`~agent_core.capabilities.resolver.CapabilityResolver` computes an
agent's effective capability set from its tool binding, bound skills' allowed
tools, tool availability, permission rules and the risk floor. The builder, the
action gate and the console all read the same object, so what the UI shows and
what the runtime enforces cannot diverge.
"""

from agent_core.capabilities.model import (
    CapabilityEntry,
    CapabilityState,
    EffectiveCapabilitySet,
)
from agent_core.capabilities.resolver import CapabilityResolver, SkillAllowedTools

__all__ = [
    "CapabilityEntry",
    "CapabilityResolver",
    "CapabilityState",
    "EffectiveCapabilitySet",
    "SkillAllowedTools",
]
