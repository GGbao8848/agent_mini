"""Skill registry endpoints: read-only.

A skill is a directory under ``<workspace>/skills`` and that directory is the
source of truth (see ``docs/skills-as-directory.md``). The agent adds, edits,
and deletes skills with its file tools; the console only *reads* what is on
disk. There are deliberately no write endpoints — a console write would be
reverted by the next directory sync, so offering one would be a lie.
"""

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
