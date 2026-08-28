"""Skill domain model.

A Skill tells the agent *how* to do something (instructions, knowledge,
workflow, optional resources); Tools/MCP tell it *what* it can do. Skill
layout follows the directory convention::

    skills/<skill_id>/
        SKILL.md
        references/
        scripts/
        assets/

Loading itself is delegated to the DeepAgents skills mechanism (Phase 3);
this model is the registry-side metadata contract.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    """Metadata describing one skill discovered or registered in the Skill Registry."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str = ""
    path: Path | None = Field(default=None, description="Directory containing SKILL.md")
    dependencies: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tool names this skill may use; empty means unrestricted",
    )
    metadata: dict[str, str] = Field(default_factory=dict)
