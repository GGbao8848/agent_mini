"""Skill registry endpoints: list, install (from a server-side directory or a
zip upload), and remove.

Installing registers the manifest against a directory following the skill
layout convention (the directory must contain ``SKILL.md``). ``POST /skills``
points at a server-side directory; ``POST /skills/upload`` accepts a skill
zip that is extracted under the workspace and registered from its
``SKILL.md`` frontmatter.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import SkillCreateRequest, SkillOut
from agent_core.api.skills_upload import install_skill_from_zip
from agent_core.config.settings import get_settings
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


@router.post("/upload", response_model=SkillOut, status_code=201)
async def upload_skill(
    service: ServiceDep,
    file: Annotated[UploadFile, File()],
    skill_id: Annotated[str | None, Form()] = None,
    version: Annotated[str, Form()] = "0.1.0",
) -> SkillOut:
    """Install a skill from an uploaded zip (SKILL.md at root or a top folder)."""
    archive = await file.read()
    manifest = install_skill_from_zip(
        archive,
        service.runtime.skills,
        get_settings().workspace_dir,
        skill_id=skill_id,
        version=version,
    )
    return SkillOut.of(manifest)


@router.delete("/{skill_id}", response_model=SkillOut)
def uninstall_skill(
    skill_id: str, service: ServiceDep, version: str | None = Query(default=None)
) -> SkillOut:
    """Remove one version, or the whole skill when ``version`` is omitted."""
    return SkillOut.of(service.runtime.skills.remove(skill_id, version))
