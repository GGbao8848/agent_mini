"""Skill registry endpoints: list, register a server-side directory, and remove.

Registering points the registry at an existing directory following the skill
layout convention (the directory must contain ``SKILL.md``). Installing a
*new* skill is the agent's job (its ``install_skill`` tool authors the
directory and registers it), so there is no console upload channel here.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import SkillCreateRequest, SkillOut, SkillUpdateRequest
from agent_core.domain.skill import SkillManifest

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillOut])
def list_skills(service: ServiceDep) -> list[SkillOut]:
    return [SkillOut.of(manifest) for manifest in service.runtime.skills.list()]


@router.get("/{skill_id}", response_model=SkillOut)
def get_skill(skill_id: str, service: ServiceDep, version: str | None = None) -> SkillOut:
    return SkillOut.of(service.runtime.skills.get(skill_id, version))


@router.get("/{skill_id}/versions", response_model=list[SkillOut])
def list_skill_versions(skill_id: str, service: ServiceDep) -> list[SkillOut]:
    return [SkillOut.of(manifest) for manifest in service.runtime.skills.list_versions(skill_id)]


@router.post("", response_model=SkillOut, status_code=201)
def install_skill(payload: SkillCreateRequest, service: ServiceDep) -> SkillOut:
    """Install a skill from a server-side directory (must contain SKILL.md)."""
    path = payload.validate_directory()
    manifest = SkillManifest(
        id=payload.id,
        name=payload.name,
        version=payload.version,
        description=payload.description,
        path=path,
    )
    service.runtime.skills.register(manifest)
    return SkillOut.of(manifest)


@router.delete("/{skill_id}", response_model=SkillOut)
def uninstall_skill(
    skill_id: str, service: ServiceDep, version: str | None = Query(default=None)
) -> SkillOut:
    """Remove one version, or the whole skill when ``version`` is omitted."""
    return SkillOut.of(service.runtime.skills.remove(skill_id, version))


@router.patch("/{skill_id}", response_model=SkillOut)
def update_skill(skill_id: str, payload: SkillUpdateRequest, service: ServiceDep) -> SkillOut:
    """Toggle/edit a skill's registration fields (enabled drives staging)."""
    manifest = service.runtime.skills.get(skill_id)
    if payload.enabled is not None:
        manifest.enabled = payload.enabled
    return SkillOut.of(service.runtime.skills.update(manifest))
