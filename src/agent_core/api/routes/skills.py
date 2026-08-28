"""Skill registry endpoints (read-only: skills are registered from disk)."""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import SkillOut

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
