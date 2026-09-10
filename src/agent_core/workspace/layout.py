"""Physical layout of a task's working root.

Directories are created on demand so the logical mounts (``/inputs``,
``/workspace``, ``/outputs``, ``/tmp``) always resolve, whether or not a task
has produced anything yet. The skill mount is *not* here: skill sources stay in
their registry location and are mounted read-only (see ``builder``), never
copied into the task root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

READ_ONLY_DIRS: tuple[str, ...] = ("inputs",)
"""Logical directories the agent may read but never write."""

_WRITABLE_DIRS: tuple[str, ...] = ("workspace", "outputs", "tmp")


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
    def tmp(self) -> Path:
        return self.root / "tmp"

    @classmethod
    def ensure(cls, root: Path) -> WorkspaceLayout:
        """Create the layout under ``root`` (idempotent) and return it."""
        layout = cls(root=root)
        for name in (*READ_ONLY_DIRS, *_WRITABLE_DIRS):
            (root / name).mkdir(parents=True, exist_ok=True)
        return layout
