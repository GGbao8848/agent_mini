"""Agent registry endpoints.

Agents are code-defined artifacts; the API exposes the registry plus a
narrow editing surface (tool binding) used by the Console toolbox.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import AgentOut, AgentUpdateRequest

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
def list_agents(service: ServiceDep) -> list[AgentOut]:
    return [AgentOut.of(spec) for spec in service.runtime.agents.list()]


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, service: ServiceDep) -> AgentOut:
    return AgentOut.of(service.runtime.agents.get(agent_id))


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: str, payload: AgentUpdateRequest, service: ServiceDep
) -> AgentOut:
    return AgentOut.of(
        service.update_agent(agent_id, tools=payload.tools)
    )
