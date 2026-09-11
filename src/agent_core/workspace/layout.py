"""Physical layout of a task's working root.

Directories are created on demand so the logical mounts (``/inputs``,
``/workspace``, ``/outputs``, ``/scratch``) always resolve, whether or not a
task has produced anything yet. The skill mount is *not* here: skills live in
their own shared root ``<workspace>/skills`` (see :func:`skills_root`), mounted
read-write at ``/skills`` — a skill is a directory the agent owns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

READ_ONLY_DIRS: tuple[str, ...] = ("inputs",)
"""Logical directories the agent may read but never write."""

_WRITABLE_DIRS: tuple[str, ...] = ("workspace", "outputs", "scratch")


def skills_root(workspace: Path) -> Path:
    """The shared skills directory for a workspace (created on demand).

    One directory per skill, each holding a ``SKILL.md``. This is the single
    source of truth: the registry scans it rather than storing skills itself.
    """
    root = workspace / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass(frozen=True)
class WorkspaceLayout:
    """The logical directory set rooted at one task working directory."""

    root: Path

    @property
    def inputs(self) -> Path:
        return self.root / "inputs"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def scratch(self) -> Path:
        return self.root / "scratch"

    @classmethod
    def ensure(cls, root: Path) -> WorkspaceLayout:
        """Create the layout under ``root`` (idempotent) and return it."""
        layout = cls(root=root)
        for name in (*READ_ONLY_DIRS, *_WRITABLE_DIRS):
            (root / name).mkdir(parents=True, exist_ok=True)
        return layout
