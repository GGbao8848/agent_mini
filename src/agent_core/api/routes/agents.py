"""Agent registry endpoints (read-only: agents are code-defined artifacts)."""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import AgentOut

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
def list_agents(service: ServiceDep) -> list[AgentOut]:
    return [AgentOut.of(spec) for spec in service.runtime.agents.list()]


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, service: ServiceDep) -> AgentOut:
    return AgentOut.of(service.runtime.agents.get(agent_id))
