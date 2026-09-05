"""Project domain model.

A Project binds conversations to a real folder on the host (the ZCode-style
workspace): tasks bound to a project read, write and execute directly in that
directory instead of the anonymous ``workspace/tasks/<task_id>/`` tree, so
deliverables land where the user can keep working on them. Projects must be
registered by a human (Console/API) — the agent can never choose a directory
itself, which keeps the path confinement meaningful.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agent_core.domain.task import _now


class Project(BaseModel):
    """A host directory that conversations can be bound to."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    path: Path
    """Absolute host directory; the working root for bound tasks."""
    created_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        expanded = value.expanduser()
        if not expanded.is_absolute():
            raise ValueError(f"project path must be absolute, got '{value}'")
        return expanded.resolve()
