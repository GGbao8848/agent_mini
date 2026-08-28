"""Application layer: transport-agnostic use cases over the Agent Runtime."""

from agent_core.application.bootstrap import default_service
from agent_core.application.service import AgentCoreService

__all__ = ["AgentCoreService", "default_service"]
