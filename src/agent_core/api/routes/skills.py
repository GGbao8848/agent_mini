"""Skill registry endpoints: list, toggle, and remove.

Read/manage-only. Installing a skill is the agent's job (its ``install_skill``
tool authors the skill directory and registers it), so the console has no
register/upload channel here — every write enters through the agent and its
approval queue.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import SkillOut, SkillUpdateRequest

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
