"""Project endpoints: host directories conversations can be bound to.

A project is the ZCode-style workspace: tasks bound to it read, write and
execute directly inside its directory. Registration is human-driven (Console
or API) — the agent can never choose a working directory itself, so the path
confinement of the file backend, run_code and the sandbox stays meaningful.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import ProjectCreateRequest, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(service: ServiceDep) -> list[ProjectOut]:
    return [ProjectOut.of(project) for project in service.list_projects()]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreateRequest, service: ServiceDep) -> ProjectOut:
    return ProjectOut.of(service.create_project(payload.name, payload.path))


@router.delete("/{project_id}", response_model=ProjectOut)
def delete_project(project_id: str, service: ServiceDep) -> ProjectOut:
    """Remove the binding; bound tasks fall back to their per-task directory."""
    return ProjectOut.of(service.delete_project(project_id))
