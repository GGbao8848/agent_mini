"""Where conversations work, and where skills live.

The workspace directory is a **container of working folders**. Each bound
project works in its own directory; every unbound conversation shares the
``default`` folder. Nothing else is pre-created — how a conversation organizes
files inside its folder (sub-directories, naming, layout) is the agent's call,
not a structure the framework imposes.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_GROUP_NAME = "default"
"""Working folder for conversations not bound to a project."""


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
    sibling of the working folders, not inside any one of them.
    """
    root = workspace / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root
