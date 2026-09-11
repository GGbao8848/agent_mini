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

DEFAULT_GROUP_NAME = "default"
"""Working folder for conversations not bound to a project.

The workspace is a *container* of working folders: each bound project works in
its own directory, and every unbound conversation shares the ``default`` one.
So the root holds the group folders side by side, with the global ``skills/``
and the staging ``uploads/`` as siblings of them (never inside a working root).
"""


def default_root(workspace: Path) -> Path:
    """The shared working folder for unbound conversations (created on demand)."""
    root = workspace / DEFAULT_GROUP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def skills_root(workspace: Path) -> Path:
    """The shared skills directory for a workspace (created on demand).

    One directory per skill, each holding a ``SKILL.md``. This is the single
    source of truth: the registry scans it rather than storing skills itself.
    Skills are global capabilities, so this sits at the workspace root — a
    sibling of the group folders, not inside any one of them.
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
